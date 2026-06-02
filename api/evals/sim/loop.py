"""Loop fechado cliente-simulado <-> grafo da jornada dual-control (EVAL-12, 08b §3.2/§5).

NAO-GATE (ver sim/README.md): o verde-no-sim NUNCA conta para o cutover. QUALQUER falha encontrada
numa jornada e PROMOVIDA a fixture pre-roteirizada de `scripted_5/` (EVAL-01) -- e o corpus
DETERMINISTICO (pre-roteirizado, mesmas seeds) que conta para o gate, jamais o simulador.

A jornada e um loop fechado com TETO de turnos: a cada passo o cliente decide (cliente.decidir) e
ou (a) manda uma MENSAGEM -> o grafo roda 1 turno (reusa o seeding/invoke do runner.py), ou
(b) aplica um ATO dual-control (atos.py) que muta o estado real sem rodar o grafo. A trajetoria
(mensagens da IA + atos + estado) e coletada para o operador inspecionar e roteirizar a fixture.

Reusa `runner.py` (mesmo banco de teste, mesmo seeding, mesmo grafo sem checkpointer) carregando-o
por CAMINHO via importlib -- evals/ esta fora do pacote `barra` (igual tests/evals/test_runner_gate).
needs_db + needs_anthropic_api: NAO rodar offline (o loop chama o grafo e o cliente-LLM).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from . import atos as _atos
from .cliente import AcaoCliente, ClienteSimulado

_RUNNERS = Path(__file__).resolve().parents[1] / "runners"


def _carregar_runner() -> Any:
    """Carrega runner.py por caminho (evals/ fora do pacote `barra`) -- reusa seeding/invoke/captura."""
    caminho = _RUNNERS / "runner.py"
    spec = importlib.util.spec_from_file_location("eval_runner", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_runner", modulo)
    spec.loader.exec_module(modulo)
    return modulo


@dataclass
class PassoJornada:
    """Um passo do loop: a acao do cliente + a bolha da IA (se rodou turno) + o estado pos-passo."""

    indice: int
    acao_mensagem: str | None
    acao_ato: str | None
    bolha_ia: str | None
    estado_atendimento: str | None
    ia_pausada: bool | None


@dataclass
class Trajetoria:
    """O que a jornada produziu -- a sequencia de passos para o operador roteirizar a fixture."""

    passos: list[PassoJornada] = field(default_factory=list)

    def bolhas_da_ia(self) -> list[str]:
        """So as falas da IA, na ordem -- o `historico_visivel` que o cliente observa no proximo passo."""
        return [p.bolha_ia for p in self.passos if p.bolha_ia]


async def _aplicar_ato(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID, ato: str
) -> None:
    """Aplica um ato dual-control mutando o estado real (atos.py). Espelha os gatilhos de producao."""
    if ato == "enviar_pix_valido":
        await _atos.enviar_pix(conn, atendimento_id, valido=True)
    elif ato == "enviar_pix_duvidoso":
        await _atos.enviar_pix(conn, atendimento_id, valido=False)
    elif ato == "enviar_foto_portaria":
        await _atos.enviar_foto_portaria(conn, atendimento_id)
    elif ato == "enviar_aviso_saida":
        await _atos.enviar_aviso_saida(conn, atendimento_id)
    elif ato == "ficar_em_silencio":
        _atos.ficar_em_silencio()  # no-op: deixa o timeout decidir
    else:
        raise ValueError(f"ato desconhecido: {ato!r}")


async def jornada(
    conn: AsyncConnection[dict[str, Any]],
    fixture_seed: dict[str, Any],
    cliente: ClienteSimulado,
    decidir_ato: Any | None = None,
    *,
    max_turnos: int = 8,
) -> Trajetoria:
    """Roda a jornada dual-control fechada (needs_db + needs_anthropic_api). Coleta a trajetoria.

    `fixture_seed` so carrega `estado_inicial` (entidades) -- NUNCA expectativas (o cliente nao as
    ve). Reusa `runner._seed_entidades` para criar modelo/cliente/conversa/atendimento e
    `runner._inserir_mensagem` + grafo para rodar cada turno de texto. `decidir_ato(passo, estado)`
    e um hook opcional (roteiro da persona) que, dado o passo/estado, devolve um nome de ato a
    aplicar em vez de pedir texto ao cliente; default None = sempre texto.

    O caller envolve isto em transacao + ROLLBACK (como `runner.rodar`). Promova qualquer falha
    observada na trajetoria a uma fixture de `scripted_5/`.
    """
    runner = _carregar_runner()
    grafo = runner.build_graph()
    modelo_id, atendimento_id, _cliente_id, conversa_id = await runner._seed_entidades(
        conn, fixture_seed
    )
    handler = runner.NodesVisitedHandler()
    trajetoria = Trajetoria()

    for indice in range(max_turnos):
        estado_atual = await _ler_estado(conn, atendimento_id)
        ato = decidir_ato(indice, estado_atual) if decidir_ato else None
        if ato:
            await _aplicar_ato(conn, atendimento_id, ato)
            pos = await _ler_estado(conn, atendimento_id)
            trajetoria.passos.append(
                PassoJornada(
                    indice=indice,
                    acao_mensagem=None,
                    acao_ato=ato,
                    bolha_ia=None,
                    estado_atendimento=pos["estado"],
                    ia_pausada=pos["ia_pausada"],
                )
            )
            if pos["ia_pausada"]:
                break  # IA pausada (handoff/atendimento): a jornada conversacional terminou
            continue

        acao: AcaoCliente = await cliente.decidir(trajetoria.bolhas_da_ia())
        await runner._inserir_mensagem(
            conn, conversa_id, {"direcao": "cliente", "texto": acao.mensagem or ""}
        )
        resultado = await grafo.ainvoke(
            {"messages": []},
            config={"recursion_limit": 18, "callbacks": [handler]},
            context=runner.ContextAgente(
                db_pool=runner._PoolDeUmaConexao(conn),
                redis=None,
                modelo_id=str(modelo_id),
                atendimento_id=str(atendimento_id),
                cliente_id=str(_cliente_id),
                turno_id=str(runner.uuid4()),
                cache_modelo_e_janela=False,
            ),
        )
        captura = await runner._capturar(conn, atendimento_id, resultado)
        trajetoria.passos.append(
            PassoJornada(
                indice=indice,
                acao_mensagem=acao.mensagem,
                acao_ato=None,
                bolha_ia=captura.texto_final,
                estado_atendimento=captura.estado_atendimento,
                ia_pausada=captura.ia_pausada,
            )
        )
        if captura.ia_pausada:
            break

    return trajetoria


async def _ler_estado(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    """Le o estado observavel do atendimento (estado + ia_pausada) -- o que constrange os atos."""
    res = await conn.execute(
        "SELECT estado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row
