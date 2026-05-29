"""Orquestração do Módulo de Tarefas (ADR 0017).

Painel-only por construção: não chama nada de `agente/`. Injeta `criado_por`
como o usuário logado e valida a consistência do responsável polimórfico.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import EntradaInvalida, NaoEncontrado
from barra.dominio.tarefas import repo
from barra.dominio.tarefas.schemas import (
    PrazoFiltro,
    ResponsaveisResponse,
    TarefaCriar,
    TarefaPatch,
    TarefaResponse,
    TarefasListaResponse,
)


def _validar_atribuido(tipo: str | None, id_: UUID | None) -> None:
    if (tipo is None) != (id_ is None):
        raise EntradaInvalida(
            "ATRIBUIDO_INCONSISTENTE",
            "atribuido_tipo e atribuido_id devem ser informados juntos",
        )


async def listar_tarefas(
    conn: AsyncConnection[Any],
    *,
    status: str | None,
    minhas: bool,
    user_id: UUID,
    prazo: PrazoFiltro,
    limit: int = 500,
) -> TarefasListaResponse:
    # "minhas" = tarefas atribuídas ao usuário logado (no P0 todo login é 'usuario').
    atribuido_tipo = "usuario" if minhas else None
    atribuido_id = user_id if minhas else None
    items = await repo.listar(
        conn,
        status=status,
        atribuido_tipo=atribuido_tipo,
        atribuido_id=atribuido_id,
        prazo=prazo,
        limit=limit,
    )
    return TarefasListaResponse(items=items)


async def obter_tarefa(conn: AsyncConnection[Any], tarefa_id: UUID) -> TarefaResponse:
    tarefa = await repo.obter(conn, tarefa_id)
    if tarefa is None:
        raise NaoEncontrado("Tarefa")
    return tarefa


async def criar_tarefa(
    conn: AsyncConnection[Any],
    body: TarefaCriar,
    user_id: UUID,
) -> TarefaResponse:
    _validar_atribuido(body.atribuido_tipo, body.atribuido_id)
    tarefa_id = await repo.criar(
        conn,
        titulo=body.titulo.strip(),
        descricao=body.descricao,
        prioridade=body.prioridade,
        prazo=body.prazo,
        criado_por_tipo="usuario",
        criado_por_id=user_id,
        atribuido_tipo=body.atribuido_tipo,
        atribuido_id=body.atribuido_id,
    )
    tarefa = await repo.obter(conn, tarefa_id)
    assert tarefa is not None
    return tarefa


async def atualizar_tarefa(
    conn: AsyncConnection[Any],
    tarefa_id: UUID,
    body: TarefaPatch,
) -> TarefaResponse:
    enviados: dict[str, Any] = body.model_dump(exclude_unset=True)

    # Responsável: para reatribuir ou limpar, ambos os campos devem vir juntos.
    tem_tipo = "atribuido_tipo" in enviados
    tem_id = "atribuido_id" in enviados
    if tem_tipo != tem_id:
        raise EntradaInvalida(
            "ATRIBUIDO_INCONSISTENTE",
            "atribuido_tipo e atribuido_id devem ser informados juntos",
        )
    if tem_tipo and tem_id:
        _validar_atribuido(enviados["atribuido_tipo"], enviados["atribuido_id"])

    if "titulo" in enviados and enviados["titulo"] is not None:
        enviados["titulo"] = enviados["titulo"].strip()

    if not enviados:
        return await obter_tarefa(conn, tarefa_id)

    ok = await repo.atualizar(conn, tarefa_id, enviados)
    if not ok:
        raise NaoEncontrado("Tarefa")
    tarefa = await repo.obter(conn, tarefa_id)
    assert tarefa is not None
    return tarefa


async def excluir_tarefa(conn: AsyncConnection[Any], tarefa_id: UUID) -> None:
    ok = await repo.excluir(conn, tarefa_id)
    if not ok:
        raise NaoEncontrado("Tarefa")


async def listar_responsaveis(conn: AsyncConnection[Any]) -> ResponsaveisResponse:
    items = await repo.listar_responsaveis(conn)
    return ResponsaveisResponse(items=items)
