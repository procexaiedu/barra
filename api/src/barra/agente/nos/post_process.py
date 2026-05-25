"""No post_process.

M0: refetch de ia_pausada (cinto-suspensorio, 04 §3.5); se a IA foi pausada por um pipeline
    sem lock (Pix/foto portaria) no meio do turno, descarta o texto da ultima AIMessage
    (conteudo "") -- o coordenador detecta a resposta vazia e nao despacha humanizacao.
M3+: extrai tambem a lista de midias dos tool_calls. Humanizacao real (chunking, presence,
    jitter, dedupe) entra em M4 como worker ARQ separado.
"""

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from barra.core.db import conexao

from ..contexto import ContextAgente
from ..estado import EstadoAgente


async def post_process(state: EstadoAgente, runtime: Runtime[ContextAgente]) -> dict[str, Any]:
    """Refetch ia_pausada; se pausou durante o turno, zera o texto da resposta."""
    async with conexao(runtime.context.db_pool) as conn:
        result = await conn.execute(
            "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
            (runtime.context.atendimento_id,),
        )
        row = await result.fetchone()

    if not (row and row["ia_pausada"]):
        return {}

    ultima = state["messages"][-1]
    # mesmo id -> o reducer add_messages substitui (nao anexa) a AIMessage por uma vazia.
    return {"messages": [AIMessage(id=ultima.id, content="")]}
