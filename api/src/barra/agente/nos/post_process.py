"""No post_process.

M0: refetch de ia_pausada (cinto-suspensorio, 04 §3.5); se a IA foi pausada por um pipeline
    sem lock (Pix/foto portaria) no meio do turno, descarta o texto das AIMessages do turno
    (conteudo "") -- o coordenador detecta a resposta vazia e nao despacha humanizacao.
M3+: extrai tambem a lista de midias dos tool_calls. Humanizacao real (chunking, presence,
    jitter, dedupe) entra em M4 como worker ARQ separado.
"""

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from barra.core.db import conexao

from .._texto_turno import mensagens_do_turno
from ..contexto import ContextAgente
from ..estado import EstadoAgente


async def post_process(state: EstadoAgente, runtime: Runtime[ContextAgente]) -> dict[str, Any]:
    """Refetch ia_pausada; se pausou durante o turno, zera o texto da resposta."""
    # Webhook fino (atendimento_id None): nada a pausar — espelha o gate do prepare_context.
    if runtime.context.atendimento_id is None:
        return {}
    async with conexao(runtime.context.db_pool) as conn:
        result = await conn.execute(
            "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
            (runtime.context.atendimento_id,),
        )
        row = await result.fetchone()

    if not (row and row["ia_pausada"]):
        return {}

    # Zera TODAS as AIMessages geradas no turno (mesmo id -> o reducer add_messages substitui por
    # vazia), nao so a ultima: na reentrada pos-tools o `[-1]` e uma ToolMessage, e quando ja houve
    # texto na 1a passagem (extracao/resposta inline) zerar so o ultimo deixaria essa fala viva p/ o
    # coordenador despachar APOS a pausa. Mesmo criterio (`mensagens_do_turno`) do output_guard.
    vazias = [AIMessage(id=m.id, content="") for m in mensagens_do_turno(state["messages"])]
    return {"messages": vazias}
