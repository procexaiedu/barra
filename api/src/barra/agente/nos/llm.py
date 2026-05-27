"""No llm.

M0: no real -- chama Anthropic Sonnet 4.6 via ChatAnthropic (langchain-anthropic 1.x) com
    as tools bindadas e roteia por Command(goto=...). Sem modelo de fallback: 429/5xx/timeout
    sobem como excecao (retry ja foi do SDK, max_retries) e, na exaustao, escalam para Fernando
    via escalar_por_exaustao (TODO M3f; 01 §2.6). O check de stop_reason (refusal/max_tokens
    chegam em 200 OK, nao como excecao -- docs/claudedocs/stop.md) vive dentro do try/except
    (09 §4.2). Sem effort hibridizado por turno (removido, 03 §6.2.1); a classificacao de
    disclosure roda no prepare_context sobre a janela (03 §7), nao no webhook.
"""

import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol

from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command

from barra.core.metrics import AGENTE_CUSTO_TURNO_BRL, AGENTE_TURNO_TOKENS, TURNO_TRUNCADO
from barra.settings import get_settings

from .._custo import calcular_custo_brl
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..llm import build_tools_para_bind

logger = logging.getLogger(__name__)


def _instrumentar_tokens(resp: BaseMessage, modelo: str) -> None:
    """Incrementa AGENTE_TURNO_TOKENS nas 4 series {input,output,cache_read,cache_write} (03 §4.2).

    WRITE vem de `ephemeral_5m+ephemeral_1h`, NUNCA de `cache_creation` (no langchain-anthropic
    1.4.3 esse campo vem sempre 0 -- spike 2026-05-24). `modelo` e o nome Anthropic
    (claude-sonnet-4-6), nao o modelo_id da agencia: misturar quebra o tripwire de write-rate.
    `getattr` porque usage_metadata so existe em AIMessage, nao em BaseMessage.
    """
    um = getattr(resp, "usage_metadata", None)
    if not um:
        return
    det = um.get("input_token_details") or {}
    read = det.get("cache_read", 0)
    write = det.get("ephemeral_5m_input_tokens", 0) + det.get("ephemeral_1h_input_tokens", 0)
    AGENTE_TURNO_TOKENS.labels(modelo, "input").inc(um["input_tokens"])
    AGENTE_TURNO_TOKENS.labels(modelo, "output").inc(um["output_tokens"])
    AGENTE_TURNO_TOKENS.labels(modelo, "cache_read").inc(read)
    AGENTE_TURNO_TOKENS.labels(modelo, "cache_write").inc(write)
    # Custo BRL: tabela Sonnet 4.6 + cotacao USD/BRL (settings). Observado pelo Histogram
    # AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta <=0.12 BRL/turno). Mesmo label `modelo` p/ correlato.
    AGENTE_CUSTO_TURNO_BRL.labels(modelo).observe(
        calcular_custo_brl(um, get_settings().usd_brl_cotacao)
    )

class _NoLLM(Protocol):
    """Forma do no llm aceita pelo StateGraph (runtime keyword-only, como langgraph espera)."""

    def __call__(
        self, state: EstadoAgente, *, runtime: Runtime[ContextAgente]
    ) -> Coroutine[Any, Any, Command[Literal["tools", "post_process"]]]: ...


def no_llm(chat: ChatAnthropic, tools: Sequence[BaseTool]) -> _NoLLM:
    """Factory: liga o ChatAnthropic + catalogo de tools ao no llm.

    O chat e injetado por build_graph (09 §4.5) para nao reconstruir o ChatAnthropic a cada
    invocacao. bind_tools roda uma vez aqui com `cache_control` na ULTIMA tool (TTL = cache_ttl_geral,
    pois tools sao GERAIS como BP1/BP2; doc oficial Anthropic tool-use-with-prompt-caching). Lista
    vazia (P0 pre-M1) -> passa direto, prefixo de tools vazio e byte-identico (invariante de cache,
    agente/CLAUDE.md). Mudanca em qualquer tool invalida tools+system+messages (hierarquia).
    """
    settings = get_settings()
    tools_para_bind = build_tools_para_bind(
        tools, ttl=settings.cache_ttl_geral, strict=settings.anthropic_strict_tools
    )
    chat_bound = chat.bind_tools(tools_para_bind)
    # nome Anthropic (claude-sonnet-4-6) p/ o label das metricas de token, nao o modelo_id da
    # agencia (03 §4.2). Lido via `.model`, nao `.model_name` (M0-T1; alias write-only no 1.4.3).
    modelo_anthropic = chat.model

    async def llm(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["tools", "post_process"]]:
        try:
            resp = await chat_bound.ainvoke(state["messages"])
            _instrumentar_tokens(resp, modelo_anthropic)
            # stop_reason chega num 200 OK, nao como excecao (09 §4.2 / docs/claudedocs/stop.md):
            stop_reason = (resp.response_metadata or {}).get("stop_reason")
            if stop_reason == "refusal":
                # safety filter do Sonnet -> escala p/ Fernando (sem fallback de modelo, 01 §2.6).
                # TODO(M3): escalar_por_exaustao(motivo="modelo_recusou") -- nasce no M3f
                logger.warning("llm stop_reason=refusal (turno_id=%s)", runtime.context.turno_id)
            elif stop_reason == "max_tokens":
                # premissa: max_tokens=1024 nao trunca (03 §6.1). No P0 so observa, nao escala
                # (09 §4.2); o spike na metrica e quem decide revisar o teto / mid-tool_use.
                TURNO_TRUNCADO.inc()
                logger.warning("llm stop_reason=max_tokens (turno_id=%s)", runtime.context.turno_id)
        except (RateLimitError, APITimeoutError, APIStatusError) as exc:
            # exaustao de retry do SDK / 5xx / timeout -> escala (sem fallback de modelo, 01 §2.6).
            # TODO(M3): escalar_por_exaustao(motivo="modelo_indisponivel") -- nasce no M3f
            logger.warning(
                "llm indisponivel: %s (turno_id=%s)", type(exc).__name__, runtime.context.turno_id
            )
            raise

        # roteamento por Command (09 §4.1): tem tool_calls -> loop ReAct; senao -> post_process.
        # No M0 (TOOLS=[]) o LLM nunca pede tool_call -> sempre post_process; o ramo "tools" fica
        # dormente p/ o M1. getattr porque tool_calls so existe em AIMessage, nao em BaseMessage.
        if getattr(resp, "tool_calls", None):
            return Command(goto="tools", update={"messages": [resp]})
        return Command(goto="post_process", update={"messages": [resp]})

    return llm
