"""Orquestração do Módulo Financeiro (ADR 0011).

Recebe entidades dos schemas, chama o repo, faz validações de negócio (que
não couberam no Pydantic). Não chama nada de `agente/` — financeiro é
painel-only por construção (decisão S do ADR).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = Any  # type: ignore[misc,assignment]

from psycopg import AsyncConnection

from barra.core.errors import EntradaInvalida, NaoEncontrado
from barra.core.janela import Janela, filtro_aplicado_dict, janela_anterior
from barra.dominio.financeiro import repo
from barra.dominio.financeiro.schemas import (
    AtendimentosSemSnapshotResponse,
    ComissaoPagaCriar,
    ComissaoPagaPatch,
    ComissaoPagaResponse,
    ComissoesPagamentosListaResponse,
    ComissoesPorVendedorResponse,
    ComprovanteUploadResponse,
    FinanceiroResumo,
    FinanceiroResumoResponse,
    FinanceiroSerieResponse,
    ImportadosSemData,
    JanelaComparacao,
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

# =============================================================================
# Resumo
# =============================================================================


async def montar_resumo(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    modelo_ids: list[UUID] | None,
) -> FinanceiroResumoResponse:
    """Resumo do período + comparativo com período anterior automático.

    'tudo' não tem comparativo (igual ao dashboard).
    """
    janela_ant = janela_anterior(janela) if periodo != "tudo" else None

    resumo = await repo.resumo_periodo(conn, janela, modelo_ids)
    resumo_ant: FinanceiroResumo | None = None
    if janela_ant:
        resumo_ant = await repo.resumo_periodo(conn, janela_ant, modelo_ids)

    imp_contagem, imp_bruto = await repo.importados_sem_data(conn, modelo_ids)

    return FinanceiroResumoResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        janela_comparacao=(
            JanelaComparacao(de=janela_ant.de.isoformat(), ate=janela_ant.ate.isoformat())
            if janela_ant
            else None
        ),
        resumo=resumo,
        resumo_anterior=resumo_ant,
        importados_sem_data=ImportadosSemData(contagem=imp_contagem, valor_bruto_brl=imp_bruto),
    )


# =============================================================================
# Série / visão geral analítica
# =============================================================================


async def montar_serie(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    modelo_ids: list[UUID] | None,
    top_limite: int = 8,
) -> FinanceiroSerieResponse:
    """Série diária + mix forma de pagamento + top modelos do período.

    Complemento analítico da visão geral (KPIs já vivem em /financeiro).
    """
    serie = await repo.serie_diaria(conn, janela, modelo_ids)
    mix = await repo.mix_forma_pagamento(conn, janela, modelo_ids)
    top = await repo.top_modelos(conn, janela, modelo_ids, top_limite)
    return FinanceiroSerieResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        serie_diaria=serie,
        mix_forma_pagamento=mix,
        top_modelos=top,
    )


# =============================================================================
# Receitas
# =============================================================================


async def montar_receitas(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    modelo_ids: list[UUID] | None,
    forma_pagamento: str | None,
    limit: int,
    cursor_iso: str | None,
) -> ReceitasListaResponse:
    cursor = _decodificar_cursor_receita(cursor_iso) if cursor_iso else None
    items, next_cursor = await repo.listar_receitas(
        conn, janela, modelo_ids, forma_pagamento, limit, cursor
    )
    return ReceitasListaResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        items=items,
        next_cursor=_codificar_cursor_receita(next_cursor) if next_cursor else None,
    )


async def montar_contexto_receita(
    conn: AsyncConnection,
    *,
    atendimento_id: UUID,
    janela: Janela,
) -> ReceitaContextoResponse:
    ctx = await repo.obter_contexto_receita(conn, atendimento_id, janela)
    if ctx is None:
        raise NaoEncontrado("Receita")
    return ctx


def _codificar_cursor_receita(cursor: tuple[datetime, UUID]) -> str:
    ts, aid = cursor
    return f"{ts.isoformat()}|{aid}"


def _decodificar_cursor_receita(raw: str) -> tuple[datetime, UUID]:
    try:
        ts_str, aid_str = raw.split("|", 1)
        return (datetime.fromisoformat(ts_str), UUID(aid_str))
    except (ValueError, TypeError) as exc:
        raise EntradaInvalida("CURSOR_INVALIDO", "cursor mal formado") from exc


# =============================================================================
# Repasses por modelo
# =============================================================================


async def montar_repasse_por_modelo(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    modelo_ids: list[UUID] | None,
) -> RepassesPorModeloResponse:
    items = await repo.repasse_por_modelo(conn, janela, modelo_ids)
    return RepassesPorModeloResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        items=items,
    )


async def montar_comissao_por_vendedor(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    vendedor_ids: list[UUID] | None,
) -> ComissoesPorVendedorResponse:
    """Saldo de comissão por vendedor no período (ADR 0012). Espelha o repasse por modelo."""
    items = await repo.comissao_por_vendedor(conn, janela, vendedor_ids)
    return ComissoesPorVendedorResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, vendedor_ids),
        items=items,
    )


async def montar_pagamentos(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    modelo_ids: list[UUID] | None,
    limit: int,
    cursor_iso: str | None,
) -> RepassesPagamentosListaResponse:
    cursor = _decodificar_cursor_pagamento(cursor_iso) if cursor_iso else None
    items, next_cursor = await repo.listar_pagamentos(conn, janela, modelo_ids, limit, cursor)
    return RepassesPagamentosListaResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        items=items,
        next_cursor=_codificar_cursor_pagamento(next_cursor) if next_cursor else None,
    )


def _codificar_cursor_pagamento(cursor: tuple[date, UUID]) -> str:
    d, pid = cursor
    return f"{d.isoformat()}|{pid}"


def _decodificar_cursor_pagamento(raw: str) -> tuple[date, UUID]:
    try:
        d_str, pid_str = raw.split("|", 1)
        return (date.fromisoformat(d_str), UUID(pid_str))
    except (ValueError, TypeError) as exc:
        raise EntradaInvalida("CURSOR_INVALIDO", "cursor mal formado") from exc


async def criar_pagamento(
    conn: AsyncConnection,
    body: RepassePagoCriar,
    user_id: UUID,
) -> RepassePagoResponse:
    pag_id = await repo.criar_pagamento(
        conn,
        modelo_id=body.modelo_id,
        data_pagamento=body.data_pagamento,
        valor=body.valor,
        forma_pagamento=body.forma_pagamento,
        observacao=body.observacao,
        comprovante_object_key=body.comprovante_object_key,
        user_id=user_id,
    )
    pag = await repo.obter_pagamento(conn, pag_id)
    assert pag is not None
    return pag


async def atualizar_pagamento(
    conn: AsyncConnection,
    pagamento_id: UUID,
    body: RepassePagoPatch,
) -> RepassePagoResponse:
    ok = await repo.atualizar_pagamento(
        conn,
        pagamento_id,
        data_pagamento=body.data_pagamento,
        valor=body.valor,
        forma_pagamento=body.forma_pagamento,
        observacao=body.observacao,
        comprovante_object_key=body.comprovante_object_key,
    )
    if not ok:
        raise NaoEncontrado("Pagamento de repasse")
    pag = await repo.obter_pagamento(conn, pagamento_id)
    assert pag is not None
    return pag


async def excluir_pagamento(conn: AsyncConnection, pagamento_id: UUID) -> None:
    ok = await repo.excluir_pagamento(conn, pagamento_id)
    if not ok:
        raise NaoEncontrado("Pagamento de repasse")


# =============================================================================
# Pagamentos de comissão (ADR 0012) — espelha os de repasse, eixo vendedor.
# Reaproveita o codec de cursor (date|uuid, genérico).
# =============================================================================


async def montar_comissao_pagamentos(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    vendedor_ids: list[UUID] | None,
    limit: int,
    cursor_iso: str | None,
) -> ComissoesPagamentosListaResponse:
    cursor = _decodificar_cursor_pagamento(cursor_iso) if cursor_iso else None
    items, next_cursor = await repo.listar_comissao_pagamentos(
        conn, janela, vendedor_ids, limit, cursor
    )
    return ComissoesPagamentosListaResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, vendedor_ids),
        items=items,
        next_cursor=_codificar_cursor_pagamento(next_cursor) if next_cursor else None,
    )


async def criar_comissao_pagamento(
    conn: AsyncConnection,
    body: ComissaoPagaCriar,
    user_id: UUID,
) -> ComissaoPagaResponse:
    pag_id = await repo.criar_comissao_pagamento(
        conn,
        vendedor_id=body.vendedor_id,
        data_pagamento=body.data_pagamento,
        valor=body.valor,
        forma_pagamento=body.forma_pagamento,
        observacao=body.observacao,
        comprovante_object_key=body.comprovante_object_key,
        user_id=user_id,
    )
    pag = await repo.obter_comissao_pagamento(conn, pag_id)
    assert pag is not None
    return pag


async def atualizar_comissao_pagamento(
    conn: AsyncConnection,
    pagamento_id: UUID,
    body: ComissaoPagaPatch,
) -> ComissaoPagaResponse:
    ok = await repo.atualizar_comissao_pagamento(
        conn,
        pagamento_id,
        data_pagamento=body.data_pagamento,
        valor=body.valor,
        forma_pagamento=body.forma_pagamento,
        observacao=body.observacao,
        comprovante_object_key=body.comprovante_object_key,
    )
    if not ok:
        raise NaoEncontrado("Pagamento de comissão")
    pag = await repo.obter_comissao_pagamento(conn, pagamento_id)
    assert pag is not None
    return pag


async def excluir_comissao_pagamento(conn: AsyncConnection, pagamento_id: UUID) -> None:
    ok = await repo.excluir_comissao_pagamento(conn, pagamento_id)
    if not ok:
        raise NaoEncontrado("Pagamento de comissão")


# =============================================================================
# Preencher repasse retroativo
# =============================================================================


async def listar_atendimentos_sem_snapshot(
    conn: AsyncConnection,
    modelo_id: UUID,
) -> AtendimentosSemSnapshotResponse:
    items = await repo.listar_atendimentos_sem_snapshot(conn, modelo_id)
    return AtendimentosSemSnapshotResponse(modelo_id=modelo_id, items=items)


async def preencher_repasse_retroativo(
    conn: AsyncConnection,
    body: PreencherRepasseRetroativoBody,
    user_id: UUID,
) -> PreencherRepasseRetroativoResponse:
    atualizados = await repo.preencher_repasse_retroativo(
        conn, body.atendimento_ids, body.percentual, user_id
    )
    return PreencherRepasseRetroativoResponse(atualizados=atualizados)


# =============================================================================
# Comprovante (upload + URL)
# =============================================================================


def montar_upload_comprovante(
    *,
    bucket: str,
    minio_client: Minio | None,
    filename: str,
) -> ComprovanteUploadResponse:
    from pathlib import PurePosixPath

    from barra.core.storage import presigned_put

    nome_seguro = PurePosixPath(filename).name
    object_key = f"repasses/{uuid4()}/{nome_seguro}"
    put_url = presigned_put(minio_client, bucket, object_key)
    return ComprovanteUploadResponse(object_key=object_key, put_url=put_url)


def obter_url_comprovante(*, bucket: str, minio_client: Minio | None, object_key: str) -> str:
    from barra.core.storage import presigned_get

    if not object_key.startswith("repasses/"):
        raise EntradaInvalida(
            "OBJECT_KEY_INVALIDO",
            "comprovante deve estar sob prefixo 'repasses/'",
        )
    return presigned_get(minio_client, bucket, object_key)
