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
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command

from ..contexto import ContextAgente
from ..estado import EstadoAgente

logger = logging.getLogger(__name__)

class _NoLLM(Protocol):
    """Forma do no llm aceita pelo StateGraph (runtime keyword-only, como langgraph espera)."""

    def __call__(
        self, state: EstadoAgente, *, runtime: Runtime[ContextAgente]
    ) -> Coroutine[Any, Any, Command[Literal["tools", "post_process"]]]: ...


def no_llm(chat: ChatAnthropic, tools: Sequence[BaseTool]) -> _NoLLM:
    """Factory: liga o ChatAnthropic + catalogo de tools ao no llm.

    O chat e injetado por build_graph (09 §4.5) para nao reconstruir o ChatAnthropic a cada
    invocacao. bind_tools roda uma vez aqui; com TOOLS=[] (M0) o prefixo de tools sai vazio e
    byte-identico p/ todas as modelos (invariante de cache -- agente/CLAUDE.md).
    """
    chat_bound = chat.bind_tools(tools)

    async def llm(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["tools", "post_process"]]:
        try:
            resp = await chat_bound.ainvoke(state["messages"])
            # stop_reason chega num 200 OK, nao como excecao (09 §4.2 / docs/claudedocs/stop.md):
            stop_reason = (resp.response_metadata or {}).get("stop_reason")
            if stop_reason == "refusal":
                # safety filter do Sonnet -> escala p/ Fernando (sem fallback de modelo, 01 §2.6).
                # TODO(M3): escalar_por_exaustao(motivo="modelo_recusou") -- nasce no M3f
                logger.warning("llm stop_reason=refusal (turno_id=%s)", runtime.context.turno_id)
            elif stop_reason == "max_tokens":
                # premissa: max_tokens=1024 nao trunca (03 §6.1). No P0 so observa, nao escala.
                # TODO(M2): TURNO_TRUNCADO.inc() -- metrica nasce no M2-T2
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
