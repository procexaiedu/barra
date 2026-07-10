"""no_llm: cap do loop de `enviar_midia` sem mídia (trace 8194e2c0, 2026-07-10).

Quando a modelo não tem mídia, o modelo insiste em `enviar_midia` (tag após tag); sem freio o loop
tools<->llm estoura o recursion_limit -> GraphRecursionError -> escalar_por_exaustao -> SILÊNCIO ao
cliente. Ao ver >=2 `enviar_midia` com erro no turno, o nó força UMA resposta em texto (bind
tool_choice="none") e fecha. Sem API real (chat FAKE) nem banco: cobre só o roteamento do nó `llm`.
Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.ferramentas.midia import enviar_midia
from barra.agente.nos.llm import _midias_falharam_no_turno, no_llm

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeBound:
    def __init__(self, resp: AIMessage) -> None:
        self._resp = resp
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        return self._resp


class _FakeChat:
    """bind_tools distingue tool_choice="none" (fecha em texto) de None (normal) e da força."""

    model = "deepseek-test"

    def __init__(self, resp_normal: AIMessage, resp_sem_tool: AIMessage) -> None:
        self.normal = _FakeBound(resp_normal)
        self.sem_tool = _FakeBound(resp_sem_tool)
        self.forcado = _FakeBound(resp_normal)  # não exercitado aqui

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeBound:
        if tool_choice == "none":
            return self.sem_tool
        if tool_choice is not None:
            return self.forcado
        return self.normal


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))


def _texto_normal() -> AIMessage:
    return AIMessage(
        content="oii amor 🥰",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "stop"},
        tool_calls=[],
    )


def _texto_sem_midia() -> AIMessage:
    """Resposta em texto do fecha-em-texto (tool_choice="none")."""
    return AIMessage(
        content="poxa amor, minhas fotos tão indisponíveis agora, mas você vai gostar ao vivo 😊",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "stop"},
        tool_calls=[],
    )


def _midia_erro(i: int) -> ToolMessage:
    """ToolMessage de erro de enviar_midia (modelo sem mídia)."""
    return ToolMessage(
        content="ERRO: você não tem NENHUMA foto cadastrada no sistema. NÃO tente outras tags.",
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


_TOOLS = [registrar_extracao, enviar_midia]


def test_helper_conta_so_erros_de_enviar_midia() -> None:
    msgs = [
        HumanMessage(content="tem foto?"),
        _midia_erro(1),
        ToolMessage(content="ok", name="enviar_midia", tool_call_id="m2"),  # sucesso: não conta
        _midia_erro(3),
        ToolMessage(
            content="ERRO: agenda", name="registrar_extracao", tool_call_id="e1", status="error"
        ),
    ]
    assert _midias_falharam_no_turno(msgs) == 2  # só os 2 erros de enviar_midia


async def test_duas_falhas_de_midia_fecham_em_texto() -> None:
    """>=2 enviar_midia com erro -> fecha em TEXTO (tool_choice="none"), não reinvoca o chat normal."""
    chat = _FakeChat(_texto_normal(), _texto_sem_midia())
    node = no_llm(chat, _TOOLS)
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
    assert cmd.update["messages"] == [chat.sem_tool._resp]  # texto ao cliente (garantido)
    assert chat.sem_tool.chamadas == [state["messages"]]  # fechou via bind sem-tool-call
    assert chat.normal.chamadas == []  # NÃO reinvoca o loop -> sem crash/silêncio


async def test_uma_falha_de_midia_nao_dispara_o_cap() -> None:
    """1 falha só (pode ser tag vazia / foto travada) -> segue o fluxo normal, não fecha ainda."""
    chat = _FakeChat(_texto_normal(), _texto_sem_midia())
    node = no_llm(chat, _TOOLS)
    state = {"messages": [HumanMessage(content="tem foto?"), _ai_pede_midia(1), _midia_erro(1)]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto in ("tools", "post_process")  # fluxo normal
    assert chat.sem_tool.chamadas == []  # cap NÃO disparou
    assert "_midia_esgotada" not in (cmd.update or {})


async def test_midia_esgotada_ja_setada_nao_redispara() -> None:
    """One-shot: _midia_esgotada já True -> não fecha em texto de novo (segue fluxo normal)."""
    chat = _FakeChat(_texto_normal(), _texto_sem_midia())
    node = no_llm(chat, _TOOLS)
    state = {
        "messages": [
            HumanMessage(content="tem foto?"),
            _ai_pede_midia(1),
            _midia_erro(1),
            _ai_pede_midia(2),
            _midia_erro(2),
        ],
        "_midia_esgotada": True,
    }

    await node(state, _runtime())  # type: ignore[arg-type]

    assert chat.sem_tool.chamadas == []  # não re-dispara o fecha-em-texto
    assert chat.normal.chamadas == [state["messages"]]  # segue o fluxo normal (reinvoca uma vez)
