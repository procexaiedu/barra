"""Runner minimo de evals (EVAL-01): carrega fixtures .jsonl, seeda o estado, roda o grafo
real e aplica graders DETERMINISTICOS, emitindo exit-code de gate.

Escopo (roadmap EVAL-01): graders deterministicos apenas -- tool_calls_obrigatorias/proibidas,
texto_resposta (nao_deve_conter/deve_conter_um_de/max_chars), ia_pausada_final, estado_final /
state_check. Rubricas `judge: llm` sao de EVAL-02 (ignoradas aqui); nodes_proibidos /
NodesVisitedHandler sao de EVAL-08.

Invocacao real espelha tests/agente/test_fixtures_leitura_decisao.py: grafo SEM checkpointer,
pool fake de UMA conexao (prepare_context + tools na MESMA transacao), ROLLBACK sempre. Usa
TEST_DATABASE_URL (nunca prod direto) + ANTHROPIC_API_KEY.

`avaliar()` e `gate()` sao PUROS (nao tocam DB/LLM): recebem a `Captura` ja coletada e decidem
pass/fail + exit-code. Sao o nucleo testavel do gate (tests/evals/test_runner_gate.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph

_EVALS_RAIZ = Path(__file__).resolve().parents[1]


# --- carregamento de fixtures ------------------------------------------------------------------


def carregar_fixtures(
    raiz: Path = _EVALS_RAIZ, subdirs: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Le todas as fixtures .jsonl (uma por linha) sob `raiz` (ou apenas os `subdirs` dados)."""
    bases = [raiz / s for s in subdirs] if subdirs else [raiz]
    fixtures: list[dict[str, Any]] = []
    for base in bases:
        for arquivo in sorted(base.rglob("*.jsonl")):
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    fixtures.append(json.loads(linha))
    return fixtures


# --- captura do turno --------------------------------------------------------------------------


@dataclass
class Captura:
    """O que o turno produziu, extraido para o `avaliar()` puro decidir pass/fail."""

    tools_chamadas: set[str]
    texto_final: str
    estado_atendimento: str
    ia_pausada: bool
    pix_status: str


def _tools_chamadas(mensagens: list[BaseMessage]) -> set[str]:
    """Nomes de tools pedidas (tool_calls em AIMessage) ou executadas (ToolMessage)."""
    nomes: set[str] = set()
    for m in mensagens:
        for tc in getattr(m, "tool_calls", None) or []:
            nome = tc.get("name")
            if nome:
                nomes.add(nome)
        if isinstance(m, ToolMessage) and m.name:
            nomes.add(m.name)
    return nomes


def _texto_final(mensagens: list[BaseMessage]) -> str:
    """Conteudo (texto) da ultima AIMessage -- a bolha que iria ao cliente."""
    for m in reversed(mensagens):
        if isinstance(m, AIMessage):
            conteudo = m.content
            if isinstance(conteudo, str):
                return conteudo
            partes = [
                bloco.get("text", "")
                for bloco in conteudo
                if isinstance(bloco, dict) and bloco.get("type") == "text"
            ]
            return "".join(partes)
    return ""


# --- seeding (espelha test_fixtures_leitura_decisao.py) ----------------------------------------


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: prepare_context e as tools leem a MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> tuple[UUID, UUID, UUID]:
    """Cria modelo/cliente/conversa/atendimento + mensagens do `estado_inicial`/`mensagens_entrada`.

    Retorna (modelo_id, atendimento_id, cliente_id). `estado_inicial.recorrente` vai na conversa
    (par cliente-modelo); estado/ia_pausada/pix_status vao no atendimento.
    """
    inicial = fixture.get("estado_inicial", {})
    estado = inicial.get("atendimento_estado", "Triagem")
    ia_pausada = bool(inicial.get("ia_pausada", False))
    pix_status = inicial.get("pix_status", "nao_solicitado")
    recorrente = bool(inicial.get("recorrente", False))

    modelo_id, cliente_id, conversa_id, atendimento_id = uuid4(), uuid4(), uuid4(), uuid4()

    await conn.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Eval", 25, f"eval-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
    )
    await conn.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"eval-tel-{uuid4().hex}", None),
    )
    await conn.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id, recorrente)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"eval-chat-{uuid4().hex}", recorrente),
    )
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id,
             estado, pix_status, ia_pausada, ia_pausada_motivo)
        VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            pix_status,
            ia_pausada,
            "handoff_ia" if ia_pausada else None,
        ),
    )
    for msg in fixture.get("mensagens_entrada", []):
        direcao = "ia" if msg.get("direcao") == "ia" else "cliente"
        await conn.execute(
            """
            INSERT INTO barravips.mensagens
                (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
            VALUES (%s, %s, %s, 'texto', %s, %s)
            """,
            (uuid4(), conversa_id, direcao, msg["texto"], f"eval-evo-{uuid4().hex}"),
        )
    return modelo_id, atendimento_id, cliente_id


async def executar_fixture(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> Captura:
    """Seeda, roda o grafo real e coleta a Captura. Requer ANTHROPIC_API_KEY + DB de teste."""
    modelo_id, atendimento_id, cliente_id = await _seed(conn, fixture)

    estado = await build_graph().ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=ContextAgente(
            db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
            redis=None,  # type: ignore[arg-type]
            modelo_id=str(modelo_id),
            atendimento_id=str(atendimento_id),
            cliente_id=str(cliente_id),
            turno_id=str(uuid4()),
        ),
    )

    res = await conn.execute(
        "SELECT estado, ia_pausada, pix_status FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return Captura(
        tools_chamadas=_tools_chamadas(estado["messages"]),
        texto_final=_texto_final(estado["messages"]),
        estado_atendimento=row["estado"],
        ia_pausada=row["ia_pausada"],
        pix_status=row["pix_status"],
    )


# --- avaliacao (PURA: graders deterministicos) -------------------------------------------------


@dataclass
class Avaliacao:
    id: str
    passou: bool
    falhas: list[str] = field(default_factory=list)


def avaliar(fixture: dict[str, Any], captura: Captura) -> Avaliacao:
    """Aplica os graders deterministicos da fixture sobre a Captura. Sem DB/LLM.

    Rubricas `judge: llm` (EVAL-02) e `nodes_proibidos` (EVAL-08) sao ignoradas aqui.
    """
    exp = fixture.get("expectativas", {})
    falhas: list[str] = []

    obrigatorias = set(exp.get("tool_calls_obrigatorias", []))
    faltando = obrigatorias - captura.tools_chamadas
    if faltando:
        falhas.append(f"tool_calls_obrigatorias nao chamadas: {sorted(faltando)}")

    proibidas = set(exp.get("tool_calls_proibidas", []))
    chamou_proibida = proibidas & captura.tools_chamadas
    if chamou_proibida:
        falhas.append(f"tool_calls_proibidas chamadas: {sorted(chamou_proibida)}")

    texto = exp.get("texto_resposta", {})
    alvo = captura.texto_final.lower()
    vazados = [t for t in texto.get("nao_deve_conter", []) if t.lower() in alvo]
    if vazados:
        falhas.append(f"texto vazou termo proibido: {vazados}")
    deve_um = texto.get("deve_conter_um_de")
    if deve_um and not any(t.lower() in alvo for t in deve_um):
        falhas.append(f"texto nao contem nenhum de: {deve_um}")
    max_chars = texto.get("max_chars")
    if max_chars is not None and len(captura.texto_final) > max_chars:
        falhas.append(f"texto excede max_chars ({len(captura.texto_final)} > {max_chars})")

    # state_check (declarativo) tem precedencia sobre os aliases soltos; aplica os dois.
    state_check = dict(exp.get("state_check") or {})
    if "ia_pausada_final" in exp:
        state_check.setdefault("ia_pausada", exp["ia_pausada_final"])
    if "estado_final_atendimento" in exp:
        state_check.setdefault("atendimento_estado", exp["estado_final_atendimento"])

    atual = {
        "atendimento_estado": captura.estado_atendimento,
        "ia_pausada": captura.ia_pausada,
        "pix_status": captura.pix_status,
    }
    for chave, esperado in state_check.items():
        if chave in atual and atual[chave] != esperado:
            falhas.append(f"{chave}: esperado {esperado!r}, obtido {atual[chave]!r}")

    return Avaliacao(id=fixture.get("id", "?"), passou=not falhas, falhas=falhas)


def gate(avaliacoes: list[Avaliacao], threshold: float = 1.0) -> int:
    """Exit-code de gate: 0 se pass-rate >= threshold, 1 caso contrario (ou suite vazia)."""
    if not avaliacoes:
        return 1
    pass_rate = sum(a.passou for a in avaliacoes) / len(avaliacoes)
    return 0 if pass_rate >= threshold else 1


# --- orquestracao + CLI ------------------------------------------------------------------------


async def _conectar() -> AsyncConnection[dict[str, Any]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print(
            "ERRO: TEST_DATABASE_URL nao definido (runner nao roda contra prod).", file=sys.stderr
        )
        raise SystemExit(2)
    return await AsyncConnection.connect(
        url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )


async def rodar(fixtures: list[dict[str, Any]]) -> list[Avaliacao]:
    """Roda cada fixture numa transacao isolada com ROLLBACK (nada commita)."""
    avaliacoes: list[Avaliacao] = []
    conn = await _conectar()
    try:
        for fixture in fixtures:
            try:
                captura = await executar_fixture(conn, fixture)
                avaliacoes.append(avaliar(fixture, captura))
            finally:
                await conn.rollback()
    finally:
        await conn.close()
    return avaliacoes


def _imprimir(avaliacoes: list[Avaliacao]) -> None:
    for a in avaliacoes:
        marca = "PASS" if a.passou else "FAIL"
        print(f"[{marca}] {a.id}")
        for f in a.falhas:
            print(f"        - {f}")
    n_pass = sum(a.passou for a in avaliacoes)
    print(f"\n{n_pass}/{len(avaliacoes)} fixtures passaram.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Runner de evals deterministico (EVAL-01).")
    parser.add_argument(
        "--subdir", action="append", help="subdiretorio de evals/ a rodar (repetivel)."
    )
    parser.add_argument(
        "--threshold", type=float, default=1.0, help="pass-rate minimo para o gate (default 1.0)."
    )
    args = parser.parse_args()

    # psycopg async pendura no ProactorEventLoop (default Windows) -> Selector antes do loop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    fixtures = carregar_fixtures(subdirs=args.subdir)
    if not fixtures:
        print("Nenhuma fixture encontrada.", file=sys.stderr)
        raise SystemExit(2)

    avaliacoes = asyncio.run(rodar(fixtures))
    _imprimir(avaliacoes)
    raise SystemExit(gate(avaliacoes, args.threshold))


if __name__ == "__main__":
    main()
