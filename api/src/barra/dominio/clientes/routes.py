from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import NaoEncontrado
from barra.dominio.clientes.schemas import ClientePatch

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("/clientes")
async def listar_clientes(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: UUID | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    joins = ""
    if modelo_id:
        joins = "JOIN barravips.conversas cv ON cv.cliente_id = c.id"
        filtros.append("cv.modelo_id = %s")
        params.append(modelo_id)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if cursor:
        filtros.append("c.updated_at < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT DISTINCT c.id, c.nome, c.telefone, c.primeiro_contato_modelo_id,
                        c.created_at, c.updated_at
          FROM barravips.clientes c
          {joins}
         WHERE {" AND ".join(filtros)}
         ORDER BY c.updated_at DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = rows[-1]["updated_at"].isoformat() if len(rows) > limit else None
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row["id"],
                "nome": row["nome"],
                "telefone_mascarado": _mascarar_telefone(row["telefone"]),
                "primeiro_contato_modelo_id": row["primeiro_contato_modelo_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/clientes/{cliente_id}")
async def obter_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT * FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    conversas = await _all(
        conn,
        """
        SELECT cv.id, cv.modelo_id, cv.recorrente, cv.ultimo_motivo_perda,
               cv.ultima_mensagem_em, cv.observacoes_internas,
               m.nome AS modelo_nome
          FROM barravips.conversas cv
          JOIN barravips.modelos m ON m.id = cv.modelo_id
         WHERE cv.cliente_id = %s
         ORDER BY cv.ultima_mensagem_em DESC NULLS LAST, cv.updated_at DESC
        """,
        (cliente_id,),
    )
    return {
        "cliente": {
            "id": cliente["id"],
            "nome": cliente["nome"],
            "telefone_mascarado": _mascarar_telefone(cliente["telefone"]),
            "primeiro_contato_modelo_id": cliente["primeiro_contato_modelo_id"],
            "created_at": cliente["created_at"],
            "updated_at": cliente["updated_at"],
        },
        "conversas": conversas,
    }


@router.patch("/clientes/{cliente_id}")
async def editar_cliente(
    cliente_id: UUID,
    body: ClientePatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        cliente = await _one(conn, "SELECT id FROM barravips.clientes WHERE id = %s", (cliente_id,))
        if cliente is None:
            raise NaoEncontrado("Cliente")
        nome = body.nome
        if isinstance(nome, str):
            nome = nome.strip() or None
        await conn.execute(
            "UPDATE barravips.clientes SET nome = %s WHERE id = %s",
            (nome, cliente_id),
        )
        atualizado = await _one(
            conn,
            "SELECT id, nome, telefone FROM barravips.clientes WHERE id = %s",
            (cliente_id,),
        )
    return {
        "id": atualizado["id"],
        "nome": atualizado["nome"],
        "telefone": atualizado["telefone"],
    }


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())


def _mascarar_telefone(telefone: str | None) -> str | None:
    if not telefone:
        return None
    return telefone[:3] + "*****" + telefone[-4:]
