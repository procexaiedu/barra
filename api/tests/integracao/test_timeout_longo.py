"""`aplicar_timeout_longo` contra o Postgres real (regressao do FOR UPDATE + agregacao).

Os testes em `test_workers.py` usam `FakeConn` (nao executam SQL), entao nao pegavam o
`FeatureNotSupported: FOR UPDATE is not allowed with aggregate functions` que o LEFT JOIN
LATERAL com `max()` + `FOR UPDATE` (sem `OF a`) dispara no Postgres. Antes do fix (trocar
`FOR UPDATE SKIP LOCKED` -> `FOR UPDATE OF a SKIP LOCKED`) o caso happy levanta a excecao;
depois, marca o atendimento como Perdido/sumiu.

`needs_db` (Postgres via TEST_DATABASE_URL); fake-pool de UMA conexao reusa a transacao do
teste -> ROLLBACK limpa tudo (mesmo padrao de test_reengajamento).

Cobre:
  - happy: alvo elegivel (estado ativo, ia_pausada=false, ultima msg do cliente > 24h) ->
    1 marcado como Perdido/sumiu, com evento de transicao.
  - recente: ultima msg do cliente < 24h -> 0 alvos (a query roda, mas o WHERE descarta).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.timeouts import aplicar_timeout_longo

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


# --- seeds -----------------------------------------------------------------------------------


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    estado: str = "Triagem",
    ia_pausada: bool = False,
) -> tuple[UUID, UUID]:
    modelo_id, cliente_id, conversa_id, atendimento_id = (uuid4() for _ in range(4))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Timeout", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, ia_pausada,
             fonte_decisao_ultima_transicao)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum, %s, 'extracao_ia')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, ia_pausada),
    )
    return atendimento_id, conversa_id


async def _seed_msg_cliente(
    c: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    atendimento_id: UUID,
    *,
    horas_atras: float,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, atendimento_id, direcao, tipo, conteudo,
             evolution_message_id, created_at)
        VALUES (%s, %s, %s, 'cliente', 'texto', %s, %s, %s)
        """,
        (
            uuid4(),
            conversa_id,
            atendimento_id,
            "oi sumido",
            f"test-evo-{uuid4().hex}",
            datetime.now(UTC) - timedelta(hours=horas_atras),
        ),
    )


# --- testes integrados -----------------------------------------------------------------------


@pytest.mark.needs_db
async def test_timeout_longo_marca_perdido_no_banco_real(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Regressao: antes do fix esta chamada levantava FeatureNotSupported (FOR UPDATE + max()).
    # TEST_DATABASE_URL aponta para o banco compartilhado, entao a varredura pode apanhar outros
    # atendimentos reais elegiveis (desfeitos pelo ROLLBACK da fixture) -> assertamos sobre o
    # registro semeado, nunca sobre a contagem global.
    atendimento_id, conversa_id = await _seed_atendimento(conn, estado="Triagem")
    await _seed_msg_cliente(conn, conversa_id, atendimento_id, horas_atras=25)

    total = await aplicar_timeout_longo(conn)
    assert total >= 1

    res = await conn.execute(
        "SELECT estado, motivo_perda FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    assert row["estado"] == "Perdido"
    assert row["motivo_perda"] == "sumiu"

    # Evento de transicao emitido pela CTE.
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'transicao_estado'",
        (atendimento_id,),
    )
    evt = await res.fetchone()
    assert evt is not None and evt["n"] == 1


@pytest.mark.needs_db
async def test_timeout_longo_ignora_msg_recente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Banco compartilhado: a contagem global pode ser > 0 por outros atendimentos reais; o que
    # importa e que o registro semeado (msg < 24h) NAO foi tocado.
    atendimento_id, conversa_id = await _seed_atendimento(conn, estado="Triagem")
    await _seed_msg_cliente(conn, conversa_id, atendimento_id, horas_atras=1)

    await aplicar_timeout_longo(conn)

    res = await conn.execute(
        "SELECT estado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None and row["estado"] == "Triagem"
