from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import NaoEncontrado
from barra.dominio.conversas.schemas import ConversaPatch

router = APIRouter(dependencies=[Depends(get_user)])

PERIODOS_DIAS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/conversas")
async def listar_conversas(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: UUID | None = None,
    recorrente: bool | None = None,
    motivo_perda: str | None = None,
    periodo: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if modelo_id:
        filtros.append("cv.modelo_id = %s")
        params.append(modelo_id)
    if recorrente is not None:
        filtros.append("cv.recorrente = %s")
        params.append(recorrente)
    if motivo_perda:
        filtros.append("cv.ultimo_motivo_perda = %s")
        params.append(motivo_perda)
    if periodo in PERIODOS_DIAS:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.atendimentos a "
            "WHERE a.conversa_id = cv.id "
            f"AND a.created_at >= NOW() - INTERVAL '{PERIODOS_DIAS[periodo]} days')"
        )
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if cursor:
        filtros.append("cv.ultima_mensagem_em < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT
          cv.id, cv.recorrente, cv.ultimo_motivo_perda::text AS ultimo_motivo_perda,
          cv.ultima_mensagem_em, cv.ultima_mensagem_direcao::text AS ultima_mensagem_direcao,
          cv.created_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          m.id AS modelo_id, m.nome AS modelo_nome,
          ult.id AS ult_id, ult.numero_curto AS ult_numero_curto,
          ult.estado AS ult_estado, ult.created_at AS ult_created_at,
          ult.valor_final AS ult_valor_final, ult.motivo_perda AS ult_motivo_perda,
          EXISTS (
            SELECT 1 FROM barravips.atendimentos ab
             WHERE ab.conversa_id = cv.id
               AND ab.estado NOT IN ('Fechado', 'Perdido')
          ) AS tem_atendimento_aberto
        FROM barravips.conversas cv
        JOIN barravips.clientes c ON c.id = cv.cliente_id
        JOIN barravips.modelos m ON m.id = cv.modelo_id
        LEFT JOIN LATERAL (
          SELECT a.id, a.numero_curto, a.estado::text AS estado, a.created_at,
                 a.valor_final, a.motivo_perda::text AS motivo_perda
            FROM barravips.atendimentos a
           WHERE a.conversa_id = cv.id
           ORDER BY a.created_at DESC
           LIMIT 1
        ) ult ON TRUE
        WHERE {" AND ".join(filtros)}
        ORDER BY cv.ultima_mensagem_em DESC NULLS LAST, cv.created_at DESC
        LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = (
        rows[limit - 1]["ultima_mensagem_em"].isoformat()
        if len(rows) > limit and rows[limit - 1]["ultima_mensagem_em"] is not None
        else None
    )
    rows = rows[:limit]
    items = [
        {
            "id": row["id"],
            "cliente": {
                "id": row["cliente_id"],
                "nome": row["cliente_nome"],
                "telefone": row["cliente_telefone"],
            },
            "modelo": {"id": row["modelo_id"], "nome": row["modelo_nome"]},
            "recorrente": row["recorrente"],
            "ultima_mensagem_em": row["ultima_mensagem_em"],
            "ultima_mensagem_direcao": row["ultima_mensagem_direcao"],
            "ultimo_motivo_perda": row["ultimo_motivo_perda"],
            "ultimo_atendimento": None
            if row["ult_id"] is None
            else {
                "numero_curto": row["ult_numero_curto"],
                "estado": row["ult_estado"],
                "created_at": row["ult_created_at"],
                "valor_final": row["ult_valor_final"],
                "motivo_perda": row["ult_motivo_perda"],
            },
            "tem_atendimento_aberto": row["tem_atendimento_aberto"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/conversas/{conversa_id}")
async def obter_conversa(
    conversa_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    conversa = await _one(
        conn,
        """
        SELECT
          cv.id, cv.recorrente, cv.observacoes_internas,
          cv.ultimo_motivo_perda::text AS ultimo_motivo_perda,
          cv.ultima_mensagem_em,
          cv.ultima_mensagem_direcao::text AS ultima_mensagem_direcao,
          cv.created_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          c.created_at AS cliente_created_at,
          mp.nome AS primeiro_contato_modelo_nome,
          m.id AS modelo_id, m.nome AS modelo_nome
        FROM barravips.conversas cv
        JOIN barravips.clientes c ON c.id = cv.cliente_id
        JOIN barravips.modelos m ON m.id = cv.modelo_id
        LEFT JOIN barravips.modelos mp ON mp.id = c.primeiro_contato_modelo_id
        WHERE cv.id = %s
        """,
        (conversa_id,),
    )
    if conversa is None:
        raise NaoEncontrado("Conversa")

    aberto = await _one(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado,
               tipo_atendimento::text AS tipo_atendimento,
               urgencia::text AS urgencia,
               valor_acordado, proxima_acao_esperada
          FROM barravips.atendimentos
         WHERE conversa_id = %s
           AND estado NOT IN ('Fechado', 'Perdido')
         LIMIT 1
        """,
        (conversa_id,),
    )

    historico = await _all(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado, valor_final,
               motivo_perda::text AS motivo_perda, motivo_perda_obs, created_at
          FROM barravips.atendimentos
         WHERE conversa_id = %s
           AND estado IN ('Fechado', 'Perdido')
         ORDER BY created_at DESC
        """,
        (conversa_id,),
    )

    return {
        "conversa": {
            "id": conversa["id"],
            "recorrente": conversa["recorrente"],
            "observacoes_internas": conversa["observacoes_internas"],
            "ultimo_motivo_perda": conversa["ultimo_motivo_perda"],
            "ultima_mensagem_em": conversa["ultima_mensagem_em"],
            "ultima_mensagem_direcao": conversa["ultima_mensagem_direcao"],
            "created_at": conversa["created_at"],
        },
        "cliente": {
            "id": conversa["cliente_id"],
            "nome": conversa["cliente_nome"],
            "telefone": conversa["cliente_telefone"],
            "primeiro_contato_modelo_nome": conversa["primeiro_contato_modelo_nome"],
            "created_at": conversa["cliente_created_at"],
        },
        "modelo": {"id": conversa["modelo_id"], "nome": conversa["modelo_nome"]},
        "atendimento_aberto": None if aberto is None else aberto,
        "historico_atendimentos": historico,
    }


@router.patch("/conversas/{conversa_id}")
async def editar_conversa(
    conversa_id: UUID,
    body: ConversaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        existe = await _one(
            conn, "SELECT id FROM barravips.conversas WHERE id = %s", (conversa_id,)
        )
        if existe is None:
            raise NaoEncontrado("Conversa")
        valor = body.observacoes_internas
        if isinstance(valor, str):
            valor = valor.strip() or None
        await conn.execute(
            "UPDATE barravips.conversas SET observacoes_internas = %s WHERE id = %s",
            (valor, conversa_id),
        )
    return {"id": str(conversa_id), "observacoes_internas": valor}


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
