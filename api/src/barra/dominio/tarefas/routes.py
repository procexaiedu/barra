"""HTTP do Módulo de Tarefas (ADR 0017).

Todas as rotas herdam `Depends(get_user)` → `core/auth.py:103` rejeita papel ≠
'fernando'. Sem RBAC adicional: quem loga vê todas as tarefas (P0).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.dominio.tarefas import service
from barra.dominio.tarefas.schemas import (
    PrazoFiltro,
    ResponsaveisResponse,
    StatusTarefa,
    TarefaCriar,
    TarefaPatch,
    TarefaResponse,
    TarefasListaResponse,
)

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar(
    status: StatusTarefa | None = None,
    prazo: PrazoFiltro = "todos",
    minhas: bool = False,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TarefasListaResponse:
    return await service.listar_tarefas(
        conn, status=status, minhas=minhas, user_id=user.id, prazo=prazo
    )


# Declarado antes de "/{tarefa_id}" para não ser capturado pela rota paramétrica.
@router.get("/responsaveis")
async def listar_responsaveis(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ResponsaveisResponse:
    return await service.listar_responsaveis(conn)


@router.post("", status_code=201)
async def criar(
    body: TarefaCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TarefaResponse:
    return await service.criar_tarefa(conn, body, user.id)


@router.get("/{tarefa_id}")
async def obter(
    tarefa_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TarefaResponse:
    return await service.obter_tarefa(conn, tarefa_id)


@router.patch("/{tarefa_id}")
async def atualizar(
    tarefa_id: UUID,
    body: TarefaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TarefaResponse:
    return await service.atualizar_tarefa(conn, tarefa_id, body)


@router.delete("/{tarefa_id}", status_code=204)
async def excluir(
    tarefa_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await service.excluir_tarefa(conn, tarefa_id)
