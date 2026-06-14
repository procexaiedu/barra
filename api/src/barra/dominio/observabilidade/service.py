"""Orquestracao do contexto Observabilidade: lista respostas da IA com contexto + avaliacao, e
registra a avaliacao humana. SQL puro parametrizado (padrao do vizinho `atendimentos`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import ErroDominio

from .schemas import (
    AvaliacaoResposta,
    AvaliarRequest,
    MensagemTurno,
    TurnoObservabilidade,
    TurnosObservabilidadeResponse,
)

# Lista cada RESPOSTA da IA (direcao='ia') com: cliente/modelo do par, numero_curto do atendimento,
# a ULTIMA mensagem do cliente ate aquele instante (LATERAL) e a avaliacao humana (LEFT JOIN).
# Cross-modelo por natureza (Fernando ve todas as modelos) — painel-only, nunca acessado pela IA.
_SQL_BASE = """
SELECT
  ia.id                AS resposta_ia_id,
  ia.conteudo          AS ia_conteudo,
  ia.created_at        AS ia_created_at,
  ia.atendimento_id    AS atendimento_id,
  at.numero_curto      AS numero_curto,
  cl.nome              AS cliente_nome,
  cl.telefone          AS cliente_telefone,
  mo.nome              AS modelo_nome,
  cliente_msg.conteudo   AS cliente_conteudo,
  cliente_msg.created_at AS cliente_created_at,
  av.veredito::text    AS veredito,
  av.nota              AS nota,
  av.comentario        AS comentario,
  av.avaliado_em       AS avaliado_em
FROM barravips.mensagens ia
JOIN barravips.conversas co ON co.id = ia.conversa_id
JOIN barravips.clientes cl ON cl.id = co.cliente_id
JOIN barravips.modelos  mo ON mo.id = co.modelo_id
LEFT JOIN barravips.atendimentos at ON at.id = ia.atendimento_id
LEFT JOIN LATERAL (
  SELECT m.conteudo, m.created_at
  FROM barravips.mensagens m
  WHERE m.conversa_id = ia.conversa_id
    AND m.direcao = 'cliente'
    AND m.created_at <= ia.created_at
  ORDER BY m.created_at DESC, m.id DESC
  LIMIT 1
) cliente_msg ON true
LEFT JOIN barravips.avaliacoes_resposta_ia av ON av.mensagem_id = ia.id
WHERE ia.direcao = 'ia'
"""


async def listar_turnos(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID | None,
    desde: datetime | None,
    ate: datetime | None,
    apenas_nao_avaliadas: bool,
    cursor: str | None,
    limit: int,
    origem: str = "prod",
) -> TurnosObservabilidadeResponse:
    cond: list[str] = []
    params: list[Any] = []
    # `origem` separa trafego real ('prod', default) das corridas do harness e2e ('e2e'); 'todos'
    # mostra ambos. Esconder e2e por padrao evita misturar conversas sinteticas com as reais.
    if origem in ("prod", "e2e"):
        cond.append("co.origem = %s")
        params.append(origem)
    if modelo_id is not None:
        cond.append("co.modelo_id = %s")
        params.append(modelo_id)
    if desde is not None:
        cond.append("ia.created_at >= %s")
        params.append(desde)
    if ate is not None:
        cond.append("ia.created_at <= %s")
        params.append(ate)
    if apenas_nao_avaliadas:
        cond.append("av.id IS NULL")
    if cursor and "|" in cursor:
        cursor_ts, cursor_id = cursor.rsplit("|", 1)
        cond.append("(ia.created_at, ia.id) < (%s::timestamptz, %s::uuid)")
        params.extend([cursor_ts, cursor_id])

    sql = _SQL_BASE + "".join(f"  AND {c}\n" for c in cond)
    sql += "ORDER BY ia.created_at DESC, ia.id DESC\nLIMIT %s"
    params.append(limit + 1)

    res = await conn.execute(sql, params)
    rows = await res.fetchall()

    tem_mais = len(rows) > limit
    visiveis = rows[:limit]
    items = [_row_para_turno(r) for r in visiveis]
    next_cursor = None
    if tem_mais and visiveis:
        ultimo = visiveis[limit - 1]
        next_cursor = f"{ultimo['ia_created_at'].isoformat()}|{ultimo['resposta_ia_id']}"
    return TurnosObservabilidadeResponse(items=items, next_cursor=next_cursor)


def _row_para_turno(r: dict[str, Any]) -> TurnoObservabilidade:
    mensagem_cliente = None
    if r.get("cliente_conteudo") is not None:
        mensagem_cliente = MensagemTurno(
            conteudo=r["cliente_conteudo"], created_at=r["cliente_created_at"]
        )
    avaliacao = None
    if r.get("veredito") is not None:
        avaliacao = AvaliacaoResposta(
            veredito=r["veredito"],
            nota=r.get("nota"),
            comentario=r.get("comentario"),
            avaliado_em=r["avaliado_em"],
        )
    return TurnoObservabilidade(
        resposta_ia_id=r["resposta_ia_id"],
        atendimento_id=r.get("atendimento_id"),
        numero_curto=r.get("numero_curto"),
        cliente_nome=r.get("cliente_nome"),
        cliente_telefone=r["cliente_telefone"],
        modelo_nome=r["modelo_nome"],
        mensagem_cliente=mensagem_cliente,
        resposta_ia=MensagemTurno(conteudo=r["ia_conteudo"], created_at=r["ia_created_at"]),
        avaliacao=avaliacao,
    )


async def avaliar_resposta(
    conn: AsyncConnection[Any],
    *,
    resposta_ia_id: UUID,
    body: AvaliarRequest,
    avaliado_por: UUID,
) -> AvaliacaoResposta:
    """Upsert da avaliacao de uma resposta da IA. Valida que o id e mesmo uma mensagem da IA."""
    chk = await conn.execute(
        "SELECT 1 FROM barravips.mensagens WHERE id = %s AND direcao = 'ia'",
        (resposta_ia_id,),
    )
    if await chk.fetchone() is None:
        raise ErroDominio(
            "RESPOSTA_NAO_ENCONTRADA",
            "Resposta da IA nao encontrada para avaliar.",
            status_code=404,
        )
    res = await conn.execute(
        """
        INSERT INTO barravips.avaliacoes_resposta_ia
            (mensagem_id, veredito, nota, comentario, avaliado_por)
        VALUES (%s, %s::barravips.veredito_avaliacao_enum, %s, %s, %s)
        ON CONFLICT (mensagem_id) DO UPDATE SET
            veredito = EXCLUDED.veredito,
            nota = EXCLUDED.nota,
            comentario = EXCLUDED.comentario,
            avaliado_por = EXCLUDED.avaliado_por,
            atualizado_em = now()
        RETURNING veredito::text AS veredito, nota, comentario, avaliado_em
        """,
        (resposta_ia_id, body.veredito, body.nota, body.comentario, avaliado_por),
    )
    row = await res.fetchone()
    assert row is not None
    return AvaliacaoResposta(
        veredito=row["veredito"],
        nota=row.get("nota"),
        comentario=row.get("comentario"),
        avaliado_em=row["avaliado_em"],
    )
