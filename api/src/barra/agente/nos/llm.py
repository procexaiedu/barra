"""No llm.

M0: stub que adiciona uma AIMessage trivial para validar o pipe.
M2+: chama Anthropic Sonnet 4.6 via ChatAnthropic com cache_control nos SystemMessages,
    fallback Haiku 4.5, effort hibridizado por categoria classificada no webhook.
"""

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from ..estado import EstadoAgente


async def llm(state: EstadoAgente, config: RunnableConfig) -> dict[str, Any]:
    """Skeleton M0: anexa AIMessage placeholder.

    Em M2+ esta funcao chama Anthropic e respeita cache_control / fallback / effort.
    """
    return {"messages": [AIMessage(content="[skeleton] llm node nao implementado")]}
