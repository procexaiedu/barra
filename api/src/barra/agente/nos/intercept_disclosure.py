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

from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from psycopg import AsyncConnection

from barra.core.db import conexao
from barra.core.metrics import (
    AGENTE_ESCALADA,
    DISCLOSURE_DETECTADO,
    JAILBREAK_DETECTADO,
    REINCIDENCIA_SEGURANCA,
)
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff, mapear_bucket
from barra.settings import get_settings

from .._canned import escolher_negacao
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..ferramentas._idempotencia import _executar_idempotente

_ACAO_ASSUMIR = "Assumir a conversa com o cliente."
_RESUMO_DISCLOSURE = "Cliente insistiu (3a vez) perguntando se a Bia e IA."
_RESUMO_JAILBREAK = "Cliente tentou override de instrucao (jailbreak)."
_RESUMO_REINCIDENCIA = (
    "Telefone reincidente em tentativas de disclosure/jailbreak (>= limiar em 24h)."
)
_JANELA_REINCIDENCIA_S = 86400  # 24h


async def _contabilizar_reincidencia(ctx: ContextAgente) -> None:
    """Conta tentativas de disclosure/jailbreak por telefone (cliente) em 24h e, ao cruzar o limiar,
    escala a Fernando UMA vez por janela (SEC-JB-02). NUNCA bloqueia o cliente — é sinal p/ Fernando,
    então falso-positivo custa só um card.

    Dedupe por `turno_id` cobre o RETRY do mesmo job ARQ (o `turno_id` é estável no retry, que
    reproduz o drain loop do zero) — não conta 2x o mesmo evento reprocessado. O drain normal de
    várias mensagens do cliente sob o mesmo lock gera `turno_id` distinto por mensagem e conta cada
    uma como um evento próprio, que é o desejado (cada tentativa é um evento)."""
    settings = get_settings()
    if not settings.reincidencia_seguranca_habilitada:
        return
    redis = ctx.redis
    if not await redis.set(
        f"reincid:contado:{ctx.turno_id}", "1", ex=_JANELA_REINCIDENCIA_S, nx=True
    ):
        return  # mesmo job ARQ reprocessado (retry): evento já contado
    chave = f"reincid:count:{ctx.cliente_id}"
    n = await redis.incr(chave)
    if n == 1:
        await redis.expire(chave, _JANELA_REINCIDENCIA_S)
    REINCIDENCIA_SEGURANCA.labels("contabilizada").inc()
    if n < settings.reincidencia_seguranca_limiar:
        return
    # Escala 1x por janela. O marcador é setado ANTES (gate de concorrência: o abrir_handoff também
    # deduplica no DB), mas é REVERTIDO se o handoff falhar — senão uma falha transitória de DB
    # queimaria a janela de 24h sem ter escalado (o evento re-tenta no próximo turno).
    chave_escalado = f"reincid:escalado:{ctx.cliente_id}"
    if not await redis.set(chave_escalado, "1", ex=_JANELA_REINCIDENCIA_S, nx=True):
        return
    try:
        async with conexao(ctx.db_pool) as conn:
            await abrir_handoff(
                conn,
                atendimento_id=UUID(ctx.atendimento_id),
                responsavel="Fernando",
                tipo=TipoEscalada.comportamento_atipico,
                resumo_operacional=_RESUMO_REINCIDENCIA,
                acao_esperada=_ACAO_ASSUMIR,
                origem="agente",
                autor="sistema",
                observacao="reincidencia_seguranca",
            )
    except Exception:
        await redis.delete(chave_escalado)  # não queima a janela se o handoff falhou
        raise
    AGENTE_ESCALADA.labels(mapear_bucket("reincidencia_seguranca"), "reincidencia_seguranca").inc()
    REINCIDENCIA_SEGURANCA.labels("escalada").inc()


async def _incrementar_disclosure(
    conn: AsyncConnection[Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Executor do incremento de `disclosure_tentativas` (efeito de escrita do `_executar_idempotente`).

    Roda no MAXIMO uma vez por `turno_id` (chave sintetica `_disclosure_incr`): devolve o contador
    ja incrementado, persistido como `resultado` para o replay reler o mesmo valor sem re-somar.
    """
    res = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET disclosure_tentativas = disclosure_tentativas + 1
         WHERE id = %s
         RETURNING disclosure_tentativas
        """,
        (UUID(payload["atendimento_id"]),),
    )
    row = await res.fetchone()
    return {"tentativas": row["disclosure_tentativas"] if row else 1}


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
            AGENTE_ESCALADA.labels(mapear_bucket("jailbreak_attempt"), "jailbreak_attempt").inc()
        await _contabilizar_reincidencia(ctx)
        return Command(goto=END)  # type: ignore[arg-type]

    # Disclosure de alta confianca: negacao canned contornando a resistencia do Sonnet 4.6 a
    # negar identidade; conta a insistencia para escalar na 3a (10 §3.1).
    if categoria == "disclosure_attempt" and confianca == "alta":
        await _contabilizar_reincidencia(ctx)
        async with conexao(ctx.db_pool) as conn:
            # Incremento idempotente cross-retry (M3a): o contador vive na MESMA transacao do
            # `_executar_idempotente` (chave sintetica `_disclosure_incr`, call_idx=0). No replay
            # do ARQ (mesmo turno_id) o ON CONFLICT devolve o `tentativas` da 1a execucao sem
            # re-somar -- senao o contador subiria 2x e escalaria um toque antes do tempo.
            resultado = await _executar_idempotente(
                conn,
                ctx.turno_id,
                "_disclosure_incr",
                0,
                {"atendimento_id": ctx.atendimento_id},
                _incrementar_disclosure,
            )
            tentativas = resultado["tentativas"]

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
            AGENTE_ESCALADA.labels(
                mapear_bucket("disclosure_insistente"), "disclosure_insistente"
            ).inc()
        DISCLOSURE_DETECTADO.labels("escalado").inc()
        return Command(goto=END)  # type: ignore[arg-type]

    # prova_humanidade_attempt, ambiguo (regex nao bate) ou None -> o LLM trata com os
    # protocolos few-shot de regras.md.j2 (10 §3, §4).
    return Command(goto="llm")
