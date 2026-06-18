"""`existe_vizinho_no_buffer` contra o Postgres real (gap de preparo/intervalo, ADR 0025).

A EXCLUDE `bloqueios_sem_sobreposicao` usa `tstzrange(inicio, fim, '[)')` -> adjacência colada
(fim == inicio) é PERMITIDA por ela. O gap de buffer vive na aplicação: este teste fixa o
comportamento da SQL — adjacência colada e quase-adjacência (< buffer) acham vizinho; gap >= buffer
não; `excluir_id` ignora o próprio bloqueio (caminho do PATCH).

`needs_db` (Postgres via TEST_DATABASE_URL); ROLLBACK sempre. Banco compartilhado: cada teste semeia
a sua própria modelo + bloqueio e consulta só contra ela.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.agenda.service import existe_vizinho_no_buffer

BRT = timezone(timedelta(hours=-3))
BUFFER = 30
BASE = datetime(2026, 12, 1, 20, 0, tzinfo=BRT)  # bloqueio semeado = [20:00, 21:00]


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


async def _seed_modelo_com_bloqueio(c: AsyncConnection[dict[str, Any]]) -> tuple[UUID, UUID]:
    modelo_id, bloqueio_id = uuid4(), uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Buffer", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, BASE, BASE + timedelta(hours=1)),
    )
    return modelo_id, bloqueio_id


@pytest.mark.needs_db
async def test_adjacencia_colada_acha_vizinho(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Novo [21:00, 22:00] cola no fim do vizinho (21:00). A EXCLUDE permitiria; o buffer rejeita.
    modelo_id, _ = await _seed_modelo_com_bloqueio(conn)
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1),
        fim=BASE + timedelta(hours=2),
        buffer_min=BUFFER,
    )


@pytest.mark.needs_db
async def test_gap_menor_que_buffer_acha_vizinho(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Novo [21:20, 22:20]: gap de 20 min < 30 -> vizinho dentro do buffer.
    modelo_id, _ = await _seed_modelo_com_bloqueio(conn)
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1, minutes=20),
        fim=BASE + timedelta(hours=2, minutes=20),
        buffer_min=BUFFER,
    )


@pytest.mark.needs_db
async def test_gap_igual_ao_buffer_nao_acha_vizinho(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Novo [21:30, 22:30]: gap de exatamente 30 min == buffer -> reservável (gap >= buffer).
    modelo_id, _ = await _seed_modelo_com_bloqueio(conn)
    assert not await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1, minutes=30),
        fim=BASE + timedelta(hours=2, minutes=30),
        buffer_min=BUFFER,
    )


@pytest.mark.needs_db
async def test_excluir_id_ignora_o_proprio_bloqueio(conn: AsyncConnection[dict[str, Any]]) -> None:
    # PATCH: o mesmo intervalo do bloqueio não pode colidir consigo mesmo quando excluído.
    modelo_id, bloqueio_id = await _seed_modelo_com_bloqueio(conn)
    assert await existe_vizinho_no_buffer(
        conn, modelo_id=modelo_id, inicio=BASE, fim=BASE + timedelta(hours=1), buffer_min=BUFFER
    )
    assert not await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE,
        fim=BASE + timedelta(hours=1),
        buffer_min=BUFFER,
        excluir_id=bloqueio_id,
    )
