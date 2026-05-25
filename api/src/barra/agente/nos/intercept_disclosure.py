"""No intercept_disclosure.

Le `_categoria`/`_confianca` (gravados pelo prepare_context, 10 §8) e roteia por Command
(09 §4.1 -- sem flag de state):
    - jailbreak_attempt -> escala DIRETO (handoff Fernando) + END, sem canned nem contagem;
    - disclosure_attempt alta confianca -> incrementa o contador e: <3 -> negacao canned
      (pool em personagem) + post_process; >=3 -> escala (disclosure_insistente) + END;
    - prova_humanidade_attempt / ambiguo / None -> llm (few-shot de regras.md.j2).

Ver 10 §2-3 e 10 §8. O gate de pausa dobra no prepare_context (Command(goto=END), 02 §1);
este no nao pode ter aresta estatica de saida -- roteia TODOS os caminhos por Command
(09 §4.1, armadilha verificada M0-T4).
"""

from typing import Literal
from uuid import UUID

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command

from barra.core.db import conexao
from barra.core.metrics import DISCLOSURE_DETECTADO, JAILBREAK_DETECTADO
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff

from .._canned import escolher_negacao
from ..contexto import ContextAgente
from ..estado import EstadoAgente

_ACAO_ASSUMIR = "Assumir a conversa com o cliente."
_RESUMO_DISCLOSURE = "Cliente insistiu (3a vez) perguntando se a Bia e IA."
_RESUMO_JAILBREAK = "Cliente tentou override de instrucao (jailbreak)."


async def intercept_disclosure(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["llm", "post_process", "__end__"]]:
    """Roteia disclosure/jailbreak: canned, escala ou segue para o llm (10 §2-3, §8)."""
    categoria = state.get("_categoria")
    confianca = state.get("_confianca")
    ctx = runtime.context

    # Jailbreak: override de instrucao, nao pergunta de identidade -> escala direto, sem
    # deflecao nem contagem (10 §2.1, §4.4).
    if categoria == "jailbreak_attempt":
        JAILBREAK_DETECTADO.inc()
        async with conexao(ctx.db_pool) as conn:
            await abrir_handoff(
                conn,
                atendimento_id=UUID(ctx.atendimento_id),
                responsavel="Fernando",
                tipo=TipoEscalada.comportamento_atipico,
                resumo_operacional=_RESUMO_JAILBREAK,
                acao_esperada=_ACAO_ASSUMIR,
                origem="agente",
                autor="sistema",
                observacao="jailbreak_attempt",
            )
        return Command(goto=END)  # type: ignore[arg-type]

    # Disclosure de alta confianca: negacao canned contornando a resistencia do Sonnet 4.6 a
    # negar identidade; conta a insistencia para escalar na 3a (10 §3.1).
    if categoria == "disclosure_attempt" and confianca == "alta":
        async with conexao(ctx.db_pool) as conn:
            # Incremento atomico (1 statement, roda 1x por invocacao). A idempotencia
            # cross-retry (mesmo turno_id contando 2x no replay do ARQ) ainda nao esta coberta:
            # TODO(M3a): guardar o incremento por (turno_id) via _executar_idempotente.
            res = await conn.execute(
                """
                UPDATE barravips.atendimentos
                   SET disclosure_tentativas = disclosure_tentativas + 1
                 WHERE id = %s
                 RETURNING disclosure_tentativas
                """,
                (UUID(ctx.atendimento_id),),
            )
            row = await res.fetchone()
            tentativas = row["disclosure_tentativas"] if row else 1

            if tentativas < 3:
                DISCLOSURE_DETECTADO.labels("negado").inc()
                return Command(
                    goto="post_process",
                    update={"messages": [AIMessage(content=escolher_negacao())]},
                )

            await abrir_handoff(
                conn,
                atendimento_id=UUID(ctx.atendimento_id),
                responsavel="Fernando",
                tipo=TipoEscalada.comportamento_atipico,
                resumo_operacional=_RESUMO_DISCLOSURE,
                acao_esperada=_ACAO_ASSUMIR,
                origem="agente",
                autor="sistema",
                observacao="disclosure_insistente",
            )
        DISCLOSURE_DETECTADO.labels("escalado").inc()
        return Command(goto=END)  # type: ignore[arg-type]

    # prova_humanidade_attempt, ambiguo (regex nao bate) ou None -> o LLM trata com os
    # protocolos few-shot de regras.md.j2 (10 §3, §4).
    return Command(goto="llm")
