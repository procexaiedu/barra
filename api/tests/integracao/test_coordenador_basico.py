"""M3b — `processar_turno` (coordenador) contra o Postgres real, LLM e Redis mockados.

`needs_db` (Postgres via TEST_DATABASE_URL), nao `needs_key`: o grafo e MOCKADO (objeto fake que
devolve uma AIMessage), o Redis e o `fakeredis` (com `enqueue_job` trocado por AsyncMock, que o
FakeRedis nao tem). Um fake-pool de UMA conexao faz `resolver_atendimento`/`atualizar_orfaos`/
gates lerem a MESMA transacao — `conn.transaction()` interno vira SAVEPOINT (a conexao ja esta
em transacao por causa do seed), entao NADA commita; o ROLLBACK do teardown descarta tudo.

Cobre:
  - test_coordenador_basico: resolve/cria o atendimento, vincula mensagens orfas, invoca o grafo
    e despacha `enviar_turno`.
  - test_drain_excede_max: pending sempre cheio -> estoura MAX_DRAIN e re-enfileira processar_turno
    (`_job_id=turno:{id}`), 09 §4.9 / 07 §3.
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
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings
from barra.workers.coordenador import MAX_DRAIN, processar_turno

# --- grafo mockado ---------------------------------------------------------------------------


# `usage_metadata` simula uma AIMessage GERADA pelo LLM (criterio de filtro do
# _extrair_texto_do_turno; sem ele a msg e tratada como historica re-injetada e ignorada).
_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _GrafoFake:
    """ainvoke devolve uma AIMessage fixa e conta as invocacoes."""

    def __init__(self, texto: str = "oi amor") -> None:
        self._texto = texto
        self.chamadas = 0

    async def ainvoke(
        self, entrada: Any, *, config: Any = None, context: Any = None
    ) -> dict[str, Any]:
        self.chamadas += 1
        return {"messages": [AIMessage(content=self._texto, usage_metadata=_USAGE)]}


class _GrafoFakeDrena:
    """ainvoke re-seta o pending a cada chamada — simula msgs chegando com o lock retido."""

    def __init__(self, redis: FakeRedis, conversa_id: str, texto: str = "oi") -> None:
        self._redis = redis
        self._conversa_id = conversa_id
        self._texto = texto
        self.chamadas = 0

    async def ainvoke(
        self, entrada: Any, *, config: Any = None, context: Any = None
    ) -> dict[str, Any]:
        self.chamadas += 1
        await self._redis.set(f"pending:conv:{self._conversa_id}", "1")
        return {"messages": [AIMessage(content=self._texto, usage_metadata=_USAGE)]}


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
    """Pool fake de UMA conexao: todo `.connection()` devolve a MESMA conexao, sem commit nem
    close (o teardown da fixture faz rollback). Os `conn.transaction()` do coordenador viram
    savepoints aninhados na transacao corrente -> zero persistencia."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _ctx(pool: _PoolDeUmaConexao, redis: FakeRedis, graph: Any) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": pool,
        "graph": graph,
        "settings": get_settings(),
        "job_id": "job-test",
        "score": 1_700_000_000_000,  # ms timestamp injetado pelo ARQ por job
    }


# --- seeds (espelham test_loop_leitura / test_repo_integracao) -------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
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


async def _seed_msg_cliente_orfa(c: AsyncConnection[dict[str, Any]], conversa_id: UUID) -> UUID:
    """Mensagem do cliente com atendimento_id=NULL (orfa) e evolution_message_id setado."""
    mensagem_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s, %s)
        """,
        (mensagem_id, conversa_id, "oi, quanto é?", f"test-evo-{uuid4().hex}", datetime.now(UTC)),
    )
    return mensagem_id


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_coordenador_basico(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    mensagem_id = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    graph = _GrafoFake(texto="oi amor")
    ctx = _ctx(_PoolDeUmaConexao(conn), redis, graph)

    await redis.set(f"pending:conv:{conversa_id}", "1")  # gate de pendencia do coordenador
    await processar_turno(ctx, conversa_id=str(conversa_id))

    # 1. resolveu/criou o atendimento (estado Novo) para a conversa.
    res = await conn.execute(
        "SELECT id, estado::text AS estado FROM barravips.atendimentos WHERE conversa_id = %s",
        (conversa_id,),
    )
    atendimentos = await res.fetchall()
    assert len(atendimentos) == 1
    assert atendimentos[0]["estado"] == "Novo"
    atendimento_id = atendimentos[0]["id"]

    # 2. vinculou a mensagem orfa ao atendimento.
    res = await conn.execute(
        "SELECT atendimento_id FROM barravips.mensagens WHERE id = %s", (mensagem_id,)
    )
    row = await res.fetchone()
    assert row is not None
    assert row["atendimento_id"] == atendimento_id

    # 3. invocou o grafo.
    assert graph.chamadas == 1

    # 4. despachou enviar_turno com o texto do grafo + a msg do cliente (read receipt).
    calls = redis.enqueue_job.call_args_list
    envios = [c for c in calls if c.args and c.args[0] == "enviar_turno"]
    assert len(envios) == 1
    kwargs = envios[0].kwargs
    assert kwargs["conversa_id"] == str(conversa_id)
    assert kwargs["chunks"] == ["oi amor"]
    assert kwargs["critico"] is False
    assert kwargs["midias"] == []
    assert len(kwargs["msg_ids_cliente"]) == 1
    assert kwargs["_job_id"] == f"turno_envio:{kwargs['turno_id']}"

    # nao re-enfileirou processar_turno (sem pending pendente).
    assert not [c for c in calls if c.args and c.args[0] == "processar_turno"]


@pytest.mark.needs_db
async def test_defer_humano_no_envio_e_judge_alinhado(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fio fim-a-fim do defer humano (05 §4.1): processar_turno despacha enviar_turno com
    _defer_by e o judge pós-envio acompanha (120 + defer) — senão ele dispara antes do fire,
    lê `enviados:` vazio e perde a telemetria (max_tries=1)."""
    from barra.settings import get_settings as _gs
    from barra.workers import coordenador as coord_mod

    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    await _seed_msg_cliente_orfa(conn, conversa_id)

    settings_judge_on = _gs().model_copy(update={"judge_pos_envio_ativo": True})
    monkeypatch.setattr(coord_mod, "get_settings", lambda: settings_judge_on)
    monkeypatch.setattr(coord_mod, "amostrar_defer_humano_s", lambda **_kw: 33)

    redis = _redis_fake()
    graph = _GrafoFake(texto="oi amor")
    ctx = _ctx(_PoolDeUmaConexao(conn), redis, graph)

    await redis.set(f"pending:conv:{conversa_id}", "1")
    await processar_turno(ctx, conversa_id=str(conversa_id))

    calls = redis.enqueue_job.call_args_list
    envios = [c for c in calls if c.args and c.args[0] == "enviar_turno"]
    assert len(envios) == 1
    assert envios[0].kwargs["_defer_by"] == 33

    judges = [c for c in calls if c.args and c.args[0] == "julgar_turno_pos_envio"]
    assert len(judges) == 1
    assert judges[0].kwargs["_defer_by"] == 120 + 33


@pytest.mark.needs_db
async def test_drain_excede_max(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    graph = _GrafoFakeDrena(redis, str(conversa_id))  # re-seta pending a cada turno
    ctx = _ctx(_PoolDeUmaConexao(conn), redis, graph)

    await redis.set(f"pending:conv:{conversa_id}", "1")  # gate de pendencia do coordenador
    await processar_turno(ctx, conversa_id=str(conversa_id))

    # estourou o teto de drain: o grafo rodou MAX_DRAIN vezes sob o MESMO lock.
    assert graph.chamadas == MAX_DRAIN

    # ao estourar, re-enfileirou processar_turno com _job_id estavel (libera o lock).
    calls = redis.enqueue_job.call_args_list
    reenq = [c for c in calls if c.args and c.args[0] == "processar_turno"]
    assert len(reenq) == 1
    assert reenq[0].kwargs["_job_id"] == f"turno:{conversa_id}"
    assert reenq[0].kwargs["conversa_id"] == str(conversa_id)
