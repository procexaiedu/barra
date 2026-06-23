"""HTTP do Módulo Financeiro (ADR 0011).

Todas as rotas herdam `Depends(get_user)` → `usuario_por_token` em
`core/auth.py:103` rejeita papel ≠ 'fernando' (decisão L).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from datetime import date
from io import StringIO
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.core.janela import Janela as _Janela
from barra.core.janela import resolver_janela
from barra.dominio.financeiro import repo, service
from barra.dominio.financeiro.schemas import (
    AtendimentosSemSnapshotResponse,
    ComissaoPagaCriar,
    ComissaoPagaPatch,
    ComissaoPagaResponse,
    ComissoesPagamentosListaResponse,
    ComissoesPorVendedorResponse,
    ComprovanteUploadResponse,
    ComprovanteUrlResponse,
    FinanceiroResumoResponse,
    FinanceiroSerieResponse,
    PreencherRepasseRetroativoBody,
    PreencherRepasseRetroativoResponse,
    ReceitaContextoResponse,
    ReceitasListaResponse,
    RepassePagoCriar,
    RepassePagoPatch,
    RepassePagoResponse,
    RepassesPagamentosListaResponse,
    RepassesPorModeloResponse,
)

router = APIRouter(dependencies=[Depends(get_user)])

Periodo = Literal["hoje", "7d", "30d", "mes", "tudo", "custom"]


async def _janela_periodo(
    conn: AsyncConnection[Any],
    periodo: str,
    de: date | None,
    ate: date | None,
    modelo_ids: list[UUID] | None = None,
) -> _Janela:
    """Resolve a janela do período. Em "tudo", ancora no 1º fechamento da operação
    (escopado pelo filtro de modelo) em vez do antigo piso fixo 2020."""
    piso = await repo.primeiro_fechamento(conn, modelo_ids) if periodo == "tudo" else None
    return resolver_janela(periodo, de, ate, piso_tudo=piso)


# =============================================================================
# Resumo
# =============================================================================


@router.get("")
async def get_resumo(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> FinanceiroResumoResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_resumo(conn, periodo=periodo, janela=janela, modelo_ids=modelo_id)


# =============================================================================
# Série / visão geral analítica
# =============================================================================


@router.get("/serie")
async def get_serie(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> FinanceiroSerieResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_serie(conn, periodo=periodo, janela=janela, modelo_ids=modelo_id)


# =============================================================================
# Receitas
# =============================================================================


@router.get("/receitas")
async def get_receitas(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    forma_pagamento: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ReceitasListaResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_receitas(
        conn,
        periodo=periodo,
        janela=janela,
        modelo_ids=modelo_id,
        forma_pagamento=forma_pagamento,
        limit=limit,
        cursor_iso=cursor,
    )


@router.get("/receitas/{atendimento_id}/contexto")
async def get_receita_contexto(
    atendimento_id: UUID,
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ReceitaContextoResponse:
    janela = await _janela_periodo(conn, periodo, de, ate)
    return await service.montar_contexto_receita(conn, atendimento_id=atendimento_id, janela=janela)


@router.get("/receitas/export")
async def export_receitas(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    forma_pagamento: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> StreamingResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    # Sem cursor — exporta tudo do período. Limite generoso para evitar abuso.
    resp = await service.montar_receitas(
        conn,
        periodo=periodo,
        janela=janela,
        modelo_ids=modelo_id,
        forma_pagamento=forma_pagamento,
        limit=10_000,
        cursor_iso=None,
    )
    headers_csv = [
        "data",
        "numero_curto",
        "modelo",
        "cliente",
        "forma_pagamento",
        "valor_bruto",
        "percentual_repasse",
        "valor_repasse_calculado",
    ]
    rows: list[list[Any]] = [
        [
            it.fechado_em,
            it.numero_curto,
            it.modelo_nome,
            it.cliente_nome,
            it.forma_pagamento or "",
            _fmt_br(it.valor_bruto),
            _fmt_br(it.percentual_repasse_snapshot)
            if it.percentual_repasse_snapshot is not None
            else "",
            _fmt_br(it.valor_repasse_calculado),
        ]
        for it in resp.items
    ]
    return _csv_response(f"receitas_{_periodo_label(janela)}.csv", headers_csv, rows)


# =============================================================================
# Repasses (visão saldo por modelo + pagamentos)
# =============================================================================


@router.get("/repasses")
async def get_repasses(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RepassesPorModeloResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_repasse_por_modelo(
        conn, periodo=periodo, janela=janela, modelo_ids=modelo_id
    )


@router.get("/comissoes")
async def get_comissoes(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    vendedor_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ComissoesPorVendedorResponse:
    """Saldo de Comissão de vendedor por vendedor no período (ADR 0012)."""
    janela = await _janela_periodo(conn, periodo, de, ate)
    return await service.montar_comissao_por_vendedor(
        conn, periodo=periodo, janela=janela, vendedor_ids=vendedor_id
    )


@router.get("/comissoes/pagamentos")
async def get_comissao_pagamentos(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    vendedor_id: Annotated[list[UUID] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ComissoesPagamentosListaResponse:
    """Pagamentos de Comissão de vendedor registrados no período (ADR 0012)."""
    janela = await _janela_periodo(conn, periodo, de, ate)
    return await service.montar_comissao_pagamentos(
        conn,
        periodo=periodo,
        janela=janela,
        vendedor_ids=vendedor_id,
        limit=limit,
        cursor_iso=cursor,
    )


@router.post("/comissoes/pagamentos", status_code=201)
async def post_comissao_pagamento(
    body: ComissaoPagaCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ComissaoPagaResponse:
    return await service.criar_comissao_pagamento(conn, body, user.id)


@router.patch("/comissoes/pagamentos/{pagamento_id}")
async def patch_comissao_pagamento(
    pagamento_id: UUID,
    body: ComissaoPagaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ComissaoPagaResponse:
    return await service.atualizar_comissao_pagamento(conn, pagamento_id, body)


@router.delete("/comissoes/pagamentos/{pagamento_id}", status_code=204)
async def delete_comissao_pagamento(
    pagamento_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await service.excluir_comissao_pagamento(conn, pagamento_id)


@router.get("/repasses/pagamentos")
async def get_pagamentos(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RepassesPagamentosListaResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_pagamentos(
        conn,
        periodo=periodo,
        janela=janela,
        modelo_ids=modelo_id,
        limit=limit,
        cursor_iso=cursor,
    )


@router.get("/repasses/pagamentos/export")
async def export_pagamentos(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> StreamingResponse:
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    resp = await service.montar_pagamentos(
        conn,
        periodo=periodo,
        janela=janela,
        modelo_ids=modelo_id,
        limit=10_000,
        cursor_iso=None,
    )
    headers_csv = ["data", "modelo", "valor", "forma_pagamento", "observacao"]
    rows: list[list[Any]] = [
        [
            it.data_pagamento.isoformat(),
            it.modelo_nome or "",
            _fmt_br(float(it.valor)),
            it.forma_pagamento,
            it.observacao or "",
        ]
        for it in resp.items
    ]
    return _csv_response(f"repasses_{_periodo_label(janela)}.csv", headers_csv, rows)


@router.post("/repasses/pagamentos", status_code=201)
async def post_pagamento(
    body: RepassePagoCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RepassePagoResponse:
    return await service.criar_pagamento(conn, body, user.id)


@router.patch("/repasses/pagamentos/{pagamento_id}")
async def patch_pagamento(
    pagamento_id: UUID,
    body: RepassePagoPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> RepassePagoResponse:
    return await service.atualizar_pagamento(conn, pagamento_id, body)


@router.delete("/repasses/pagamentos/{pagamento_id}", status_code=204)
async def delete_pagamento(
    pagamento_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    await service.excluir_pagamento(conn, pagamento_id)


# ---- comprovante (upload + URL) --------------------------------------------


@router.post("/repasses/pagamentos/comprovante-upload-url")
async def post_comprovante_upload(
    request: Request,
    filename: str,
) -> ComprovanteUploadResponse:
    return service.montar_upload_comprovante(
        bucket=request.app.state.settings.minio_bucket_media,
        minio_client=getattr(request.app.state, "minio", None),
        filename=filename,
    )


@router.get("/repasses/pagamentos/{pagamento_id}/comprovante")
async def get_comprovante(
    pagamento_id: UUID,
    request: Request,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ComprovanteUrlResponse:

    pag = await repo.obter_pagamento(conn, pagamento_id)
    if pag is None or not pag.comprovante_object_key:
        from barra.core.errors import NaoEncontrado

        raise NaoEncontrado("Comprovante")
    url = service.obter_url_comprovante(
        bucket=request.app.state.settings.minio_bucket_media,
        minio_client=getattr(request.app.state, "minio", None),
        object_key=pag.comprovante_object_key,
    )
    return ComprovanteUrlResponse(url=url)


# =============================================================================
# Preencher repasse retroativo
# =============================================================================


@router.get("/atendimentos-sem-snapshot")
async def get_atendimentos_sem_snapshot(
    modelo_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> AtendimentosSemSnapshotResponse:
    return await service.listar_atendimentos_sem_snapshot(conn, modelo_id)


@router.post("/atendimentos/preencher-repasse-retroativo")
async def post_preencher_retroativo(
    body: PreencherRepasseRetroativoBody,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> PreencherRepasseRetroativoResponse:
    return await service.preencher_repasse_retroativo(conn, body, user.id)


# =============================================================================
# Helpers CSV
# =============================================================================


def _periodo_label(janela: _Janela) -> str:
    """Filename amigável: se de==ate, usa AAAA-MM; senão, intervalo."""
    if janela.de.replace(day=1) == janela.ate.replace(day=1):
        return janela.de.strftime("%Y-%m")
    return f"{janela.de.isoformat()}_a_{janela.ate.isoformat()}"


def _fmt_br(valor: float | None) -> str:
    """Format BR (vírgula decimal). Para uso em CSV destinado a Excel BR."""
    if valor is None:
        return ""
    return f"{valor:.2f}".replace(".", ",")


def _csv_response(
    filename: str, headers: list[str], rows: Iterable[list[Any]]
) -> StreamingResponse:
    """CSV utf-8-sig (BOM para Excel BR), delimitador `;`."""

    def _stream() -> Iterator[bytes]:
        # BOM primeiro para Excel BR reconhecer UTF-8.
        buf = StringIO()
        buf.write("﻿")
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        yield buf.getvalue().encode("utf-8")
        for row in rows:
            buf.seek(0)
            buf.truncate()
            writer.writerow(row)
            yield buf.getvalue().encode("utf-8")

    return StreamingResponse(
        _stream(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
