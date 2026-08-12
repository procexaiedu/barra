"""No llm.

No real -- chama o chat principal (#1) bindado com as tools e roteia por Command(goto=...). O chat
    e DeepSeek V4 Flash direto via ChatOpenAI (criar_chat_deepseek); o no le motivo de parada/nome
    do modelo de forma unificada (motivo_parada/nome_modelo, core.llm) -- codigo provider-agnostico,
    nao campos crus do provider. Sem modelo de
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

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command
from openai import APIStatusError, APITimeoutError, RateLimitError

from barra.core.llm import (
    PARADA_RECUSA,
    PARADA_TRUNCADA,
    motivo_parada,
    nome_modelo,
    nomear_run,
)
from barra.core.metrics import TURNO_TRUNCADO

from .._instrumentar import instrumentar_tokens
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from .extrair import DisparoExtracao, cancelar

logger = logging.getLogger(__name__)

# Indisponibilidade do provider (retry do SDK exausto / 5xx / timeout) -> escala. O chat e DeepSeek
# via openai SDK (unico provider); `request_id` vem no header da resposta.
_EXCECOES_LLM = (
    RateLimitError,
    APITimeoutError,
    APIStatusError,
)

# Recusa do provider (safety filter) -> escala sem mandar a bolha crua. Alias local do vocabulario
# canonico de core.llm (fonte unica; antes era um frozenset duplicado aqui -> risco de drift).
_PARADA_RECUSA = PARADA_RECUSA

# Truncamento da resposta (args de tool podem vir incompletos -> nao despachar; STOP-03/06): o
# conjunto canonico vive em core.llm.PARADA_TRUNCADA (provider-aware: `length` do OpenAI/DeepSeek
# + o vocabulario legado max_tokens/model_context_window_exceeded). Lido via motivo_parada
# (finish_reason | stop_reason), nao do campo cru. Todos chegam em 200 OK.

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


def no_llm(
    chat: BaseChatModel, tools: Sequence[BaseTool], disparo: DisparoExtracao | None = None
) -> _NoLLM:
    """Factory: liga o chat principal (#1) + catalogo de tools ao no llm.

    O chat e injetado por build_graph (09 §4.5) para nao reconstruir o cliente a cada invocacao.
    Chat = DeepSeek V4 Flash direto (ChatOpenAI): binda as BaseTool cruas no schema
    function-calling OpenAI (o cache de prefixo e automatico no provider, sem `cache_control`).
    Lista vazia (P0 pre-M1) -> passa direto.

    O no NAO forca extracao: quando o LLM encerra sem tool_call, roteia para o no `extrair`
    (nos/extrair.py), que le o estado da negociacao pos-fala. `registrar_extracao` nao esta em
    `tools` -- o chat #1 nunca a chama.

    `disparo` (settings.extracao_paralela_habilitada, injetado por build_graph): a MESMA instancia
    que o no `extrair` recebe. Este no dispara a chamada forcada em paralelo com o chat e publica a
    Task no State; o `extrair` decide se ela serve. None -> nada de paralelismo (turno em serie).
    """
    # DeepSeek-direct: binda as BaseTool cruas no schema function-calling OpenAI; o cache de prefixo
    # e automatico no provider. Lista vazia (P0 pre-M1) -> bind_tools([]) e no-op.
    # `run_name` nomeia a GENERATION no trace do Langfuse: sem ele TODA chamada de LLM do turno
    # (fala, extracao forcada, regen do guard) vira uma observation "ChatOpenAI" e so da p/ saber
    # quem e pelo pai. Com nome, `fetch_observations(name="chat_fala")` isola a fala direto.
    chat_bound = nomear_run(chat.bind_tools(tools), "chat_fala")
    # Fecha-em-texto do cap de midia (trace 8194e2c0): bind com tool_choice="none" -> o modelo NAO
    # pode pedir tool nesta chamada, responde em TEXTO. Cache-safe (tool_choice e param de request do
    # bind, nao muda o prefixo cacheado tools+system). Lista vazia (M0/testes) -> usa o chat cru
    # (sem tools ja garante texto).
    chat_sem_tool_call = nomear_run(
        chat.bind_tools(tools, tool_choice="none") if tools else chat, "chat_fecha_em_texto"
    )
    # nome do modelo p/ o label das metricas de token, nao o modelo_id da agencia (03 §4.2).
    # `nome_modelo` le .model_name do ChatOpenAI (com fallback .model p/ fakes de teste).
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
            # Fecha DIRETO no post_process: ninguem vai consumir a extracao. A Task aqui so pode ter
            # vindo de uma passagem ANTERIOR do ReAct (este ramo exige >=2 enviar_midia falhadas).
            cancelar(state.get("_extracao_task"))
            resp = await chat_sem_tool_call.ainvoke(state["messages"])
            instrumentar_tokens(resp, modelo_chat)
            return Command(
                goto="post_process",
                update={"messages": [resp], "_midia_esgotada": True},
            )

        # DISPARO ESPECULATIVO da extracao (settings.extracao_paralela_habilitada): a janela da
        # extracao e a conversa CRUA + ancora + <ja_registrado> e exclui a fala do turno, entao neste
        # ponto — a fala deste invoke ainda nao existe — ela ja esta pronta. Aqui e o ponto mais cedo
        # SEGURO: depois da pausa do prepare_context (Command(goto=END)), do bloqueio do
        # intercept_disclosure e do cap de midia acima — os gates que encerram o turno SEM extracao.
        # Uma vez por turno (`_extracao_task` ausente no State): na 2a passagem da auto-reoferta a
        # janela mudou de qualquer jeito, e o `extrair` ja cai em serie ao ver a impressao divergir.
        # No ReAct o disparo se repete de proposito: o ramo `tools` cancela e NAO publica a Task,
        # entao a passagem seguinte redispara — e ai com as ToolMessages ja no State, que e a janela
        # certa. Efeitos colaterais aceitos (validar ao vivo antes de ligar em prod): a Task herda os
        # contextvars daqui, entao a generation da extracao pendura sob o span DESTE no e nao sob o
        # `extrair`; e o pico de requisicoes em voo contra a DeepSeek dobra por turno.
        disparado = (
            disparo.disparar(state["messages"], state)
            if disparo is not None and state.get("_extracao_task") is None
            else None
        )
        # `pendente` cobre tambem a Task de uma passagem ANTERIOR do ReAct: quem cancela nos ramos
        # que nao chegam ao `extrair` tem de alcancar as duas, senao a chamada fica orfa.
        pendente = disparado[0] if disparado is not None else state.get("_extracao_task")
        publicar_disparo: dict[str, Any] = (
            {"_extracao_task": disparado[0], "_extracao_janela": disparado[1]}
            if disparado is not None
            else {}
        )

        # Rede de seguranca do disparo: SO o ramo que publica a Task no Command (o goto="extrair")
        # a deixa viva. Todo o resto passa pelo `finally` e corta a chamada -- inclusive o caso que
        # nenhum `cancelar` pontual pegava: o CANCELAMENTO do grafo durante o `ainvoke` do chat
        # (teto de 60s do coordenador, shutdown do worker). A Task e DESTACADA (`create_task`),
        # entao o cancelamento do no NAO a alcanca sozinho: ela sobreviveria ao turno morto,
        # pagando o request e reabrindo o "Task exception was never retrieved".
        entregue = False
        try:
            try:
                resp = await chat_bound.ainvoke(state["messages"])
                instrumentar_tokens(resp, modelo_chat)
                # motivo de parada chega num 200 OK, nao como excecao. Lido provider-agnostico
                # (finish_reason OpenAI/DeepSeek | stop_reason legado) via motivo_parada:
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
                        (resp.response_metadata or {}).get(
                            "id"
                        ),  # REL-OBS-02: id da msg do provider
                    )
                elif parada in PARADA_TRUNCADA:
                    # premissa: max_tokens=1024 nao trunca (03 §6.1). Quando trunca COM tool_use, o
                    # roteamento abaixo NAO despacha a tool e o coordenador escala (modelo_truncado);
                    # sem tool_use so observa -- o spike na metrica decide revisar o teto.
                    TURNO_TRUNCADO.inc()
                    logger.warning("llm parada=%s (turno_id=%s)", parada, runtime.context.turno_id)
            except _EXCECOES_LLM as exc:
                # exaustao de retry do SDK / 5xx / timeout -> escala (sem fallback de modelo, 01 §2.6).
                # REL-OBS-02: loga o request_id do provider (header `x-request-id`, chave do ticket de
                # suporte) -- presente em APIStatusError/RateLimitError; timeout sem resposta -> None.
                logger.warning(
                    "llm indisponivel: %s (turno_id=%s llm_request_id=%s)",
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
                # Loop ReAct: as ToolMessages deste turno VAO entrar na janela da extracao (`do_turno`,
                # em `_janela_para_extracao`), entao a Task disparada la atras leu uma janela
                # incompleta e ja nasceu invalida. Sai sem publicar -> o `finally` a corta aqui, e nao
                # la no `extrair`, p/ nao pagar a chamada em paralelo com a 2a volta do chat. Como o
                # State fica sem Task, a passagem seguinte do no REDISPARA — ai ja com as ToolMessages
                # dentro, que e a janela certa.
                return Command(goto="tools", update={"messages": [resp]})

            # Resposta final ao cliente (sem tool_calls): o no `extrair` le o estado da negociacao
            # pos-fala (forca 1 registrar_extracao sobre a janela SEM esta fala, executa inline, decide
            # a reoferta). A extracao roda SEMPRE -- deixou de ser fallback condicional (02 §4).
            # UNICO ramo que publica o disparo: e o unico que chega ao `extrair`, quem consome a Task.
            entregue = bool(publicar_disparo)
            return Command(goto="extrair", update={"messages": [resp], **publicar_disparo})
        finally:
            if not entregue:
                cancelar(pendente)

    return llm
