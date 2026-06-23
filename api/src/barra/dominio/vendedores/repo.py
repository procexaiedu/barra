"""SQL puro psycopg3 do Vendedor (ADR 0012 / 0002).

Sem hard-delete: o vendedor é referenciado por `modelos.vendedor_id`,
`atendimentos.vendedor_id` (ON DELETE SET NULL) e `financeiro_comissoes_pagas`
(ON DELETE RESTRICT). Desativação é via `ativo=false` (preserva histórico).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.dominio.vendedores.schemas import VendedorResponse

_SELECT_BASE = """
    SELECT v.id, v.nome, v.nivel::text AS nivel, v.ativo, v.created_at, v.updated_at
      FROM barravips.vendedores v
"""


def _row_to_response(row: dict[str, Any]) -> VendedorResponse:
    return VendedorResponse(
        id=row["id"],
        nome=row["nome"],
        nivel=row["nivel"],
        ativo=row["ativo"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


async def listar(conn: AsyncConnection[Any], *, incluir_inativos: bool) -> list[VendedorResponse]:
    where = "" if incluir_inativos else "WHERE v.ativo"
    result = await conn.execute(f"{_SELECT_BASE} {where} ORDER BY v.ativo DESC, v.nome")
    rows = list(await result.fetchall())
    return [_row_to_response(row) for row in rows]


async def obter(conn: AsyncConnection[Any], vendedor_id: UUID) -> VendedorResponse | None:
    result = await conn.execute(f"{_SELECT_BASE} WHERE v.id = %s", (vendedor_id,))
    row = await result.fetchone()
    return _row_to_response(row) if row is not None else None


async def criar(
    conn: AsyncConnection[Any],
    *,
    nome: str,
    nivel: str,
    created_by: UUID,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.vendedores (nome, nivel, created_by)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (nome, nivel, created_by),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar(
    conn: AsyncConnection[Any],
    vendedor_id: UUID,
    campos: dict[str, Any],
) -> bool:
    """UPDATE dinâmico. `campos` já validado pelo service (chaves de coluna reais)."""
    if not campos:
        return True
    sets = [f"{col} = %s" for col in campos]
    params = list(campos.values()) + [vendedor_id]
    result = await conn.execute(
        f"UPDATE barravips.vendedores SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0
