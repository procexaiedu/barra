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
    ComprovanteUploadResponse,
    DespesaCriar,
    DespesaPatch,
    DespesaRecorrenteCriar,
    DespesaRecorrentePatch,
    DespesaRecorrenteResponse,
    DespesasListaResponse,
    FinanceiroResumo,
    FinanceiroResumoResponse,
    JanelaComparacao,
    MaterializarRecorrenteBody,
    PreencherRepasseRetroativoBody,
    PreencherRepasseRetroativoResponse,
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

    return FinanceiroResumoResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, modelo_ids),
        janela_comparacao=(
            JanelaComparacao(de=janela_ant.de.isoformat(), ate=janela_ant.ate.isoformat())
            if janela_ant else None
        ),
        resumo=resumo,
        resumo_anterior=resumo_ant,
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
# Despesas (pontuais + materializadas + projeções)
# =============================================================================


async def montar_despesas(
    conn: AsyncConnection,
    *,
    periodo: str,
    janela: Janela,
    categorias: list[str] | None,
) -> DespesasListaResponse:
    items = await repo.listar_despesas(conn, janela, categorias)
    return DespesasListaResponse(
        filtro_aplicado=filtro_aplicado_dict(periodo, janela, None),
        items=items,
        next_cursor=None,  # sem paginação no P0
    )


async def criar_despesa(
    conn: AsyncConnection,
    body: DespesaCriar,
    user_id: UUID,
) -> UUID:
    return await repo.criar_despesa_pontual(
        conn,
        categoria=body.categoria,
        valor=body.valor,
        data=body.data,
        descricao=body.descricao,
        user_id=user_id,
    )


async def materializar_recorrente(
    conn: AsyncConnection,
    body: MaterializarRecorrenteBody,
    user_id: UUID,
) -> UUID:
    try:
        return await repo.materializar_recorrente(
            conn,
            recorrente_id=body.recorrente_id,
            competencia_mes=body.competencia_mes,
            user_id=user_id,
        )
    except ValueError as exc:
        raise NaoEncontrado("Template de despesa recorrente") from exc


async def atualizar_despesa(
    conn: AsyncConnection,
    despesa_id: UUID,
    body: DespesaPatch,
) -> None:
    ok = await repo.atualizar_despesa(
        conn,
        despesa_id,
        categoria=body.categoria,
        valor=body.valor,
        data=body.data,
        descricao=body.descricao,
    )
    if not ok:
        raise NaoEncontrado("Despesa")


async def excluir_despesa(conn: AsyncConnection, despesa_id: UUID) -> None:
    ok = await repo.excluir_despesa(conn, despesa_id)
    if not ok:
        raise NaoEncontrado("Despesa")


# =============================================================================
# Despesas recorrentes (templates)
# =============================================================================


async def listar_recorrentes(
    conn: AsyncConnection,
    incluir_inativas: bool,
) -> list[DespesaRecorrenteResponse]:
    return await repo.listar_recorrentes(conn, incluir_inativas)


async def criar_recorrente(
    conn: AsyncConnection,
    body: DespesaRecorrenteCriar,
    user_id: UUID,
) -> UUID:
    return await repo.criar_recorrente(
        conn,
        categoria=body.categoria,
        valor=body.valor,
        descricao=body.descricao,
        dia_do_mes=body.dia_do_mes,
        ativo_desde=body.ativo_desde,
        user_id=user_id,
    )


async def atualizar_recorrente(
    conn: AsyncConnection,
    recorrente_id: UUID,
    body: DespesaRecorrentePatch,
) -> None:
    ok = await repo.atualizar_recorrente(
        conn,
        recorrente_id,
        categoria=body.categoria,
        valor=body.valor,
        descricao=body.descricao,
        dia_do_mes=body.dia_do_mes,
    )
    if not ok:
        raise NaoEncontrado("Template de despesa recorrente")


async def desativar_recorrente(
    conn: AsyncConnection,
    recorrente_id: UUID,
    inativo_em: date,
) -> None:
    if inativo_em.day != 1:
        raise EntradaInvalida(
            "INATIVO_EM_INVALIDO",
            "inativo_em deve ser o primeiro dia do mês",
            {"campo": "inativo_em"},
        )
    ok = await repo.desativar_recorrente(conn, recorrente_id, inativo_em)
    if not ok:
        raise NaoEncontrado("Template de despesa recorrente")


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
    items, next_cursor = await repo.listar_pagamentos(
        conn, janela, modelo_ids, limit, cursor
    )
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


def obter_url_comprovante(
    *, bucket: str, minio_client: Minio | None, object_key: str
) -> str:
    from barra.core.storage import presigned_get

    if not object_key.startswith("repasses/"):
        raise EntradaInvalida(
            "OBJECT_KEY_INVALIDO",
            "comprovante deve estar sob prefixo 'repasses/'",
        )
    return presigned_get(minio_client, bucket, object_key)
