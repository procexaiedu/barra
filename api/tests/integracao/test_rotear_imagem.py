"""M5b — `rotear_imagem` sob lock:conv (06 §2.1).

Testes contra Postgres real (`needs_db`) com Redis efemero (fakeredis) e `enqueue_job` mockado.

Cobre os 5 caminhos de decisao (06 §2.1):
  - test_pix_aguardando: Aguardando_confirmacao + pix_status='aguardando' -> enqueue validar_pix
  - test_interno: Aguardando_confirmacao + tipo_atendimento='interno' -> chama stub _handoff_foto_portaria
  - test_fora_fluxo_com_legenda: caption setado -> enfileira processar_turno
  - test_fora_fluxo_pura: sem legenda + sem atendimento aberto -> silencio
  - test_lock_busy: lock:conv pre-adquirido -> re-enfileira rotear_imagem com _defer_by
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings
from barra.workers.media import rotear_imagem

# --- infra: pool de UMA conexao + redis fake (espelha test_coordenador_basico) ---------------


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
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _ctx(pool: _PoolDeUmaConexao, redis: FakeRedis) -> dict[str, Any]:
    return {"redis": redis, "db_pool": pool, "settings": get_settings()}


# --- seeds -----------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
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


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    estado: str,
    tipo_atendimento: str,
    pix_status: str,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                %s::barravips.pix_status_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status),
    )
    return atendimento_id


async def _seed_msg_cliente_orfa(c: AsyncConnection[dict[str, Any]], conversa_id: UUID) -> UUID:
    mensagem_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id,
             created_at)
        VALUES (%s, %s, 'cliente', 'imagem', '', %s, %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg",
            f"test-evo-{uuid4().hex}",
            datetime.now(UTC),
        ),
    )
    return mensagem_id


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_pix_aguardando(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Aguardando_confirmacao + pix_status='aguardando' -> enqueue validar_pix com _job_id estavel."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="externo",
        pix_status="aguardando",
    )
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=str(mensagem_id),
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/img.jpg",
        caption=None,
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("validar_pix",)
    kwargs = calls[0].kwargs
    assert kwargs["mensagem_id"] == str(mensagem_id)
    assert kwargs["atendimento_id"] == str(atendimento_id)
    assert kwargs["media_url"] == "https://evolution.test/img.jpg"
    assert kwargs["_job_id"] == f"pix:{atendimento_id}:{mensagem_id}"


@pytest.mark.needs_db
async def test_interno_aciona_foto_portaria(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Aguardando_confirmacao + interno (sem Pix em curso) -> chama _handoff_foto_portaria (stub M5d)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        pix_status="nao_solicitado",
    )
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    with pytest.raises(NotImplementedError, match="M5d"):
        await rotear_imagem(
            ctx,
            mensagem_id=str(mensagem_id),
            conversa_id=str(conversa_id),
            media_url="https://evolution.test/portaria.jpg",
            caption=None,
        )

    # Stub falha antes de qualquer enqueue.
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_fora_fluxo_com_legenda_enfileira_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fora-fluxo COM legenda: IA cega responde a legenda -> enfileira processar_turno (06 §3)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    # estado fora dos dois branches: Novo e nao-interno (ou interno, mas estado != Aguardando).
    await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Triagem",
        tipo_atendimento="externo",
        pix_status="nao_solicitado",
    )
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=str(mensagem_id),
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/foto-aleatoria.jpg",
        caption="olha que linda essa selfie minha",
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("processar_turno",)
    assert calls[0].kwargs["conversa_id"] == str(conversa_id)
    assert calls[0].kwargs["_job_id"] == f"turno:{conversa_id}"


@pytest.mark.needs_db
async def test_fora_fluxo_sem_legenda_fica_em_silencio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem atendimento aberto e sem legenda: IA cega fica calada (06 §3)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    # Sem atendimento aberto: resolver_atendimento_existente devolve None -> silencio.
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=str(mensagem_id),
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/nada.jpg",
        caption=None,
    )

    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_lock_busy_redefer(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Lock pre-adquirido (turno de texto em voo): re-enfileira rotear_imagem com _defer_by."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    # Simula turno de texto retendo o lock — o adquirir_lock vai erguer LockBusy.
    await redis.set(f"lock:conv:{conversa_id}", "outro-worker", ex=60)

    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=str(mensagem_id),
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/img.jpg",
        caption=None,
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("rotear_imagem",)
    kwargs = calls[0].kwargs
    assert kwargs["mensagem_id"] == str(mensagem_id)
    assert kwargs["conversa_id"] == str(conversa_id)
    assert kwargs["caption"] is None
    assert "_defer_by" in kwargs
