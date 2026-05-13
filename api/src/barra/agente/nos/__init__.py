"""Nos do grafo LangGraph do agente Barra Vips.

Cada no e uma funcao async que recebe (state, config) e retorna dict parcial do state.
Skeleton M0: nos retornam {} (no-op). Implementacao real entra em M1+.
"""

from .gate_pausa import gate_pausa
from .llm import llm
from .post_process import post_process
from .prepare_context import prepare_context
from .tools import tools_node

__all__ = [
    "prepare_context",
    "gate_pausa",
    "llm",
    "tools_node",
    "post_process",
]
