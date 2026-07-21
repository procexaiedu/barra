"""Digest diário pro Fernando — cron de manhã (produção assistida).

Um card por modelo ativa no grupo de Coordenação dela (mesma porta do lembrete_valor:
`modelos.coordenacao_chat_id` + `evolution.enviar_texto` tipo='card'), com o dia em números:
conversas com cliente, atendimentos novos, fechados (+valor), handoffs e incidentes CONTIDOS
pelo sistema (defesas do gate/disclosure que viraram handoff sem chegar ao cliente). É o
combinado do plano do piloto (ADR 0034): Fernando recebe 1 resumo automático por dia — score ruim NUNCA
vira tarefa pra ele, então o card só informa, não pede ação. Os scores do judge pós-envio ficam
de FORA do card de propósito: são telemetria dev (Langfuse/Prometheus) e o grupo de Coordenação
também é lido pela modelo.

Janela: 1 dia corrido até o momento do cron. Idempotência: dedupe por `envios_evolution`
(payload card_kind='digest_semanal' + modelo_id nas últimas ~20h) — reexecução do cron no mesmo
ciclo não reenvia. Best-effort por modelo: falha de um envio não aborta o lote.

Fechados usam a MESMA âncora do dashboard (último evento `fechado_registrado` na janela), não o
created_at do atendimento — fechado importado sem evento fica de fora, igual lá.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection

from barra.core.evolution import EvolutionClient
from barra.core.metrics import DIGEST_SEMANAL
from barra.settings import Settings
from barra.workers._cards import render_card

logger = logging.getLogger(__name__)

CARD_KIND = "digest_semanal"
_JANELA_DIAS = 1

_SQL_MODELOS = """
SELECT id, nome, evolution_instance_id, coordenacao_chat_id
  FROM barravips.modelos
 WHERE status = 'ativa'
   AND evolution_instance_id IS NOT NULL
   AND coordenacao_chat_id IS NOT NULL
 ORDER BY nome
"""

# Dedupe: já mandamos o digest desta modelo neste ciclo? (20h cobre reexecução no mesmo dia
# sem engolir o envio legítimo do dia seguinte.)
_SQL_JA_ENVIADO = """
SELECT 1
  FROM barravips.envios_evolution
 WHERE payload->>'card_kind' = %s
   AND payload->>'modelo_id' = %s
   AND created_at >= now() - interval '20 hours'
 LIMIT 1
"""

_SQL_CONVERSAS = """
SELECT count(DISTINCT m.conversa_id) AS n
  FROM barravips.mensagens m
  JOIN barravips.conversas c ON c.id = m.conversa_id
 WHERE c.modelo_id = %s
   AND m.direcao = 'cliente'
   AND m.created_at >= now() - make_interval(days => %s)
"""

_SQL_NOVOS = """
SELECT count(*) AS n
  FROM barravips.atendimentos
 WHERE modelo_id = %s
   AND created_at >= now() - make_interval(days => %s)
"""

_SQL_FECHADOS = """
SELECT count(DISTINCT a.id) AS n, COALESCE(sum(a.valor_final), 0) AS total
  FROM barravips.atendimentos a
  JOIN LATERAL (
    SELECT created_at
      FROM barravips.eventos
     WHERE atendimento_id = a.id
       AND tipo = 'fechado_registrado'
     ORDER BY created_at DESC
     LIMIT 1
  ) e ON true
 WHERE a.modelo_id = %s
   AND a.estado = 'Fechado'
   AND e.created_at >= now() - make_interval(days => %s)
"""


# Incidentes CONTIDOS = handoffs do bucket de DEFESA (gate pré-envio, judge de AUP, rede final do
# envio, disclosure/jailbreak): o sistema segurou antes de chegar ao cliente. Derivado do
# _BUCKET_DEFESA canônico (dominio/escaladas/service.py) — fonte única, não re-declara a
# taxonomia. Prefixo LIKE porque a observacao persistida é granular ("output_leak_ia_self")
# enquanto o bucket lista a chave grossa; o `_` do LIKE é escapado (é wildcard).
def _prefixos_defesa() -> list[str]:
    from barra.dominio.escaladas.service import _BUCKET_DEFESA

    return [obs.replace("_", r"\_") + "%" for obs in sorted(_BUCKET_DEFESA)]


_SQL_HANDOFFS = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE e.observacao LIKE ANY(%(defesa)s)) AS contidos
  FROM barravips.escaladas e
  JOIN barravips.atendimentos a ON a.id = e.atendimento_id
 WHERE a.modelo_id = %(modelo_id)s
   AND e.aberta_em >= now() - make_interval(days => %(dias)s)
"""


async def _numeros_da_semana(conn: AsyncConnection[Any], modelo_id: Any) -> dict[str, Any]:
    async def _um(sql: str) -> dict[str, Any]:
        res = await conn.execute(sql, (modelo_id, _JANELA_DIAS))
        row = await res.fetchone()
        return dict(row) if row else {}

    conversas = await _um(_SQL_CONVERSAS)
    novos = await _um(_SQL_NOVOS)
    fechados = await _um(_SQL_FECHADOS)
    res = await conn.execute(
        _SQL_HANDOFFS,
        {"modelo_id": modelo_id, "dias": _JANELA_DIAS, "defesa": _prefixos_defesa()},
    )
    row = await res.fetchone()
    handoffs = dict(row) if row else {}
    return {
        "conversas": int(conversas.get("n") or 0),
        "novos": int(novos.get("n") or 0),
        "fechados": int(fechados.get("n") or 0),
        "valor_fechado": fechados.get("total") or 0,
        "handoffs": int(handoffs.get("total") or 0),
        "incidentes_contidos": int(handoffs.get("contidos") or 0),
    }


async def enviar_digest_semanal(
    conn: AsyncConnection[Any],
    evolution: EvolutionClient,
    settings: Settings,
) -> int:
    """Envia o card de digest para cada modelo ativa com canal. Devolve o nº de cards enviados."""
    if not settings.digest_semanal_ativo:
        return 0

    hoje = datetime.now(UTC)
    periodo = f"{(hoje - timedelta(days=_JANELA_DIAS)):%d/%m} a {hoje:%d/%m}"

    res = await conn.execute(_SQL_MODELOS)
    modelos = list(await res.fetchall())
    enviados = 0
    for m in modelos:
        try:
            res = await conn.execute(_SQL_JA_ENVIADO, (CARD_KIND, str(m["id"])))
            if await res.fetchone() is not None:
                DIGEST_SEMANAL.labels("pulado").inc()
                continue
            numeros = await _numeros_da_semana(conn, m["id"])
            texto = render_card(CARD_KIND, modelo_nome=m["nome"], periodo=periodo, **numeros)
            await evolution.enviar_texto(
                conn=conn,
                instance_id=m["evolution_instance_id"],
                remote_jid=m["coordenacao_chat_id"],
                texto=texto,
                contexto="grupo_coordenacao",
                tipo="card",
                payload={"card_kind": CARD_KIND, "modelo_id": str(m["id"])},
            )
            DIGEST_SEMANAL.labels("enviado").inc()
            enviados += 1
        except Exception:
            logger.exception("digest_semanal_falha modelo_id=%s", m["id"])
            DIGEST_SEMANAL.labels("falha").inc()
    return enviados
