"""No llm.

No real -- chama o chat principal (#1) bindado com as tools e roteia por Command(goto=...). O chat
    e DeepSeek V4 Flash direto via ChatOpenAI (criar_chat_deepseek); o no le motivo de parada/nome
    do modelo de forma unificada (motivo_parada/nome_modelo, core.llm) -- codigo provider-agnostico,
    nao campos Anthropic crus. Sem modelo de
    fallback: 429/5xx/timeout sobem como excecao (retry ja foi do SDK, max_retries) e, na exaustao,
    escalam para Fernando via escalar_por_exaustao (TODO M3f; 01 §2.6). O check de parada
    (refusal/max_tokens chegam em 200 OK, nao como excecao) vive dentro do try/except. Sem effort
    hibridizado por turno (removido, 03 §6.2.1); a classificacao de disclosure roda no
    prepare_context sobre a janela (03 §7), nao no webhook.

Roteamento (02 §4.1): tem tool_calls -> loop ReAct (`tools`); tool_use truncado ou midia esgotada
    -> `post_process` direto; senao (resposta final ao cliente, sem tool_calls) -> `extrair`, o no
    que le o estado da negociacao pos-fala (forca a extracao, executa inline, decide a reoferta).
    A `registrar_extracao` NAO esta em `TOOLS` -- o chat #1 nunca a chama; a extracao e um no proprio.
"""

import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol

from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command
from openai import APIStatusError as OpenAIAPIStatusError
from openai import APITimeoutError as OpenAIAPITimeoutError
from openai import RateLimitError as OpenAIRateLimitError

from barra.core.llm import PARADA_RECUSA, PARADA_TRUNCADA, motivo_parada, nome_modelo
from barra.core.metrics import TURNO_TRUNCADO

from .._instrumentar import instrumentar_tokens
from ..contexto import ContextAgente
from ..estado import EstadoAgente

logger = logging.getLogger(__name__)

# Indisponibilidade do provider (retry do SDK exausto / 5xx / timeout) -> escala. O chat e DeepSeek
# via openai SDK; cobrimos tambem os tipos homonimos do SDK anthropic (infra de cache dormente/evals).
# `request_id` existe nos dois.
_EXCECOES_LLM = (
    RateLimitError,
    APITimeoutError,
    APIStatusError,
    OpenAIRateLimitError,
    OpenAIAPITimeoutError,
    OpenAIAPIStatusError,
)

# Recusa do provider (safety filter) -> escala sem mandar a bolha crua. Alias local do vocabulario
# canonico de core.llm (fonte unica; antes era um frozenset duplicado aqui -> risco de drift).
_PARADA_RECUSA = PARADA_RECUSA

# Truncamento da resposta (args de tool podem vir incompletos -> nao despachar; STOP-03/06): o
# conjunto canonico vive em core.llm.PARADA_TRUNCADA (provider-aware: max_tokens/
# model_context_window_exceeded da Anthropic + length do OpenAI/OpenRouter). Lido via motivo_parada
# (stop_reason Anthropic | finish_reason OpenAI), nao do campo cru. Todos chegam em 200 OK.

# Cap do loop de `enviar_midia` (trace 8194e2c0): quantas chamadas de midia FALHARAM no turno antes
# de o no fechar em texto. 2 = a modelo tentou 2 tags/tipos e nenhuma tinha midia -> nao ha o que
# enviar; fechar agora poupa os ~7 super-steps restantes ate o recursion_limit.
_LIMIAR_MIDIA_FALHA = 2


def _midias_falharam_no_turno(messages: Sequence[BaseMessage]) -> int:
    """Quantas `enviar_midia` FALHARAM (ToolMessage `status="error"`) neste turno.

    So conta erro, nao envio bem-sucedido: o cap fecha o turno quando o modelo insiste em
    `enviar_midia` sem midia disponivel e loopa. Turno-local: o prepare_context nao re-injeta
    ToolMessages historicas (so AIMessages, sem tool_calls) -- ver nos/tools.py.
    """
    return sum(
        1
        for m in messages
        if isinstance(m, ToolMessage)
        and m.name == "enviar_midia"
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
    )


class _NoLLM(Protocol):
    """Forma do no llm aceita pelo StateGraph (runtime keyword-only, como langgraph espera)."""

    def __call__(
        self, state: EstadoAgente, *, runtime: Runtime[ContextAgente]
    ) -> Coroutine[Any, Any, Command[Literal["tools", "post_process", "extrair"]]]: ...


def no_llm(chat: BaseChatModel, tools: Sequence[BaseTool]) -> _NoLLM:
    """Factory: liga o chat principal (#1) + catalogo de tools ao no llm.

    O chat e injetado por build_graph (09 §4.5) para nao reconstruir o cliente a cada invocacao.
    Chat = DeepSeek V4 Flash direto (ChatOpenAI): binda as BaseTool cruas no schema
    function-calling OpenAI (o cache de prefixo e automatico no provider, sem `cache_control`).
    Lista vazia (P0 pre-M1) -> passa direto.

    O no NAO forca extracao: quando o LLM encerra sem tool_call, roteia para o no `extrair`
    (nos/extrair.py), que le o estado da negociacao pos-fala. `registrar_extracao` nao esta em
    `tools` -- o chat #1 nunca a chama.
    """
    # DeepSeek-direct: binda as BaseTool cruas no schema function-calling OpenAI; o cache de prefixo
    # e automatico no provider. Lista vazia (P0 pre-M1) -> bind_tools([]) e no-op.
    chat_bound = chat.bind_tools(tools)
    # Fecha-em-texto do cap de midia (trace 8194e2c0): bind com tool_choice="none" -> o modelo NAO
    # pode pedir tool nesta chamada, responde em TEXTO. Cache-safe (tool_choice e param de request do
    # bind, nao muda o prefixo cacheado tools+system). Lista vazia (M0/testes) -> usa o chat cru
    # (sem tools ja garante texto).
    chat_sem_tool_call = chat.bind_tools(tools, tool_choice="none") if tools else chat
    # nome do modelo p/ o label das metricas de token, nao o modelo_id da agencia (03 §4.2).
    # `nome_modelo` tolera os dois wrappers (.model do ChatAnthropic / .model_name do ChatOpenAI),
    # entao funciona p/ Sonnet e DeepSeek.
    modelo_chat = nome_modelo(chat)

    async def llm(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["tools", "post_process", "extrair"]]:
        # Cap do loop de midia (trace 8194e2c0): o modelo pediu enviar_midia, a modelo nao tem midia,
        # e ele tenta tag apos tag -> sem freio o loop tools<->llm estoura o recursion_limit ->
        # GraphRecursionError -> escalar_por_exaustao -> SILENCIO ao cliente. Ao ver >=2 enviar_midia
        # com erro no turno, forca UMA resposta em TEXTO (chat_sem_tool_call: tool_choice="none")
        # e fecha DIRETO no post_process. One-shot (_midia_esgotada) p/ nao re-disparar -- garante
        # que o cliente recebe texto.
        if not state.get("_midia_esgotada") and (
            _midias_falharam_no_turno(state["messages"]) >= _LIMIAR_MIDIA_FALHA
        ):
            logger.warning(
                "midia esgotada -> fecha em texto (turno_id=%s)", runtime.context.turno_id
            )
            resp = await chat_sem_tool_call.ainvoke(state["messages"])
            instrumentar_tokens(resp, modelo_chat)
            return Command(
                goto="post_process",
                update={"messages": [resp], "_midia_esgotada": True},
            )
        try:
            resp = await chat_bound.ainvoke(state["messages"])
            instrumentar_tokens(resp, modelo_chat)
            # motivo de parada chega num 200 OK, nao como excecao. Lido provider-agnostico
            # (stop_reason Anthropic | finish_reason OpenAI/OpenRouter) via motivo_parada:
            parada = motivo_parada(resp.response_metadata)
            if parada in _PARADA_RECUSA:
                # safety filter do provider -> escala p/ Fernando (sem fallback de modelo, 01 §2.6).
                # O sinal viaja no response_metadata da AIMessage (canal `messages` do state):
                # o coordenador le a parada apos o ainvoke e aciona escalar_por_exaustao
                # (motivo="modelo_recusou"), pausando a IA sem mandar a bolha crua ao cliente.
                detalhes = (resp.response_metadata or {}).get("stop_details") or {}
                logger.warning(
                    "llm parada=recusa (turno_id=%s motivo=%s category=%s msg_id=%s)",
                    runtime.context.turno_id,
                    parada,
                    detalhes.get("category"),
                    (resp.response_metadata or {}).get("id"),  # REL-OBS-02: id da msg do provider
                )
            elif parada in PARADA_TRUNCADA:
                # premissa: max_tokens=1024 nao trunca (03 §6.1). Quando trunca COM tool_use, o
                # roteamento abaixo NAO despacha a tool e o coordenador escala (modelo_truncado);
                # sem tool_use so observa -- o spike na metrica decide revisar o teto.
                TURNO_TRUNCADO.inc()
                logger.warning("llm parada=%s (turno_id=%s)", parada, runtime.context.turno_id)
        except _EXCECOES_LLM as exc:
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

        # roteamento por Command (09 §4.1): tem tool_calls -> loop ReAct; senao -> extrair.
        # No M0 (TOOLS=[]) o LLM nunca pede tool_call -> sempre extrair; o ramo "tools" fica
        # dormente p/ o M1. getattr porque tool_calls so existe em AIMessage, nao em BaseMessage.
        if getattr(resp, "tool_calls", None):
            if parada in PARADA_TRUNCADA:
                # STOP-03/06: tool_use truncado (teto do turno / janela de contexto) -> args podem
                # estar incompletos. NAO despacha a tool; vai p/ post_process e o coordenador escala
                # (modelo_truncado) lendo o sinal parada+tool_calls, sem bolha crua ao cliente.
                logger.warning(
                    "llm tool_use truncado por %s (turno_id=%s) -> nao despacha tool",
                    parada,
                    runtime.context.turno_id,
                )
                return Command(goto="post_process", update={"messages": [resp]})
            return Command(goto="tools", update={"messages": [resp]})

        # Resposta final ao cliente (sem tool_calls): o no `extrair` le o estado da negociacao
        # pos-fala (forca 1 registrar_extracao sobre a janela SEM esta fala, executa inline, decide
        # a reoferta). A extracao roda SEMPRE -- deixou de ser fallback condicional (02 §4).
        return Command(goto="extrair", update={"messages": [resp]})

    return llm
