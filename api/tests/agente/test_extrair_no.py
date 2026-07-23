"""no_extrair: roteamento do turno com a extracao executada INLINE (issue 01).

Prova os 4+1 caminhos de decisao do no `extrair` com chat FAKE + tool de extracao FAKE (sem API
real nem banco): a EXECUCAO da tool e substituida por um ToolMessage roteirizado, entao o assunto
aqui e so a decisao de rota. A injecao real do ToolRuntime + persistencia vive em
tests/integracao/test_extrair_inline.py (needs_db). Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from barra.agente.nos.extrair import no_extrair
from barra.dominio.atendimentos.service import _MSG_GUARD_PISO
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeForcado:
    """Bind forcado fake: ainvoke devolve o AIMessage forcado fixo e registra as janelas recebidas."""

    def __init__(self, forcado: AIMessage) -> None:
        self._forcado = forcado
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        return self._forcado


class _FakeChat:
    """bind_tools(tool_choice=...) -> o bind forcado. `model` p/ o label das metricas de token."""

    model = "deepseek-test"

    def __init__(self, forcado: AIMessage) -> None:
        self.forcado = _FakeForcado(forcado)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeForcado:
        return self.forcado


class _FakeToolExtracao:
    """Tool de extracao fake: `ainvoke` devolve um ToolMessage roteirizado (nao toca o DB).

    Registra as chamadas p/ os testes provarem que o guard de qualidade NAO executa a tool.
    """

    name = "registrar_extracao"

    def __init__(self, tool_message: ToolMessage) -> None:
        self._tm = tool_message
        self.chamadas: list[Any] = []

    async def ainvoke(self, chamada: Any) -> ToolMessage:
        self.chamadas.append(chamada)
        return self._tm


def _runtime() -> SimpleNamespace:
    # _executar_inline le context/stream_writer/store do Runtime do no.
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"), stream_writer=None, store=None)


def _fala(id_: str = "resp-1", content: str = "às 22h te serve?") -> AIMessage:
    """Fala final do turno: texto client-facing, sem tool_calls (ultima msg do state, contrato)."""
    return AIMessage(id=id_, content=content, usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]


def _forcado(
    *, stop: str = "tool_calls", chave: str = "finish_reason", com_tool: bool = True
) -> AIMessage:
    return AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={chave: stop},
        tool_calls=(
            [
                {
                    "name": "registrar_extracao",
                    "args": {"intencao": "cotacao"},
                    "id": "ex1",
                    "type": "tool_call",
                }
            ]
            if com_tool
            else []
        ),
    )


def _tool_ok(content: str = "Extracao registrada.") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="ex1", name="registrar_extracao")


def _tool_erro() -> ToolMessage:
    return ToolMessage(
        content="ERRO: o horário escolhido já está reservado para a modelo. Ofereça outro.",
        tool_call_id="ex1",
        name="registrar_extracao",
        status="error",
    )


# --- sucesso / escalada canned -> post_process -----------------------------------------------


async def test_sucesso_roteia_post_process_com_registro() -> None:
    """Extracao OK -> post_process carregando o AIMessage forcado + o ToolMessage; a fala original
    ja esta no state (nao e re-emitida nem removida)."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    fala = _fala()
    state = {"messages": [HumanMessage(content="22h"), fala]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.forcado._forcado, tool._tm]
    # a extracao rodou sobre a janela SEM a fala final (so a HumanMessage)
    assert chat.forcado.chamadas == [[HumanMessage(content="22h")]]
    assert len(tool.chamadas) == 1  # tool executada inline


async def test_escalada_canned_roteia_post_process() -> None:
    """Escalada canned (guard de piso/tipo/reagendamento) retorna `mensagem` normal (novo_estado:
    None), NAO erro -> mesmo ramo do sucesso (post_process). A canned de espera e solta la (o
    content bate MENSAGENS_GUARD_ESCALADA)."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok(content=_MSG_GUARD_PISO))
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="faz 300?"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.forcado._forcado, tool._tm]


# --- guard de qualidade: forcado truncado / sem tool_call -> post_process (so a fala) ---------


async def test_forcado_truncado_descarta_e_fecha_com_fala() -> None:
    """Forcado trunca (finish_reason=length) -> descarta, fecha SO com a fala original (ja no
    state), e NAO executa a tool (nunca persiste payload parcial)."""
    chat = _FakeChat(_forcado(stop="length"))
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert not cmd.update  # sem messages: a fala ja esta no state
    assert tool.chamadas == []  # tool NAO executada


async def test_forcado_sem_tool_call_descarta_e_fecha_com_fala() -> None:
    """Forcado sem tool_call (raro) -> mesmo guard: descarta e fecha so com a fala; tool intacta."""
    chat = _FakeChat(_forcado(com_tool=False, stop="stop"))
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert not cmd.update
    assert tool.chamadas == []


# --- erro recuperavel: auto-reoferta (goto=llm) e 2a falha (mute) -----------------------------


async def test_erro_recuperavel_reoferta_on_volta_pro_llm() -> None:
    """Default ON: erro recuperavel -> goto=llm, seta _reoferta_tentada, remove a fala stale (falsa
    confirmacao) e carrega o par forcado+ToolMessage p/ o llm ler o erro e reofertar."""
    assert get_settings().reoferta_automatica_habilitada is True  # contrato do default
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    fala = _fala(content="combinado, te espero às 22h")  # falsa confirmacao
    state = {"messages": [HumanMessage(content="22h"), fala]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "llm"
    assert cmd.update["_reoferta_tentada"] is True
    msgs = cmd.update["messages"]
    assert chat.forcado._forcado in msgs and tool._tm in msgs  # par p/ o llm ver o erro
    remocoes = [m for m in msgs if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]  # fala stale removida


async def test_erro_recuperavel_reoferta_off_fecha_mudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """flag OFF: erro recuperavel fecha MUDO (post_process) removendo a fala stale -- silencio >
    reserva fantasma. NAO volta ao llm."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", False)
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert "_reoferta_tentada" not in cmd.update
    remocoes = [m for m in cmd.update["messages"] if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]


async def test_erro_recuperavel_segunda_falha_fecha_mudo() -> None:
    """flag ON mas _reoferta_tentada ja True (a reoferta TAMBEM errou): NAO reoferta de novo, fecha
    MUDO. Bounded: no maximo uma reoferta por turno."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()], "_reoferta_tentada": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"  # mute, nao reoferta de novo
    remocoes = [m for m in cmd.update["messages"] if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]


# --- extracao barata: janela sem o BP_GERAL --------------------------------------------------


async def test_extracao_barata_roda_sem_system_geral() -> None:
    """chat_extracao_barata injetado -> forca no barato sobre a janela SEM o SystemMessage geral
    (system minimo de extracao no lugar), a fala final excluida."""
    from langchain_core.messages import SystemMessage

    chat = _FakeChat(_forcado())  # nao usado p/ a extracao (barato tem prioridade)
    barato = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, barato, tool)  # type: ignore[arg-type]
    system = SystemMessage(content="PERSONA GIGANTE ~14k tokens")
    state = {"messages": [system, HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.forcado.chamadas == []  # o principal NAO foi chamado
    assert len(barato.forcado.chamadas) == 1
    janela = barato.forcado.chamadas[0]
    systems = [m for m in janela if isinstance(m, SystemMessage)]
    assert len(systems) == 1 and systems[0].content != system.content  # system minimo
    assert HumanMessage(content="22h") in janela
    assert _fala() not in janela  # a fala final foi excluida da janela de extracao
