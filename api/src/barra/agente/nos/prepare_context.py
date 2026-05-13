"""No prepare_context.

M0: no-op skeleton.
M2: hidrata persona/regras/FAQ/programas em 4 SystemMessages com cache_control 1h
    + 1 SystemMessage de contexto dinamico com cache_control 5m. Ver 03-prompts.md.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from ..estado import EstadoAgente


async def prepare_context(state: EstadoAgente, config: RunnableConfig) -> dict[str, Any]:
    """Skeleton M0: passa adiante sem mudar nada."""
    return {}
