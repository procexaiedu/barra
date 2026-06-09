"""no_llm: fallback deterministico de extracao por turno (#2, diagnostico E2E 2026-06-09).

Quando o LLM encerra o turno SEM chamar registrar_extracao, o no forca 1 chamada (tool_choice)
antes de fechar -- a FSM nao defasa. Sem API real (chat FAKE) nem banco: cobre so o roteamento
do no `llm`. Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.nos.llm import no_llm
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeBound:
    """ainvoke devolve um AIMessage fixo e registra as mensagens com que foi chamado."""

    def __init__(self, resp: AIMessage | None) -> None:
        self._resp = resp
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        assert self._resp is not None
        return self._resp


class _FakeChat:
    """bind_tools devolve binds distintos p/ o caminho normal e o forcado (tool_choice)."""

    model = "claude-test"

    def __init__(self, resp_normal: AIMessage, resp_forcado: AIMessage | None) -> None:
        self.normal = _FakeBound(resp_normal)
        self.forcado = _FakeBound(resp_forcado)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeBound:
        return self.forcado if tool_choice is not None else self.normal


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))


def _texto_final() -> AIMessage:
    """Resposta final ao cliente: texto, sem tool_calls (o caso que defasava a FSM)."""
    return AIMessage(
        content="às 10h15 te serve?",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


def _extracao(stop_reason: str = "tool_use", *, com_tool: bool = True) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": stop_reason},
        tool_calls=(
            [{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}]
            if com_tool
            else []
        ),
    )


async def test_forca_extracao_quando_llm_esquece() -> None:
    """LLM encerra sem registrar_extracao -> forca 1 chamada e despacha pelo `tools`."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="daqui uma hr")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_extracao_forcada"] is True
    # texto ao cliente preservado + extracao forcada anexada, nessa ordem
    assert cmd.update["messages"] == [chat.normal._resp, chat.forcado._resp]
    # forcado roda sobre o contexto SEM o `resp` assistant (senao 2 assistant consecutivas = 400)
    assert chat.forcado.chamadas == [state["messages"]]


async def test_reentrada_pos_forca_fecha_sem_reinvocar_modelo() -> None:
    """Guard `_extracao_forcada`: pós-`tools`, fecha no post_process sem chamar o modelo de novo."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")], "_extracao_forcada": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []  # modelo NAO reinvocado (sem bolha dupla, sem custo)
    assert chat.forcado.chamadas == []


async def test_nao_forca_quando_ja_extraiu_no_turno() -> None:
    """registrar_extracao ja rodou neste turno (AIMessage com usage) -> sem forcamento."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    # janela ja contem uma extracao deste turno (usage_metadata != None)
    state = {"messages": [HumanMessage(content="oi"), _extracao()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]
    assert chat.forcado.chamadas == []  # nao forcou


async def test_extracao_forcada_truncada_e_descartada() -> None:
    """Forcado trunca (args incompletos) -> descarta e fecha; nunca persiste payload parcial."""
    chat = _FakeChat(_texto_final(), _extracao("max_tokens"))
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]  # so o texto; forcado descartado
    assert "_extracao_forcada" not in cmd.update


async def test_kill_switch_desliga_forcamento(monkeypatch: pytest.MonkeyPatch) -> None:
    """forcar_extracao_por_turno=False -> chat_forcado None, comportamento antigo (sem força)."""
    monkeypatch.setattr(get_settings(), "forcar_extracao_por_turno", False)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.forcado.chamadas == []


async def test_tool_call_normal_segue_react_sem_forcar() -> None:
    """Regressao: resposta COM tool_call (loop ReAct) nao aciona o fallback."""
    chat = _FakeChat(_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert "_extracao_forcada" not in cmd.update
    assert chat.forcado.chamadas == []
