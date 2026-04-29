"""build_graph() compõe os nodes em StateGraph + AsyncPostgresSaver.

Padrão:
    pool = AsyncConnectionPool(DATABASE_URL, kwargs={"autocommit": True, "row_factory": dict_row})
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    graph = StateGraph(Estado).add_node(...).compile(checkpointer=checkpointer)

Handoff: node chama interrupt(); resume via Command(resume=...).
"""
