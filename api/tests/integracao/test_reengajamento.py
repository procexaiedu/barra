"""M5f -- `reengajar_silenciosos` contra o Postgres real, Redis e settings em memoria.

`needs_db` (Postgres via TEST_DATABASE_URL); o Redis e o `fakeredis` com `enqueue_job` mockado
(o FakeRedis nao tem). Um fake-pool de UMA conexao reusa a transacao do teste -> ROLLBACK
limpa tudo. Os settings sao construidos por `model_copy(update=...)` p/ cada cenario.

Cobre:
  - flag_off: nao consulta o banco, nao enfileira.
  - happy: alvo qualificado dentro do horario -> 1 toque enfileirado + reengajado_em marcado;
    2a varredura imediatamente depois nao reabre (idempotencia da coluna).
  - fora_horario: monkeypatch em `_dentro_da_janela` retornando False -> 0 alvos.
  - ja_reengajado: reengajado_em setado -> filtro do WHERE descarta.
  - cliente_respondeu: ultima msg do cliente recente (dentro do delay) -> 0 alvos.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra import workers
from barra.settings import get_settings
from barra.workers.timeouts import _dentro_da_janela, reengajar_silenciosos

# --- infra de DB real (ROLLBACK sempre) + Redis efemero --------------------------------------


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
    """Mesmo padrao do test_coordenador_basico: todo .connection() devolve a MESMA conexao,
    sem commit nem close (o teardown da fixture faz rollback)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _settings(**over: Any) -> Any:
    base = {
        "reengajamento_ativo": True,
        "reengajamento_delay_min": 30,
        "operacao_hora_inicio": 0,
        "operacao_hora_fim": 0,  # inicio == fim -> janela cobre 24h (_dentro_da_janela)
    }
    base.update(over)
    return get_settings().model_copy(update=base)


# --- seeds -----------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Reengajo", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
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
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    *,
    estado: str = "Qualificado",
    intencao: str = "cotacao",
    ia_pausada: bool = False,
    reengajado_em: datetime | None = None,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, intencao,
             ia_pausada, reengajado_em, fonte_decisao_ultima_transicao)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.intencao_enum, %s, %s, 'extracao_ia')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado,
         intencao, ia_pausada, reengajado_em),
    )
    return atendimento_id


async def _seed_msg_cliente(
    c: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    atendimento_id: UUID,
    *,
    minutos_atras: int,
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
            "qual valor amor",
            f"test-evo-{uuid4().hex}",
            datetime.now(UTC) - timedelta(minutes=minutos_atras),
        ),
    )


async def _seed_cenario_padrao(
    c: AsyncConnection[dict[str, Any]],
    *,
    minutos_silencio: int = 40,
    estado: str = "Qualificado",
    intencao: str = "cotacao",
    ia_pausada: bool = False,
    reengajado_em: datetime | None = None,
) -> tuple[UUID, UUID]:
    modelo_id = await _seed_modelo(c)
    cliente_id = await _seed_cliente(c)
    conversa_id = await _seed_conversa(c, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        c, cliente_id, modelo_id, conversa_id,
        estado=estado, intencao=intencao, ia_pausada=ia_pausada,
        reengajado_em=reengajado_em,
    )
    await _seed_msg_cliente(c, conversa_id, atendimento_id, minutos_atras=minutos_silencio)
    return atendimento_id, conversa_id


# --- unit do helper (sem DB) -----------------------------------------------------------------


def test_dentro_da_janela_normal() -> None:
    # 10..18 (sem cruzar meia-noite)
    assert _dentro_da_janela(10, 10, 18) is True
    assert _dentro_da_janela(17, 10, 18) is True
    assert _dentro_da_janela(18, 10, 18) is False  # fim exclusivo
    assert _dentro_da_janela(9, 10, 18) is False


def test_dentro_da_janela_cruza_meia_noite() -> None:
    # 10..2 (default): cobre 10..23 e 0..1
    assert _dentro_da_janela(10, 10, 2) is True
    assert _dentro_da_janela(23, 10, 2) is True
    assert _dentro_da_janela(0, 10, 2) is True
    assert _dentro_da_janela(1, 10, 2) is True
    assert _dentro_da_janela(2, 10, 2) is False
    assert _dentro_da_janela(9, 10, 2) is False


def test_dentro_da_janela_24h() -> None:
    # fim == inicio: janela cobre 24h (usado nos testes integrados para neutralizar horario)
    for h in range(24):
        assert _dentro_da_janela(h, 0, 0) is True


# --- testes integrados -----------------------------------------------------------------------


@pytest.mark.needs_db
async def test_flag_off_nao_age(conn: AsyncConnection[dict[str, Any]]) -> None:
    await _seed_cenario_padrao(conn)
    redis = _redis_fake()
    total = await reengajar_silenciosos(conn, redis, _settings(reengajamento_ativo=False))
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_alvo_qualificado_envia_e_marca_reengajado_em(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, conversa_id = await _seed_cenario_padrao(conn)
    redis = _redis_fake()

    total = await reengajar_silenciosos(conn, redis, _settings())
    assert total == 1

    # reengajado_em foi marcado pela CTE.
    res = await conn.execute(
        "SELECT reengajado_em FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None and row["reengajado_em"] is not None

    # 1 enqueue de enviar_turno + turno_atual setado no Redis.
    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    args, kwargs = calls[0].args, calls[0].kwargs
    assert args[0] == "enviar_turno"
    assert kwargs["conversa_id"] == str(conversa_id)
    assert kwargs["midias"] == []
    assert kwargs["critico"] is False
    assert len(kwargs["chunks"]) == 1
    assert kwargs["chunks"][0]  # frase canned nao-vazia
    assert kwargs["_job_id"] == f"reengajo:{atendimento_id}"

    turno_atual = await redis.get(f"turno_atual:{conversa_id}")
    assert turno_atual is not None and turno_atual.decode() == kwargs["turno_id"]

    # Idempotencia: 2a varredura imediatamente depois nao reabre (reengajado_em IS NOT NULL).
    redis2 = _redis_fake()
    total2 = await reengajar_silenciosos(conn, redis2, _settings())
    assert total2 == 0
    assert redis2.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_fora_do_horario_nao_age(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_cenario_padrao(conn)
    monkeypatch.setattr(
        "barra.workers.timeouts._dentro_da_janela", lambda *_a, **_kw: False
    )
    redis = _redis_fake()
    total = await reengajar_silenciosos(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_ja_reengajado_nao_reabre(conn: AsyncConnection[dict[str, Any]]) -> None:
    await _seed_cenario_padrao(
        conn,
        reengajado_em=datetime.now(UTC) - timedelta(hours=1),
    )
    redis = _redis_fake()
    total = await reengajar_silenciosos(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_cliente_respondeu_recentemente_nao_dispara(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # silencio < reengajamento_delay_min (30) -> filtro do WHERE descarta.
    await _seed_cenario_padrao(conn, minutos_silencio=5)
    redis = _redis_fake()
    total = await reengajar_silenciosos(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


# Anti-import-quebrado: garante que o submodulo workers existe no namespace
# (caso o teste de cima tenha um typo de import, falha aqui mais cedo).
def test_modulo_workers_importavel() -> None:
    assert workers is not None
