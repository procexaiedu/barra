"""Freio manual do piloto: `modelos.status` também vale para o atendimento que ainda vai NASCER.

`POST /v1/modelos/{id}/pausar` só pausa os atendimentos ABERTOS naquele instante. Sem este gate,
cliente novo (ou recorrência depois de um `Fechado`/`Perdido`) abria atendimento com a IA ativa e
a modelo pausada — o freio vazava exatamente no caso que o rollback do piloto precisa cobrir.

`needs_db` contra o Postgres real (TEST_DATABASE_URL), sempre com ROLLBACK: o que está sob teste é
o `CASE WHEN` do INSERT, que só o banco sabe avaliar (enums, DEFAULT e CHECK de motivo).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.coordenador import resolver_atendimento

pytestmark = pytest.mark.needs_db


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


async def _seed_conversa(c: AsyncConnection[dict[str, Any]], status: str) -> UUID:
    modelo_id, cliente_id, conversa_id = (uuid4() for _ in range(3))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[],
                %s::barravips.modelo_status_enum)
        """,
        (modelo_id, "Modelo Freio", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"], status),
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
    return conversa_id


async def test_modelo_ativa_abre_atendimento_com_ia_respondendo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    novo = await resolver_atendimento(conn, await _seed_conversa(conn, "ativa"))

    assert novo["ia_pausada"] is False
    assert novo["ia_pausada_motivo"] is None
    assert novo["responsavel_atual"] == "IA"


@pytest.mark.parametrize("status", ["pausada", "inativa"])
async def test_modelo_nao_ativa_abre_atendimento_ja_pausado(
    conn: AsyncConnection[dict[str, Any]], status: str
) -> None:
    novo = await resolver_atendimento(conn, await _seed_conversa(conn, status))

    assert novo["ia_pausada"] is True
    # Mesmo motivo do endpoint de pausa — o card e a devolução para IA já sabem ler este.
    assert novo["ia_pausada_motivo"] == "modelo_em_atendimento"
    assert novo["responsavel_atual"] == "modelo"
