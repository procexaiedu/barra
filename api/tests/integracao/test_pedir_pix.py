"""M3e — pedir_pix_deslocamento + bloqueio prévio externo contra o Postgres real (04 §3.2).

Exercita a tool pela MECÂNICA real do grafo (ToolNode injeta o ToolRuntime), com o LLM
MOCKADO (script de AIMessages) — `needs_db`, não `needs_key`. Um fake-pool de UMA conexão
deixa prepare_context, a tool e as asserções lerem a MESMA transação; ROLLBACK no teardown
(nada commita no banco prod self-hosted). Espelha test_loop_leitura.py / test_tools_idempotencia.py.

Cobertura:
- externo qualificado → Aguardando_confirmacao + pix_status=aguardando + bloqueio do slot;
- a string da tool NÃO contém a chave Pix, e o payload persistido (tool_calls) tem só `valor`
  — chave/titular NUNCA vão em claro para a persistência (guard-rail de dado sensível);
- 2ª chamada (mesmo turno_id) é idempotente: não duplica bloqueio;
- slot já reservado → ConflitoAgenda → erro recuperável + estado revertido;
- modelo sem chave_pix → erro instrutivo + estado inalterado.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, ToolMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.dominio.agenda.service import BRT
from barra.settings import get_settings

DATA_SLOT = date(2026, 6, 1)
HORARIO_SLOT = time(22, 0)
DURACAO_SLOT = 2  # horas


# --- LLM mockado -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sem_forca_extracao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola este módulo da extração forçada (#2, default-ON): aqui o assunto é a tool pedir_pix,
    não a força. Com a flag ligada, o turno final sem auto-extração ganharia 1 ainvoke a mais,
    defasando as asserções. A força tem teste dedicado em test_llm_forca_extracao."""
    monkeypatch.setattr(get_settings(), "forcar_extracao_por_turno", False)


class _FakeChat:
    """Chat roteirizado: bind_tools é no-op; ainvoke devolve o próximo AIMessage do script e
    guarda as mensagens vistas (p/ inspecionar o ToolMessage que voltou da tool)."""

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


def _chama_pix(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "pedir_pix_deslocamento", "args": {}, "id": call_id, "type": "tool_call"}
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
    """Pool fake de UMA conexão: prepare_context, a tool e as asserções na MESMA transação."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed_modelo(
    connection: AsyncConnection[dict[str, Any]], *, chave_pix: str | None, titular: str | None
) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             chave_pix, titular_chave)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            chave_pix,
            titular,
        ),
    )
    return modelo_id


async def _seed_cliente(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Teste"),
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


async def _seed_atendimento_externo(
    connection: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    tipo: str = "externo",
) -> UUID:
    atendimento_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             data_desejada, horario_desejado, duracao_horas)
        VALUES (%s, 1, %s, %s, %s, 'Qualificado', %s::barravips.tipo_atendimento_enum,
                %s, %s, %s)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            tipo,
            DATA_SLOT,
            HORARIO_SLOT,
            DURACAO_SLOT,
        ),
    )
    return atendimento_id


async def _inserir_mensagem(
    connection: AsyncConnection[dict[str, Any]], *, conversa_id: UUID
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
            "fechado, qual a chave pra eu te mandar o pix do deslocamento?",
            f"test-evo-{uuid4().hex}",
            datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        ),
    )


async def _contar_bloqueios(
    connection: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> int:
    res = await connection.execute(
        "SELECT count(*) AS n FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return int(row["n"])


async def _atendimento(
    connection: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await connection.execute(
        "SELECT estado::text AS estado, pix_status::text AS pix_status, bloqueio_id"
        " FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


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


def _tool_messages(vistas: list[list[Any]]) -> list[ToolMessage]:
    """Todos os ToolMessage de pedir_pix vistos pelo LLM ao longo do loop."""
    return [
        m
        for visao in vistas
        for m in visao
        if isinstance(m, ToolMessage) and m.name == "pedir_pix_deslocamento"
    ]


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_pede_pix_reserva_slot_e_nao_vaza_chave(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chave = f"test-pix-key-{uuid4().hex}"
    titular = "Modelo Teste"
    modelo_id = await _seed_modelo(conn, chave_pix=chave, titular=titular)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="prontinho amor, te mandei tudo 🥰")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    turno_id = str(uuid4())
    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=turno_id,
        ),
    )

    # estado + reserva.
    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Aguardando_confirmacao"
    assert at["pix_status"] == "aguardando"
    assert at["bloqueio_id"] is not None
    assert await _contar_bloqueios(conn, atendimento_id) == 1

    # o bloqueio cobre o slot combinado (data_desejada + horario_desejado, duração).
    res = await conn.execute(
        "SELECT inicio, fim, estado::text AS estado, origem::text AS origem"
        " FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    bloqueio = await res.fetchone()
    assert bloqueio is not None
    assert bloqueio["estado"] == "bloqueado"
    assert bloqueio["origem"] == "ia"
    assert bloqueio["inicio"] == datetime.combine(DATA_SLOT, HORARIO_SLOT, tzinfo=BRT)
    assert bloqueio["fim"] == datetime.combine(DATA_SLOT, HORARIO_SLOT, tzinfo=BRT) + timedelta(
        hours=DURACAO_SLOT
    )

    # a chave NÃO vaza pelo retorno da tool.
    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert chave not in str(tmsgs[0].content)

    # e o payload de tool_calls tem SÓ `valor` — chave/titular NUNCA são persistidos em claro.
    # Filtra pelo turno DESTE teste: tool_calls do banco real tem linhas commitadas de turnos
    # de prod com o mesmo tool_name/call_idx (fetchone sem filtro pegaria uma arbitrária).
    res = await conn.execute(
        "SELECT payload FROM barravips.tool_calls"
        " WHERE tool_name = 'pedir_pix_deslocamento' AND call_idx = 0 AND turno_id = %s",
        (turno_id,),
    )
    tc = await res.fetchone()
    assert tc is not None
    # valor vem da setting (fonte unica), nao de constante hardcoded.
    assert tc["payload"] == {"valor": str(get_settings().pix_deslocamento_valor)}
    assert "chave" not in tc["payload"]
    assert "titular" not in tc["payload"]

    # evento de auditoria registrado.
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.eventos WHERE atendimento_id = %s AND tipo = 'pix_solicitado'",
        (atendimento_id,),
    )
    ev = await res.fetchone()
    assert ev is not None and ev["n"] == 1


@pytest.mark.needs_db
async def test_segunda_chamada_mesmo_turno_e_idempotente(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay do turno (mesmo turno_id, call_idx=0) não duplica bloqueio nem mensagem."""
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    # LLM pede pedir_pix DUAS vezes no mesmo turno antes de fechar (simula replay/insistência).
    fake = _FakeChat([_chama_pix("call_1"), _chama_pix("call_2"), AIMessage(content="feito 🥰")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    assert await _contar_bloqueios(conn, atendimento_id) == 1  # não duplicou
    at = await _atendimento(conn, atendimento_id)
    assert at["pix_status"] == "aguardando"


@pytest.mark.needs_db
async def test_slot_ja_reservado_reverte_e_erro_recuperavel(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outra conversa já cravou o slot: ConflitoAgenda → turno revertido + erro instrutivo."""
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    # bloqueio prévio de OUTRA conversa da mesma modelo, sobrepondo o slot.
    inicio = datetime.combine(DATA_SLOT, HORARIO_SLOT, tzinfo=BRT)
    await conn.execute(
        """
        INSERT INTO barravips.bloqueios (modelo_id, inicio, fim, origem, estado)
        VALUES (%s, %s, %s, 'manual', 'bloqueado')
        """,
        (modelo_id, inicio, inicio + timedelta(hours=DURACAO_SLOT)),
    )

    fake = _FakeChat(
        [_chama_pix("call_1"), AIMessage(content="ah, esse horário fechou — que tal mais tarde?")]
    )
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    # estado revertido: o atendimento NÃO entrou em Aguardando_confirmacao.
    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Qualificado"
    assert at["pix_status"] == "nao_solicitado"
    assert at["bloqueio_id"] is None
    # nenhum bloqueio NOVO ligado ao atendimento (o pré-seedado é avulso, sem atendimento_id).
    assert await _contar_bloqueios(conn, atendimento_id) == 0

    # erro recuperável instruiu a IA (não levantou exceção no grafo).
    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert "ERRO" in str(tmsgs[0].content)


@pytest.mark.needs_db
async def test_atendimento_interno_nao_pede_pix(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTEXT.md "Pix de deslocamento": sem Pix no interno. Guarda determinística sobre a
    docstring da tool ("Use APENAS para atendimento externo"): tool-call alucinado num interno
    NAO grava pix_status=aguardando (que desviaria a proxima imagem do branch foto-portaria
    para o branch pix em rotear_imagem) — erro recuperavel, estado intacto."""
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id, tipo="interno"
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="deixa eu te explicar amor")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Qualificado"  # inalterado
    assert at["pix_status"] == "nao_solicitado"
    assert await _contar_bloqueios(conn, atendimento_id) == 0

    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert "ERRO" in str(tmsgs[0].content)
    assert "externo" in str(tmsgs[0].content).lower()


@pytest.mark.needs_db
async def test_atendimento_remoto_nao_pede_pix(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vídeo chamada (remoto, ADR 0021) nao tem Pix de deslocamento — ninguem se desloca. A mesma
    guarda determinística do interno (`tipo != 'externo'`) rejeita o tool-call alucinado: estado
    intacto, pix_status preservado, erro recuperavel."""
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id, tipo="remoto"
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="deixa eu te explicar amor")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Qualificado"  # inalterado
    assert at["pix_status"] == "nao_solicitado"
    assert await _contar_bloqueios(conn, atendimento_id) == 0

    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    conteudo = str(tmsgs[0].content).lower()
    assert "ERRO" in str(tmsgs[0].content)
    # Mensagem dedicada do remoto: orienta seguir sem Pix, NAO reclassificar como externo.
    assert "vídeo chamada" in conteudo
    assert "sem pix" in conteudo


@pytest.mark.needs_db
async def test_valor_do_pix_vem_do_setting(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pix_deslocamento_valor` é a fonte única do valor: payload de auditoria e retorno da tool
    refletem a setting (antes havia constante hardcoded de 100 que driftava do setting usado na
    validação do comprovante e na bolha da chave)."""
    monkeypatch.setattr(get_settings(), "pix_deslocamento_valor", Decimal("150.00"))
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="te mandei tudo 🥰")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    turno_id = str(uuid4())
    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=turno_id,
        ),
    )

    # Filtra pelo turno DESTE teste (tool_calls do banco real tem linhas de turnos de prod).
    res = await conn.execute(
        "SELECT payload FROM barravips.tool_calls"
        " WHERE tool_name = 'pedir_pix_deslocamento' AND call_idx = 0 AND turno_id = %s",
        (turno_id,),
    )
    tc = await res.fetchone()
    assert tc is not None
    assert tc["payload"] == {"valor": "150.00"}

    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert "150" in str(tmsgs[0].content)


@pytest.mark.needs_db
async def test_modelo_sem_chave_pix_retorna_erro(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    modelo_id = await _seed_modelo(conn, chave_pix=None, titular=None)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="só um instante amor")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Qualificado"  # inalterado
    assert at["pix_status"] == "nao_solicitado"
    assert await _contar_bloqueios(conn, atendimento_id) == 0

    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert "ERRO" in str(tmsgs[0].content)


@pytest.mark.needs_db
async def test_pickup_cliente_busca_nao_pede_pix(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0020: externo-pickup (cliente_busca=true, o cliente vem buscar a modelo) nao tem Pix
    de deslocamento. Guarda deterministica sobre a docstring/prompt (<externo_cliente_busca>):
    tool-call num pickup NAO grava pix_status nem cria bloqueio — erro recuperavel, estado
    intacto (a promocao do pickup e da extracao, nao desta tool)."""
    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET cliente_busca = true WHERE id = %s",
        (atendimento_id,),
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id)

    fake = _FakeChat([_chama_pix("call_1"), AIMessage(content="te espero na rua amor")])
    monkeypatch.setattr("barra.agente.graph.criar_chat_anthropic", lambda settings, **_kw: fake)

    graph = build_graph()
    await graph.ainvoke(
        {"messages": []},
        config={"recursion_limit": 18},
        context=_contexto(
            _PoolDeUmaConexao(conn),
            modelo_id=modelo_id,
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=str(uuid4()),
        ),
    )

    at = await _atendimento(conn, atendimento_id)
    assert at["estado"] == "Qualificado"  # inalterado
    assert at["pix_status"] == "nao_solicitado"
    assert await _contar_bloqueios(conn, atendimento_id) == 0

    tmsgs = _tool_messages(fake.vistas)
    assert len(tmsgs) == 1
    assert "ERRO" in str(tmsgs[0].content)
    assert "buscar" in str(tmsgs[0].content)


@pytest.mark.needs_db
async def test_pix_apos_pickup_corrigido_nao_recria_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Correção pickup→Uber (ADR 0020): atendimento que JÁ tem bloqueio prévio (criado pela
    promoção do pickup na extração) e vira fluxo Uber NÃO recria o bloqueio — recriar colidiria
    com o próprio slot (EXCLUDE → ConflitoAgenda) e derrubaria o turno (achado do
    domain-isolation-reviewer)."""
    from barra.agente.ferramentas.pix import _aplicar_pedido_pix
    from barra.dominio.atendimentos.service import registrar_extracao_ia

    modelo_id = await _seed_modelo(conn, chave_pix=f"k-{uuid4().hex}", titular="T")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_externo(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    # Pickup promovido pela extração: Aguardando_confirmacao + bloqueio prévio, sem Pix.
    await registrar_extracao_ia(
        conn, str(atendimento_id), {"cliente_busca": True, "proxima_acao_esperada": "aguardar"}
    )
    assert await _contar_bloqueios(conn, atendimento_id) == 1
    # Cliente muda de ideia: ela vai de uber afinal — corrige e pede o Pix.
    await registrar_extracao_ia(
        conn, str(atendimento_id), {"cliente_busca": False, "proxima_acao_esperada": "pedir pix"}
    )

    await _aplicar_pedido_pix(conn, str(atendimento_id), {"valor": "100"})

    at = await _atendimento(conn, atendimento_id)
    assert at["pix_status"] == "aguardando"
    assert await _contar_bloqueios(conn, atendimento_id) == 1  # não recriou nem duplicou
