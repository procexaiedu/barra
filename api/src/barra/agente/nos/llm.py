"""No llm.

No real -- chama o chat principal (#1) bindado com as tools e roteia por Command(goto=...). O
    modelo e provider-agnostico (settings.llm_chat_provider): Sonnet 4.6 via ChatAnthropic (default)
    ou DeepSeek via ChatOpenAI/OpenRouter -- o no le motivo de parada/nome do modelo de forma
    unificada (motivo_parada/nome_modelo, core.llm), nao campos Anthropic crus. Sem modelo de
    fallback: 429/5xx/timeout sobem como excecao (retry ja foi do SDK, max_retries) e, na exaustao,
    escalam para Fernando via escalar_por_exaustao (TODO M3f; 01 §2.6). O check de parada
    (refusal/max_tokens chegam em 200 OK, nao como excecao) vive dentro do try/except. Sem effort
    hibridizado por turno (removido, 03 §6.2.1); a classificacao de disclosure roda no
    prepare_context sobre a janela (03 §7), nao no webhook.
"""

import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol

from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command
from openai import APIStatusError as OpenAIAPIStatusError
from openai import APITimeoutError as OpenAIAPITimeoutError
from openai import RateLimitError as OpenAIRateLimitError

from barra.core.llm import PARADA_TRUNCADA, motivo_parada, nome_modelo
from barra.core.metrics import AGENTE_CUSTO_TURNO_BRL, AGENTE_TURNO_TOKENS, TURNO_TRUNCADO
from barra.settings import get_settings

from .._custo import calcular_custo_brl
from .._texto_turno import texto_da_mensagem
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..ferramentas import INPUT_EXAMPLES, STRICT_TOOLS
from ..llm import build_tools_para_bind

logger = logging.getLogger(__name__)

# Indisponibilidade do provider (retry do SDK exausto / 5xx / timeout) -> escala. Os dois SDKs
# levantam tipos homonimos em modulos distintos (anthropic vs openai): cobrir ambos para o chat #1
# rodar em qualquer provider (settings.llm_chat_provider). `request_id` existe nos dois.
_EXCECOES_LLM = (
    RateLimitError,
    APITimeoutError,
    APIStatusError,
    OpenAIRateLimitError,
    OpenAIAPITimeoutError,
    OpenAIAPIStatusError,
)

# Recusa do provider (safety filter) -> escala sem mandar a bolha crua: `refusal` (Anthropic) /
# `content_filter` (OpenAI/OpenRouter). E o complemento de PARADA_TRUNCADA dentro de PARADA_INSEGURA.
_PARADA_RECUSA = frozenset({"refusal", "content_filter"})

# Truncamento da resposta (args de tool podem vir incompletos -> nao despachar; STOP-03/06): o
# conjunto canonico vive em core.llm.PARADA_TRUNCADA (provider-aware: max_tokens/
# model_context_window_exceeded da Anthropic + length do OpenAI/OpenRouter). Lido via motivo_parada
# (stop_reason Anthropic | finish_reason OpenAI), nao do campo cru. Todos chegam em 200 OK.

# Fallback deterministico de extracao (#2): nome da tool de escrita que persiste o snapshot do
# turno. Quando o LLM encerra sem chama-la, o no forca 1 chamada (tool_choice) antes de fechar.
_TOOL_EXTRACAO = "registrar_extracao"

# Reducao de custo (settings.extracao_no_modelo_barato): system prompt MINIMO da extracao forcada
# barata. Substitui o BP_GERAL (~14,7k tokens persona+regras+FAQ) — a extracao e nota interna
# estruturada, nao gera texto ao cliente, entao nao precisa da voz nem do FAQ. As regras de cada
# campo ja viajam na descricao da tool (Annotated+Field); a hora atual e o periodo de trabalho
# vem no contexto dinamico anexado a ULTIMA HumanMessage (preservada pelo strip).
_SYSTEM_EXTRACAO_BARATA = (
    "Voce le uma conversa entre uma acompanhante e um cliente e registra o ESTADO da negociacao "
    "chamando a ferramenta registrar_extracao. Voce NAO responde ao cliente e NAO inventa dados: "
    "registre apenas o que esta claro na conversa. As regras de cada campo estao na descricao da "
    "ferramenta. A hora atual e o periodo de trabalho vem no contexto da ultima mensagem."
)


def _janela_para_extracao_barata(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Janela do turno SEM os blocos system gerais, prefixada pelo system minimo de extracao.

    O ganho de custo vem exatamente de NAO enviar o BP_GERAL (persona+regras+FAQ) na chamada
    barata: troca ~14,7k tokens de prefixo por ~70. As mensagens da conversa (incluindo a ultima
    HumanMessage, que carrega o contexto dinamico/`<agenda agora=...>`) sao preservadas na ordem —
    a request continua comecando por user apos o system, valida na Anthropic.
    """
    conversa = [m for m in messages if not isinstance(m, SystemMessage)]
    return [SystemMessage(content=_SYSTEM_EXTRACAO_BARATA), *conversa]


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
    # Custo BRL: tabela do PROPRIO modelo (`calcular_custo_brl` despacha por `modelo` — Haiku p/ a
    # extracao barata, Sonnet p/ o resto) + cotacao USD/BRL (settings). Observado pelo Histogram
    # AGENTE_CUSTO_TURNO_BRL (03 §4.2; meta em settings.custo_alvo_brl). Mesmo label `modelo` p/ correlato.
    AGENTE_CUSTO_TURNO_BRL.labels(modelo).observe(
        calcular_custo_brl(um, get_settings().usd_brl_cotacao, model_name=modelo)
    )


class _NoLLM(Protocol):
    """Forma do no llm aceita pelo StateGraph (runtime keyword-only, como langgraph espera)."""

    def __call__(
        self, state: EstadoAgente, *, runtime: Runtime[ContextAgente]
    ) -> Coroutine[Any, Any, Command[Literal["tools", "post_process"]]]: ...


def no_llm(
    chat: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    chat_extracao_barata: BaseChatModel | None = None,
) -> _NoLLM:
    """Factory: liga o chat principal (#1) + catalogo de tools ao no llm.

    O chat e injetado por build_graph (09 §4.5) para nao reconstruir o cliente a cada invocacao.
    Provider-agnostico (settings.llm_chat_provider): ChatAnthropic (Sonnet) ou ChatOpenAI
    (DeepSeek/OpenRouter). No caminho Anthropic, bind_tools roda com `cache_control` na ULTIMA tool
    (TTL = cache_ttl_geral, tools GERAIS como BP1/BP2; doc oficial tool-use-with-prompt-caching). No
    OpenRouter o `cache_control` e Anthropic-only e quebraria o roteamento, alem de inutil (cache do
    DeepSeek e automatico): binda as BaseTool cruas (sem convert/strict/input_examples). Lista vazia
    (P0 pre-M1) -> passa direto. Mudanca em qualquer tool invalida tools+system+messages (hierarquia).

    `chat_extracao_barata` (settings.extracao_no_modelo_barato): quando injetado, a chamada
    FORCADA de registrar_extracao roda nesse chat barato (Haiku) ligado SO a tool de extracao e
    sobre a janela sem o BP_GERAL — corta ~14,7k tokens de prefixo da ~metade das geracoes que
    hoje sao so extracao. None (default) -> caminho inalterado (forca no chat principal c/ prefixo).
    """
    settings = get_settings()
    # cache_control e Anthropic-only (ephemeral): so no caminho Anthropic. No OpenRouter binda
    # BaseTool cru — o `convert_to_anthropic_tool`/strict/input_examples nao se aplicam e o
    # cache_control quebraria o roteamento do OpenRouter (eval teste_v4flash_cenario1).
    if settings.cache_control_anthropic:
        # strict PER-TOOL (STRICT_TOOLS = {"escalar"}); master-switch anthropic_strict_tools desliga
        # tudo sem deploy. input_examples sempre injetados (ajudam tool-calling, custo no cache de
        # tools pago 1x). Ambos byte-identicos p/ todas as modelos (invariante de prefixo).
        tools_para_bind: Sequence[Any] = build_tools_para_bind(
            tools,
            ttl=settings.cache_ttl_geral,
            strict_tools=STRICT_TOOLS if settings.anthropic_strict_tools else frozenset(),
            exemplos=INPUT_EXAMPLES,
        )
    else:
        tools_para_bind = tools
    chat_bound = chat.bind_tools(tools_para_bind)
    # Fallback deterministico de extracao (#2): 2o bind que FORCA registrar_extracao via
    # tool_choice (doc oficial `tool-use` / langchain-anthropic bind_tools). So existe quando a
    # tool esta no catalogo e o kill-switch esta ligado -- em M0/testes (TOOLS=[]) fica None e o
    # caminho de forcamento some, sem tocar o bind normal nem o cache do prefixo (tool_choice e
    # parametro de request do 2o bind, nao altera o prefixo cacheado tools+system do 1o).
    nomes_tools = {t.name for t in tools}
    forca_ligada = _TOOL_EXTRACAO in nomes_tools and settings.forcar_extracao_por_turno
    chat_forcado = (
        chat.bind_tools(tools_para_bind, tool_choice=_TOOL_EXTRACAO) if forca_ligada else None
    )
    # Bind barato da extracao forcada (settings.extracao_no_modelo_barato): liga o chat Haiku SO a
    # tool de extracao (nao o catalogo todo) com tool_choice. Sem cache_control nas tools — o
    # prefixo barato e curto (system minimo + janela), nao ha 14,7k a cachear. `tool_extracao` e
    # a propria BaseTool achada por nome (o convert/strict do build_tools_para_bind nao importa
    # aqui: e 1 tool so e nao compartilha o prefixo cacheado do Sonnet).
    tool_extracao = next((t for t in tools if t.name == _TOOL_EXTRACAO), None)
    chat_forcado_barato = (
        chat_extracao_barata.bind_tools([tool_extracao], tool_choice=_TOOL_EXTRACAO)
        if forca_ligada and chat_extracao_barata is not None and tool_extracao is not None
        else None
    )
    # nome do modelo p/ o label das metricas de token, nao o modelo_id da agencia (03 §4.2).
    # `nome_modelo` tolera os dois wrappers (.model do ChatAnthropic / .model_name do ChatOpenAI),
    # entao funciona p/ Sonnet e DeepSeek.
    modelo_chat = nome_modelo(chat)
    # Label de metrica da extracao barata: nome do modelo barato (Haiku), p/ NAO poluir o tripwire
    # de write-rate do Sonnet (mesmo cuidado do output_guard, 03 §4.2). `custo BRL` da extracao
    # barata agora sai pela tabela do PROPRIO modelo (Haiku) — `_custo.calcular_custo_brl` despacha
    # por `model_name`, casando com o `total_cost` por-modelo do Langfuse.
    modelo_extracao_barata = (
        nome_modelo(chat_extracao_barata) if chat_extracao_barata is not None else ""
    )

    async def llm(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["tools", "post_process"]]:
        # Reentrada pos-`tools` sem nada a reprocessar: NAO reinvocar o modelo -- fecharia uma 2a
        # bolha e custaria 1 request a toa. Fecha o turno direto no post_process (que ainda refaz o
        # gate de pausa). Dois caminhos setam esses guards na ida ao `tools`:
        #  - _extracao_forcada (#2): o LLM esqueceu registrar_extracao e o no forcou 1 chamada;
        #  - _resposta_inline_concluida: o LLM ja respondeu o cliente (texto) E so pediu
        #    registrar_extracao na MESMA msg (padrao DeepSeek). A tool de escrita nao devolve nada
        #    acionavel; reinvocar so faz o DeepSeek tagarelar uma 2a bolha (trace 022e0a70).
        # O primeiro guard tambem corta loop infinito de forcamento.
        if state.get("_extracao_forcada") or state.get("_resposta_inline_concluida"):
            return Command(goto="post_process")
        try:
            resp = await chat_bound.ainvoke(state["messages"])
            _instrumentar_tokens(resp, modelo_chat)
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

        # roteamento por Command (09 §4.1): tem tool_calls -> loop ReAct; senao -> post_process.
        # No M0 (TOOLS=[]) o LLM nunca pede tool_call -> sempre post_process; o ramo "tools" fica
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
            update: dict[str, Any] = {"messages": [resp]}
            # 1a passagem inline: o modelo ja respondeu o cliente (texto) E so pediu a tool de
            # escrita (registrar_extracao nao devolve nada acionavel). O DeepSeek reincide com texto
            # na reentrada do ReAct (2a bolha espuria, trace 022e0a70); o Sonnet volta vazio. Em
            # ambos nao ha o que reprocessar -> marca o turno p/ a reentrada (guard no topo) fechar
            # sem reinvocar -- corta a bolha e poupa 1 request. Tool de LEITURA no conjunto (ex.
            # consultar_agenda) -> `all` falha, segue o ReAct normal (o modelo precisa do resultado).
            if (
                isinstance(resp, AIMessage)
                and texto_da_mensagem(resp)
                and all(tc.get("name") == _TOOL_EXTRACAO for tc in resp.tool_calls)
            ):
                update["_resposta_inline_concluida"] = True
            return Command(goto="tools", update=update)

        # Resposta final ao cliente (sem tool_calls). Fallback deterministico (#2): se NENHUM
        # registrar_extracao rodou neste turno, a FSM defasaria (valor/tipo/horario nao persistem).
        # Forca 1 extracao via tool_choice e despacha pelo `tools`; a reentrada (guard acima) fecha
        # o turno sem reinvocar o modelo -> sem bolha dupla, +1 request so quando o LLM esqueceu.
        if chat_forcado is not None and not _extraiu_no_turno(state["messages"]):
            # Forca sobre `state["messages"]` (NAO inclui `resp`): a request precisa terminar numa
            # msg user/tool p/ o modelo responder -- anexar `resp` (assistant) daria 2 assistant
            # consecutivas (400). `resp` so vai no update local; nunca volta a Anthropic (a
            # reentrada nao reinvoca). A extracao olha o contexto do cliente, ja completo aqui.
            #
            # Caminho barato (settings.extracao_no_modelo_barato): roda no Haiku sobre a janela SEM
            # o BP_GERAL (system minimo de extracao) — corta ~14,7k tokens de prefixo. O resultado
            # (AIMessage com tool_call de registrar_extracao) e despachado pelo MESMO `tools`, entao
            # a execucao de dominio/idempotencia/FSM e identica ao caminho Sonnet. Instrumenta sob o
            # label do modelo barato p/ nao poluir o write-rate do Sonnet.
            if chat_forcado_barato is not None:
                forcado = await chat_forcado_barato.ainvoke(
                    _janela_para_extracao_barata(state["messages"])
                )
                _instrumentar_tokens(forcado, modelo_extracao_barata)
            else:
                forcado = await chat_forcado.ainvoke(state["messages"])
                _instrumentar_tokens(forcado, modelo_chat)
            # motivo_parada: provider-aware (stop_reason Anthropic / finish_reason OpenRouter) — a
            # extracao barata pode rodar no ChatOpenAI (settings.extracao_provider), cujo truncamento
            # vem como finish_reason="length".
            forcado_stop = motivo_parada(forcado.response_metadata)
            if forcado_stop in PARADA_TRUNCADA or not getattr(forcado, "tool_calls", None):
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
