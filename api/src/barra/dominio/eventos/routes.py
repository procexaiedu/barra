"""Audit log read-only para o painel (timeline + feed recente)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar_eventos(
    conn: AsyncConnection[Any] = Depends(get_conn),
    atendimento_id: UUID | None = None,
    tipo: str | None = None,
    origem: str | None = None,
    autor: str | None = None,
    modelo_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    joins = ""
    if modelo_id:
        joins = "LEFT JOIN barravips.atendimentos a ON a.id = e.atendimento_id"
        filtros.append("a.modelo_id = %s")
        params.append(modelo_id)
    if atendimento_id:
        filtros.append("e.atendimento_id = %s")
        params.append(atendimento_id)
    if tipo:
        filtros.append("e.tipo = %s")
        params.append(tipo)
    if origem:
        filtros.append("e.origem = %s")
        params.append(origem)
    if autor:
        filtros.append("e.autor = %s")
        params.append(autor)
    if cursor:
        filtros.append("e.created_at < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT e.id, e.atendimento_id,
               e.tipo::text AS tipo,
               e.origem::text AS origem,
               e.autor::text AS autor,
               e.payload, e.created_at
          FROM barravips.eventos e
          {joins}
         WHERE {" AND ".join(filtros)}
         ORDER BY e.created_at DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = rows[-1]["created_at"].isoformat() if len(rows) > limit else None
    return {"items": rows[:limit], "next_cursor": next_cursor}
