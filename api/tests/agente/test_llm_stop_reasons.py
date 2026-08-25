"""no_llm: tratamento de parada por truncamento (STOP-03/06) e log do id do provider (REL-OBS-02).

Sem API real (chat FAKE) nem banco: cobre o roteamento do no `llm` por motivo de parada e os logs
de correlacao com o provider (DeepSeek via SDK openai). Roda no gate
`-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import APIStatusError, APITimeoutError, RateLimitError

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
    # `turno_deadline_mono=None` = sem relogio de turno (o coordenador e quem o preenche): o
    # `_invocar_chat` cai no caminho sem `wait_for` e sem retry, que e o que estes testes exercem.
    # O campo TEM de existir no fake — o no o le direto (como o output_guard faz), sem getattr
    # defensivo, para que um ContextAgente sem o campo falhe alto em vez de perder o deadline calado.
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1", turno_deadline_mono=None))


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


async def test_refusal_loga_msg_id_do_provider(caplog: pytest.LogCaptureFixture) -> None:
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


async def test_insufficient_system_resource_nao_despacha_tool() -> None:
    """5o `finish_reason` do DeepSeek (api-docs `api/create-chat-completion`): o servidor fica sem
    recurso NO MEIO da geracao e devolve resposta parcial em 200 OK. Antes nao estava em conjunto
    nenhum -> a fala cortada ia ao cliente e a tool_call truncada era DESPACHADA. Agora e TRUNCADA."""
    from barra.agente.nos.llm import no_llm

    node = no_llm(_FakeChat(_ai_openai("insufficient_system_resource", com_tool=True)), [])
    comando = await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert comando.goto == "post_process"  # NAO "tools"


# --- deadline duro + retry seletivo (_invocar_chat) ---------------------------------------------


def _runtime_com_deadline(sobra_s: float) -> SimpleNamespace:
    """Runtime com relogio de turno: `sobra_s` segundos ate o deadline, como o coordenador monta."""
    return SimpleNamespace(
        context=SimpleNamespace(turno_id="t-1", turno_deadline_mono=monotonic() + sobra_s)
    )


class _FakeChatFalhaDepoisOk:
    """Levanta `exc` nas `falhas` primeiras chamadas e devolve `resp` na seguinte."""

    model = "deepseek-test"

    def __init__(self, resp: AIMessage, exc: Exception, falhas: int) -> None:
        self._resp = resp
        self._exc = exc
        self.restantes = falhas
        self.chamadas = 0

    def bind_tools(self, _tools: Any) -> _FakeChatFalhaDepoisOk:
        return self

    async def ainvoke(self, _messages: Any) -> AIMessage:
        self.chamadas += 1
        if self.restantes > 0:
            self.restantes -= 1
            raise self._exc
        return self._resp


def _erro_status(status: int) -> APIStatusError:
    resp = httpx.Response(
        status,
        headers={"x-request-id": "req_1"},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    if status == 429:
        return RateLimitError("rate limited", response=resp, body=None)
    return APIStatusError("server error", response=resp, body=None)


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retenta_429_e_5xx_quando_ha_orcamento(status: int) -> None:
    """A doc do DeepSeek (`quick_start/error_codes`) prescreve retry para 429/500/503, e o
    `max_retries` do SDK esta em 0 (o teto por-chamada nao cabe duas vezes no turno). Estes erros
    voltam em milissegundos: com o turno inteiro no relogio, retentar recupera a bolha."""
    from barra.agente.nos.llm import no_llm

    chat = _FakeChatFalhaDepoisOk(
        _ai_openai("stop", com_tool=False), _erro_status(status), falhas=1
    )
    comando = await no_llm(chat, [])({"messages": []}, _runtime_com_deadline(55.0))  # type: ignore[arg-type]
    assert chat.chamadas == 2  # falhou, retentou, entregou
    assert comando.goto == "extrair"


async def test_nao_retenta_status_que_nao_melhora() -> None:
    """400/401/402/422 nao entram: payload invalido, chave errada e saldo zerado nao mudam na
    segunda tentativa — retentar so queimaria o orcamento do turno."""
    from barra.agente.nos.llm import no_llm

    chat = _FakeChatFalhaDepoisOk(_ai_openai("stop", com_tool=False), _erro_status(400), falhas=1)
    with pytest.raises(APIStatusError):
        await no_llm(chat, [])({"messages": []}, _runtime_com_deadline(55.0))  # type: ignore[arg-type]
    assert chat.chamadas == 1


async def test_nao_retenta_sem_orcamento_para_a_segunda_chamada() -> None:
    """Com pouco tempo no relogio, reabrir a chamada so garante a morte por timeout: melhor levantar
    agora e deixar o coordenador escalar `modelo_indisponivel` com folga para gravar o handoff."""
    from barra.agente.nos.llm import no_llm

    chat = _FakeChatFalhaDepoisOk(_ai_openai("stop", com_tool=False), _erro_status(503), falhas=1)
    with pytest.raises(APIStatusError):
        await no_llm(chat, [])({"messages": []}, _runtime_com_deadline(6.0))  # type: ignore[arg-type]
    assert chat.chamadas == 1


class _FakeChatPendurado:
    """Nunca responde — o endpoint pendurado que o keep-alive do DeepSeek deixa o read timeout do
    httpx ignorar (`quick_start/rate_limit`: em nao-streaming ele manda linhas vazias enquanto espera)."""

    model = "deepseek-test"

    def bind_tools(self, _tools: Any) -> _FakeChatPendurado:
        return self

    async def ainvoke(self, _messages: Any) -> AIMessage:
        await asyncio.sleep(30)
        raise AssertionError("nao deveria completar")


async def test_chamada_pendurada_morre_dentro_do_grafo_como_apitimeout() -> None:
    """O deadline do turno mata a chamada DENTRO do no, e o erro sai como `APITimeoutError` — o
    vocabulario que o coordenador le como `modelo_indisponivel`. Solto, um `TimeoutError` subiria
    ate o `except TimeoutError` de la e viraria `timeout_grafo`, que e o diagnostico errado."""
    from barra.agente.nos.llm import no_llm

    with pytest.raises(APITimeoutError):
        await no_llm(_FakeChatPendurado(), [])({"messages": []}, _runtime_com_deadline(0.05))  # type: ignore[arg-type]


async def test_erro_sdk_loga_request_id_do_provider(caplog: pytest.LogCaptureFixture) -> None:
    """REL-OBS-02: erro do SDK (429/5xx) loga o request_id do provider (header x-request-id)."""
    from barra.agente.nos.llm import no_llm

    http_resp = httpx.Response(
        429,
        headers={"x-request-id": "req_XYZ789"},
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )
    exc = RateLimitError("rate limited", response=http_resp, body=None)
    node = no_llm(_FakeChat(None, exc=exc), [])

    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        with pytest.raises(RateLimitError):  # erro propaga (escala no coordenador), mas loga antes
            await node({"messages": []}, _runtime())  # type: ignore[arg-type]
    assert "llm_request_id=req_XYZ789" in caplog.text
