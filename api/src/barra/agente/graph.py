"""build_graph() compoe os nos em StateGraph (sem checkpointer no P0).

Grafo de 6 nos; o no llm e real (chama Sonnet 4.6) e o roteamento e por Command(goto=...) --
nao por arestas condicionais nem flags de state (09 §4.1). Wiring:
    START -(estatica)-> prepare_context -(Command)-> intercept_disclosure | END
          intercept_disclosure -(Command)-> llm -(Command)-> tools | post_process
          tools -(estatica)-> llm   (loop ReAct)
          post_process -(estatica)-> output_guard -(Command)-> END   (ADR 0016, antes da bolha)
O loop ReAct esta ATIVO a partir do M1: o llm roteia p/ "tools" (Command) quando ha tool_calls,
o ToolNode executa as tools de TOOLS e devolve ao llm pela aresta "tools" -> "llm"; o teto e o
`recursion_limit` (config de invocacao, nao constante aqui -- 03 §8, 09 §4.7).

Decisao 01 §6.7 (grilling 2026-05-22): SEM checkpointer no P0. O grafo compila com
`builder.compile()` (checkpointer=None); o prompt e montado do zero a cada turno a partir
de `mensagens` (sliding window), nao de checkpoint. O parametro `checkpointer` segue
opcional so para reintroducao futura (P1, se vier interrupt/time-travel) -- nao usar no P0.

Handoff: nao usa interrupt(); ia_pausada=true em dominio/atendimentos e early exit no
prepare_context (Command(goto=END), 02 §1). Devolucao via Devolucao para IA (comando
explicito, ver CONTEXT.md).
"""

from typing import Any

from langgraph.graph import START, StateGraph

from barra.core.llm import criar_chat_anthropic, criar_chat_deepseek, criar_chat_openrouter
from barra.settings import Settings, get_settings

from .contexto import ContextAgente
from .estado import EstadoAgente
from .ferramentas import TOOLS
from .nos import (
    intercept_disclosure,
    no_llm,
    output_guard,
    post_process,
    prepare_context,
    tools_node,
)


def _criar_chat_principal(settings: Settings) -> Any:
    """Chat principal (#1) pelo provider em settings.llm_chat_provider.

    `deepseek` -> ChatOpenAI DIRETO na API DeepSeek (cache automático garantido + modelo/quant
    cravados; preferido em escala). `deepseek-chat` já é non-thinking, só passa `temperature`.
    `openrouter` -> ChatOpenAI no pool OpenRouter (id em openrouter_model_chat), SEM
    `require_parameters` (o deepseek-v4-flash dá 404 com ele, mesmo honrando tool_choice), com
    `reasoning_off` (voz vem da persona), `temperature` e piso de `quantizations`.
    `anthropic` (default) -> Sonnet via criar_chat_anthropic. Devolve um BaseChatModel; o nó llm só
    usa bind_tools/ainvoke/nome_modelo, espelhados pelos wrappers.
    """
    if settings.llm_chat_provider == "deepseek":
        return criar_chat_deepseek(settings, temperature=settings.chat_temperature)
    if settings.llm_chat_provider == "openrouter":
        assert settings.openrouter_model_chat is not None  # garantido pelo model_validator
        return criar_chat_openrouter(
            settings,
            modelo=settings.openrouter_model_chat,
            require_parameters=False,
            reasoning_off=True,
            temperature=settings.chat_temperature,
            quantizations=settings.openrouter_quantizations,
        )
    return criar_chat_anthropic(settings)


def _criar_chat_extracao_barata(settings: Settings) -> Any:
    """Chat da extracao forcada barata (#2) pelo provider em settings.extracao_provider.

    `deepseek` -> ChatOpenAI DIRETO na API DeepSeek (deepseek_model_chat). `deepseek-chat` ja e
    non-thinking — nao corrompe o structured output da extracao (tool_choice) e dispensa
    reasoning_off; o cache automatico do DeepSeek barateia o prefixo curto (system minimo + janela).
    `openrouter` -> ChatOpenAI (id em openrouter_model_extracao; settings valida que esta setado).
    `anthropic` -> Haiku via ChatAnthropic com com_effort=False. Devolve um BaseChatModel; o no
    llm so usa bind_tools/ainvoke/.model_name|.model, espelhados pelos dois wrappers.
    """
    if settings.extracao_provider == "deepseek":
        return criar_chat_deepseek(settings)
    if settings.extracao_provider == "openrouter":
        assert settings.openrouter_model_extracao is not None  # garantido pelo model_validator
        # reasoning_off: a extracao forcada e structured output (tool_choice) — o thinking mode do
        # DeepSeek V4 corrompe structured output (vllm#41132) alem de custar 2-5x latencia. quant:
        # mesmo piso de qualidade do chat. require_parameters fica True (default): garante provedor
        # que honra tool_choice.
        return criar_chat_openrouter(
            settings,
            modelo=settings.openrouter_model_extracao,
            reasoning_off=True,
            quantizations=settings.openrouter_quantizations,
        )
    return criar_chat_anthropic(settings, modelo=settings.extracao_modelo, com_effort=False)


def build_graph(settings: Settings | None = None, checkpointer: Any | None = None) -> Any:
    """Constroi o StateGraph do agente.

    Args:
        settings: configuracao da app. None -> get_settings() (09 §4.5). Usada para construir
            o ChatAnthropic (criar_chat_anthropic) injetado no no llm via factory no_llm.
        checkpointer: AsyncPostgresSaver. None no P0 (01 §6.7); reservado p/ P1.

    Returns:
        Grafo compilado, pronto para `await graph.ainvoke(state, context=ContextAgente(...))`.
    """
    if settings is None:
        settings = get_settings()
    chat = _criar_chat_principal(settings)
    # Extracao forcada barata (settings.extracao_no_modelo_barato): chat injetado no no llm. None
    # quando desligado -> o no forca no Sonnet com prefixo inteiro (comportamento atual). O provider
    # e por-chamada (settings.extracao_provider): `openrouter` usa ChatOpenAI (id em
    # openrouter_model_extracao); `anthropic` (default) usa Haiku via ChatAnthropic com com_effort
    # =False (Haiku nao aceita `effort`, igual ao judge do output_guard).
    chat_extracao_barata = (
        _criar_chat_extracao_barata(settings) if settings.extracao_no_modelo_barato else None
    )

    # context_schema: deps de runtime + ids de escopo via Runtime Context API (04 §1.1).
    # Nao usar config["configurable"] p/ pool/redis (legado; quebra ao ligar checkpointer).
    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)

    builder.add_node("prepare_context", prepare_context)
    builder.add_node("intercept_disclosure", intercept_disclosure)
    builder.add_node("llm", no_llm(chat, TOOLS, chat_extracao_barata=chat_extracao_barata))
    builder.add_node("tools", tools_node)
    builder.add_node("post_process", post_process)
    builder.add_node("output_guard", output_guard)

    builder.add_edge(START, "prepare_context")
    # prepare_context, intercept_disclosure e llm roteiam SO por Command(goto=...) -- sem aresta
    # estatica de saida. Uma aresta estatica em prepare_context faria fan-out com o Command(goto=END)
    # da pausa (o turno chamaria o llm mesmo pausado), por isso o caminho normal tambem e Command
    # (goto="intercept_disclosure"). Ver nos/prepare_context.py (M0-T4).
    builder.add_edge("tools", "llm")  # loop ReAct: ToolNode executou as tool_calls -> volta ao llm
    # Output-guard antes da bolha (ADR 0016): post_process (que so refaz o gate de pausa, retorna
    # dict) tem aresta estatica UNICA -> output_guard. O output_guard roteia SO por Command(goto=END)
    # -- sem aresta estatica de saida (mesma armadilha do fan-out: bloquear+seguir nao podem coexistir).
    builder.add_edge("post_process", "output_guard")

    return builder.compile(checkpointer=checkpointer)
