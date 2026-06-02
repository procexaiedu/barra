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

from barra.core.llm import criar_chat_anthropic
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
    chat = criar_chat_anthropic(settings)

    # context_schema: deps de runtime + ids de escopo via Runtime Context API (04 §1.1).
    # Nao usar config["configurable"] p/ pool/redis (legado; quebra ao ligar checkpointer).
    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)

    builder.add_node("prepare_context", prepare_context)
    builder.add_node("intercept_disclosure", intercept_disclosure)
    builder.add_node("llm", no_llm(chat, TOOLS))
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
