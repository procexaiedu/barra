"""no_extrair: execucao INLINE de registrar_extracao dentro do graph.ainvoke, contra o Postgres
real (issue 01 — de-risco do footgun).

`needs_db` (Postgres via TEST_DATABASE_URL); chat FAKE (sem `needs_key`). Monta um StateGraph
minimo START -> extrair -> post_process|llm (dummies) -> END e prova, com a tool REAL de
`TOOLS`, que a execucao acontece FORA de uma aresta do grafo (nao ha no `tools`), dentro do
`graph.ainvoke`:
  - `ToolRuntime[ContextAgente]` e injetado corretamente: a tool le db_pool/atendimento_id/
    turno_id do context e persiste em `barravips.tool_calls`;
  - `horario_minimo` (state) + `agora_utc` (context) propagam: o fallback #4 (urgencia=imediato
    sem horario) assume o horario_minimo;
  - `novo_estado`/`pix_solicitado` ficam legiveis no `resultado` persistido;
  - o card de aviso de saida e enfileirado quando o snapshot o dispara;
  - erro recuperavel (ConflitoAgenda) vira ToolMessage status="error" e o no roteia p/ reoferta,
    com a transacao revertida.

ROLLBACK sempre (autocommit=False, dict_row, prepare_threshold=None) — nada commita no prod
self-hosted. Espelha test_registrar_extracao / test_aviso_saida.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.estado import EstadoAgente
from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.nos.extrair import no_extrair
from barra.dominio.agenda.service import BRT
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
# registrar_extracao saiu de TOOLS (bindada so no no `extrair`); importada direto p/ a execucao real.
_TOOL_REAL = registrar_extracao


# --- chat FAKE: forca uma AIMessage com o tool_call de registrar_extracao (args reais) --------


class _FakeForcado:
    def __init__(self, args: dict[str, Any]) -> None:
        self._args = args

    async def ainvoke(self, _messages: Any) -> AIMessage:
        return AIMessage(
            content="",
            usage_metadata=_USAGE,  # type: ignore[arg-type]
            response_metadata={"finish_reason": "tool_calls"},
            tool_calls=[
                {"name": "registrar_extracao", "args": self._args, "id": "ex1", "type": "tool_call"}
            ],
        )


class _FakeChat:
    model = "deepseek-test"

    def __init__(self, args: dict[str, Any]) -> None:
        self._forcado = _FakeForcado(args)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeForcado:
        return self._forcado


async def _dummy(state: EstadoAgente, runtime: Any) -> dict[str, Any]:
    return {}


def _build_graph(args: dict[str, Any]) -> Any:
    """StateGraph minimo com o no extrair (tool REAL) e nos dummy p/ post_process/llm."""
    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)
    builder.add_node("extrair", no_extrair(_FakeChat(args), None, _TOOL_REAL))
    builder.add_node("post_process", _dummy)
    builder.add_node("llm", _dummy)
    builder.add_edge(START, "extrair")
    builder.add_edge("post_process", END)
    builder.add_edge("llm", END)
    return builder.compile()


def _fala() -> AIMessage:
    """Fala final do turno (ultima msg do state, contrato do no)."""
    return AIMessage(
        id="resp-1",
        content="fechou, combinado",
        usage_metadata=_USAGE,
        tool_calls=[],  # type: ignore[arg-type]
    )


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


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: a tool le/escreve na MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


# --- seeds (espelham test_registrar_extracao) ------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], aceita: list[str] | None = None) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            aceita if aceita is not None else ["interno", "externo"],
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
        "INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)"
        " VALUES (%s, %s, %s, %s)",
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    cliente_id: UUID,
    modelo_id: UUID,
    *,
    estado: str = "Novo",
    tipo_atendimento: str | None = None,
    intencao: str | None = None,
    horario_desejado: time | None = None,
    data_desejada: date | None = None,
    duracao_horas: Decimal | None = None,
    cotou: bool = True,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, intencao,
             horario_desejado, data_desejada, duracao_horas, cotacao_enviada_em)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum, %s::barravips.intencao_enum, %s, %s, %s,
                CASE WHEN %s THEN now() ELSE NULL END)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            tipo_atendimento,
            intencao,
            horario_desejado,
            data_desejada,
            duracao_horas,
            cotou,
        ),
    )
    return atendimento_id


async def _seed_par(
    c: AsyncConnection[dict[str, Any]], aceita: list[str] | None = None, **kw: Any
) -> tuple[UUID, UUID]:
    modelo_id = await _seed_modelo(c, aceita)
    cliente_id = await _seed_cliente(c)
    conversa_id = await _seed_conversa(c, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(c, conversa_id, cliente_id, modelo_id, **kw)
    return modelo_id, atendimento_id


def _contexto(
    pool: _PoolDeUmaConexao,
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    turno_id: str,
    redis: Any = None,
    agora_utc: datetime | None = None,
) -> ContextAgente:
    return ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=redis,
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(uuid4()),
        turno_id=turno_id,
        agora_utc=agora_utc,
    )


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_injecao_inline_persiste_e_promove(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Footgun: a tool executa INLINE (fora da aresta `tools`), le db_pool/atendimento_id/turno_id
    do ToolRuntime injetado, persiste em barravips.tool_calls e aplica a FSM — interno qualificado
    -> Aguardando_confirmacao + bloqueio. `novo_estado` fica legivel no resultado persistido."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(14, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("2"),
    )
    turno_id = str(uuid4())
    graph = _build_graph({"proxima_acao_esperada": "confirmar saida do cliente"})

    resultado = await graph.ainvoke(
        {"messages": [HumanMessage(content="14h então"), _fala()]},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            turno_id=turno_id,
        ),
    )

    # A ultima AIMessage do turno (fala) segue viva + o registro (forcado + ToolMessage) foi anexado.
    tool_messages = [m for m in resultado["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status != "error"

    # Linha em barravips.tool_calls com a chave canonica + resultado legivel.
    res = await conn.execute(
        "SELECT resultado FROM barravips.tool_calls "
        "WHERE turno_id = %s AND tool_name = %s AND call_idx = 0",
        (turno_id, "registrar_extracao"),
    )
    linha = await res.fetchone()
    assert linha is not None
    assert linha["resultado"]["novo_estado"] == "Aguardando_confirmacao"

    # FSM aplicada de fato no atendimento.
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["bloqueio_id"] is not None


@pytest.mark.needs_db
async def test_horario_minimo_propaga_pelo_state(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Must-verify: `horario_minimo` (state) e `agora_utc` (context) propagam pela injecao inline.
    Remoto qualificado, urgencia=imediato SEM horario -> o fallback #4 (que le AMBOS) assume o
    horario_minimo. Se a injecao falhasse, o campo nao seria lido e nao haveria promocao."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        aceita=["remoto"],
        estado="Qualificado",
        tipo_atendimento="remoto",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    turno_id = str(uuid4())
    agora = datetime(2026, 12, 1, 9, 0, tzinfo=BRT)
    horario_minimo = datetime(2026, 12, 1, 9, 30, tzinfo=BRT)
    graph = _build_graph({"urgencia": "imediato", "proxima_acao_esperada": "reservar a chamada"})

    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="da pra ser já?"), _fala()],
            "horario_minimo": horario_minimo,
        },
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            turno_id=turno_id,
            agora_utc=agora,
        ),
    )

    res = await conn.execute(
        "SELECT estado::text AS estado, horario_desejado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["horario_desejado"] == time(9, 30)  # assumiu o horario_minimo (nao o now cru)


@pytest.mark.needs_db
async def test_pix_solicitado_legivel_no_resultado(conn: AsyncConnection[dict[str, Any]]) -> None:
    """`pix_solicitado` fica legivel no resultado persistido: externo-Uber qualificado promove e
    solicita o Pix de deslocamento pela execucao inline."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        aceita=["externo"],
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        horario_desejado=time(16, 0),
        data_desejada=date(2026, 12, 4),
        duracao_horas=Decimal("12"),
    )
    turno_id = str(uuid4())
    graph = _build_graph({"proxima_acao_esperada": "pedir o pix"})

    await graph.ainvoke(
        {"messages": [HumanMessage(content="pode vir aqui"), _fala()]},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            turno_id=turno_id,
        ),
    )

    res = await conn.execute(
        "SELECT resultado FROM barravips.tool_calls "
        "WHERE turno_id = %s AND tool_name = %s AND call_idx = 0",
        (turno_id, "registrar_extracao"),
    )
    linha = await res.fetchone()
    assert linha is not None
    assert linha["resultado"]["novo_estado"] == "Aguardando_confirmacao"
    assert linha["resultado"]["pix_solicitado"] is True
    # guard-rail: a chave/titular do Pix nunca vazam pelo resultado persistido.
    assert "chave" not in linha["resultado"]


@pytest.mark.needs_db
async def test_card_aviso_saida_enfileirado(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O enqueue do card de aviso de saida (dentro do corpo da tool) roda na execucao inline:
    interno em Aguardando_confirmacao + aviso_saida_detectado -> enqueue_job(tipo='aviso_saida')."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, data_desejada, horario_desejado, duracao_horas)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao'::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, %s, %s, %s)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, date(2026, 12, 1), time(14, 0), 2),
    )
    turno_id = str(uuid4())
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()
    graph = _build_graph({"aviso_saida_detectado": True, "proxima_acao_esperada": "esperar chegar"})

    await graph.ainvoke(
        {"messages": [HumanMessage(content="to indo"), _fala()]},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            turno_id=turno_id,
            redis=redis,
        ),
    )

    assert any(c.kwargs.get("tipo") == "aviso_saida" for c in redis.enqueue_job.call_args_list)


@pytest.mark.needs_db
async def test_erro_recuperavel_inline_vira_toolmessage_e_reverte(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ConflitoAgenda na execucao inline: handle_tool_error converte em ToolMessage status='error',
    o no roteia p/ reoferta (goto=llm, default ON) e a transacao reverteu (o 2o atendimento NAO
    ficou com bloqueio)."""
    assert get_settings().reoferta_automatica_habilitada is True
    modelo_id = await _seed_modelo(conn)
    horario, data, duracao = time(20, 0), date(2026, 12, 2), Decimal("1")
    # 1o atendimento reserva o slot (via a propria execucao inline).
    cliente1 = await _seed_cliente(conn)
    conversa1 = await _seed_conversa(conn, cliente1, modelo_id)
    at1 = await _seed_atendimento(
        conn,
        conversa1,
        cliente1,
        modelo_id,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=horario,
        data_desejada=data,
        duracao_horas=duracao,
    )
    graph = _build_graph({"proxima_acao_esperada": "confirmar"})
    await graph.ainvoke(
        {"messages": [HumanMessage(content="20h"), _fala()]},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=at1,
            turno_id=str(uuid4()),
        ),
    )

    # 2o atendimento da MESMA modelo disputa o MESMO slot -> ConflitoAgenda.
    cliente2 = await _seed_cliente(conn)
    conversa2 = await _seed_conversa(conn, cliente2, modelo_id)
    at2 = await _seed_atendimento(
        conn,
        conversa2,
        cliente2,
        modelo_id,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=horario,
        data_desejada=data,
        duracao_horas=duracao,
    )
    resultado = await graph.ainvoke(
        {"messages": [HumanMessage(content="20h"), _fala()]},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=at2,
            turno_id=str(uuid4()),
        ),
    )

    # ToolMessage de erro recuperavel presente + a fala stale (resp-1) removida do turno.
    tool_messages = [m for m in resultado["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert str(tool_messages[0].content).startswith("ERRO:")
    assert not any(getattr(m, "id", None) == "resp-1" for m in resultado["messages"])

    # A transacao do 2o registro reverteu: sem bloqueio.
    res = await conn.execute("SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (at2,))
    a = await res.fetchone()
    assert a is not None
    assert a["bloqueio_id"] is None
