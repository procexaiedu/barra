"""no_llm: tratamento de stop_reason de truncamento (STOP-03/06) e log do id Anthropic (REL-OBS-02).

Sem API real (chat FAKE) nem banco: cobre o roteamento do no `llm` por stop_reason e os logs de
correlacao com a Anthropic. Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from anthropic import RateLimitError
from langchain_core.messages import AIMessage

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_TOOL_CALL = {"name": "consultar_agenda", "args": {}, "id": "tc1", "type": "tool_call"}


class _FakeChatBound:
    """ainvoke devolve um AIMessage fixo OU levanta uma excecao (caminho de erro do SDK)."""

    def __init__(self, resp: AIMessage | None, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc

    async def ainvoke(self, _messages: Any) -> AIMessage:
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


class _FakeChat:
    model = "claude-test"

    def __init__(self, resp: AIMessage | None, exc: Exception | None = None) -> None:
        self._bound = _FakeChatBound(resp, exc)

    def bind_tools(self, _tools: Any) -> _FakeChatBound:
        return self._bound


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))


def _ai(stop_reason: str, *, com_tool: bool, extra_meta: dict[str, Any] | None = None) -> AIMessage:
    meta = {"stop_reason": stop_reason, **(extra_meta or {})}
    return AIMessage(
        content="" if com_tool else "texto truncado",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata=meta,
        tool_calls=[_TOOL_CALL] if com_tool else [],
    )


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
async def test_tool_use_truncado_nao_despacha_tool(
    stop_reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    """STOP-03/06: truncamento COM tool_use -> post_process (nao 'tools'); a tool nao executa."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai(stop_reason, com_tool=True)), [])
    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        comando = await node({"messages": []}, _runtime())  # type: ignore[arg-type]

    assert comando.goto == "post_process"  # NAO "tools": args podem estar incompletos
    assert "tool_use truncado" in caplog.text


async def test_max_tokens_sem_tool_use_vai_para_extrair() -> None:
    """Truncamento de TEXTO (sem tool_use): so observa a metrica e segue o ramo sem tool_call ->
    `extrair` (02 §4, a extracao le o estado pos-fala). Antes ia a post_process via o fallback #2,
    hoje removido."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai("max_tokens", com_tool=False)), [])
    comando = await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert comando.goto == "extrair"


async def test_tool_use_completo_vai_para_tools() -> None:
    """Regressao: tool_use SEM truncamento (stop_reason=tool_use) segue o loop ReAct p/ 'tools'."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai("tool_use", com_tool=True)), [])
    comando = await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert comando.goto == "tools"


async def test_refusal_loga_anthropic_msg_id(caplog: pytest.LogCaptureFixture) -> None:
    """REL-OBS-02: refusal (200 OK) loga o id da mensagem do provider p/ correlacao/suporte."""
    from barra.agente.nos.llm import no_llm

    resp = _ai("refusal", com_tool=False, extra_meta={"id": "msg_01ABC", "stop_details": {}})
    node = no_llm(_FakeChat(resp), [])
    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert "msg_id=msg_01ABC" in caplog.text


def _ai_openai(finish_reason: str, *, com_tool: bool) -> AIMessage:
    """AIMessage no formato OpenAI/OpenRouter (DeepSeek): parada em `finish_reason`, nao stop_reason."""
    return AIMessage(
        content="" if com_tool else "texto",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": finish_reason},
        tool_calls=[_TOOL_CALL] if com_tool else [],
    )


async def test_finish_reason_length_trata_como_truncado() -> None:
    """Provider-agnostico: truncamento OpenAI/OpenRouter vem como finish_reason='length' e cai no
    mesmo caminho de PARADA_TRUNCADA (tool_use nao despachado), via motivo_parada."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai_openai("length", com_tool=True)), [])
    comando = await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert comando.goto == "post_process"  # NAO "tools"


async def test_finish_reason_content_filter_trata_como_recusa(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Provider-agnostico: recusa OpenAI/OpenRouter vem como finish_reason='content_filter' e cai
    no branch de recusa (loga parada=recusa), via _PARADA_RECUSA."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai_openai("content_filter", com_tool=False)), [])
    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert "parada=recusa" in caplog.text


async def test_erro_sdk_loga_anthropic_request_id(caplog: pytest.LogCaptureFixture) -> None:
    """REL-OBS-02: erro do SDK (429/5xx) loga o request_id da Anthropic (header request-id)."""
    from barra.agente.nos.llm import no_llm

    http_resp = httpx.Response(
        429,
        headers={"request-id": "req_XYZ789"},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    exc = RateLimitError("rate limited", response=http_resp, body=None)
    node = no_llm(_FakeChat(None, exc=exc), [])

    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        with pytest.raises(RateLimitError):  # erro propaga (escala no coordenador), mas loga antes
            await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert "anthropic_request_id=req_XYZ789" in caplog.text
