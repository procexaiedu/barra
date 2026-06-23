"""HTTP do Vendedor (ADR 0012).

Todas as rotas herdam `Depends(get_user)` → rejeita papel ≠ 'fernando' (painel-only).
CRUD enxuto: criar, listar, obter, editar. Sem hard-delete — desativar via PATCH
`ativo=false` (ver repo).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.dominio.vendedores import service
from barra.dominio.vendedores.schemas import (
    VendedorCriar,
    VendedoresListaResponse,
    VendedorPatch,
    VendedorResponse,
)

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar(
    incluir_inativos: bool = False,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> VendedoresListaResponse:
    return await service.listar_vendedores(conn, incluir_inativos=incluir_inativos)


@router.post("", status_code=201)
async def criar(
    body: VendedorCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> VendedorResponse:
    return await service.criar_vendedor(conn, body, user.id)


@router.get("/{vendedor_id}")
async def obter(
    vendedor_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> VendedorResponse:
    return await service.obter_vendedor(conn, vendedor_id)


@router.patch("/{vendedor_id}")
async def atualizar(
    vendedor_id: UUID,
    body: VendedorPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> VendedorResponse:
    return await service.atualizar_vendedor(conn, vendedor_id, body)
