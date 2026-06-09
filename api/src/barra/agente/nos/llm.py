"""No llm.

M0: no real -- chama Anthropic Sonnet 4.6 via ChatAnthropic (langchain-anthropic 1.x) com
    as tools bindadas e roteia por Command(goto=...). Sem modelo de fallback: 429/5xx/timeout
    sobem como excecao (retry ja foi do SDK, max_retries) e, na exaustao, escalam para Fernando
    via escalar_por_exaustao (TODO M3f; 01 §2.6). O check de stop_reason (refusal/max_tokens
    chegam em 200 OK, nao como excecao -- docs/agente/referencia/stop.md) vive dentro do try/except
    (09 §4.2). Sem effort hibridizado por turno (removido, 03 §6.2.1); a classificacao de
    disclosure roda no prepare_context sobre a janela (03 §7), nao no webhook.
"""

import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol

from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command

from barra.core.metrics import AGENTE_CUSTO_TURNO_BRL, AGENTE_TURNO_TOKENS, TURNO_TRUNCADO
from barra.settings import get_settings

from .._custo import calcular_custo_brl
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..ferramentas import INPUT_EXAMPLES, STRICT_TOOLS
from ..llm import build_tools_para_bind

logger = logging.getLogger(__name__)

# stop_reasons de TRUNCAMENTO (a resposta foi cortada): max_tokens (teto do turno) e
# model_context_window_exceeded (janela do modelo). Quando truncam COM tool_use, os args podem
# vir incompletos -> nao despachar a tool (STOP-03/06). Ambos chegam em 200 OK, nao como excecao.
_STOP_TRUNCADO = ("max_tokens", "model_context_window_exceeded")

# Fallback deterministico de extracao (#2): nome da tool de escrita que persiste o snapshot do
# turno. Quando o LLM encerra sem chama-la, o no forca 1 chamada (tool_choice) antes de fechar.
_TOOL_EXTRACAO = "registrar_extracao"


def _extraiu_no_turno(messages: Sequence[BaseMessage]) -> bool:
    """True se `registrar_extracao` foi chamada por uma AIMessage GERADA neste turno.

    `usage_metadata is not None` isola as AIMessages reais deste `ainvoke` das historicas
    re-injetadas pelo prepare_context (sem usage) -- mesma heuristica de `_extrair_texto_do_turno`
    no coordenador. So conta tool_call cujo nome bate exatamente.
    """
    for m in messages:
        if isinstance(m, AIMessage) and m.usage_metadata is not None:
            if any(tc.get("name") == _TOOL_EXTRACAO for tc in (m.tool_calls or [])):
                return True
    return False


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
    # AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta em settings.custo_alvo_brl). Mesmo label `modelo` p/ correlato.
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
    # strict PER-TOOL (STRICT_TOOLS = {"escalar"}); master-switch anthropic_strict_tools desliga
    # tudo sem deploy. input_examples sempre injetados (ajudam tool-calling, custo no cache de
    # tools pago 1x). Ambos byte-identicos p/ todas as modelos (invariante de prefixo).
    tools_para_bind = build_tools_para_bind(
        tools,
        ttl=settings.cache_ttl_geral,
        strict_tools=STRICT_TOOLS if settings.anthropic_strict_tools else frozenset(),
        exemplos=INPUT_EXAMPLES,
    )
    chat_bound = chat.bind_tools(tools_para_bind)
    # Fallback deterministico de extracao (#2): 2o bind que FORCA registrar_extracao via
    # tool_choice (doc oficial `tool-use` / langchain-anthropic bind_tools). So existe quando a
    # tool esta no catalogo e o kill-switch esta ligado -- em M0/testes (TOOLS=[]) fica None e o
    # caminho de forcamento some, sem tocar o bind normal nem o cache do prefixo (tool_choice e
    # parametro de request do 2o bind, nao altera o prefixo cacheado tools+system do 1o).
    nomes_tools = {t.name for t in tools}
    chat_forcado = (
        chat.bind_tools(tools_para_bind, tool_choice=_TOOL_EXTRACAO)
        if _TOOL_EXTRACAO in nomes_tools and settings.forcar_extracao_por_turno
        else None
    )
    # nome Anthropic (claude-sonnet-4-6) p/ o label das metricas de token, nao o modelo_id da
    # agencia (03 §4.2). Lido via `.model`, nao `.model_name` (M0-T1; alias write-only no 1.4.3).
    modelo_anthropic = chat.model

    async def llm(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["tools", "post_process"]]:
        # Reentrada pos-extracao forcada (#2): o `tools` ja rodou a registrar_extracao forcada e
        # o texto ao cliente ja vive em `messages` (resp do turno). NAO reinvocar o modelo --
        # fecharia uma 2a bolha e custaria 1 request a toa. Fecha o turno direto no post_process
        # (que ainda refaz o gate de pausa). O guard tambem corta loop infinito de forcamento.
        if state.get("_extracao_forcada"):
            return Command(goto="post_process")
        try:
            resp = await chat_bound.ainvoke(state["messages"])
            _instrumentar_tokens(resp, modelo_anthropic)
            # stop_reason chega num 200 OK, nao como excecao (09 §4.2 / docs/agente/referencia/stop.md):
            stop_reason = (resp.response_metadata or {}).get("stop_reason")
            if stop_reason == "refusal":
                # safety filter do Sonnet -> escala p/ Fernando (sem fallback de modelo, 01 §2.6).
                # O sinal viaja no response_metadata da AIMessage (canal `messages` do state):
                # o coordenador le stop_reason apos o ainvoke e aciona escalar_por_exaustao
                # (motivo="modelo_recusou"), pausando a IA sem mandar a bolha crua ao cliente.
                detalhes = (resp.response_metadata or {}).get("stop_details") or {}
                logger.warning(
                    "llm stop_reason=refusal (turno_id=%s category=%s anthropic_msg_id=%s)",
                    runtime.context.turno_id,
                    detalhes.get("category"),
                    (resp.response_metadata or {}).get("id"),  # REL-OBS-02: id da msg Anthropic
                )
            elif stop_reason in _STOP_TRUNCADO:
                # premissa: max_tokens=1024 nao trunca (03 §6.1). Quando trunca COM tool_use, o
                # roteamento abaixo NAO despacha a tool e o coordenador escala (modelo_truncado);
                # sem tool_use so observa -- o spike na metrica decide revisar o teto.
                TURNO_TRUNCADO.inc()
                logger.warning(
                    "llm stop_reason=%s (turno_id=%s)", stop_reason, runtime.context.turno_id
                )
        except (RateLimitError, APITimeoutError, APIStatusError) as exc:
            # exaustao de retry do SDK / 5xx / timeout -> escala (sem fallback de modelo, 01 §2.6).
            # REL-OBS-02: loga o request_id da Anthropic (header `request-id`, chave do ticket de
            # suporte) -- presente em APIStatusError/RateLimitError; timeout sem resposta -> None.
            logger.warning(
                "llm indisponivel: %s (turno_id=%s anthropic_request_id=%s)",
                type(exc).__name__,
                runtime.context.turno_id,
                getattr(exc, "request_id", None),
            )
            raise

        # roteamento por Command (09 §4.1): tem tool_calls -> loop ReAct; senao -> post_process.
        # No M0 (TOOLS=[]) o LLM nunca pede tool_call -> sempre post_process; o ramo "tools" fica
        # dormente p/ o M1. getattr porque tool_calls so existe em AIMessage, nao em BaseMessage.
        if getattr(resp, "tool_calls", None):
            if stop_reason in _STOP_TRUNCADO:
                # STOP-03/06: tool_use truncado (teto do turno / janela de contexto) -> args podem
                # estar incompletos. NAO despacha a tool; vai p/ post_process e o coordenador escala
                # (modelo_truncado) lendo o sinal stop_reason+tool_calls, sem bolha crua ao cliente.
                logger.warning(
                    "llm tool_use truncado por %s (turno_id=%s) -> nao despacha tool",
                    stop_reason,
                    runtime.context.turno_id,
                )
                return Command(goto="post_process", update={"messages": [resp]})
            return Command(goto="tools", update={"messages": [resp]})

        # Resposta final ao cliente (sem tool_calls). Fallback deterministico (#2): se NENHUM
        # registrar_extracao rodou neste turno, a FSM defasaria (valor/tipo/horario nao persistem).
        # Forca 1 extracao via tool_choice e despacha pelo `tools`; a reentrada (guard acima) fecha
        # o turno sem reinvocar o modelo -> sem bolha dupla, +1 request so quando o LLM esqueceu.
        if chat_forcado is not None and not _extraiu_no_turno(state["messages"]):
            # Forca sobre `state["messages"]` (NAO inclui `resp`): a request precisa terminar numa
            # msg user/tool p/ o modelo responder -- anexar `resp` (assistant) daria 2 assistant
            # consecutivas (400). `resp` so vai no update local; nunca volta a Anthropic (a
            # reentrada nao reinvoca). A extracao olha o contexto do cliente, ja completo aqui.
            forcado = await chat_forcado.ainvoke(state["messages"])
            _instrumentar_tokens(forcado, modelo_anthropic)
            forcado_stop = (forcado.response_metadata or {}).get("stop_reason")
            if forcado_stop in _STOP_TRUNCADO or not getattr(forcado, "tool_calls", None):
                # Extracao forcada truncou (args incompletos) ou nao saiu tool_call: descarta o
                # forcado e fecha como antes do fix (turno sem extracao) -- nunca persiste payload
                # incompleto. Caso raro (max_tokens=1024 nao trunca o schema pequeno, 03 §6.1).
                logger.warning(
                    "extracao forcada sem tool_call util (stop=%s turno_id=%s)",
                    forcado_stop,
                    runtime.context.turno_id,
                )
                return Command(goto="post_process", update={"messages": [resp]})
            logger.info("extracao forcada (turno_id=%s)", runtime.context.turno_id)
            return Command(
                goto="tools",
                update={"messages": [resp, forcado], "_extracao_forcada": True},
            )
        return Command(goto="post_process", update={"messages": [resp]})

    return llm
