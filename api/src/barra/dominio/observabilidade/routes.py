"""HTTP do contexto Observabilidade (painel-only). Todas as rotas herdam Depends(get_user) ->
papel='fernando'. Sem regra de negocio aqui (ver dominio/CLAUDE.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.dominio.observabilidade import service
from barra.dominio.observabilidade.schemas import (
    AvaliacaoResposta,
    AvaliarRequest,
    TurnosObservabilidadeResponse,
)

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar(
    modelo_id: UUID | None = None,
    desde: datetime | None = None,
    ate: datetime | None = None,
    apenas_nao_avaliadas: bool = False,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TurnosObservabilidadeResponse:
    return await service.listar_turnos(
        conn,
        modelo_id=modelo_id,
        desde=desde,
        ate=ate,
        apenas_nao_avaliadas=apenas_nao_avaliadas,
        cursor=cursor,
        limit=limit,
    )


@router.post("/{resposta_ia_id}/avaliar")
async def avaliar(
    resposta_ia_id: UUID,
    body: AvaliarRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> AvaliacaoResposta:
    return await service.avaliar_resposta(
        conn, resposta_ia_id=resposta_ia_id, body=body, avaliado_por=user.id
    )
