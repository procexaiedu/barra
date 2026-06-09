"""M1-T2 — mecânica do loop ReAct `llm <-> tools` contra o Postgres real.

Dois cenários, ambos com o LLM MOCKADO (script de AIMessages) — não é `needs_key`, só `needs_db`:
  1. caso feliz: o llm pede `consultar_agenda`, o ToolNode executa de verdade (lê os bloqueios
     semeados), o resultado volta como ToolMessage e o llm responde — prova que o loop fecha;
  2. recursion ativo: um llm que SEMPRE pede tool_call estoura `recursion_limit` e encerra com
     `GraphRecursionError` (de `langgraph.errors`) — prova que o teto mata o loop infinito.

Um fake-pool de UMA conexão deixa `prepare_context` E a tool lerem o MESMO seed na mesma
transação (ROLLBACK no teardown — nada commita). Espelha test_consultar_agenda.py /
test_repo_integracao.py (TEST_DATABASE_URL, autocommit=False, dict_row, prepare_threshold=None).
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.settings import get_settings

# --- LLM mockado: scripts de AIMessages (sem chamar a API real) ------------------------------


@pytest.fixture(autouse=True)
def _sem_forca_extracao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola este módulo da extração forçada (#2, default-ON): aqui o assunto é o loop ReAct, não
    a força. Com a flag ligada, o turno sem auto-extração ganharia 1 ainvoke a mais (3 em vez de
    2), defasando as asserções de contagem. A força tem teste dedicado em test_llm_forca_extracao."""
    monkeypatch.setattr(get_settings(), "forcar_extracao_por_turno", False)


class _FakeChat:
    """Chat roteirizado: bind_tools é no-op; ainvoke devolve o próximo AIMessage do script e
    grava as mensagens que recebeu (p/ provar que o ToolMessage chegou na 2ª chamada)."""

    model = "claude-sonnet-4-6"  # no_llm le chat.model p/ o label das metricas de token (M2-T2)

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


class _FakeChatLoopInfinito:
    """Chat que SEMPRE pede consultar_agenda (id novo a cada chamada) — loop sem fim."""

    model = "claude-sonnet-4-6"  # no_llm le chat.model p/ o label das metricas de token (M2-T2)

    def __init__(self, data_inicio: str, data_fim: str) -> None:
        self._di = data_inicio
        self._df = data_fim
        self._n = 0

    def bind_tools(
        self, tools: Any, *, tool_choice: Any = None, **_kw: Any
    ) -> "_FakeChatLoopInfinito":
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self._n += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "consultar_agenda",
                    "args": {"data_inicio": self._di, "data_fim": self._df},
                    "id": f"call_{self._n}",
                    "type": "tool_call",
                }
            ],
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
    """Pool fake de UMA conexao: prepare_context e a tool leem a MESMA transacao (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


async def _seed_cliente(
    connection: AsyncConnection[dict[str, Any]], nome: str | None = None
) -> UUID:
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", nome),
    )
    return cliente_id


async def _seed_conversa(
    connection: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    connection: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    estado: str = "Triagem",
    tipo_atendimento: str | None = None,
    numero_curto: int = 1,
) -> UUID:
    atendimento_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            atendimento_id,
            numero_curto,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            tipo_atendimento,
        ),
    )
    return atendimento_id


async def _inserir_mensagem(
    connection: AsyncConnection[dict[str, Any]],
    *,
    conversa_id: UUID,
    conteudo: str,
) -> None:
    await connection.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s, %s)
        """,
        (
            uuid4(),
            conversa_id,
            conteudo,
            f"test-evo-{uuid4().hex}",
            datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        ),
    )


def _contexto(
    pool: _PoolDeUmaConexao, *, modelo_id: UUID, atendimento_id: UUID, cliente_id: UUID
) -> ContextAgente:
    return ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=str(uuid4()),
    )


def _janela_tool() -> tuple[str, str]:
    """Janela futura válida (<=14 dias) p/ as tool_calls do script."""
    hoje = date.today()
    return (hoje + timedelta(days=1)).isoformat(), (hoje + timedelta(days=5)).isoformat()


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_loop_executa_tool_e_retorna_aimessage(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caso feliz: o loop executa consultar_agenda de verdade e o llm responde apos o ToolMessage."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id, conteudo="tem horario sabado que vem?")

    di, df = _janela_tool()
    fake = _FakeChat(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "consultar_agenda",
                        "args": {"data_inicio": di, "data_fim": df},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="amor, sábado que vem tô livre sim 🥰"),
        ]
    )
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings: fake)

    graph = build_graph()
    estado = await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
        ),
    )

    # resultado final: AIMessage de texto nao-vazio (o llm respondeu apos a tool).
    final = estado["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.content

    # o llm foi chamado 2x; na 2a chamada VIU um ToolMessage com o resultado real de consultar_agenda.
    assert len(fake.vistas) == 2
    tool_msgs = [m for m in fake.vistas[1] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].name == "consultar_agenda"
    # leitura real do banco (modelo sem bloqueios na janela) -> prova que o ToolNode executou a tool.
    assert "Nenhum horário ocupado" in tool_msgs[0].content


@pytest.mark.needs_db
async def test_recursion_limit_encerra_loop_infinito(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Um llm que sempre pede tool_call estoura recursion_limit -> GraphRecursionError."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id, conteudo="e nos outros dias?")

    di, df = _janela_tool()
    monkeypatch.setattr(
        "barra.agente.graph.criar_chat_anthropic", lambda settings: _FakeChatLoopInfinito(di, df)
    )

    graph = build_graph()
    with pytest.raises(GraphRecursionError):
        await graph.ainvoke(
            {"messages": []},
            config={"recursion_limit": 18},
            context=_contexto(
                _PoolDeUmaConexao(conn),
                modelo_id=modelo_id,
                atendimento_id=atendimento_id,
                cliente_id=cliente_id,
            ),
        )
