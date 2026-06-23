"""Coletor de turnos de baixo score (avaliação humana 'ruim') para dataset de regressão.

Cron diário, observacional (flag `baixo_score_ativo`, default OFF). Lê do painel de observabilidade
(`barravips.avaliacoes_resposta_ia`, veredito='ruim') os turnos que Fernando reprovou e os empurra
para um dataset de regressão no Langfuse (`revisao-baixo-score`) — tornando a avaliação humana
NÃO-terminal (hoje entra na tabela e para ali). Cada item = 1 turno reprovado, com o texto da IA,
o contexto do cliente e o comentário humano.

Invariante: READ-ONLY no banco; identifica turnos só por UUID opaco (sem telefone/nome do cliente);
o texto já vive nos traces do Langfuse self-hosted (ADR 0019, mesmo perímetro de confiança). Nunca
volta ao contexto da IA ao vivo — mesma postura do `fluxo_drift` / `eval_v1_score` / Mapa de clientes.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg import AsyncConnection

from barra.core.tracing import garantir_dataset, registrar_score_agregado, upsert_item_dataset
from barra.settings import Settings

logger = logging.getLogger(__name__)

DATASET_BAIXO_SCORE = "revisao-baixo-score"

# Turnos reprovados pelo humano (veredito='ruim') no tráfego real, com o contexto do cliente
# (última mensagem dele até o instante da resposta, LATERAL). Só identidade por UUID opaco —
# nunca telefone/nome. Janela por `avaliado_em` (quando o Fernando avaliou), não por created_at.
_SQL_RUINS = """
SELECT
  ia.id            AS resposta_ia_id,
  ia.conversa_id   AS conversa_id,
  co.modelo_id     AS modelo_id,
  ia.conteudo      AS ia_conteudo,
  cliente_msg.conteudo AS cliente_conteudo,
  av.nota          AS nota,
  av.comentario    AS comentario,
  av.avaliado_em   AS avaliado_em
FROM barravips.avaliacoes_resposta_ia av
JOIN barravips.mensagens ia ON ia.id = av.mensagem_id
JOIN barravips.conversas co ON co.id = ia.conversa_id
LEFT JOIN LATERAL (
  SELECT m.conteudo
  FROM barravips.mensagens m
  WHERE m.conversa_id = ia.conversa_id
    AND m.direcao = 'cliente'
    AND m.created_at <= ia.created_at
  ORDER BY m.created_at DESC, m.id DESC
  LIMIT 1
) cliente_msg ON true
WHERE av.veredito = 'ruim'
  AND co.origem = 'prod'
  AND av.avaliado_em >= now() - make_interval(days => %s)
ORDER BY av.avaliado_em
"""


async def coletar_baixo_score(conn: AsyncConnection[Any], settings: Settings) -> int:
    """Coleta turnos reprovados ('ruim') da janela e os upserta no dataset de regressão do Langfuse.

    Retorna o nº de turnos coletados (0 quando a flag está off ou não há reprovação na janela).
    """
    if not settings.baixo_score_ativo:
        return 0

    res = await conn.execute(_SQL_RUINS, (settings.baixo_score_janela_dias,))
    rows = await res.fetchall()
    if not rows:
        logger.info(
            "baixo_score sem turnos reprovados na janela (%d dias)",
            settings.baixo_score_janela_dias,
        )
        return 0

    garantir_dataset(DATASET_BAIXO_SCORE)
    for r in rows:
        avaliado_em = r["avaliado_em"]
        upsert_item_dataset(
            DATASET_BAIXO_SCORE,
            f"baixo-score:{r['resposta_ia_id']}",
            {
                "resposta_ia_id": str(r["resposta_ia_id"]),
                "conversa_id": str(r["conversa_id"]),
                "modelo_id": str(r["modelo_id"]),
                "ia_conteudo": r["ia_conteudo"],
                "cliente_conteudo": r["cliente_conteudo"],
                "nota": r["nota"],
                "comentario": r["comentario"],
                "avaliado_em": avaliado_em.isoformat() if avaliado_em is not None else None,
            },
        )
    registrar_score_agregado("baixo_score_n_turnos", float(len(rows)))
    logger.info("baixo_score upsertou n=%d turnos no dataset %s", len(rows), DATASET_BAIXO_SCORE)
    return len(rows)
