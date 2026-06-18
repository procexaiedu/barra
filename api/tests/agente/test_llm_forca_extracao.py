"""no_llm: fallback deterministico de extracao por turno (#2, diagnostico E2E 2026-06-09).

Quando o LLM encerra o turno SEM chamar registrar_extracao, o no forca 1 chamada (tool_choice)
antes de fechar -- a FSM nao defasa. Sem API real (chat FAKE) nem banco: cobre so o roteamento
do no `llm`. Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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


def _texto_mais_extracao() -> AIMessage:
    """1a passagem inline do DeepSeek: texto client-facing + registrar_extracao na MESMA AIMessage.

    Padrao que o Sonnet nao faz no abridor (responde OU extrai), mas o DeepSeek V4 Flash faz --
    e que, sem o curto-circuito, deixa a reentrada do ReAct reinvocar o modelo (2a bolha espuria,
    trace 022e0a70 de 2026-06-18). finish_reason=tool_calls (formato OpenRouter).
    """
    return AIMessage(
        content="Oii\n\ntudo sim, e você",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )


def _texto_mais_leitura() -> AIMessage:
    """ReAct legitimo: texto + tool de LEITURA (consultar_agenda). A reentrada deve reinvocar
    (o modelo precisa do resultado da agenda p/ seguir) -- nao pode cair no curto-circuito."""
    return AIMessage(
        content="deixa eu ver minha agenda",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[{"name": "consultar_agenda", "args": {}, "id": "ca1", "type": "tool_call"}],
    )


def _extracao(
    motivo_parada: str = "tool_use", *, com_tool: bool = True, chave: str = "stop_reason"
) -> AIMessage:
    # chave="stop_reason" (Anthropic) ou "finish_reason" (OpenRouter): o no le os dois via
    # core.llm.motivo_parada.
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={chave: motivo_parada},
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


async def test_extracao_forcada_openrouter_length_descartada() -> None:
    """Forcado no provider OpenRouter trunca como finish_reason=length (com tool_call presente) ->
    o no descarta via PARADA_TRUNCADA, igual ao max_tokens da Anthropic. Prova o mapeamento
    provider-aware do motivo de parada na #2."""
    chat = _FakeChat(_texto_final(), _extracao("length", chave="finish_reason"))
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]  # forcado truncado descartado
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


async def test_extracao_forcada_roteia_pro_chat_barato_sem_system() -> None:
    """chat_extracao_barata injetado -> forca no Haiku sobre a janela SEM o SystemMessage geral."""
    chat = _FakeChat(_texto_final(), _extracao())
    barato = _FakeChat(_extracao(), _extracao())  # so o bind forcado (tool_choice) e usado
    node = no_llm(chat, [registrar_extracao], chat_extracao_barata=barato)
    system = SystemMessage(content="PERSONA GIGANTE ~14k tokens")
    state = {"messages": [system, HumanMessage(content="daqui uma hr")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_extracao_forcada"] is True
    # texto do Sonnet preservado + extracao do chat BARATO, nessa ordem
    assert cmd.update["messages"] == [chat.normal._resp, barato.forcado._resp]
    # o Sonnet NAO foi chamado p/ a extracao; o barato foi
    assert chat.forcado.chamadas == []
    assert len(barato.forcado.chamadas) == 1
    # janela do barato: system minimo de extracao (nao o gigante) + a conversa preservada
    janela = barato.forcado.chamadas[0]
    systems = [m for m in janela if isinstance(m, SystemMessage)]
    assert len(systems) == 1 and systems[0].content != system.content
    assert HumanMessage(content="daqui uma hr") in janela


async def test_tool_call_normal_segue_react_sem_forcar() -> None:
    """Regressao: resposta COM tool_call (loop ReAct) nao aciona o fallback."""
    chat = _FakeChat(_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert "_extracao_forcada" not in cmd.update
    assert chat.forcado.chamadas == []


async def test_texto_mais_extracao_inline_marca_turno_concluido() -> None:
    """Bug DeepSeek (1/2): texto + registrar_extracao na MESMA msg -> marca o turno concluido.

    A extracao ainda roteia pelo `tools` (FSM intacta), mas a flag sinaliza a reentrada a fechar
    sem reinvocar (espelha _extracao_forcada). NAO forca: a extracao ja veio inline."""
    chat = _FakeChat(_texto_mais_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_resposta_inline_concluida"] is True
    assert cmd.update["messages"] == [chat.normal._resp]
    assert chat.forcado.chamadas == []  # extracao veio inline -> sem forcamento


async def test_reentrada_pos_extracao_inline_nao_reinvoca_modelo() -> None:
    """Bug DeepSeek (2/2): pos-`tools`, a reentrada do ReAct NAO pode reinvocar o modelo.

    Sem o guard, o DeepSeek tagarela "deixou ele conduzir" (2a bolha espuria, trace 022e0a70).
    Com a flag, fecha direto no post_process -- mesma protecao do _extracao_forcada."""
    chat = _FakeChat(_texto_mais_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")], "_resposta_inline_concluida": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []  # modelo NAO reinvocado -> sem 2a bolha
    assert chat.forcado.chamadas == []


async def test_texto_mais_tool_de_leitura_nao_curto_circuita() -> None:
    """ReAct legitimo: texto + tool de LEITURA (consultar_agenda) deve reinvocar normalmente --
    o curto-circuito so vale p/ a tool write-only de extracao."""
    chat = _FakeChat(_texto_mais_leitura(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="amanha 10h tem?")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert "_resposta_inline_concluida" not in cmd.update  # nao curto-circuita
