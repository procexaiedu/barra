"""M5e — enviar_midia (rotacao + call_idx + idempotencia) contra Postgres real (04 §3.3).

Exercita a tool pela MECANICA real do grafo (ToolNode subclass injeta `call_idx` ordinal), com o
LLM MOCKADO (script de AIMessages) -- `needs_db`, nao `needs_key`. Um fake-pool de UMA conexao
deixa prepare_context, a tool e as assercoes lerem a MESMA transacao; ROLLBACK no teardown (nada
commita no banco prod self-hosted). Espelha test_loop_leitura.py.

Cobertura:
- (a) `NULLS FIRST, created_at` escolhe a foto nunca enviada no 1o call; a 2a chamada exclui
      essa via `NOT (id = ANY(...))` e cai na 2a menos-recente.
- (b) `barravips.tool_calls` tem 2 linhas com `call_idx=0,1` -- prova que `_ToolNodeComMidiaIdx`
      injetou o indice ordinal nas chamadas de `enviar_midia` antes de delegar.
- (c) Replay (mesmo `turno_id`, mesma sequencia) -> ON CONFLICT deduplica, NAO cria 2 novas
      linhas (count permanece 2) e NAO re-executa `_registrar_envio_midia`.
- (d) `modelo_midia.ultimo_envio_em` foi atualizado nas 2 fotos escolhidas; a 3a (recente, nao
      escolhida) ficou intocada.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.workers.envio import _enviar_midias

# --- LLM mockado ---------------------------------------------------------------------------


class _FakeChat:
    """Chat roteirizado: bind_tools devolve self; ainvoke devolve o proximo AIMessage do script."""

    model = "claude-sonnet-4-6"

    def __init__(self, scripts: list[AIMessage]) -> None:
        self._scripts = scripts
        self._i = 0
        self.vistas: list[list[Any]] = []

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **_kw: Any) -> "_FakeChat":
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.vistas.append(messages)
        msg = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        return msg

    def resetar(self) -> None:
        """Replay no mesmo grafo: volta ao script[0] e zera o historico de visoes."""
        self._i = 0
        self.vistas = []


def _ai_1_midia(tag: str) -> AIMessage:
    """AIMessage com UMA chamada de `enviar_midia` na `tag` pedida."""
    return AIMessage(
        content="ja te mando 😏",
        tool_calls=[
            {"name": "enviar_midia", "args": {"tag": tag}, "id": "call_1", "type": "tool_call"},
        ],
    )


def _ai_2_midias(tag: str) -> AIMessage:
    """AIMessage com DUAS chamadas paralelas de `enviar_midia` na MESMA tag.

    O `_ToolNodeComMidiaIdx` deve anotar `call_idx=0` na 1a e `call_idx=1` na 2a, na ordem do
    array `tool_calls` (estavel, 04 §3.3 nota).
    """
    return AIMessage(
        content="ja te mando 😏",
        tool_calls=[
            {"name": "enviar_midia", "args": {"tag": tag}, "id": "call_1", "type": "tool_call"},
            {"name": "enviar_midia", "args": {"tag": tag}, "id": "call_2", "type": "tool_call"},
        ],
    )


# --- infra de DB real (ROLLBACK sempre) ----------------------------------------------------


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
    """Pool fake de UMA conexao serializada por asyncio.Lock.

    Em prod o pool real entrega UMA conexao por concorrente; no teste a mesma conn e
    compartilhada (p/ que a transacao com ROLLBACK abrace o turno inteiro), e o ToolNode
    roda as tool_calls em `asyncio.gather` (`_afunc`). Sem o lock, 2 `conn.transaction()`
    paralelos disparam `OutOfOrderTransactionNesting` no psycopg (a conn async nao suporta
    operacoes concorrentes). O lock serializa: replica o comportamento de prod (uma
    conexao por critical section), mantendo a transacao unica do teste.
    """

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        async with self._lock:
            yield self._conn


async def _garantir_coluna_ultimo_envio_em(connection: AsyncConnection[dict[str, Any]]) -> None:
    """Aplica a migration `<ts>_modelo_midia_ultimo_envio.sql` (IF NOT EXISTS) dentro da
    transacao do teste -- desfeita pelo ROLLBACK do teardown.

    Em prod self-hosted, a migration sera aplicada pelo orquestrador no merge (memoria
    `migrations_pendentes_prod_selfhosted`); ate la, o teste a aplica e desfaz.
    """
    await connection.execute(
        "ALTER TABLE barravips.modelo_midia ADD COLUMN IF NOT EXISTS ultimo_envio_em timestamptz"
    )


# --- seeds (espelham test_loop_leitura) -----------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo M5e", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
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
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento)
        VALUES (%s, 1, %s, %s, %s, 'Triagem', 'interno')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _seed_mensagem(c: AsyncConnection[dict[str, Any]], *, conversa_id: UUID) -> None:
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s, %s)
        """,
        (
            uuid4(),
            conversa_id,
            "manda uma foto sua",
            f"test-evo-{uuid4().hex}",
            datetime.now(UTC),
        ),
    )


async def _seed_3_midias(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, tag: str
) -> dict[str, UUID]:
    """3 fotos da tag, `ultimo_envio_em` distintos. Ordem esperada por
    `ORDER BY ultimo_envio_em NULLS FIRST, created_at`:

        1. `nunca`    (ultimo_envio_em = NULL)
        2. `ja_velha` (2026-01-01)
        3. `recente`  (2026-02-01)
    """
    ja_velha, recente, nunca = uuid4(), uuid4(), uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelo_midia
            (id, modelo_id, tipo, tag, bucket, object_key, aprovada,
             ultimo_envio_em, created_at)
        VALUES
            (%s, %s, 'foto', %s, 'media', %s, true,
             '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            (%s, %s, 'foto', %s, 'media', %s, true,
             '2026-02-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00'),
            (%s, %s, 'foto', %s, 'media', %s, true,
             NULL,                        '2026-01-03T00:00:00+00:00')
        """,
        (
            ja_velha,
            modelo_id,
            tag,
            f"media/{ja_velha}.jpg",
            recente,
            modelo_id,
            tag,
            f"media/{recente}.jpg",
            nunca,
            modelo_id,
            tag,
            f"media/{nunca}.jpg",
        ),
    )
    return {"ja_velha": ja_velha, "recente": recente, "nunca": nunca}


async def _seed_1_midia(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, tag: str, tipo: str = "foto"
) -> UUID:
    """Uma unica midia aprovada com a `tag` dada (sem `ultimo_envio_em` -> topo da rotacao)."""
    midia_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelo_midia
            (id, modelo_id, tipo, tag, bucket, object_key, aprovada, created_at)
        VALUES (%s, %s, %s::barravips.midia_tipo_enum, %s, 'media', %s, true,
                '2026-01-01T00:00:00+00:00')
        """,
        (midia_id, modelo_id, tipo, tag, f"media/{midia_id}.jpg"),
    )
    return midia_id


def _contexto(
    pool: _PoolDeUmaConexao,
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    cliente_id: UUID,
    turno_id: str,
) -> ContextAgente:
    return ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=turno_id,
    )


# --- teste ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_enviar_midia_rotacao_call_idx_e_idempotencia(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _garantir_coluna_ultimo_envio_em(conn)
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _seed_mensagem(conn, conversa_id=conversa_id)
    fotos = await _seed_3_midias(conn, modelo_id, tag="apresentacao")

    fake = _FakeChat([_ai_2_midias("apresentacao"), AIMessage(content="ta ai amor 😘")])
    # Caminhos de texto sao DeepSeek-only -> _criar_chat_principal/extracao chamam criar_chat_deepseek;
    # mocka o factory com o fake p/ o teste não escapar pra API real (§0).
    monkeypatch.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: fake)

    graph = build_graph()
    turno_id = str(uuid4())
    contexto = _contexto(
        _PoolDeUmaConexao(conn),
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        cliente_id=cliente_id,
        turno_id=turno_id,
    )

    # 1a execucao --------------------------------------------------------------------------
    await graph.ainvoke({"messages": []}, config={"recursion_limit": 18}, context=contexto)

    # (b) tool_calls tem 2 linhas com call_idx 0 e 1
    res = await conn.execute(
        """
        SELECT call_idx,
               payload->>'midia_id' AS midia_id,
               payload->>'tag'      AS tag,
               payload->>'tipo'     AS tipo
          FROM barravips.tool_calls
         WHERE turno_id = %s AND tool_name = 'enviar_midia'
         ORDER BY call_idx
        """,
        (turno_id,),
    )
    linhas = await res.fetchall()
    assert [r["call_idx"] for r in linhas] == [0, 1]

    # (a) menos-recente (nunca, NULLS FIRST) no 1o call; 2a menos-recente (ja_velha) no 2o
    assert UUID(linhas[0]["midia_id"]) == fotos["nunca"]
    assert UUID(linhas[1]["midia_id"]) == fotos["ja_velha"]
    # ambas as chamadas usaram a tag pedida e tipo foto (default).
    assert all(r["tag"] == "apresentacao" and r["tipo"] == "foto" for r in linhas)

    # (d) ultimo_envio_em foi atualizado nas 2 escolhidas; a recente (nao escolhida) intocada.
    res = await conn.execute(
        "SELECT id, ultimo_envio_em FROM barravips.modelo_midia WHERE modelo_id = %s",
        (modelo_id,),
    )
    estados_pos = {r["id"]: r["ultimo_envio_em"] for r in await res.fetchall()}
    nunca_apos = estados_pos[fotos["nunca"]]
    velha_apos = estados_pos[fotos["ja_velha"]]
    recente_apos = estados_pos[fotos["recente"]]
    assert nunca_apos is not None  # era NULL -> agora setada por now()
    assert velha_apos is not None and velha_apos > datetime(2026, 1, 1, tzinfo=UTC)
    assert recente_apos == datetime(2026, 2, 1, tzinfo=UTC)  # nao escolhida -> intocada

    # Replay (c) ---------------------------------------------------------------------------
    # mesma sequencia, MESMO turno_id -> ON CONFLICT na PK (turno_id,'enviar_midia',call_idx)
    # devolve o payload anterior sem rodar `_registrar_envio_midia`. count nao cresce p/ 4.
    fake.resetar()
    await graph.ainvoke({"messages": []}, config={"recursion_limit": 18}, context=contexto)

    res = await conn.execute(
        """
        SELECT count(*) AS n
          FROM barravips.tool_calls
         WHERE turno_id = %s AND tool_name = 'enviar_midia'
        """,
        (turno_id,),
    )
    cont = await res.fetchone()
    assert cont is not None and cont["n"] == 2  # ainda 2, nao 4

    # E a midia 'recente' continua intocada apos o replay (defesa adicional).
    res = await conn.execute(
        "SELECT ultimo_envio_em FROM barravips.modelo_midia WHERE id = %s",
        (fotos["recente"],),
    )
    rec = await res.fetchone()
    assert rec is not None and rec["ultimo_envio_em"] == datetime(2026, 2, 1, tzinfo=UTC)


async def _preparar_conversa(
    conn: AsyncConnection[dict[str, Any]],
) -> tuple[UUID, UUID, UUID]:
    """Seeds comuns (modelo/cliente/conversa/atendimento/mensagem). Devolve
    (modelo_id, cliente_id, atendimento_id)."""
    await _garantir_coluna_ultimo_envio_em(conn)
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _seed_mensagem(conn, conversa_id=conversa_id)
    return modelo_id, cliente_id, atendimento_id


async def _rodar_turno_1_midia(
    conn: AsyncConnection[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    *,
    modelo_id: UUID,
    cliente_id: UUID,
    atendimento_id: UUID,
    tag_pedida: str,
) -> UUID | None:
    """Roda um turno com UMA `enviar_midia(tag=tag_pedida)` e devolve o `midia_id` que a tool
    escolheu (ou None se nenhuma foi anexada)."""
    fake = _FakeChat([_ai_1_midia(tag_pedida), AIMessage(content="ta ai amor 😘")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: fake)

    graph = build_graph()
    turno_id = str(uuid4())
    contexto = _contexto(
        _PoolDeUmaConexao(conn),
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        cliente_id=cliente_id,
        turno_id=turno_id,
    )
    await graph.ainvoke({"messages": []}, config={"recursion_limit": 18}, context=contexto)

    res = await conn.execute(
        """
        SELECT payload->>'midia_id' AS midia_id
          FROM barravips.tool_calls
         WHERE turno_id = %s AND tool_name = 'enviar_midia'
         ORDER BY call_idx
        """,
        (turno_id,),
    )
    linhas = await res.fetchall()
    return UUID(linhas[0]["midia_id"]) if linhas else None


@pytest.mark.needs_db
async def test_enviar_midia_fallback_por_tipo_quando_tag_diverge(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mídia subida pelo painel com tag FORA do vocabulario do agente ('Sensual') ainda é enviada
    quando o LLM pede uma tag que a modelo não tem ('apresentacao') — via fallback por tipo.
    Sem o fallback a tool levantava ToolException e o cliente não recebia nada (loop → cap)."""
    modelo_id, cliente_id, atendimento_id = await _preparar_conversa(conn)
    foto = await _seed_1_midia(conn, modelo_id, tag="Sensual")  # tag estilo-painel, divergente

    escolhida = await _rodar_turno_1_midia(
        conn,
        monkeypatch,
        modelo_id=modelo_id,
        cliente_id=cliente_id,
        atendimento_id=atendimento_id,
        tag_pedida="apresentacao",  # modelo NAO tem essa tag
    )
    assert escolhida == foto  # fallback pegou a unica foto aprovada do tipo


@pytest.mark.needs_db
async def test_enviar_midia_tag_case_insensitive(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Match de tag é case-insensitive: painel grava 'Corpo' (capitalizado), agente pede 'corpo'.
    A foto 'Corpo' é escolhida pela tag (query direta), NÃO pela outra ('Sensual') via fallback —
    prova que o `lower()` casa a tag pedida antes de relaxar a categoria."""
    modelo_id, cliente_id, atendimento_id = await _preparar_conversa(conn)
    # 'Sensual' é chamariz: a query direta (com filtro `lower(tag)='corpo'`) só enxerga a linha
    # 'Corpo', então a escolha é determinística e prova o match por tag antes de qualquer fallback.
    await _seed_1_midia(conn, modelo_id, tag="Sensual")
    corpo = await _seed_1_midia(conn, modelo_id, tag="Corpo")

    escolhida = await _rodar_turno_1_midia(
        conn,
        monkeypatch,
        modelo_id=modelo_id,
        cliente_id=cliente_id,
        atendimento_id=atendimento_id,
        tag_pedida="corpo",  # minusculo -> casa 'Corpo' via lower()
    )
    assert escolhida == corpo


class _FakeMinioMidia:
    def presigned_get_object(self, bucket: str, object_key: str, expires: Any = None) -> str:
        return f"https://fake/{bucket}/{object_key}"


class _FakeEvolutionMidia:
    """Absorve `set_presence`/`enviar_midia` (a fase de mídia do worker); devolve um message_id
    único por envio p/ o INSERT em `mensagens` não colidir no ON CONFLICT."""

    async def set_presence(self, **_: Any) -> None:
        return None

    async def enviar_midia(self, *, caption: str | None = None, **_: Any) -> str:
        return f"mid-{uuid4().hex}"


@pytest.mark.needs_db
async def test_fase_midia_persiste_mensagem_como_imagem(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fase de mídia do `enviar_turno` (`_enviar_midias`) persiste a mensagem de saída em
    `barravips.mensagens`. O enum `tipo_mensagem_enum` só aceita texto/audio/imagem — inserir
    `m["tipo"]` ('foto'/'video') estourava o enum DEPOIS do POST (cliente recebia, a transação
    revertia, o mark `midia:{idx}` não gravava e o retry reenviava duplicado). Toda mídia de saída
    persiste como 'imagem'. Este teste roda o INSERT REAL — o teste de `test_enviar_turno.py` usa
    um fake-conn que engole o INSERT e não pegaria o enum."""

    async def _noop_sleep(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    await _garantir_coluna_ultimo_envio_em(conn)
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    foto = await _seed_1_midia(conn, modelo_id, tag="corpo", tipo="foto")

    ctx: dict[str, Any] = {
        "redis": FakeRedis(),
        "db_pool": _PoolDeUmaConexao(conn),
        "minio": _FakeMinioMidia(),
        "evolution": _FakeEvolutionMidia(),
    }
    conv = {
        "evolution_instance_id": "inst-1",
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": atendimento_id,
    }

    # critico=True -> pula o cancel-on-new-message (não precisamos semear `turno_atual`).
    ok = await _enviar_midias(
        ctx,
        str(conversa_id),
        str(uuid4()),
        [{"midia_id": str(foto), "legenda": "olha 😏"}],
        conv,
        critico=True,
        chunks=[],
    )
    assert ok is True

    res = await conn.execute(
        """
        SELECT tipo::text AS tipo, media_object_key
          FROM barravips.mensagens
         WHERE conversa_id = %s AND direcao = 'ia'
        """,
        (conversa_id,),
    )
    row = await res.fetchone()
    assert row is not None  # sem o fix o INSERT estourava o enum e nada persistia
    assert row["tipo"] == "imagem"
    assert row["media_object_key"] == f"media/{foto}.jpg"
