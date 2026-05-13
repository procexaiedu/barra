"""No post_process.

M0: no-op skeleton.
M3+: extrai AIMessage final + lista de midias de tool_calls; verifica se ia_pausada=true
    apareceu durante o turno (escalada via tool) -- nesse caso descarta texto e nao
    despacha chunks. Humanizacao real (chunking, presence, jitter, dedupe) entra em M4
    como worker ARQ separado.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig

from ..estado import EstadoAgente


async def post_process(state: EstadoAgente, config: RunnableConfig) -> dict[str, Any]:
    """Skeleton M0: passa adiante sem mudar nada."""
    return {}
