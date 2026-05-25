"""Prova que as fixtures de leitura induzem a decisao de tool esperada com Sonnet REAL.

Diferente de tests/integracao/test_loop_leitura.py (LLM mockado, so prova a mecanica do loop),
aqui o chat NAO e mockado: build_graph() liga o ChatAnthropic real. E a "rodada manual" do
aceite -- prova que a regra das 48h (04 §2.1) discrimina de fato:
  - 001/002 (>48h): o Sonnet CHAMA consultar_agenda antes de responder;
  - 003 (<=48h): o Sonnet responde pelo contexto dinamico e NAO chama a tool.

A expectativa vem da PROPRIA fixture (consultar_agenda em tool_calls_obrigatorias). So
consultar_agenda esta bindada no M1 (TOOLS), entao o LLM nao consegue chamar tool de escrita.

Fake-pool de UMA conexao (espelha test_loop_leitura.py): prepare_context e a tool leem o MESMO
seed na mesma transacao, ROLLBACK no teardown -- nada commita. needs_key + needs_db.
"""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import BaseMessage, ToolMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph

_LEITURA = Path(__file__).resolve().parents[2] / "evals" / "canonicos" / "leitura"


def _carregar_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for arquivo in sorted(_LEITURA.glob("*.jsonl")):
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                fixtures.append(json.loads(linha))
    return fixtures


_FIXTURES = _carregar_fixtures()


# --- infra de DB real (ROLLBACK sempre) ------------------------------------------------------


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: prepare_context e a tool leem a MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


async def _seed_cliente(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", None),
    )
    return cliente_id


async def _seed_conversa(
    connection: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    connection: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
) -> UUID:
    atendimento_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado)
        VALUES (%s, 1, %s, %s, %s, 'Triagem')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _inserir_mensagem(
    connection: AsyncConnection[dict[str, Any]], *, conversa_id: UUID, conteudo: str
) -> None:
    await connection.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s)
        """,
        (uuid4(), conversa_id, conteudo, f"test-evo-{uuid4().hex}"),
    )


async def _inserir_bloqueio_48h(
    connection: AsyncConnection[dict[str, Any]], modelo_id: UUID
) -> None:
    """Um bloqueio ativo dentro das 48h -> o contexto dinamico tem agenda (now() em SQL: sem skew)."""
    await connection.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem)
        VALUES (%s, %s, now() + interval '5 hours', now() + interval '6 hours', 'bloqueado', 'manual')
        """,
        (uuid4(), modelo_id),
    )


def _contexto(
    pool: _PoolDeUmaConexao, *, modelo_id: UUID, atendimento_id: UUID, cliente_id: UUID
) -> ContextAgente:
    return ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=str(uuid4()),
    )


def _chamou_consultar_agenda(mensagens: list[BaseMessage]) -> bool:
    """True se consultar_agenda apareceu como tool_call (pedida) ou ToolMessage (executada)."""
    for m in mensagens:
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") == "consultar_agenda":
                return True
        if isinstance(m, ToolMessage) and m.name == "consultar_agenda":
            return True
    return False


# --- teste ------------------------------------------------------------------------------------


@pytest.mark.needs_key
@pytest.mark.needs_db
@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
async def test_fixture_induz_decisao_de_tool(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> None:
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_bloqueio_48h(conn, modelo_id)
    await _inserir_mensagem(
        conn, conversa_id=conversa_id, conteudo=fixture["mensagens_entrada"][0]["texto"]
    )

    graph = build_graph()
    estado = await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
        ),
    )

    chamou = _chamou_consultar_agenda(estado["messages"])
    espera = "consultar_agenda" in fixture["expectativas"]["tool_calls_obrigatorias"]
    assert chamou is espera, (
        f"{fixture['id']}: esperava consultar_agenda chamada={espera}, obtido={chamou} "
        f"(mensagem do cliente: {fixture['mensagens_entrada'][0]['texto']!r})"
    )
