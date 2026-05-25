"""M3g — no intercept_disclosure contra o Postgres real (ROLLBACK sempre).

Tres cenarios, todos invocando o no DIRETO (sem LLM, sem grafo completo):
  1. disclosure 1a vez (disclosure_tentativas=0) -> negacao canned + Command(goto="post_process");
     NAO escala (sem escalada, ia_pausada segue false); contador vai a 1.
  2. disclosure 3a insistencia (seed disclosure_tentativas=2) -> escala (handoff Fernando,
     observacao="disclosure_insistente"): ia_pausada=true + Command(goto=END).
  3. jailbreak -> escala direto + Command(goto=END), independe da contagem (nao incrementa).

Um fake-pool de UMA conexao deixa o no E as queries de verificacao lerem a MESMA transacao
(ROLLBACK no teardown -- nada commita). Espelha test_loop_leitura.py / test_repo_integracao.py
(TEST_DATABASE_URL, autocommit=False, dict_row, prepare_threshold=None). Exige a migration
20260525171444_disclosure_tentativas aplicada no banco de teste.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._canned import NEGACOES_CANNED
from barra.agente.contexto import ContextAgente
from barra.agente.nos.intercept_disclosure import intercept_disclosure


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
    """Pool fake de UMA conexao: o no e as verificacoes leem a MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


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
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
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
    disclosure_tentativas: int = 0,
) -> UUID:
    atendimento_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, disclosure_tentativas)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (atendimento_id, 1, cliente_id, modelo_id, conversa_id, "Triagem", disclosure_tentativas),
    )
    return atendimento_id


async def _semear_atendimento(
    conn: AsyncConnection[dict[str, Any]], *, disclosure_tentativas: int = 0
) -> UUID:
    cliente_id = await _seed_cliente(conn)
    modelo_id = await _seed_modelo(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    return await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        disclosure_tentativas=disclosure_tentativas,
    )


def _runtime(conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> _Runtime:
    ctx = ContextAgente(
        db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(atendimento_id),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


async def _ler_atendimento(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT ia_pausada, disclosure_tentativas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _ler_escaladas(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> list[dict[str, Any]]:
    res = await conn.execute(
        "SELECT tipo::text AS tipo, motivo, observacao FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    return await res.fetchall()


@pytest.mark.needs_db
async def test_disclosure_primeira_vez_responde_canned(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """1a vez (contador 0): negacao canned + post_process, sem escalar; contador vai a 1."""
    atendimento_id = await _semear_atendimento(conn, disclosure_tentativas=0)
    state = {"messages": [], "_categoria": "disclosure_attempt", "_confianca": "alta"}

    res = await intercept_disclosure(state, _runtime(conn, atendimento_id))  # type: ignore[arg-type]

    assert isinstance(res, Command)
    assert res.goto == "post_process"
    msg = res.update["messages"][0]
    assert isinstance(msg, AIMessage)
    assert msg.content in NEGACOES_CANNED

    # NAO escalou: sem escalada e ia_pausada segue false; contador incrementado para 1.
    assert await _ler_escaladas(conn, atendimento_id) == []
    atendimento = await _ler_atendimento(conn, atendimento_id)
    assert atendimento["ia_pausada"] is False
    assert atendimento["disclosure_tentativas"] == 1


@pytest.mark.needs_db
async def test_disclosure_terceira_insistencia_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """3a insistencia (seed contador 2 -> vira 3): escala handoff + END."""
    atendimento_id = await _semear_atendimento(conn, disclosure_tentativas=2)
    state = {"messages": [], "_categoria": "disclosure_attempt", "_confianca": "alta"}

    res = await intercept_disclosure(state, _runtime(conn, atendimento_id))  # type: ignore[arg-type]

    assert isinstance(res, Command)
    assert res.goto == END

    atendimento = await _ler_atendimento(conn, atendimento_id)
    assert atendimento["ia_pausada"] is True
    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["tipo"] == "comportamento_atipico"
    assert escaladas[0]["observacao"] == "disclosure_insistente"


@pytest.mark.needs_db
async def test_jailbreak_escala_direto_sem_contar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Jailbreak escala direto + END, independe da contagem e NAO incrementa o contador."""
    atendimento_id = await _semear_atendimento(conn, disclosure_tentativas=0)
    state = {"messages": [], "_categoria": "jailbreak_attempt", "_confianca": "alta"}

    res = await intercept_disclosure(state, _runtime(conn, atendimento_id))  # type: ignore[arg-type]

    assert isinstance(res, Command)
    assert res.goto == END

    atendimento = await _ler_atendimento(conn, atendimento_id)
    assert atendimento["ia_pausada"] is True
    assert atendimento["disclosure_tentativas"] == 0  # jailbreak nao conta
    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["observacao"] == "jailbreak_attempt"
