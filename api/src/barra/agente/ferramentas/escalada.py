"""Tool de escrita `escalar` (04 §3.4/§3.5) + idempotencia.

A tool nao decide tipo/responsavel: o motivo (enum rico) passa pela camada de mapeamento de
`dominio/escaladas/service.py` (`mapear_motivo`/`mapear_bucket`, 09 §4.3) e a `abrir_handoff`
shipada faz o resto (`ia_pausada=true` na transacao). A metrica `agente_escalada_total` e
emitida AQUI (camada do agente), nao dentro de `abrir_handoff` — que e compartilhada com
painel/comandos/pix e nao conhece o enum de motivos da tool.
"""

from typing import Any, Literal
from uuid import UUID

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from barra.core.metrics import AGENTE_ESCALADA
from barra.dominio.escaladas.service import abrir_handoff, mapear_bucket, mapear_motivo

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente


class EscaladaPayload(BaseModel):
    """Args de `escalar`. `responsavel` NAO entra — derivado de `motivo` no servico de dominio.

    `extra="forbid"` -> additionalProperties:false em todo nivel, requisito do strict tool use
    (04 §7). O `motivo` e a chave de roteamento + metrica, entao o enum precisa bater exatamente;
    nenhum dado de cliente entra em nome de campo ou enum (guarda de privacidade, 04 §7).
    """

    model_config = ConfigDict(extra="forbid")

    motivo: Literal[
        # Operacionais
        "fora_de_oferta",
        "horario_indisponivel",
        "reagendamento_pos_bloqueio",
        "politica_nova_necessaria",
        "exaustao_iteracoes",
        "timeout_grafo",
        "modelo_recusou",
        # AUP / persona / jailbreak (cf. 10-persona-jailbreak.md)
        "disclosure_insistente",
        "disclosure_explicito",
        "jailbreak_attempt",
        "pedido_explicito_repetido",
        "prova_humanidade_persistente",
        "cross_modelo_fishing",
        # Generico (fallback)
        "outro",
    ]
    resumo_operacional: str = Field(min_length=10, max_length=1000)
    acao_esperada: str = Field(min_length=3, max_length=400)


@tool
async def escalar(
    payload: EscaladaPayload,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Escale o atendimento. O destino (Fernando p/ decisao sensivel, ou modelo p/ acao
    operacional) e decidido pelo `motivo` — voce nao escolhe o responsavel.

    Apos chamar, sua proxima fala vira quando Fernando devolver para voce explicitamente, ou
    quando a modelo registrar finalizado pelo grupo. Nao escreva mais texto nesse turno.

    Args:
        payload.motivo: enum fechado — operacionais (fora_de_oferta, horario_indisponivel, ...)
          ou AUP/persona (disclosure_insistente, jailbreak_attempt, ...).
        payload.resumo_operacional: 1-3 frases descrevendo o que aconteceu na conversa.
                                    Para AUP, incluir TEXTO LITERAL da pergunta do cliente.
        payload.acao_esperada: o que Fernando/modelo devem decidir/fazer.
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn,
            turno_id,
            "escalar",
            0,
            payload.model_dump(),
            executor=lambda c, p: _executar_handoff(c, atendimento_id, p),
        )

    # Card no grupo de Coordenacao: JOB ARQ (05 §6), despachado direto pelo Evolution (bypass
    # humanizacao). APOS o commit — re-disparo em replay e inofensivo (dedupe nativo por _job_id).
    arq = runtime.context.redis  # ArqRedis: enqueue_job
    await arq.enqueue_job(
        "enviar_card",
        tipo="escalada",
        escalada_id=str(resultado["escalada_id"]),
        atendimento_id=atendimento_id,
        _job_id=f"card:escalada:{resultado['escalada_id']}",
    )

    return (
        f"Escalada aberta para {resultado['responsavel']}. Proxima fala vira quando "
        "devolverem para voce — nao escreva mais texto neste turno."
    )


async def _executar_handoff(
    conn: AsyncConnection[Any], atendimento_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Wraps `abrir_handoff` via o mapping de motivo e devolve `escalada_id` + `responsavel`."""
    motivo: str = payload["motivo"]
    tipo, responsavel = mapear_motivo(motivo)
    await abrir_handoff(
        conn,
        atendimento_id=UUID(atendimento_id),
        responsavel=responsavel,
        tipo=tipo,
        resumo_operacional=payload["resumo_operacional"],
        acao_esperada=payload["acao_esperada"],
        origem="agente",
        autor="IA",
        observacao=motivo,  # motivo LITERAL preservado (09 §4.3)
    )
    # Metrica na camada do agente (NAO em abrir_handoff, compartilhada). Diverge de 04 §3.6
    # ("abrir_handoff emite") — arbitro = codigo shipado. Dentro do executor idempotente: um
    # replay do turno (mesma chave) nao reexecuta e nao re-conta.
    AGENTE_ESCALADA.labels(mapear_bucket(motivo), motivo).inc()
    res = await conn.execute(
        "SELECT id, responsavel FROM barravips.escaladas"
        " WHERE atendimento_id = %s ORDER BY aberta_em DESC LIMIT 1",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None  # a escalada foi inserida nesta mesma transacao
    return {"escalada_id": str(row["id"]), "responsavel": row["responsavel"]}
