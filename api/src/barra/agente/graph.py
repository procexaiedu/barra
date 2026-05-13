"""build_graph() compoe os nos em StateGraph + AsyncPostgresSaver.

Skeleton M0: grafo compila com 5 nos placeholder, fluxo linear
prepare_context -> gate_pausa -> llm -> tools -> post_process -> END.

Padrao alvo (entra em M2+):
    pool = AsyncConnectionPool(DATABASE_URL, kwargs={"autocommit": True, "row_factory": dict_row})
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    graph = build_graph(checkpointer=checkpointer, settings=settings)

Handoff: nao usa interrupt(); ia_pausada=true em dominio/atendimentos e early exit no
gate_pausa. Devolucao via Devolucao para IA (comando explicito, ver CONTEXT.md).
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from .estado import EstadoAgente
from .nos import gate_pausa, llm, post_process, prepare_context, tools_node


def build_graph(checkpointer: Any | None = None) -> Any:
    """Constroi o StateGraph do agente.

    Args:
        checkpointer: AsyncPostgresSaver ja inicializado (via lifespan do FastAPI).
            Skeleton M0 aceita None para testes locais sem Postgres.

    Returns:
        Grafo compilado, pronto para `await graph.ainvoke(state, config)`.
    """
    builder = StateGraph(EstadoAgente)

    builder.add_node("prepare_context", prepare_context)
    builder.add_node("gate_pausa", gate_pausa)
    builder.add_node("llm", llm)
    builder.add_node("tools", tools_node)
    builder.add_node("post_process", post_process)

    # Skeleton M0: fluxo linear. Em M1+ adicionar arestas condicionais
    # (tools <-> llm loop ate o LLM nao pedir mais tool_call).
    builder.add_edge(START, "prepare_context")
    builder.add_edge("prepare_context", "gate_pausa")
    builder.add_edge("gate_pausa", "llm")
    builder.add_edge("llm", "tools")
    builder.add_edge("tools", "post_process")
    builder.add_edge("post_process", END)

    return builder.compile(checkpointer=checkpointer)
