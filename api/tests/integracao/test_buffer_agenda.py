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

from barra.dominio.agenda.service import buffer_do_bloqueio_min, existe_vizinho_no_buffer

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


async def _seed_modelo_com_bloqueio(
    c: AsyncConnection[dict[str, Any]], tipo: str | None = None
) -> tuple[UUID, UUID]:
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
        INSERT INTO barravips.bloqueios
            (id, modelo_id, inicio, fim, estado, origem, tipo_atendimento)
        VALUES (%s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum,
                %s::barravips.tipo_atendimento_enum)
        """,
        (bloqueio_id, modelo_id, BASE, BASE + timedelta(hours=1), tipo),
    )
    return modelo_id, bloqueio_id


async def _seed_modelo_com_bloqueio_de_atendimento(
    c: AsyncConnection[dict[str, Any]], tipo_do_atendimento: str
) -> UUID:
    """Bloqueio VINCULADO, com o tipo só no ATENDIMENTO (a coluna do bloqueio fica NULL).

    É o caminho normal de produção — a reserva prévia da IA não copia o tipo — e o que prova que o
    `COALESCE(b.tipo_atendimento, a.tipo_atendimento)` deriva de verdade.
    """
    modelo_id, cliente_id = uuid4(), uuid4()
    conversa_id, atendimento_id = uuid4(), uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Deriva", 25, f"test-wpp-{uuid4().hex}", 500, ["externo"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"55tst{uuid4().hex[:11]}"),
    )
    await c.execute(
        "INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)"
        " VALUES (%s, %s, %s, %s)",
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, tipo_atendimento)
        VALUES (%s, %s, %s, %s, %s::barravips.tipo_atendimento_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, tipo_do_atendimento),
    )
    await c.execute(
        """
        INSERT INTO barravips.bloqueios
            (modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (modelo_id, atendimento_id, BASE, BASE + timedelta(hours=1)),
    )
    return modelo_id


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


# --- deslocamento do vizinho externo (emenda ADR 0025, 2026-08-14) ------------------------------

BUFFER_EXTERNO = 60


@pytest.mark.needs_db
async def test_gap_igual_ao_buffer_padrao_nao_basta_depois_de_um_externo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O pedido do dono: ela sai de um serviço NA CASA DE UM CLIENTE e o próximo quer ir logo.

    Vizinho externo [20:00, 21:00]; novo [21:30, 22:30] — o gap de 30 min que basta para um
    interno não cobre a volta, e a reserva recusa. Só a partir de 22:00 (fim + 60) libera.
    """
    modelo_id, _ = await _seed_modelo_com_bloqueio(conn, "externo")
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1, minutes=30),
        fim=BASE + timedelta(hours=2, minutes=30),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )
    assert not await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=2),
        fim=BASE + timedelta(hours=3),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )


@pytest.mark.needs_db
async def test_o_gap_antes_do_externo_tambem_cobre_a_ida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Novo [18:30, 19:30] termina 30 min antes do externo das 20:00 — a ida não cabe.
    modelo_id, _ = await _seed_modelo_com_bloqueio(conn, "externo")
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE - timedelta(hours=1, minutes=30),
        fim=BASE - timedelta(minutes=30),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )
    # Terminando 19:00 (60 min antes) já cabe.
    assert not await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE - timedelta(hours=2),
        fim=BASE - timedelta(hours=1),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )


@pytest.mark.needs_db
async def test_tipo_do_vizinho_e_derivado_do_atendimento_vinculado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O bloqueio da IA NÃO copia o tipo: quem sabe é o atendimento, e o COALESCE deriva.

    Sem a derivação, todo bloqueio de produção continuaria pagando o gap padrão e a emenda só
    valeria para bloqueio avulso — o caso raro.
    """
    modelo_id = await _seed_modelo_com_bloqueio_de_atendimento(conn, "externo")
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1, minutes=30),
        fim=BASE + timedelta(hours=2, minutes=30),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )


@pytest.mark.needs_db
async def test_interno_e_sem_tipo_seguem_no_buffer_padrao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """COMPATIBILIDADE: o gap de quem não declara tipo não muda com o setting novo ligado.

    O mesmo [21:30, 22:30] que o externo recusa passa para o bloqueio sem tipo e para o interno
    (derivado do atendimento) — é a garantia de que a emenda não encolheu a agenda de ninguém que
    não se desloca.
    """
    modelo_sem_tipo, _ = await _seed_modelo_com_bloqueio(conn, None)
    modelo_interno = await _seed_modelo_com_bloqueio_de_atendimento(conn, "interno")
    for modelo_id in (modelo_sem_tipo, modelo_interno):
        assert not await existe_vizinho_no_buffer(
            conn,
            modelo_id=modelo_id,
            inicio=BASE + timedelta(hours=1, minutes=30),
            fim=BASE + timedelta(hours=2, minutes=30),
            buffer_min=BUFFER,
            buffer_externo_min=BUFFER_EXTERNO,
        )


@pytest.mark.needs_db
async def test_coluna_do_bloqueio_sobrepoe_o_tipo_do_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Override do painel: o atendimento é interno, mas o bloqueio declara externo (ela vai encontrar
    # o cliente fora). O COALESCE tem de preferir a declaração do próprio bloqueio.
    modelo_id = await _seed_modelo_com_bloqueio_de_atendimento(conn, "interno")
    await conn.execute(
        "UPDATE barravips.bloqueios SET tipo_atendimento = 'externo' WHERE modelo_id = %s",
        (modelo_id,),
    )
    assert await existe_vizinho_no_buffer(
        conn,
        modelo_id=modelo_id,
        inicio=BASE + timedelta(hours=1, minutes=30),
        fim=BASE + timedelta(hours=2, minutes=30),
        buffer_min=BUFFER,
        buffer_externo_min=BUFFER_EXTERNO,
    )


@pytest.mark.needs_db
async def test_sql_e_a_regua_python_dao_o_mesmo_numero(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`buffer_do_bloqueio_min` espelha o CASE da SQL — as duas cópias divergindo é o bug de
    sempre (a IA publica o que a reserva recusa). Aqui a SQL é a autoridade e o Python confere.

    O laço varre o gap minuto a minuto em torno da fronteira: o primeiro gap que a SQL aceita tem
    de ser exatamente o que a régua Python diz.
    """
    for tipo in ("externo", "interno", None):
        modelo_id, _ = await _seed_modelo_com_bloqueio(conn, tipo)
        esperado = buffer_do_bloqueio_min(tipo, buffer_min=BUFFER)
        for gap in range(esperado - 5, esperado + 1):
            achou = await existe_vizinho_no_buffer(
                conn,
                modelo_id=modelo_id,
                inicio=BASE + timedelta(hours=1, minutes=gap),
                fim=BASE + timedelta(hours=2, minutes=gap),
                buffer_min=BUFFER,
                buffer_externo_min=BUFFER_EXTERNO,
            )
            assert achou is (gap < esperado), f"tipo={tipo} gap={gap} achou={achou}"
