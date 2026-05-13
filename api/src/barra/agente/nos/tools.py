"""No tools.

M0: no-op skeleton.
M1: ToolNode do langgraph executando tools de leitura (consultar_agenda, consultar_cliente,
    consultar_faq, consultar_pix_status, consultar_midia). Loop tools<->llm ate o LLM
    parar de pedir tool_call (max recursion 25).
M3: adiciona tools de escrita (registrar_extracao, pedir_pix_deslocamento, enviar_midia,
    escalar) com idempotencia via tabela barravips.tool_calls.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from ..estado import EstadoAgente


async def tools_node(state: EstadoAgente, config: RunnableConfig) -> dict[str, Any]:
    """Skeleton M0: nenhuma tool registrada, retorna no-op."""
    return {}
