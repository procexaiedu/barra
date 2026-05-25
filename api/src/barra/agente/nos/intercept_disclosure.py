"""No intercept_disclosure.

M0: passthrough -- roteia para o llm via Command (sem flag de state, 09 §4.1).
M3: le `_categoria`/`_confianca` (gravados pelo prepare_context, 02 §1) e roteia:
    - disclosure de alta confianca -> resposta canned (pool de variacoes) + post_process;
    - 3a insistencia -> escala (handoff Fernando) + END;
    - ambiguo/normal -> llm.
    Ver 10 §2-3 e 10 §8. Substitui o antigo gate_pausa; o gate de pausa dobra no
    prepare_context (Command(goto=END)).
"""

from typing import Literal

from langgraph.runtime import Runtime
from langgraph.types import Command

from ..contexto import ContextAgente
from ..estado import EstadoAgente


async def intercept_disclosure(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["llm"]]:
    """Skeleton M0: nunca intercepta; segue para o llm via Command."""
    return Command(goto="llm")
