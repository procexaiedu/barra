"""no_llm: roteamento para o no `extrair` (novo contrato, 02 §4).

Depois da virada de chave, o `llm` NAO forca mais a extracao nem reentra pos-`tools`: quando encerra
o turno SEM tool_call (resposta final ao cliente), roteia para o no `extrair`, que le o estado da
negociacao pos-fala. `registrar_extracao` saiu de `TOOLS` -- o chat #1 nunca a chama. Este arquivo
cobre o que e responsabilidade do `llm`:
  - resposta final (sem tool_call) -> `extrair`;
  - tool_call (leitura/midia) -> loop ReAct (`tools`), sem forcar nada;
  - tool_use truncado e midia esgotada -> `post_process` DIRETO (nao passam por `extrair`).
O roteamento INTERNO do `extrair` (sucesso/escalada canned -> post_process; erro recuperavel ->
reoferta no llm; mute na 2a falha) e a execucao inline vivem em test_extrair_no.py / test_extrair_
inline.py (needs_db). Sem API real (chat FAKE) nem banco: roda no gate `-m "not needs_key and not
needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente.ferramentas import TOOLS
from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.nos.llm import no_llm

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeBound:
    """ainvoke devolve um AIMessage fixo e registra as mensagens com que foi chamado."""

    def __init__(self, resp: AIMessage) -> None:
        self._resp = resp
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        return self._resp


class _FakeChat:
    """bind_tools distingue o bind normal do fecha-em-texto (tool_choice="none")."""

    model = "deepseek-test"

    def __init__(self, resp_normal: AIMessage, resp_sem_tool: AIMessage | None = None) -> None:
        self.normal = _FakeBound(resp_normal)
        self.sem_tool = _FakeBound(resp_sem_tool if resp_sem_tool is not None else resp_normal)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeBound:
        return self.sem_tool if tool_choice == "none" else self.normal


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))


def _texto_final() -> AIMessage:
    """Resposta final ao cliente: texto, sem tool_calls -> deve rotear a `extrair`."""
    return AIMessage(
        content="às 10h15 te serve?",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


def _leitura() -> AIMessage:
    """Tool de LEITURA (consultar_agenda): loop ReAct -> `tools`, nunca `extrair`."""
    return AIMessage(
        content="deixa eu ver minha agenda",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "tool_use"},
        tool_calls=[{"name": "consultar_agenda", "args": {}, "id": "ca1", "type": "tool_call"}],
    )


def _tool_use_truncado() -> AIMessage:
    """tool_use com truncamento (max_tokens): args podem estar incompletos -> post_process."""
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "max_tokens"},
        tool_calls=[{"name": "consultar_agenda", "args": {}, "id": "ca1", "type": "tool_call"}],
    )


async def test_resposta_final_sem_tool_call_vai_para_extrair() -> None:
    """Novo contrato: o llm encerra em texto (sem tool_call) -> `extrair` (le o estado pos-fala).
    NAO forca extracao aqui nem seta flags de fallback (removidos)."""
    chat = _FakeChat(_texto_final())
    node = no_llm(chat, TOOLS)
    state = {"messages": [HumanMessage(content="daqui uma hr")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "extrair"
    assert cmd.update["messages"] == [chat.normal._resp]  # a fala segue no state p/ o extrair
    # sem forcamento: o chat foi chamado UMA vez (a geracao da fala), nada a mais.
    assert len(chat.normal.chamadas) == 1


async def test_tool_call_segue_react_para_tools() -> None:
    """tool_call (consultar_agenda) segue o loop ReAct -> `tools`, nunca `extrair`."""
    chat = _FakeChat(_leitura())
    node = no_llm(chat, TOOLS)
    state = {"messages": [HumanMessage(content="amanha 10h tem?")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["messages"] == [chat.normal._resp]


async def test_tool_use_truncado_nao_passa_por_extrair() -> None:
    """tool_use truncado -> post_process DIRETO (o coordenador escala modelo_truncado); nao vai a
    `tools` (args incompletos) nem a `extrair`."""
    chat = _FakeChat(_tool_use_truncado())
    node = no_llm(chat, TOOLS)
    state = {"messages": [HumanMessage(content="amanha?")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]


def _midia_erro(i: int) -> ToolMessage:
    return ToolMessage(
        content="ERRO: você não tem NENHUMA foto cadastrada no sistema.",
        name="enviar_midia",
        tool_call_id=f"m{i}",
        status="error",
    )


def _ai_pede_midia(i: int) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[
            {"name": "enviar_midia", "args": {"tag": "corpo"}, "id": f"m{i}", "type": "tool_call"}
        ],
    )


async def test_midia_esgotada_nao_passa_por_extrair() -> None:
    """Cap de midia (>=2 enviar_midia com erro): fecha em texto (tool_choice="none") e vai a
    post_process DIRETO, sem passar por `extrair`. One-shot via `_midia_esgotada`."""
    chat = _FakeChat(_texto_final(), _texto_final())
    node = no_llm(chat, TOOLS)
    state = {
        "messages": [
            HumanMessage(content="tem foto?"),
            _ai_pede_midia(1),
            _midia_erro(1),
            _ai_pede_midia(2),
            _midia_erro(2),
        ]
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["_midia_esgotada"] is True
    assert cmd.update["messages"] == [chat.sem_tool._resp]  # texto garantido ao cliente
    assert chat.sem_tool.chamadas == [state["messages"]]  # fechou via bind sem-tool-call
    assert chat.normal.chamadas == []  # nao reinvocou o loop


def test_registrar_extracao_fora_do_catalogo() -> None:
    """Invariante do ticket: `registrar_extracao` NAO esta em `TOOLS` (bindada so no `extrair`),
    e as 3 tools restantes ficam na ordem fixa (invariante de prefixo)."""
    assert [t.name for t in TOOLS] == ["consultar_agenda", "enviar_midia", "escalar"]
    assert registrar_extracao.name == "registrar_extracao"
    assert registrar_extracao not in TOOLS
    # continua com handle_tool_error (setado explicitamente ao sair da lista iterada).
    assert registrar_extracao.handle_tool_error is True
