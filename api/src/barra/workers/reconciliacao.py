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
from typing import Any

from barra.dominio.escaladas.service import OBS_LEMBRETE_SEM_RESPOSTA
from barra.workers.envio import enviar_card

logger = logging.getLogger(__name__)

# Folga antes do backstop disparar: deixa o caminho inline (enqueue na tool `escalar`) entregar
# normalmente em ~1s; só escaladas "presas" além disso entram na reconciliação, evitando corrida.
_RECONCILIACAO_FOLGA_SEGUNDOS = 30

# Card canônico por tipo de escalada. Cada tipo com card PRÓPRIO é reconciliado com o SEU card; o
# resto (escalar tool, jailbreak, política) cai no card genérico de Handoff (`escalada`).
# Próprios: `foto_portaria` → 🚪 chegada (+ foto); `cliente_busca`/`video_chamada` (pickup/remoto,
# ADR 0020/0021) → 🤝/🎥 "go-time" (não são Handoff, e sim "chegou a hora"). Reconciliar qualquer
# um deles com `escalada` mandaria o 🔔 genérico e envenenaria a idempotência por owner, deixando
# o card próprio nunca sair (regressão `foto_portaria`, bug E2E 2026-06-17).
_CARD_POR_TIPO_ESCALADA = {
    "foto_portaria": "chegada",
    "cliente_busca": "cliente_busca",
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
