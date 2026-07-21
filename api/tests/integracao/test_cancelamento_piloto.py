"""`cancelar_piloto_teste` contra o Postgres real (ADR-0033, spec 0004).

`needs_db` (Postgres via TEST_DATABASE_URL); o Redis e o `fakeredis` com `enqueue_job` mockado
(o FakeRedis nao tem). A conexao da fixture e passada DIRETO pra `cancelar_piloto_teste` (que
recebe `conn`, nao pool) -> ROLLBACK no teardown limpa tudo. Mesmo padrao de
`test_reengajamento.py`/`test_timeout_interno.py`.

Gatilho ancorado em `aguardando_confirmacao_em` (carimbado na transicao para Aguardando_confirmacao,
`dominio/atendimentos/service.py`), distinto de `bloqueios.inicio` (o horario do encontro em si).

Cobre:
  - flag_off: nao consulta/nao age, mesmo com atendimento elegivel.
  - happy: entrou em Aguardando_confirmacao ha > 10min -> Perdido/outro + observacao de auditoria,
    IA pausada (handoff aberto, ia_pausada=true), bloqueio cancelado, desculpa enfileirada.
  - recente: entrou ha < 10min -> intacto.
  - ja_processado: `piloto_cancelado_em` ja setado -> idempotente, nao reprocessa.
  - sem_ancora: `aguardando_confirmacao_em` NULL (atendimento pre-existente sem o carimbo) -> intacto.
  - estado_errado: atendimento em outro estado (ex. Confirmado) -> fora de escopo do cron.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings
from barra.workers.timeouts import cancelar_piloto_teste

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


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _settings(**over: Any) -> Any:
    base: dict[str, Any] = {"piloto_auto_cancela_ativo": True}
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
        (modelo_id, "Modelo Piloto", 25, f"test-wpp-{uuid4().hex}", 500, ["externo"]),
    )
    return modelo_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    estado: str = "Aguardando_confirmacao",
    aguardando_confirmacao_min_atras: float | None = 15,
    piloto_cancelado: bool = False,
    bloqueio_estado: str = "bloqueado",
) -> tuple[UUID, UUID, UUID]:
    """Atendimento em `estado` (default Aguardando_confirmacao), com bloqueio vinculado.

    `aguardando_confirmacao_min_atras=None` deixa a coluna NULL (atendimento sem a ancora, ex.
    pre-existente a migration). Devolve (atendimento_id, conversa_id, bloqueio_id)."""
    modelo_id = await _seed_modelo(c)
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    atendimento_id = uuid4()
    aguardando_em = (
        None
        if aguardando_confirmacao_min_atras is None
        else datetime.now(UTC) - timedelta(minutes=aguardando_confirmacao_min_atras)
    )
    piloto_cancelado_em = datetime.now(UTC) - timedelta(minutes=5) if piloto_cancelado else None
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             aguardando_confirmacao_em, piloto_cancelado_em, fonte_decisao_ultima_transicao)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                'externo'::barravips.tipo_atendimento_enum, %s, %s, 'extracao_ia')
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            aguardando_em,
            piloto_cancelado_em,
        ),
    )
    bloqueio_id = uuid4()
    inicio = datetime.now(UTC) + timedelta(hours=1)
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (
            bloqueio_id,
            modelo_id,
            atendimento_id,
            inicio,
            inicio + timedelta(hours=2),
            bloqueio_estado,
        ),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return atendimento_id, conversa_id, bloqueio_id


# --- testes integrados -----------------------------------------------------------------------


@pytest.mark.needs_db
async def test_flag_off_nao_age(conn: AsyncConnection[dict[str, Any]]) -> None:
    await _seed_atendimento(conn)
    redis = _redis_fake()
    total = await cancelar_piloto_teste(conn, redis, _settings(piloto_auto_cancela_ativo=False))
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_cancela_apos_10min_perdido_pausa_ia_e_cancela_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, conversa_id, bloqueio_id = await _seed_atendimento(
        conn, aguardando_confirmacao_min_atras=15
    )
    redis = _redis_fake()

    total = await cancelar_piloto_teste(conn, redis, _settings())
    assert total == 1

    res = await conn.execute(
        "SELECT estado::text AS estado, motivo_perda::text AS motivo_perda, motivo_perda_obs, "
        "ia_pausada, piloto_cancelado_em, fonte_decisao_ultima_transicao::text AS fonte "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Perdido"
    assert a["motivo_perda"] == "outro"
    assert a["motivo_perda_obs"] == "cancelamento automático — piloto de teste"
    assert a["ia_pausada"] is True
    assert a["piloto_cancelado_em"] is not None
    assert a["fonte"] == "auto_cancelamento_piloto"

    # Handoff manual aberto (ADR-0032/0033): escalada de pausa, sem fechada_em.
    res = await conn.execute(
        "SELECT tipo::text AS tipo FROM barravips.escaladas "
        "WHERE atendimento_id = %s AND fechada_em IS NULL",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["tipo"] == "pausa_manual_operador"

    # Bloqueio vinculado sincronizado.
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bloqueio_id,)
    )
    b = await res.fetchone()
    assert b is not None and b["estado"] == "cancelado"

    # Eventos de auditoria emitidos.
    res = await conn.execute(
        "SELECT tipo::text AS tipo FROM barravips.eventos WHERE atendimento_id = %s ORDER BY tipo",
        (atendimento_id,),
    )
    tipos = {r["tipo"] async for r in res}
    assert {"transicao_estado", "perdido_registrado", "handoff_aberto"} <= tipos

    # Desculpa enfileirada via enviar_turno + turno_atual setado no Redis.
    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    _args, kwargs = calls[0].args, calls[0].kwargs
    assert kwargs["conversa_id"] == str(conversa_id)
    assert kwargs["midias"] == []
    # Critico: a desculpa nao pode ser cancelada pelo gate de pausa (a IA acabou de ser pausada)
    # nem pelo cancel-on-new-message (o cliente esperando confirmacao costuma escrever no meio).
    assert kwargs["critico"] is True
    assert len(kwargs["chunks"]) == 1
    assert kwargs["chunks"][0]
    assert kwargs["_job_id"] == f"cancelamento_piloto:{atendimento_id}"
    turno_atual = await redis.get(f"turno_atual:{conversa_id}")
    assert turno_atual is not None and turno_atual.decode() == kwargs["turno_id"]


@pytest.mark.needs_db
async def test_ignora_menos_de_10min(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id, _conversa_id, bloqueio_id = await _seed_atendimento(
        conn, aguardando_confirmacao_min_atras=5
    )
    redis = _redis_fake()

    total = await cancelar_piloto_teste(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []

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
async def test_ja_processado_nao_reprocessa(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id, _conversa_id, _bloqueio_id = await _seed_atendimento(
        conn, aguardando_confirmacao_min_atras=20, piloto_cancelado=True
    )
    redis = _redis_fake()

    total = await cancelar_piloto_teste(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None and a["estado"] == "Aguardando_confirmacao"


@pytest.mark.needs_db
async def test_sem_ancora_nao_dispara(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Atendimento pre-existente a migration (sem aguardando_confirmacao_em carimbado): o cron
    # nao inventa uma ancora — fica de fora ate a proxima transicao real.
    await _seed_atendimento(conn, aguardando_confirmacao_min_atras=None)
    redis = _redis_fake()

    total = await cancelar_piloto_teste(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_estado_fora_de_aguardando_confirmacao_nao_dispara(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    await _seed_atendimento(
        conn,
        estado="Confirmado",
        aguardando_confirmacao_min_atras=30,
        bloqueio_estado="em_atendimento",
    )
    redis = _redis_fake()

    total = await cancelar_piloto_teste(conn, redis, _settings())
    assert total == 0
    assert redis.enqueue_job.call_args_list == []


# Anti-import-quebrado.
def test_modulo_workers_importavel() -> None:
    from barra import workers

    assert workers is not None
