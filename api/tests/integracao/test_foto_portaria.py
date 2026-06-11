"""M5d — handoff_foto_portaria_ia + rotear_imagem path interno (06 §4).

`needs_db` (Postgres via TEST_DATABASE_URL). Cobre o caminho interno do `rotear_imagem`
(M5b -> M5d): Aguardando_confirmacao + tipo='interno' -> chama _handoff_foto_portaria,
que delega ao servico de dominio. Verifica os 4 efeitos atomicos (UPDATE atendimento,
UPDATE bloqueio, INSERT escalada owner, evento transicao_estado) + enqueue do card.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings
from barra.workers.envio import _card_chegada
from barra.workers.media import rotear_imagem


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
    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()
    return redis


def _ctx(pool: _PoolDeUmaConexao, redis: FakeRedis) -> dict[str, Any]:
    return {"redis": redis, "db_pool": pool, "settings": get_settings()}


# --- seeds (espelham test_rotear_imagem/test_registrar_extracao) -----------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             coordenacao_chat_id, evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["interno", "externo"],
            f"test-coord-{uuid4().hex}",
            f"test-instance-{uuid4().hex}",
        ),
    )
    return modelo_id


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_bloqueio(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    data_desejada: date,
    horario_desejado: time,
    duracao_horas: Decimal,
) -> UUID:
    """Cria bloqueio 'bloqueado' vinculado ao atendimento + faz UPDATE em atendimentos.bloqueio_id.
    Espelha o efeito de `criar_bloqueio_previo` sem rodar a logica (que precisaria de zona BRT)."""
    bloqueio_id = uuid4()
    inicio = datetime.combine(data_desejada, horario_desejado, tzinfo=UTC)
    fim = inicio + timedelta(hours=float(duracao_horas))
    await c.execute(
        """
        INSERT INTO barravips.bloqueios
            (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, fim),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return bloqueio_id


async def _seed_atendimento_interno_aguardando(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
) -> tuple[UUID, UUID]:
    """Atendimento interno em Aguardando_confirmacao + bloqueio bloqueado. Devolve
    (atendimento_id, bloqueio_id)."""
    atendimento_id = uuid4()
    data_desejada = date(2026, 12, 1)
    horario_desejado = time(14, 0)
    duracao = Decimal("2")
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, data_desejada, horario_desejado, duracao_horas)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao'::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, %s, %s, %s)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            data_desejada,
            horario_desejado,
            duracao,
        ),
    )
    bloqueio_id = await _seed_bloqueio(
        c,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        data_desejada=data_desejada,
        horario_desejado=horario_desejado,
        duracao_horas=duracao,
    )
    return atendimento_id, bloqueio_id


async def _seed_msg_imagem(
    c: AsyncConnection[dict[str, Any]], conversa_id: UUID
) -> tuple[UUID, str, str]:
    """Mensagem do cliente tipo='imagem' com media_object_key (gravada pelo webhook fino).

    Devolve (id interno, evolution_message_id, object_key): o `rotear_imagem` recebe o
    `evolution_message_id` (como o webhook faz) e resolve o UUID interno."""
    mensagem_id = uuid4()
    evolution_message_id = f"test-evo-{uuid4().hex}"
    object_key = f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg"
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id,
             created_at)
        VALUES (%s, %s, 'cliente', 'imagem', '', %s, %s, %s)
        """,
        (mensagem_id, conversa_id, object_key, evolution_message_id, datetime.now(UTC)),
    )
    return mensagem_id, evolution_message_id, object_key


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_foto_portaria_handoff_completo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Aguardando_confirmacao interno + imagem -> handoff implicito completo (06 §4)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id, bloqueio_id = await _seed_atendimento_interno_aguardando(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    mensagem_id, evolution_id, object_key = await _seed_msg_imagem(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/portaria.jpg",
        caption=None,
    )

    # 1. UPDATE atendimento: 5 campos virados de uma vez.
    res = await conn.execute(
        """
        SELECT estado::text AS estado, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo,
               responsavel_atual::text AS responsavel_atual,
               foto_portaria_em,
               fonte_decisao_ultima_transicao::text AS fonte_decisao
          FROM barravips.atendimentos WHERE id = %s
        """,
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Em_execucao"
    assert a["ia_pausada"] is True
    assert a["ia_pausada_motivo"] == "modelo_em_atendimento"
    assert a["responsavel_atual"] == "modelo"
    assert a["foto_portaria_em"] is not None
    assert a["fonte_decisao"] == "webhook_imagem"

    # 2. UPDATE bloqueio: bloqueado -> em_atendimento.
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s",
        (bloqueio_id,),
    )
    b = await res.fetchone()
    assert b is not None
    assert b["estado"] == "em_atendimento"

    # 3. Escalada owner do card 'chegada' (idempotencia por card_message_id, 06 §9).
    res = await conn.execute(
        "SELECT responsavel::text AS responsavel, tipo::text AS tipo, card_message_id "
        "FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["responsavel"] == "modelo"
    assert esc["tipo"] == "foto_portaria"
    assert esc["card_message_id"] is None  # ainda nao postado

    # 4. Evento transicao_estado registrado com gatilho/payload.
    res = await conn.execute(
        """
        SELECT payload
          FROM barravips.eventos
         WHERE atendimento_id = %s AND tipo = 'transicao_estado'
         ORDER BY created_at DESC LIMIT 1
        """,
        (atendimento_id,),
    )
    ev = await res.fetchone()
    assert ev is not None
    assert ev["payload"]["gatilho"] == "foto_portaria"
    assert ev["payload"]["para"] == "Em_execucao"
    assert ev["payload"]["mensagem_id"] == str(mensagem_id)
    assert ev["payload"]["media_object_key"] == object_key

    # 5. Card 'chegada' enfileirado com _job_id estavel (idempotencia ARQ).
    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("enviar_card",)
    assert calls[0].kwargs["tipo"] == "chegada"
    assert calls[0].kwargs["atendimento_id"] == str(atendimento_id)
    assert calls[0].kwargs["_job_id"] == f"card:chegada:{atendimento_id}"


@pytest.mark.needs_db
async def test_card_chegada_entrega_e_marca_owner(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Regressão E2E 2026-06-10: `_card_chegada` ordenava por `e.created_at`, coluna que
    `barravips.escaladas` NAO tem (a de tempo é `aberta_em`) -> UndefinedColumn em todo
    card de chegada, e a modelo nunca era avisada que o cliente chegou. Só pega contra o
    schema real: o teste roda o renderer e exige POST + gravação do `card_message_id`."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id, _ = await _seed_atendimento_interno_aguardando(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _seed_msg_imagem(conn, conversa_id)

    # handoff implicito cria a escalada owner (foto_portaria, card_message_id NULL).
    redis = _redis_fake()
    ctx_handoff = _ctx(_PoolDeUmaConexao(conn), redis)
    res = await conn.execute(
        "SELECT evolution_message_id FROM barravips.mensagens WHERE conversa_id = %s",
        (conversa_id,),
    )
    row = await res.fetchone()
    assert row is not None
    await rotear_imagem(
        ctx_handoff,
        mensagem_id=row["evolution_message_id"],
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/portaria.jpg",
        caption=None,
    )

    # roda o renderer do card 'chegada' com evolution/minio mockados.
    evolution = AsyncMock()
    evolution.enviar_midia = AsyncMock(return_value="card-mid-chegada")
    evolution.enviar_texto = AsyncMock(return_value="card-mid-chegada")
    minio = AsyncMock()
    minio.presigned_get_object = lambda *a, **k: "https://minio.test/portaria.jpg"
    ctx_card: dict[str, Any] = {
        "db_pool": _PoolDeUmaConexao(conn),
        "evolution": evolution,
        "minio": minio,
        "settings": get_settings(),
    }

    await _card_chegada(ctx_card, atendimento_id=str(atendimento_id))

    # 1. Card foi efetivamente postado na Coordenação (foto + caption).
    assert evolution.enviar_midia.await_count == 1

    # 2. `card_message_id` gravado na escalada owner (idempotência por owner).
    res = await conn.execute(
        "SELECT card_message_id FROM barravips.escaladas "
        "WHERE atendimento_id = %s AND tipo = 'foto_portaria'",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["card_message_id"] == "card-mid-chegada"
