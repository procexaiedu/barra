"""Reconciliação de cards de handoff — rede de segurança contra handoff silencioso.

Achado no teste E2E ao vivo (2026-06-05, grupo Lucia): a IA abriu uma escalada
(`ia_pausada=true`) mas o card no grupo de Coordenação NUNCA foi entregue — `card_message_id`
ficou NULL e o job ARQ `enviar_card` enfileirado inline pela tool `escalar`
(`agente/ferramentas/escalada.py`) não executou. A causa exata no nível do ARQ não foi isolada
(o enqueue usa a mesma ArqRedis do `enviar_turno`, que funciona). Esta varredura GARANTE a
entrega chamando `enviar_card` INLINE no contexto do cron — que comprovadamente roda a cada
minuto — em vez de re-enfileirar, contornando qualquer falha de enqueue/pickup. Idempotente:
`_card_escalada` é no-op quando o card já saiu (`card_message_id` não-nulo).
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from barra.agente._canned import escolher_cancelamento_piloto
from barra.dominio.escaladas.service import OBS_LEMBRETE_SEM_RESPOSTA
from barra.workers.coordenador import NS_TURNO
from barra.workers.envio import enviar_card

logger = logging.getLogger(__name__)

# Folga antes do backstop disparar: deixa o caminho inline (enqueue na tool `escalar`) entregar
# normalmente em ~1s; só escaladas "presas" além disso entram na reconciliação, evitando corrida.
_RECONCILIACAO_FOLGA_SEGUNDOS = 30

# Card canônico por tipo de escalada. Cada tipo com card PRÓPRIO é reconciliado com o SEU card; o
# resto (escalar tool, jailbreak, política) cai no card genérico de Handoff (`escalada`).
# Próprios: `foto_portaria` → 🚪 chegada (+ foto); `video_chamada` (remoto, ADR 0021) → 🎥
# "go-time" (não é Handoff, e sim "chegou a hora"). Reconciliar qualquer um deles com `escalada`
# mandaria o 🔔 genérico e envenenaria a idempotência por owner, deixando o card próprio nunca
# sair (regressão `foto_portaria`, bug E2E 2026-06-17).
_CARD_POR_TIPO_ESCALADA = {
    "foto_portaria": "chegada",
    "video_chamada": "video_chamada",
}


async def reconciliar_cards_escalada(ctx: dict[str, Any]) -> int:
    """Entrega cards de escalada órfãos: abertos, sem `card_message_id`, abertos há > folga.

    Devolve quantas escaladas foram processadas. Roda como cron (a cada minuto). Usa o `ctx`
    do worker (`db_pool` + `evolution`) para chamar `enviar_card` inline.
    """
    pool = ctx.get("db_pool")
    evolution = ctx.get("evolution")
    if pool is None or evolution is None:
        return 0

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT id::text AS id, tipo::text AS tipo, atendimento_id::text AS atendimento_id
              FROM barravips.escaladas
             WHERE fechada_em IS NULL
               AND card_message_id IS NULL
               AND aberta_em < now() - make_interval(secs => %s)
               -- Só escaladas que viram card no grupo (UX §9.6): owner=Fernando vai pro painel,
               -- não pro grupo, então não é "órfã" — fora daqui senão o _card_escalada no-op as
               -- reprocessaria a cada minuto, ocupando o LIMIT e represando órfãs reais da modelo.
               AND (responsavel = 'modelo' OR observacao = %s)
             ORDER BY aberta_em
             LIMIT 50
            """,
            (_RECONCILIACAO_FOLGA_SEGUNDOS, OBS_LEMBRETE_SEM_RESPOSTA),
        )
        pendentes = await res.fetchall()

    processados = 0
    for esc in pendentes:
        # Cada tipo é reconciliado com o SEU card (foto_portaria → chegada; resto → escalada);
        # mandar sempre `escalada` envenenaria a idempotência por owner do card próprio.
        tipo_card = _CARD_POR_TIPO_ESCALADA.get(esc["tipo"], "escalada")
        try:
            await enviar_card(
                ctx,
                tipo=tipo_card,
                escalada_id=esc["id"],
                atendimento_id=esc["atendimento_id"],
            )
            processados += 1
        except Exception:
            logger.warning(
                "reconciliar_card_escalada_falhou escalada_id=%s", esc["id"], exc_info=True
            )
    if processados:
        logger.info("reconciliar_cards_escalada processados=%s", processados)
    return processados


# Backstop da desculpa do Cancelamento automático do piloto (ADR-0033). O envio é crítico
# (`critico=True`), mas `MAX_TRIES_ENVIO=3` com `defer=10*job_try` esgota a janela em ~30s --
# dimensionado para soluço de rede, não para queda de instância. No incidente 24-27/07 a Evolution
# ficou 3 dias fora: o atendimento foi cancelado 15 min antes do encontro, a desculpa evaporou nos
# primeiros 30s e o cliente ficou esperando um encontro que o sistema já tinha matado -- o cenário
# exato que o ADR-0033 existe pra evitar. Mesma forma do backstop de cards acima: varre o que não
# saiu e reenfileira, em vez de confiar numa única janela de retry.
_DESCULPA_PILOTO_JANELA_HORAS = 6

# Folga antes de reenfileirar: o job original leva reading/typing delay antes de gravar a bolha.
_DESCULPA_PILOTO_FOLGA_SEGUNDOS = 120

# A prova de entrega é a mensagem GRAVADA (o texto é sorteado de um pool, então não dá pra casar
# por conteúdo) -- e gravar só acontece depois de a Evolution confirmar o envio.
_SQL_DESCULPA_PENDENTE = """
SELECT a.id::text AS atendimento_id, a.conversa_id::text AS conversa_id
  FROM barravips.atendimentos a
  JOIN barravips.conversas c ON c.id = a.conversa_id
  JOIN barravips.modelos m ON m.id = c.modelo_id
 WHERE a.piloto_cancelado_em IS NOT NULL
   AND a.piloto_cancelado_em > now() - make_interval(hours => %s)
   AND a.piloto_cancelado_em < now() - make_interval(secs => %s)
   AND m.evolution_status = 'conectado'
   AND NOT EXISTS (
         SELECT 1
           FROM barravips.mensagens msg
          WHERE msg.conversa_id = a.conversa_id
            AND msg.direcao = 'ia'
            AND msg.created_at >= a.piloto_cancelado_em
       )
 ORDER BY a.piloto_cancelado_em
 LIMIT 50
"""


def _bucket_retry() -> str:
    """Bucket de 10 min no `_job_id`: o cron roda a cada minuto, e um `_job_id` fixo faria o ARQ
    recusar a segunda tentativa enquanto o resultado da primeira estivesse no Redis — bastava uma
    tentativa cair na janela ruim pra desculpa se perder de novo. O bucket dá novas chances sem
    enfileirar 60x por hora; duplicar a bolha, o `dedupe_key` do `turno_id` já impede.
    """
    return datetime.now(UTC).strftime("%Y%m%d%H%M")[:-1]


def _turno_id_cancelamento(atendimento_id: str) -> str:
    """MESMO `turno_id` do envio original (`workers/timeouts.cancelar_piloto_teste`).

    É ele que carrega a idempotência por chunk (`dedupe_key`), então uma corrida entre o job
    original e este backstop não duplica a bolha ao cliente.
    """
    return str(uuid5(NS_TURNO, f"cancelamento_piloto:{atendimento_id}"))


async def reconciliar_desculpa_piloto(ctx: dict[str, Any]) -> int:
    """Reenfileira a desculpa do cancelamento do piloto que não chegou ao cliente.

    Devolve quantos atendimentos foram reenfileirados. Roda como cron (a cada minuto). Passada a
    janela de `_DESCULPA_PILOTO_JANELA_HORAS`, para de tentar: desculpa de "surgiu um imprevisto"
    horas depois não conserta nada, e a escalada aberta pelo cancelamento continua no painel.
    """
    pool = ctx.get("db_pool")
    redis = ctx.get("redis")
    if pool is None or redis is None:
        return 0

    async with pool.connection() as conn:
        res = await conn.execute(
            _SQL_DESCULPA_PENDENTE,
            (_DESCULPA_PILOTO_JANELA_HORAS, _DESCULPA_PILOTO_FOLGA_SEGUNDOS),
        )
        pendentes = await res.fetchall()

    processados = 0
    for alvo in pendentes:
        atendimento_id = alvo["atendimento_id"]
        conversa_id = alvo["conversa_id"]
        turno_id = _turno_id_cancelamento(atendimento_id)
        try:
            await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)
            await redis.enqueue_job(
                "enviar_turno",
                conversa_id=conversa_id,
                turno_id=turno_id,
                chunks=[escolher_cancelamento_piloto()],
                midias=[],
                msg_ids_cliente=[],
                chars_inbound=0,
                critico=True,
                _job_id=f"cancelamento_piloto_retry:{atendimento_id}:{_bucket_retry()}",
            )
            processados += 1
        except Exception:
            logger.warning(
                "reconciliar_desculpa_piloto_falhou atendimento_id=%s",
                atendimento_id,
                exc_info=True,
            )
    if processados:
        logger.info("reconciliar_desculpa_piloto processados=%s", processados)
    return processados
