"""Gerador da Camada 2 (shadow): roda o grafo REAL sobre um contexto do corpus e coleta a
resposta da IA, para comparar head-to-head com a resposta real do Vendedor humano.

Reusa `evals.harness` (seed no DB real + ROLLBACK + ainvoke). O perfil de modelo e SINTETICO e
fixo (Manu), igual a `scripts/eval_corpus/render_v1_prompt.py` — os valores nao afetam a fidelidade
da jogada (calor/empurrao/anti-padrao independem dos precos).

⚠️ §0 do CLAUDE.md: rodar isto GASTA credito de API (cada contexto = 1 ainvoke) e exige
`TEST_DATABASE_URL` (prod self-hosted, com ROLLBACK). O `__main__` so executa com
`SHADOW_AUTORIZADO=1` no ambiente — o gate de autorizacao do dev. A extracao SQL dos pontos de
decisao e o loop em massa entram depois da §0 (ver README.md); aqui fica o NUCLEO reutilizavel.
"""

from __future__ import annotations

import os
from typing import Any

from psycopg import AsyncConnection

from evals.harness import ResultadoTurno, rodar_turno, seedar

# Perfil de modelo sintetico fixo (espelha render_v1_prompt.py). Programas placeholder coerentes.
PERFIL_SINTETICO: dict[str, Any] = {
    "nome": "Manu",
    "idade": 25,
    "tipo_atendimento_aceito": ["interno", "externo"],
    "localizacao_operacional": "Barra (Campinas-SP)",
    "endereco_formatado": "Chácara da Barra, Campinas-SP",
    "programas": [
        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400},
        {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 700},
        {"nome": "Pernoite", "duracao_nome": "12 horas", "horas": 12, "preco": 2500},
    ],
}


def pseudo_fixture(contexto_turnos: list[dict[str, str]], turno_cliente: str) -> dict[str, Any]:
    """Converte um contexto do corpus numa fixture do harness.

    `contexto_turnos` = [{direcao: 'cliente'|'ia', texto}] dos turnos ANTES do ponto de decisao
    (mapeados de corpus.turnos: from_me -> 'ia', senao 'cliente'). `turno_cliente` = a ultima
    mensagem do cliente que o Vendedor humano respondeu (o turno a gerar).
    """
    return {
        "cenario": {"modelo": PERFIL_SINTETICO, "atendimento": {"estado": "Qualificado"}},
        "historico": contexto_turnos,
        "turno_cliente": turno_cliente,
    }


async def gerar_uma(
    conn: AsyncConnection[dict[str, Any]],
    contexto_turnos: list[dict[str, str]],
    turno_cliente: str,
    *,
    graph: Any | None = None,
) -> ResultadoTurno:
    """Seeda o contexto + roda UM turno do grafo real (gasta credito, §0). ROLLBACK e do caller."""
    fixture = pseudo_fixture(contexto_turnos, turno_cliente)
    cen = await seedar(conn, fixture)
    return await rodar_turno(conn, cen, turno_cliente=turno_cliente, graph=graph)


def _autorizado() -> bool:
    return os.environ.get("SHADOW_AUTORIZADO") == "1"


if __name__ == "__main__":  # pragma: no cover
    if not _autorizado():
        raise SystemExit(
            "Geracao shadow gasta credito de API (§0). Defina SHADOW_AUTORIZADO=1 e "
            "TEST_DATABASE_URL apos a autorizacao do dev. Ver evals/shadow/README.md."
        )
    raise SystemExit(
        "Loop de geracao em massa + extracao SQL dos pontos de decisao ainda nao implementados "
        "(pos-§0: definir N e orcamento). O nucleo reutilizavel e `gerar_uma`."
    )
