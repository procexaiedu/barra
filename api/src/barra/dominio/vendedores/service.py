"""Orquestração do Vendedor (ADR 0012).

Painel-only por construção: não chama nada de `agente/`. Injeta `created_by`
como o usuário logado.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import NaoEncontrado
from barra.dominio.vendedores import repo
from barra.dominio.vendedores.schemas import (
    VendedorCriar,
    VendedoresListaResponse,
    VendedorPatch,
    VendedorResponse,
)


async def listar_vendedores(
    conn: AsyncConnection[Any], *, incluir_inativos: bool
) -> VendedoresListaResponse:
    items = await repo.listar(conn, incluir_inativos=incluir_inativos)
    return VendedoresListaResponse(items=items)


async def obter_vendedor(conn: AsyncConnection[Any], vendedor_id: UUID) -> VendedorResponse:
    vendedor = await repo.obter(conn, vendedor_id)
    if vendedor is None:
        raise NaoEncontrado("Vendedor")
    return vendedor


async def criar_vendedor(
    conn: AsyncConnection[Any], body: VendedorCriar, user_id: UUID
) -> VendedorResponse:
    vendedor_id = await repo.criar(
        conn,
        nome=body.nome.strip(),
        nivel=body.nivel,
        created_by=user_id,
    )
    vendedor = await repo.obter(conn, vendedor_id)
    assert vendedor is not None
    return vendedor


async def atualizar_vendedor(
    conn: AsyncConnection[Any], vendedor_id: UUID, body: VendedorPatch
) -> VendedorResponse:
    campos: dict[str, Any] = body.model_dump(exclude_unset=True)
    if "nome" in campos and campos["nome"] is not None:
        campos["nome"] = campos["nome"].strip()
    if not campos:
        return await obter_vendedor(conn, vendedor_id)

    ok = await repo.atualizar(conn, vendedor_id, campos)
    if not ok:
        raise NaoEncontrado("Vendedor")
    vendedor = await repo.obter(conn, vendedor_id)
    assert vendedor is not None
    return vendedor
