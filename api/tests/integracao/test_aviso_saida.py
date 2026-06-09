"""M5d — aviso de saida detectado pelo agente (06 §5 + emenda §0 item 10).

`needs_db` (Postgres via TEST_DATABASE_URL); LLM mockado com fake chat scripted (sem
`needs_key`). Exercita a tool `registrar_extracao` pela mecanica real do grafo (ToolNode
injeta o ToolRuntime), com o LLM emitindo `aviso_saida_detectado=True`. Verifica:
  - aviso_saida_em setado no atendimento (guard IS NULL aplicado);
  - card 'aviso_saida' enfileirado com _job_id estavel;
  - estado preservado (Aguardando_confirmacao) — aviso NAO pausa a IA;
  - ia_pausada permanece false;
  - segunda chamada do mesmo turno (idempotencia da tool) nao reenfileira o card.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph

# --- LLM mockado (script de AIMessage) ------------------------------------------------------


class _FakeChat:
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


def _chama_extracao_com_aviso(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "registrar_extracao",
                "args": {
                    "payload": {
                        "aviso_saida_detectado": True,
                        "proxima_acao_esperada": "esperar cliente chegar",
                    }
                },
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


# --- infra (espelha test_pedir_pix) ---------------------------------------------------------


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


# --- seeds ----------------------------------------------------------------------------------


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
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Teste"),
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


async def _seed_atendimento_interno_aguardando(
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
            date(2026, 12, 1),
            time(14, 0),
            2,
        ),
    )
    return atendimento_id


async def _inserir_mensagem(c: AsyncConnection[dict[str, Any]], *, conversa_id: UUID) -> None:
    """Mensagem do cliente para o gate de `prepare_context` (precisa de pelo menos 1 msg)."""
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s, %s)
        """,
        (
            uuid4(),
            conversa_id,
            "to indo",
            f"test-evo-{uuid4().hex}",
            datetime(2026, 5, 27, 14, 30, tzinfo=UTC),
        ),
    )


def _contexto(
    pool: _PoolDeUmaConexao,
    redis: Any,
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    cliente_id: UUID,
    turno_id: str,
) -> ContextAgente:
    return ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=redis,
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=turno_id,
    )


# --- testes ---------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_aviso_saida_marca_e_enfileira_card(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interno em Aguardando_confirmacao + aviso_saida_detectado=True -> marca campo + card +
    estado preservado + IA segue ativa."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_interno_aguardando(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    # 1º AIMessage chama a tool com aviso; 2º responde texto curto (encerra o loop).
    fake = _FakeChat(
        [_chama_extracao_com_aviso("call_1"), AIMessage(content="anotado, te espero por aqui 🥰")]
    )
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings: fake)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            redis,
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    # 1. aviso_saida_em setado; estado preservado; IA segue ativa.
    res = await conn.execute(
        "SELECT estado::text AS estado, aviso_saida_em, ia_pausada, "
        "responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["aviso_saida_em"] is not None
    assert a["estado"] == "Aguardando_confirmacao"  # NAO transita
    assert a["ia_pausada"] is False  # NAO pausa
    assert a["responsavel_atual"] == "IA"

    # 2. Card 'aviso_saida' enfileirado uma unica vez com _job_id estavel.
    chamadas_card = [c for c in redis.enqueue_job.call_args_list if c.args == ("enviar_card",)]
    aviso = [c for c in chamadas_card if c.kwargs.get("tipo") == "aviso_saida"]
    assert len(aviso) == 1
    assert aviso[0].kwargs["atendimento_id"] == str(atendimento_id)
    assert aviso[0].kwargs["_job_id"] == f"card:aviso_saida:{atendimento_id}"


@pytest.mark.needs_db
async def test_aviso_saida_idempotente_no_segundo_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Guard `aviso_saida_em IS NULL` evita reenfileirar quando o cliente manda 'to indo' duas
    vezes (ou o agente erroneamente disparar o flag de novo no turno seguinte): a 2a chamada
    devolve enviar_aviso_saida=False (no-op silencioso); o wrapper NAO enfileira o card."""
    from barra.dominio.atendimentos.service import registrar_extracao_ia

    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_interno_aguardando(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )

    payload = {
        "aviso_saida_detectado": True,
        "proxima_acao_esperada": "esperar cliente chegar",
    }
    r1 = await registrar_extracao_ia(conn, str(atendimento_id), payload)
    r2 = await registrar_extracao_ia(conn, str(atendimento_id), payload)

    assert r1.get("enviar_aviso_saida") is True
    assert "enviar_aviso_saida" not in r2  # guard IS NULL: 2a vez nao seta a flag


@pytest.mark.needs_db
async def test_aviso_saida_ignora_atendimento_externo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Aviso so vale em interno em Aguardando_confirmacao (CONTEXT.md 'Aviso de saida').
    Mesmo com a flag setada, em externo (ou outro estado) o helper nao marca nem enfileira."""
    from barra.dominio.atendimentos.service import registrar_extracao_ia

    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao'::barravips.estado_atendimento_enum,
                'externo'::barravips.tipo_atendimento_enum,
                'aguardando'::barravips.pix_status_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "aviso_saida_detectado": True,
            "proxima_acao_esperada": "esperar pix",
        },
    )

    assert "enviar_aviso_saida" not in resultado
    res = await conn.execute(
        "SELECT aviso_saida_em FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["aviso_saida_em"] is None  # nao setado em externo
