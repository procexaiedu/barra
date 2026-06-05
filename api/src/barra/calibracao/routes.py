"""HTTP da rotulagem de calibracao (Loop B / EVAL-10).

Herda `Depends(get_user)` (papel 'fernando'). `rotulador_atual` mapeia o email logado p/
'fernando'|'socia' — base da INDEPENDENCIA: cada um so ve/edita o proprio rotulo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_settings_dep, get_user
from barra.calibracao import service
from barra.calibracao.schemas import (
    ExportResponse,
    FalasResponse,
    RodadaResumo,
    RodadasResponse,
    RotuloInput,
)
from barra.core.auth import UsuarioAtual
from barra.settings import Settings

router = APIRouter(dependencies=[Depends(get_user)])


def rotulador_atual(
    user: UsuarioAtual = Depends(get_user),
    settings: Settings = Depends(get_settings_dep),
) -> str:
    return service.resolver_rotulador(user.email, settings)


@router.get("/rodadas")
async def listar_rodadas(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RodadasResponse:
    return await service.listar(conn)


@router.post("/rodadas", status_code=201)
async def criar_rodada(
    nome: str = Form(...),
    descricao: str | None = Form(default=None),
    arquivo: UploadFile = File(...),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RodadaResumo:
    conteudo = await arquivo.read()
    return await service.criar_rodada(conn, nome, descricao, conteudo)


@router.get("/rodadas/{rodada_id}/falas")
async def listar_falas(
    rodada_id: UUID,
    rotulador: str = Depends(rotulador_atual),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> FalasResponse:
    return await service.falas_para_rotular(conn, rodada_id, rotulador)


@router.put("/rotulos", status_code=204)
async def marcar(
    body: RotuloInput,
    rotulador: str = Depends(rotulador_atual),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await service.marcar(conn, body, rotulador)


@router.get("/rodadas/{rodada_id}/export")
async def exportar(
    rodada_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ExportResponse:
    jsonl, avisos = await service.exportar(conn, rodada_id)
    total = sum(1 for linha in jsonl.splitlines() if linha.strip())
    return ExportResponse(golden=jsonl, total=total, avisos=avisos)
