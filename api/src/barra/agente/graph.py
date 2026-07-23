"""build_graph() compoe os nos em StateGraph (sem checkpointer no P0).

Grafo de 7 nos; o no llm e real (chama DeepSeek V4 Flash) e o roteamento e por Command(goto=...) --
nao por arestas condicionais nem flags de state (09 §4.1). Wiring:
    START -(estatica)-> prepare_context -(Command)-> intercept_disclosure | END
          intercept_disclosure -(Command)-> llm -(Command)-> tools | post_process | extrair
          tools -(estatica)-> llm   (loop ReAct)
          extrair -(Command)-> post_process | llm   (extracao pos-fala; volta ao llm na reoferta)
          post_process -(estatica)-> output_guard -(Command)-> END   (ADR 0016, antes da bolha)
O loop ReAct esta ATIVO a partir do M1: o llm roteia p/ "tools" (Command) quando ha tool_calls,
o ToolNode executa as tools de TOOLS e devolve ao llm pela aresta "tools" -> "llm"; o teto e o
`recursion_limit` (config de invocacao, nao constante aqui -- 03 §8, 09 §4.7). Quando o llm encerra
SEM tool_call (resposta final), roteia p/ "extrair" (02 §4): a extracao roda SEMPRE, pos-fala, num
no proprio -- `registrar_extracao` saiu de TOOLS (o chat #1 nunca a chama; ver nos/extrair.py).

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

from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings, get_settings

from .contexto import ContextAgente
from .estado import EstadoAgente
from .ferramentas import TOOLS
from .ferramentas.extracao import registrar_extracao
from .nos import (
    intercept_disclosure,
    no_extrair,
    no_llm,
    output_guard,
    post_process,
    prepare_context,
    tools_node,
)


def _criar_chat_principal(settings: Settings) -> Any:
    """Chat principal (#1): ChatOpenAI DIRETO na API DeepSeek (api.deepseek.com).

    DeepSeek-only (sem alternativa de provider): cache automático garantido + modelo/quant cravados.
    thinking travado em disabled (extra_body), só passa `temperature` (1.3). Devolve um BaseChatModel;
    o nó llm só usa bind_tools/ainvoke/nome_modelo.
    """
    return criar_chat_deepseek(settings, temperature=settings.chat_temperature)


def _criar_chat_extracao_barata(settings: Settings) -> Any:
    """Chat da extracao forcada barata (#2): ChatOpenAI DIRETO na API DeepSeek (deepseek_model_chat).

    DeepSeek-only. thinking travado em disabled (extra_body) — nao corrompe o structured output da
    extracao (tool_choice); o cache automatico do DeepSeek barateia o prefixo curto (system minimo +
    janela). Devolve um BaseChatModel; o no llm so usa bind_tools/ainvoke/.model.
    """
    return criar_chat_deepseek(settings)


def build_graph(settings: Settings | None = None, checkpointer: Any | None = None) -> Any:
    """Constroi o StateGraph do agente.

    Args:
        settings: configuracao da app. None -> get_settings() (09 §4.5). Usada para construir
            o chat DeepSeek (criar_chat_deepseek) injetado no no llm via factory no_llm.
        checkpointer: AsyncPostgresSaver. None no P0 (01 §6.7); reservado p/ P1.

    Returns:
        Grafo compilado, pronto para `await graph.ainvoke(state, context=ContextAgente(...))`.
    """
    if settings is None:
        settings = get_settings()
    chat = _criar_chat_principal(settings)
    # Extracao forcada barata (settings.extracao_no_modelo_barato): chat injetado no no llm. None
    # quando desligado -> o no forca com o prefixo inteiro. Sempre DeepSeek V4 Flash direto
    # (criar_chat_deepseek), igual ao chat #1; o barateamento vem da JANELA minima, nao de outro modelo.
    chat_extracao_barata = (
        _criar_chat_extracao_barata(settings) if settings.extracao_no_modelo_barato else None
    )

    # context_schema: deps de runtime + ids de escopo via Runtime Context API (04 §1.1).
    # Nao usar config["configurable"] p/ pool/redis (legado; quebra ao ligar checkpointer).
    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)

    builder.add_node("prepare_context", prepare_context)
    builder.add_node("intercept_disclosure", intercept_disclosure)
    builder.add_node("llm", no_llm(chat, TOOLS))
    builder.add_node("tools", tools_node)
    # No `extrair`: le o estado da negociacao pos-fala (02 §4). Forca 1 registrar_extracao, executa
    # a tool INLINE (schema bindado so aqui -- registrar_extracao NAO esta em TOOLS) e decide a rota
    # (post_process no sucesso/escalada canned; volta ao llm na reoferta de erro recuperavel). O bind
    # barato (chat_extracao_barata) corta o BP_GERAL da chamada de extracao quando ligado.
    builder.add_node("extrair", no_extrair(chat, chat_extracao_barata, registrar_extracao))
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
