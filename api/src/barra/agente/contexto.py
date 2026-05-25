"""ContextAgente: deps de runtime + IDs de escopo do turno (Runtime Context API).

Forma idiomatica no LangGraph 1.x (`context_schema=ContextAgente` no StateGraph +
`graph.ainvoke(state, context=ContextAgente(...))`) de passar dependencias
nao-serializaveis (pool/redis) e ids de escopo aos nos e tools -- NUNCA via
`config["configurable"]` (legado), que o checkpointer serializa e quebra com pool/redis
(TypeError; langgraph#3441). O `thread_id` (= conversa_id) segue em configurable, nativo
do checkpointer. Ver docs/agente/04-tools.md §1.1 e 01-arquitetura.md §2.3/§4.3.

Nos leem `runtime: Runtime[ContextAgente]` (runtime.context); tools leem
`runtime: ToolRuntime[ContextAgente]` (injetado pelo ToolNode, fora do schema do LLM).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arq import ArqRedis
from psycopg_pool import AsyncConnectionPool


@dataclass
class ContextAgente:
    """Run dependencies + IDs de escopo. Estaticos DENTRO de um turno (uma ainvoke).

    Injetados em `graph.ainvoke(state, context=ContextAgente(...))` pelo coordenador.
    """

    db_pool: AsyncConnectionPool[Any]
    redis: ArqRedis
    modelo_id: str
    atendimento_id: str
    cliente_id: str
    turno_id: str
