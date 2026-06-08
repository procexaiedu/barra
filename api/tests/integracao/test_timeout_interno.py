"""`aplicar_timeout_interno` contra o Postgres real (timeout de 45 min do fluxo interno).

Gemeo do `test_timeout_longo`: os testes em `test_workers.py` usam `FakeConn` (nao executam SQL),
entao so conferem o TEXTO da query — nao pegam erro de cast de enum, FK do `bloqueio_id` nem a
sincronia do bloqueio vinculado (cancelado), que so aparecem no Postgres. Aqui exercitamos a CTE
real: Aviso de saida sem Foto de portaria por > 45 min -> Perdido/sumiu + bloqueio cancelado +
evento de transicao (CONTEXT.md "Foto de portaria" / "timeout interno").

`needs_db` (Postgres via TEST_DATABASE_URL); fake-pool de UMA conexao reusa a transacao do teste
-> ROLLBACK limpa tudo. Banco compartilhado: assertamos sobre o registro semeado, nunca sobre a
contagem global.

Cobre:
  - happy: interno em Aguardando_confirmacao, aviso ha > 45 min, sem foto -> Perdido/sumiu, bloqueio
    cancelado, evento de transicao.
  - recente: aviso ha < 45 min -> intacto (a query roda, o WHERE descarta).
  - foto chegou: foto_portaria_em preenchido -> intacto (cliente chegou, nao e timeout).
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

from barra.workers.timeouts import aplicar_timeout_interno

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


async def _seed_interno_aguardando(
    c: AsyncConnection[dict[str, Any]],
    *,
    aviso_min_atras: float | None,
    foto: bool = False,
) -> tuple[UUID, UUID]:
    """Interno em Aguardando_confirmacao com bloqueio vinculado (bloqueado). `aviso_min_atras=None`
    deixa aviso_saida_em nulo; `foto=True` preenche foto_portaria_em. Devolve (atendimento, bloqueio)."""
    modelo_id, cliente_id, conversa_id, atendimento_id, bloqueio_id = (uuid4() for _ in range(5))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Timeout Interno", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
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
    aviso_em = (
        None if aviso_min_atras is None else datetime.now(UTC) - timedelta(minutes=aviso_min_atras)
    )
    foto_em = datetime.now(UTC) if foto else None
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             aviso_saida_em, foto_portaria_em, fonte_decisao_ultima_transicao)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao'::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum, %s, %s, 'extracao_ia')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, aviso_em, foto_em),
    )
    # Bloqueio previo (horario combinado), no futuro, vinculado ao atendimento. FK circular:
    # cria o bloqueio depois do atendimento e amarra via UPDATE (mesmo padrao do schema).
    inicio = datetime.now(UTC) + timedelta(hours=2)
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, inicio + timedelta(hours=2)),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return atendimento_id, bloqueio_id


# --- testes integrados -----------------------------------------------------------------------


@pytest.mark.needs_db
async def test_timeout_interno_marca_perdido_e_cancela_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, bloqueio_id = await _seed_interno_aguardando(conn, aviso_min_atras=46)

    total = await aplicar_timeout_interno(conn)
    assert total >= 1

    res = await conn.execute(
        "SELECT estado::text AS estado, motivo_perda::text AS motivo_perda "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Perdido"
    assert a["motivo_perda"] == "sumiu"

    # Bloqueio vinculado sincronizado: bloqueado -> cancelado.
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bloqueio_id,)
    )
    b = await res.fetchone()
    assert b is not None and b["estado"] == "cancelado"

    # Evento de transicao emitido pela CTE (escopado ao registro semeado).
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'transicao_estado'",
        (atendimento_id,),
    )
    evt = await res.fetchone()
    assert evt is not None and evt["n"] == 1


@pytest.mark.needs_db
async def test_timeout_interno_ignora_aviso_recente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, bloqueio_id = await _seed_interno_aguardando(conn, aviso_min_atras=10)

    await aplicar_timeout_interno(conn)

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None and a["estado"] == "Aguardando_confirmacao"
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bloqueio_id,)
    )
    b = await res.fetchone()
    assert b is not None and b["estado"] == "bloqueado"


@pytest.mark.needs_db
async def test_timeout_interno_ignora_se_foto_chegou(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Aviso ha > 45 min, mas a Foto de portaria chegou -> cliente esta no local, nao e timeout.
    atendimento_id, _ = await _seed_interno_aguardando(conn, aviso_min_atras=46, foto=True)

    await aplicar_timeout_interno(conn)

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None and a["estado"] == "Aguardando_confirmacao"
