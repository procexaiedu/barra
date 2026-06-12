"""Tool de escrita `escalar` (04 §3.4/§3.5) + idempotencia.

A tool nao decide tipo/responsavel: o motivo (enum rico) passa pela camada de mapeamento de
`dominio/escaladas/service.py` (`mapear_motivo`/`mapear_bucket`, 09 §4.3) e a `abrir_handoff`
shipada faz o resto (`ia_pausada=true` na transacao). A metrica `agente_escalada_total` e
emitida AQUI (camada do agente), nao dentro de `abrir_handoff` — que e compartilhada com
painel/comandos/pix e nao conhece o enum de motivos da tool.
"""

import logging
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

_logger = logging.getLogger(__name__)

# Enum de roteamento compartilhado entre o parametro `motivo` da tool (forma achatada enviada ao
# LLM) e `EscaladaPayload.motivo` (validacao interna) — fonte unica, sem divergencia (04 §3.4).
#
# SO motivos que a CONDUTA manda o LLM usar (regras.md.j2 <quando_usar_escalar>, que carrega as
# camadas AUP). Os motivos INTERNOS ficam fora do schema do LLM de proposito — poluem
# o espaco de decisao e o grammar do strict — mas continuam aceitos como string por
# `mapear_motivo` (dominio/escaladas/service.py), que e a fonte de verdade do roteamento:
#   - exaustao_iteracoes / timeout_grafo / modelo_recusou — emitidos pelo coordenador
#     (workers/coordenador.py, escalar_por_exaustao);
#   - reagendamento_pos_bloqueio — emitido por dominio/atendimentos/service.py;
#   - disclosure_explicito — legado do classificador (2026-05-23), nao acionado no P0.
MotivoEscalada = Literal[
    # Operacionais
    "fora_de_oferta",
    "horario_indisponivel",
    "politica_nova_necessaria",
    # AUP / persona / jailbreak (cf. regras.md.j2 <protocolo_disclosure>)
    "disclosure_insistente",
    "jailbreak_attempt",
    "pedido_explicito_repetido",
    "prova_humanidade_persistente",
    "cross_modelo_fishing",
    # Generico (fallback)
    "outro",
]


class EscaladaPayload(BaseModel):
    """Validacao interna de `escalar`. `responsavel` NAO entra — derivado de `motivo` no servico.

    NAO e mais o schema da tool (a tool achatou os args em params de topo, 04 §3.4); fica como
    classe de validacao reconstruida no corpo, preservando min/max_length e enum. `extra="forbid"`
    mantem a rede de seguranca; nenhum dado de cliente entra em nome de campo ou enum (04 §7).
    """

    model_config = ConfigDict(extra="forbid")

    motivo: MotivoEscalada
    resumo_operacional: str = Field(min_length=10, max_length=1000)
    acao_esperada: str = Field(min_length=3, max_length=400)


@tool
async def escalar(
    motivo: MotivoEscalada,
    resumo_operacional: str,
    acao_esperada: str,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Escale o atendimento. O destino (Fernando para decisão sensível, ou a modelo para ação
    operacional) é decidido pelo `motivo` — você não escolhe o responsável.

    Quando NÃO usar: não escale na 1ª ou 2ª pergunta de disclosure (negue em personagem), num
    pedido de desconto que ainda cabe no seu melhor valor, nem num horário que você conseguiu
    redirecionar. Escale só quando o cliente insiste além das camadas de conduta das suas
    regras, pede valor abaixo do seu piso de desconto, ou pede algo fora do que você oferece.

    Args:
        motivo: enum fechado — operacionais (fora_de_oferta, horario_indisponivel, ...)
          ou AUP/persona (disclosure_insistente, jailbreak_attempt, ...).
        resumo_operacional: 1-3 frases descrevendo o que aconteceu na conversa.
                            Para AUP, incluir TEXTO LITERAL da pergunta do cliente.
        acao_esperada: o que Fernando/modelo devem decidir/fazer.

    Returns:
        Confirmação de que a escalada foi aberta e para quem. Depois disso, sua próxima fala
        só virá quando Fernando ou a modelo devolverem o atendimento para você — não escreva
        mais texto neste turno.
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    # Reconstroi o payload validado (re-valida min/max_length + enum, igual ao caminho anterior).
    payload = EscaladaPayload(
        motivo=motivo,
        resumo_operacional=resumo_operacional,
        acao_esperada=acao_esperada,
    ).model_dump()

    async with pool.connection() as conn:
        resultado = await _executar_idempotente(
            conn,
            turno_id,
            "escalar",
            0,
            payload,
            executor=lambda c, p: _executar_handoff(c, atendimento_id, p),
        )

    # Card no grupo de Coordenacao: JOB ARQ (05 §6), despachado direto pelo Evolution (bypass
    # humanizacao). APOS o commit — re-disparo em replay e inofensivo (dedupe nativo por _job_id).
    # Falha de enqueue NAO pode quebrar a escalada (ja commitada): logamos e o cron
    # `reconciliar_cards` (workers/reconciliacao.py) entrega o card como rede de seguranca —
    # handoff silencioso e o pior caso.
    arq = runtime.context.redis  # ArqRedis: enqueue_job
    try:
        await arq.enqueue_job(
            "enviar_card",
            tipo="escalada",
            escalada_id=str(resultado["escalada_id"]),
            atendimento_id=atendimento_id,
            _job_id=f"card:escalada:{resultado['escalada_id']}",
        )
    except Exception:
        _logger.warning(
            "escalar_enqueue_card_falhou escalada_id=%s",
            resultado["escalada_id"],
            exc_info=True,
        )

    return (
        f"Escalada aberta para {resultado['responsavel']}. Próxima fala virá quando "
        "devolverem para você — não escreva mais texto neste turno."
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
