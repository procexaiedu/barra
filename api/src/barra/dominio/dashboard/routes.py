from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def dashboard(
    periodo: Literal["hoje", "7d", "30d"] = "hoje",
    modelo_id: UUID | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    inicio = _inicio(periodo)
    params: list[Any] = [inicio]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND modelo_id = %s"
        params.append(modelo_id)

    estados = await _dict_count(
        conn,
        f"""
        SELECT estado::text AS chave, count(*)::int AS total
          FROM barravips.atendimentos
         WHERE created_at >= %s {filtro_modelo}
         GROUP BY estado
        """,
        params,
    )
    fechamentos = await _one(
        conn,
        f"""
        SELECT count(*)::int AS quantidade, COALESCE(sum(valor_final), 0)::numeric AS valor_bruto
          FROM barravips.atendimentos
         WHERE estado = 'Fechado' AND updated_at >= %s {filtro_modelo}
        """,
        params,
    )
    perdas = await _dict_count(
        conn,
        f"""
        SELECT motivo_perda::text AS chave, count(*)::int AS total
          FROM barravips.atendimentos
         WHERE estado = 'Perdido' AND updated_at >= %s {filtro_modelo}
         GROUP BY motivo_perda
        """,
        params,
    )
    pix = await _one(
        conn,
        """
        SELECT count(*)::int AS total
          FROM barravips.comprovantes_pix p
          JOIN barravips.atendimentos a ON a.id = p.atendimento_id
         WHERE p.decisao_pipeline = 'em_revisao'
           AND p.decisao_final IS NULL
           AND p.created_at >= %s
           """ + ("AND a.modelo_id = %s" if modelo_id else ""),
        params,
    )
    escalados = await _one(
        conn,
        """
        SELECT count(*)::int AS total
          FROM barravips.escaladas e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
         WHERE e.fechada_em IS NULL AND e.aberta_em >= %s
           """ + ("AND a.modelo_id = %s" if modelo_id else ""),
        params,
    )
    return {
        "periodo": periodo,
        "atendimentos_por_estado": _estados_completos(estados),
        "fechamentos": fechamentos,
        "perdas_por_motivo": perdas,
        "pix_em_revisao": pix["total"],
        "atendimentos_escalados": escalados["total"],
    }


def _inicio(periodo: str) -> datetime:
    now = datetime.now(UTC)
    if periodo == "hoje":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "7d":
        return now - timedelta(days=7)
    return now - timedelta(days=30)


async def _one(conn: AsyncConnection[Any], query: str, params: list[Any]) -> dict[str, Any]:
    result = await conn.execute(query, params)
    row = await result.fetchone()
    assert row is not None
    return cast(dict[str, Any], row)


async def _dict_count(conn: AsyncConnection[Any], query: str, params: list[Any]) -> dict[str, int]:
    result = await conn.execute(query, params)
    return {row["chave"]: row["total"] for row in await result.fetchall() if row["chave"] is not None}


def _estados_completos(estados: dict[str, int]) -> dict[str, int]:
    chaves = [
        "Novo",
        "Triagem",
        "Qualificado",
        "Aguardando_confirmacao",
        "Confirmado",
        "Em_execucao",
        "Fechado",
        "Perdido",
    ]
    return {chave: estados.get(chave, 0) for chave in chaves}
