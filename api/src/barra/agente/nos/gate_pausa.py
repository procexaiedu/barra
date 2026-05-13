"""No gate_pausa.

M0: no-op skeleton.
M3: le `ia_pausada` do atendimento (via dominio/atendimentos/service) e, se True,
    interrompe o turno antes do LLM. Evita custo de inferencia em conversas em handoff.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from ..estado import EstadoAgente


async def gate_pausa(state: EstadoAgente, config: RunnableConfig) -> dict[str, Any]:
    """Skeleton M0: nunca pausa."""
    return {}
