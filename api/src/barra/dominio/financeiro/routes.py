"""HTTP do Módulo Financeiro (ADR 0011).

Todas as rotas herdam `Depends(get_user)` → `usuario_por_token` em
`core/auth.py:103` rejeita papel ≠ 'fernando' (decisão L).
"""

from __future__ import annotations

import csv
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.core.janela import Janela as _Janela
from barra.core.janela import resolver_janela
from barra.dominio.financeiro import (
    razao_repo,
    razao_service,
    repo,
    service,
    telefonistas_service,
    temporada_service,
)
from barra.dominio.financeiro.razao_repo import Recorte, TemporadaLida
from barra.dominio.financeiro.schemas import (
    AtendimentosSemSnapshotResponse,
    ChavePixCriar,
    ChavePixPatch,
    ChavePixResponse,
    ChavesPixListaResponse,
    ComissaoPagaCriar,
    ComissaoPagaPatch,
    ComissaoPagaResponse,
    ComissoesPagamentosListaResponse,
    ComissoesPorVendedorResponse,
    ComprovanteUploadResponse,
    ComprovanteUrlResponse,
    ConferenciaPorFormaResponse,
    ExtratoDaModeloResponse,
    FechamentoDaTemporadaResponse,
    FecharTemporadaBody,
    FinanceiroResumoResponse,
    FinanceiroSerieResponse,
    LancamentoManualCriar,
    LancamentoManualResponse,
    ModeloQueMandou,
    PapelDaChavePix,
    PreencherRepasseRetroativoBody,
    PreencherRepasseRetroativoResponse,
    ReceitaContextoResponse,
    ReceitasListaResponse,
    RepassePagoCriar,
    RepassePagoPatch,
    RepassePagoResponse,
    RepassesPagamentosListaResponse,
    RepassesPorModeloResponse,
    SugestaoDeChavePixResponse,
    SugestoesDeChavePixListaResponse,
    TelefonistaCriar,
    TelefonistaPatch,
    TelefonistaResponse,
    TelefonistasListaResponse,
    TemporadaCriar,
    TemporadaResponse,
    TemporadasListaResponse,
    VendasRegistradasListaResponse,
    validar_papel_x_dono_da_chave,
)
from barra.dominio.grupo_financeiro import repo as grupo_financeiro_repo
from barra.dominio.grupo_financeiro.comprovante import (
    MINIMO_PARA_SUGERIR,
    ChaveVista,
    montar_pergunta_da_sugestao,
    normalizar_chave,
    sugestoes_de_cadastro,
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
    """Resolve a janela do período. Em "tudo", ancora no 1º registro real da operação
    (escopado pelo filtro de modelo) em vez do antigo piso fixo 2020.

    "1º registro" agora é o mais antigo das DUAS fontes (ADR-0043). Com `atendimentos` vazio — o
    mundo de produção hoje — ancorar só no 1º fechamento devolveria `None` e "tudo" cairia no
    fallback de 2020: seis anos de vão antes da primeira venda anunciada no grupo.
    """
    if periodo != "tudo":
        return resolver_janela(periodo, de, ate)
    pisos = [
        await repo.primeiro_fechamento(conn, modelo_ids),
        await grupo_financeiro_repo.primeira_venda_registrada(conn, modelo_ids),
    ]
    reais = [p for p in pisos if p is not None]
    return resolver_janela(periodo, de, ate, piso_tudo=min(reais) if reais else None)


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
# Vendas registradas (ADR-0043) — a segunda fonte de receita
# =============================================================================


@router.get("/vendas-registradas")
async def get_vendas_registradas(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    incluir_anuladas: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> VendasRegistradasListaResponse:
    """Lista auditavel das Vendas registradas nos Grupos financeiros (spec 0005).

    Somente leitura, e de proposito: a Venda registrada se corrige NO GRUPO, respondendo o recibo
    — quem afirmou o fato foi o humano de la, e um botao de editar aqui criaria uma segunda
    autoridade sobre o mesmo numero, sem rastro no grupo que a anunciou.

    `incluir_anuladas=true` mostra o rastro do que o grupo apagou; o default e a operacao viva.
    """
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await service.montar_vendas_registradas(
        conn,
        periodo=periodo,
        janela=janela,
        modelo_ids=modelo_id,
        incluir_anuladas=incluir_anuladas,
        limit=limit,
        cursor_iso=cursor,
    )


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
# Temporadas, conferência por forma e extrato da modelo (ticket 04)
#
# As duas visões que o gestor nomeou na reunião de 20/08, sem ele precisar entrar em grupo
# nenhum: o "financeiro dos telefonistas" (`/temporadas` + `/conferencia`) e o "financeiro
# individual" (`/modelos/{id}/extrato`). São TODAS de leitura, e nenhuma toca `/atendimentos` —
# o ADR-0043 segue valendo, nenhum Atendimento é fabricado.
#
# ⚠️ Estas rotas leem tabelas da onda `20260820*` (`temporadas`, `deslocamentos_da_venda`,
# `razao_lancamentos_manuais`, `vendas_registradas.bolso`, `grupos_financeiros.papel`), cujas
# migrations estão escritas e NÃO aplicadas. Sem elas o SQL falha — de propósito: não há caminho
# degradado, porque adivinhar coluna inexistente é pior do que responder erro.
# =============================================================================


@router.get("/temporadas")
async def get_temporadas(
    estado: Literal["aberta", "fechada", "cancelada"] | None = "aberta",
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    limit: int = 25,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TemporadasListaResponse:
    """As temporadas com modelo, cidade, período e o saldo com sinal de cada uma.

    `estado=aberta` por default porque é a pergunta do dia ("quem está viajando agora e quanto
    devo a ela"); `estado=null` traz todas, inclusive as fechadas e canceladas.
    """
    return await razao_service.montar_temporadas(
        conn,
        estado=estado,
        modelo_ids=modelo_id,
        limit=max(1, min(limit, razao_service.TEMPORADAS_POR_PAGINA_MAX)),
    )


@router.get("/conferencia")
async def get_conferencia(
    periodo: Periodo = "mes",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ConferenciaPorFormaResponse:
    """Vendido por forma: pix, dinheiro, débito, crédito, link — e `sem_forma` (ADR-0046 §4)."""
    janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
    return await razao_service.montar_conferencia(
        conn, de=janela.de, ate=janela.ate, modelo_ids=modelo_id
    )


@router.get("/modelos/{modelo_id}/extrato")
async def get_extrato_da_modelo(
    modelo_id: UUID,
    de: date | None = None,
    ate: date | None = None,
    temporada_id: UUID | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ExtratoDaModeloResponse:
    """O extrato dela: vendas, comprovantes, cobranças, comissão e o saldo com sinal.

    Sem `de`/`ate`/`temporada_id` é o saldo corrente contínuo — o recorte é opcional porque
    período que "fecha" é justamente o que o domínio proíbe (ADR-0045 §7). Com `temporada_id`, o
    período vem da própria temporada e `de`/`ate` são ignorados, para não existirem dois recortes
    concorrentes na mesma resposta.

    ⚠️ Não mostra comissão de telefonista (ADR-0048): é outra conta, de outra pessoa, e a modelo
    lê esta tela junto com o gestor.
    """
    recorte = Recorte(modelo_id=modelo_id, de=de, ate=ate)
    if temporada_id is not None:
        temporada = await razao_repo.obter_temporada(conn, temporada_id)
        if temporada is None or temporada.modelo_id != modelo_id:
            raise NaoEncontrado("Temporada")
        recorte = Recorte(
            modelo_id=modelo_id,
            de=temporada.data_inicio,
            ate=temporada.data_fim,
            temporada_id=temporada.id,
        )
    extrato = await razao_service.montar_extrato(conn, recorte)
    if extrato is None:
        raise NaoEncontrado("Modelo")
    return extrato


# =============================================================================
# Vale e fechamento da temporada pelo painel (ticket 05)
#
# As duas ações do Financeiro que MOVEM DINHEIRO: lançar o vale adiantado ("tem que pagar uma
# conta de 500 reais, eu adianto") e fechar a temporada registrando o pagamento feito à modelo.
#
# ⚠️ Fechar é ação do PAINEL, nunca frase no grupo (ADR-0045 §8) — a modelo está dentro do grupo,
# e uma frase interpretada errada ali moveria dinheiro de verdade. Estas rotas são a ÚNICA porta
# de fechamento: `agente_financeiro/` não fecha temporada nenhuma.
#
# ⚠️ Fechar não congela cálculo (ADR-0045 §7): grava o pagamento como fato e a temporada como
# marca de rotina. O saldo segue derivado — um comprovante que chegar depois recalcula, e a
# diferença aparece em `saldo.falta_pagar_brl`. Não existe rota de reabertura porque não existe
# congelamento a desfazer.
# =============================================================================


@router.post("/temporadas", status_code=201)
async def post_temporada(
    body: TemporadaCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TemporadaResponse:
    """Abre a temporada da modelo (cidade + datas) — o recorte de que o gestor fala ao pagar."""
    return await temporada_service.abrir_temporada(conn, body, user.id)


@router.get("/temporadas/{temporada_id}/fechamento")
async def get_fechamento_da_temporada(
    temporada_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> FechamentoDaTemporadaResponse:
    """A tela de fechar: saldo, já pago, vales e as PENDÊNCIAS abertas — antes de confirmar.

    Pendência aqui é fila, não trava: o gestor lê e decide fechar assim mesmo (US 32).
    """
    return await temporada_service.montar_fechamento(conn, temporada_id)


@router.post("/temporadas/{temporada_id}/fechamento")
async def post_fechamento_da_temporada(
    temporada_id: UUID,
    body: FecharTemporadaBody,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> FechamentoDaTemporadaResponse:
    """Registra o pagamento feito à modelo e marca a temporada.

    Devolve o MESMO DTO do `GET`, recalculado depois de escrever — é assim que a diferença que
    ainda falta pagar aparece sem ninguém pedir. Chamar de novo, depois de um comprovante
    atrasado mudar a conta, registra a diferença como mais um pagamento da mesma temporada.
    """
    return await temporada_service.registrar_fechamento(conn, temporada_id, body, user.id)


@router.post("/razao/lancamentos", status_code=201)
async def post_lancamento_do_razao(
    body: LancamentoManualCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> LancamentoManualResponse:
    """Lança o vale adiantado (ou o ajuste) no razão da modelo, com origem `painel`.

    ⚠️ "Ficou com ela", dito sobre uma venda, NÃO é vale (ADR-0047 §5): é a venda com
    `bolso = 'dela'` mais a ausência da transferência. Lançar um vale além disso contaria o mesmo
    dinheiro duas vezes.
    """
    return await temporada_service.lancar_no_razao(conn, body, user.id)


@router.post("/razao/lancamentos/{lancamento_id}/anular")
async def post_anular_lancamento_do_razao(
    lancamento_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> LancamentoManualResponse:
    """Estorna o vale digitado errado. Estado com rastro, nunca DELETE — e idempotente."""
    return await temporada_service.anular_lancamento(conn, lancamento_id)


# =============================================================================
# Export da temporada em planilha (ticket 18, spec 0006 US 46)
#
# A planilha-espelho prometida ao gestor: *"é como se fosse um extrato bancário — no final do mês
# eu vou olhar o sistema e vou olhar pra planilha e tem que estar se falando igual"*. É o
# substituto barato do Google Sheets sincronizado, que a spec 0006 mandou para fora de escopo: sem
# OAuth, sem sincronização bidirecional e sem uma segunda fonte de verdade capaz de divergir.
#
# ⚠️ **Os números saem das MESMAS funções que montam a tela** — `razao_service.montar_extrato` e
# `razao_service.montar_temporadas` —, nunca de um SQL paralelo. É o único jeito de "os números do
# arquivo batem com os da tela" ser verdade por construção em vez de por coincidência: duas
# consultas diferentes para a mesma pergunta divergiriam no primeiro caso de borda (venda sem
# snapshot, comprovante com sobra, deslocamento de efeito zero) e ninguém saberia qual está certa.
#
# ⚠️ **Nada é congelado aqui.** A planilha é uma FOTO do que o razão apura no instante do download
# (ADR-0045 §7) — comprovante que chegar depois muda o próximo arquivo, e é por isso que toda
# planilha carrega a linha "Gerado em".
#
# ⚠️ Também **não** carrega comissão de telefonista (ADR-0048): o extrato é da modelo, e ela o lê
# junto com o gestor.
#
# Formato: CSV `;` + BOM UTF-8, o mesmo de `/receitas/export` — Excel BR reconhece separador e
# acentuação sem assistente de importação, e o detector do Google Sheets acerta o `;` porque toda
# linha é preenchida até a mesma largura (planilha retangular, sem linha curta para confundi-lo).
# XLSX exigiria dependência nova (`openpyxl`) para ganhar formatação que este arquivo não usa.
# =============================================================================

# Os rótulos são os da TELA (`interface/src/tipos/razao.ts`): a planilha é lida ao lado dela, e
# duas palavras diferentes para a mesma linha ("comissao" aqui, "Comissão" lá) é exatamente o tipo
# de divergência que a US 46 existe para eliminar.
_ROTULO_DA_LINHA: dict[str, str] = {
    "venda": "Venda no bolso dela",
    "comissao": "Comissão",
    "transferencia": "Transferência para a casa",
    "cobranca": "Cobrança da agência",
    "vale": "Vale adiantado",
    "ajuste": "Ajuste manual",
    "deslocamento": "Deslocamento",
}

_ROTULO_DA_ORIGEM: dict[str, str] = {
    "venda_registrada": "Venda registrada",
    "comprovante_do_grupo": "Comprovante do grupo",
    "cobranca_da_agencia": "Cobrança da agência",
    "razao_lancamento_manual": "Lançamento do painel",
    "deslocamento_da_venda": "Deslocamento da venda",
}

_ROTULO_DA_FORMA: dict[str, str] = {
    "pix": "Pix",
    "dinheiro": "Dinheiro",
    "debito": "Débito",
    "credito": "Crédito",
    "link": "Link",
    "sem_forma": "Sem forma",
}

_ROTULO_DA_SINALIZACAO: dict[str, str] = {
    "venda_sem_forma_de_pagamento": "venda sem forma de pagamento",
    "venda_com_bolso_nao_dito": "venda sem o bolso dito (contada como dela)",
    "cobranca_em_aberto": "cobrança da agência em aberto",
    "comprovante_retido": "comprovante retido (não classificado ou ilegível)",
    "venda_sem_snapshot_de_comissao": "venda sem percentual congelado — comissão não creditada",
    "comprovante_com_sobra": "comprovante com sobra a favor dela",
}

_COLUNAS_DA_LISTA = [
    "Modelo",
    "Cidade",
    "Início",
    "Fim",
    "Estado",
    "Vendas",
    "Vendido (R$)",
    "Débitos (R$)",
    "Créditos (R$)",
    "Saldo (R$)",
    "A casa deve (R$)",
    "Ela deve (R$)",
    "Já pago (R$)",
    "Falta pagar (R$)",
    "Pendências",
    "Fechada em",
]


@router.get("/temporadas/export")
async def export_temporadas(
    estado: Literal["aberta", "fechada", "cancelada"] | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    periodo: Periodo | None = None,
    de: date | None = None,
    ate: date | None = None,
    detalhado: bool = False,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> StreamingResponse:
    """Todas as temporadas do filtro numa planilha: uma linha por temporada, como na tela.

    `estado` nulo traz todas (abertas, fechadas e canceladas) — default aqui e NÃO em
    `GET /temporadas`, porque exportar é conferir o mês inteiro e a tela é a pergunta do dia.

    `periodo` (com `de`/`ate` em `custom`) é opcional: sem ele não há recorte de tempo nenhum e o
    arquivo espelha a lista exatamente. Com ele ficam as temporadas que **encostam** na janela —
    sobreposição, não contenção: uma viagem de 28/07 a 03/08 pertence ao fechamento de agosto
    tanto quanto ao de julho, e exigir que ela caiba inteira dentro do mês a sumiria dos dois.

    `detalhado=true` acrescenta, abaixo da lista, o extrato completo de cada temporada — o mesmo
    bloco de `GET /temporadas/{id}/export`. É uma leitura de razão por temporada, então fica de
    fora por default.
    """
    lista = await razao_service.montar_temporadas(
        conn,
        estado=estado,
        modelo_ids=modelo_id,
        limit=razao_service.TEMPORADAS_POR_PAGINA_MAX,
    )
    items = list(lista.items)

    rotulo = "todas"
    if periodo is not None:
        janela = await _janela_periodo(conn, periodo, de, ate, modelo_id)
        items = [t for t in items if t.data_fim >= janela.de and t.data_inicio <= janela.ate]
        rotulo = _periodo_label(janela)

    linhas: list[list[Any]] = [
        ["Temporadas — financeiro dos telefonistas"],
        ["Gerado em", _agora_iso()],
        ["Estado", estado or "todos"],
        ["Período", rotulo],
        [
            "Observação",
            "A temporada não congela cálculo: este arquivo é a foto do saldo no instante do download.",
        ],
        [],
        _COLUNAS_DA_LISTA,
    ]
    for t in items:
        linhas.append(
            [
                t.modelo_nome,
                t.cidade,
                t.data_inicio.isoformat(),
                t.data_fim.isoformat(),
                t.estado,
                t.vendas,
                _fmt_br(t.vendido_brl),
                _fmt_br(t.saldo.debitos_brl),
                _fmt_br(t.saldo.creditos_brl),
                _fmt_br(t.saldo.saldo_brl),
                _fmt_br(t.saldo.a_casa_deve_brl),
                _fmt_br(t.saldo.ela_deve_brl),
                _fmt_br(t.saldo.pago_brl),
                _fmt_br(t.saldo.falta_pagar_brl),
                t.pendencias,
                t.fechada_em[:10] if t.fechada_em else "",
            ]
        )
    # Os três totais são os MESMOS do cabeçalho da lista, pela mesma expressão de
    # `razao_service.montar_temporadas` — com `periodo`, recalculados sobre o que sobrou do
    # filtro, que é justamente o que o arquivo contém.
    linhas.append(
        [
            "Total",
            "",
            "",
            "",
            "",
            sum(t.vendas for t in items),
            _fmt_br(round(sum(t.vendido_brl for t in items), 2)),
            "",
            "",
            "",
            _fmt_br(round(sum(t.saldo.a_casa_deve_brl for t in items), 2)),
            _fmt_br(round(sum(t.saldo.ela_deve_brl for t in items), 2)),
            "",
            _fmt_br(round(sum(t.saldo.falta_pagar_brl for t in items), 2)),
            sum(t.pendencias for t in items),
            "",
        ]
    )

    if detalhado:
        for t in items:
            lida = await razao_repo.obter_temporada(conn, t.id)
            if lida is None:  # pragma: no cover - a lista acabou de lê-las
                continue
            linhas.append([])
            linhas.extend(await _bloco_da_temporada(conn, lida))

    return _planilha_response(f"temporadas_{_slug(rotulo)}.csv", linhas)


@router.get("/temporadas/{temporada_id}/export")
async def export_temporada(
    temporada_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> StreamingResponse:
    """O extrato bancário de UMA temporada: lançamentos, conferência, pagamentos e o saldo.

    Cada lançamento vem com a origem colada e um saldo acumulado ao lado, para o gestor conferir
    linha a linha contra o controle dele — que é literalmente o pedido da US 46.
    """
    temporada = await razao_repo.obter_temporada(conn, temporada_id)
    if temporada is None:
        raise NaoEncontrado("Temporada")
    linhas = await _bloco_da_temporada(conn, temporada)
    nome = "_".join(
        [
            "temporada",
            _slug(temporada.modelo_nome),
            _slug(temporada.cidade),
            temporada.data_inicio.isoformat(),
        ]
    )
    return _planilha_response(f"{nome}.csv", linhas)


async def _bloco_da_temporada(
    conn: AsyncConnection[Any], temporada: TemporadaLida
) -> list[list[Any]]:
    """O extrato de uma temporada em linhas de planilha, na ordem em que a tela o conta.

    Sai do `montar_extrato` recortado pela própria temporada — o mesmo objeto que a ficha da
    modelo e o diálogo de fechamento leem. Nenhuma soma nova nasce aqui: os totais são os campos
    de `SaldoDoRazao`, e o único cálculo é o saldo ACUMULADO linha a linha, feito sobre valores já
    arredondados a centavo, que por isso termina exatamente em `saldo_brl`.
    """
    extrato = await razao_service.montar_extrato(
        conn,
        Recorte(
            modelo_id=temporada.modelo_id,
            de=temporada.data_inicio,
            ate=temporada.data_fim,
            temporada_id=temporada.id,
        ),
    )
    if extrato is None:  # pragma: no cover - a FK da temporada garante a modelo
        raise NaoEncontrado("Modelo")

    saldo = extrato.saldo
    linhas: list[list[Any]] = [
        ["Extrato da temporada", f"{temporada.modelo_nome} — {temporada.cidade}"],
        ["Gerado em", _agora_iso()],
        ["Modelo", temporada.modelo_nome],
        ["Cidade", temporada.cidade],
        ["Período", f"{temporada.data_inicio.isoformat()} a {temporada.data_fim.isoformat()}"],
        ["Estado", temporada.estado],
        ["Fechada em", temporada.fechada_em.date().isoformat() if temporada.fechada_em else ""],
        ["Percentual de repasse (%)", _fmt_br(extrato.percentual_repasse)],
        ["Observação", temporada.observacao or ""],
        [],
        ["Lançamentos"],
        [
            "Data",
            "Tipo",
            "Origem",
            "Descrição",
            "Débito (R$)",
            "Crédito (R$)",
            "Saldo acumulado (R$)",
        ],
    ]

    acumulado = 0.0
    for linha in extrato.linhas:
        acumulado = round(acumulado + linha.credito_brl - linha.debito_brl, 2)
        linhas.append(
            [
                linha.data.isoformat(),
                _ROTULO_DA_LINHA.get(linha.tipo, linha.tipo),
                _ROTULO_DA_ORIGEM.get(linha.origem, linha.origem),
                linha.descricao or "",
                _fmt_br(linha.debito_brl) if linha.debito_brl else "",
                _fmt_br(linha.credito_brl) if linha.credito_brl else "",
                _fmt_br(acumulado),
            ]
        )
    linhas.append(
        [
            "",
            "",
            "",
            "Totais",
            _fmt_br(saldo.debitos_brl),
            _fmt_br(saldo.creditos_brl),
            _fmt_br(saldo.saldo_brl),
        ]
    )

    linhas.append([])
    linhas.append(["Conferência por forma de pagamento"])
    linhas.append(["Forma", "Vendas", "Valor (R$)"])
    for forma in extrato.conferencia.formas:
        linhas.append(
            [
                _ROTULO_DA_FORMA.get(forma.forma, forma.forma),
                forma.vendas,
                _fmt_br(forma.valor_brl),
            ]
        )
    linhas.append(["Total", extrato.conferencia.vendas, _fmt_br(extrato.conferencia.vendido_brl)])

    linhas.append([])
    linhas.append(["Pagamentos já feitos à modelo"])
    linhas.append(["Data", "Valor (R$)", "Forma", "Observação"])
    for pagamento in extrato.pagamentos:
        linhas.append(
            [
                pagamento.data.isoformat(),
                _fmt_br(pagamento.valor_brl),
                pagamento.forma_pagamento,
                pagamento.observacao or "",
            ]
        )
    linhas.append(["Total pago", _fmt_br(saldo.pago_brl)])

    # O saldo NÃO inclui o já pago (ADR-0045 §7): ele fica ao lado, e "falta pagar" é a diferença.
    linhas.append([])
    linhas.append(["Saldo"])
    linhas.append(["Débitos dela (dinheiro da casa que ficou com ela)", _fmt_br(saldo.debitos_brl)])
    linhas.append(["Créditos dela (comissão e o que ela transferiu)", _fmt_br(saldo.creditos_brl)])
    linhas.append(
        [
            "Saldo (positivo: a casa deve a ela / negativo: ela deve a casa)",
            _fmt_br(saldo.saldo_brl),
        ]
    )
    linhas.append(["A casa deve a ela", _fmt_br(saldo.a_casa_deve_brl)])
    linhas.append(["Ela deve à casa", _fmt_br(saldo.ela_deve_brl)])
    linhas.append(["Já pago", _fmt_br(saldo.pago_brl)])
    linhas.append(["Falta pagar", _fmt_br(saldo.falta_pagar_brl)])

    # Pendência é fila, não erro (ADR-0047 §3) — vai para a planilha pelo mesmo motivo que vai
    # para a tela de fechamento: para ser lida antes de o gestor bater o martelo.
    for titulo, itens in (
        ("Pendências abertas", extrato.pendencias),
        ("Divergências", extrato.divergencias),
    ):
        linhas.append([])
        linhas.append([titulo])
        linhas.append(["Tipo", "Quantidade", "Valor (R$)"])
        if not itens:
            linhas.append(["nenhuma", 0, _fmt_br(0.0)])
        for item in itens:
            linhas.append(
                [
                    _ROTULO_DA_SINALIZACAO.get(item.tipo, item.tipo),
                    item.quantidade,
                    _fmt_br(item.valor_brl),
                ]
            )
    return linhas


# =============================================================================
# Telefonistas: o cadastro em que o dono mexe no percentual (ticket 22, ADR-0048)
#
# "Telefonista" é o **Vendedor** dito no vocabulário do grupo financeiro — a tabela continua sendo
# `barravips.vendedores`, e não existe entidade nova. O CRUD básico (nome/nível/ativo) já tinha
# porta em `/v1/vendedores`; estas rotas existem porque o número da comissão passou a ser DO
# VENDEDOR (ADR-0048 §1) e o dono pediu a aba para poder alterá-lo — e porque ele é assunto do
# Financeiro, não do cadastro genérico.
#
# ⚠️ Sem snapshot (§6): mudar o percentual reprojeta a comissão inteira, inclusive a de vendas
# passadas. É o oposto do `percentual_repasse_snapshot` da modelo, que é negociado com ela.
#
# ⚠️ A faixa 1-10% é operacional, não invariante: quem avisa que 12% saiu do usual é a tela; o
# CHECK do banco e a validação aqui são 0..100.
#
# ⚠️ `percentual_comissao` e `whatsapp_jid` nascem em
# `infra/sql/20260820126000_vendedores_percentual_e_whatsapp_jid.sql`, escrita e NÃO aplicada.
# Sem ela estas rotas respondem erro de SQL, como as de temporada — não há caminho degradado.
# =============================================================================


@router.get("/telefonistas")
async def get_telefonistas(
    incluir_inativos: bool = False,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TelefonistasListaResponse:
    """Os telefonistas com o percentual de comissão de cada um. Ativos primeiro."""
    return await telefonistas_service.listar_telefonistas(conn, incluir_inativos=incluir_inativos)


@router.post("/telefonistas", status_code=201)
async def post_telefonista(
    body: TelefonistaCriar,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TelefonistaResponse:
    """Cadastra o telefonista. Sem percentual no corpo, entra com 7% — a referência do dono."""
    return await telefonistas_service.criar_telefonista(conn, body, user.id)


@router.patch("/telefonistas/{telefonista_id}")
async def patch_telefonista(
    telefonista_id: UUID,
    body: TelefonistaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> TelefonistaResponse:
    """Altera nome, percentual, ativo ou o JID. `ativo=false` desativa; não existe DELETE."""
    return await telefonistas_service.atualizar_telefonista(conn, telefonista_id, body)


# =============================================================================
# Chaves Pix — o registro de "de quem e esta chave" (ADR-0049, ticket 02)
#
# A aba onde o dono classifica. Ela existe porque a pergunta que a operacao faz diante de um
# comprovante tem QUATRO respostas e o sistema so sabia dar duas: "esta na lista da casa" ou "nao
# esta". O "nao esta" engolia a chave da PROPRIA MODELO — que resolve o bolso da venda (ADR-0047
# §2) — junto com a chave de um terceiro qualquer, e o aviso disparava igual nos dois ate o gestor
# aprender a ignora-lo.
#
# ⚠️ Nada aqui trava fluxo nenhum. O registro e closed-world para LEITURA (chave que nao esta aqui
# e `desconhecida`), nunca para bloqueio: comprovante com destino fora do registro continua sendo
# processado, so muda o que o gestor ve.
#
# ⚠️ Inativar nunca deletar. Nao existe DELETE nesta aba: chave que saiu de uso continua
# explicando comprovante antigo que aponta para ela.
#
# ⚠️ `modelos.chave_pix` NAO e este registro (ADR-0049 §3) e nao aparece aqui. Ela e a chave
# preferida da modelo para RECEBER REPASSE — destino de pagamento. Somar os dois sentidos num
# campo so faz um repasse da casa PARA ela ser lido como uma venda DELA, e o razao dobra.
# =============================================================================


def _chave_response(lida: grupo_financeiro_repo.ChavePixCadastrada) -> ChavePixResponse:
    return ChavePixResponse(
        id=lida.id,
        chave=lida.chave,
        chave_normalizada=lida.chave_normalizada,
        papel=lida.papel,
        modelo_id=lida.modelo_id,
        modelo_nome=lida.modelo_nome,
        vendedor_id=lida.vendedor_id,
        vendedor_nome=lida.vendedor_nome,
        titular=lida.titular,
        descricao=lida.descricao,
        padrao=lida.padrao,
        ativo=lida.ativo,
    )


def _texto_ou_none(bruto: str | None) -> str | None:
    """Espaco em volta sai; string vazia vira `None` — campo em branco no formulario nao e dado."""
    if bruto is None:
        return None
    return bruto.strip() or None


def _traduzir_chave_duplicada(exc: UniqueViolation) -> ConflitoEstado | UniqueViolation:
    if (getattr(exc.diag, "constraint_name", None) or "") == (
        "chaves_pix_conhecidas_chave_normalizada_key"
    ):
        return ConflitoEstado(
            "Esta chave Pix ja esta cadastrada — inclusive se foi digitada com outra pontuacao."
        )
    return exc


@router.get("/chaves-pix")
async def get_chaves_pix(
    incluir_inativas: bool = False,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ChavesPixListaResponse:
    """O registro de chaves, a padrao da casa primeiro. `incluir_inativas` traz as aposentadas."""
    itens = await grupo_financeiro_repo.listar_chaves_pix(conn, incluir_inativas=incluir_inativas)
    return ChavesPixListaResponse(items=[_chave_response(c) for c in itens])


def _sugestao_response(vista: ChaveVista) -> SugestaoDeChavePixResponse:
    uma = vista.de_uma_modelo_so
    return SugestaoDeChavePixResponse(
        chave=vista.chave,
        chave_normalizada=normalizar_chave(vista.chave),
        pergunta=montar_pergunta_da_sugestao(vista),
        vezes=vista.vezes,
        primeiro_em=vista.primeiro_em,
        ultimo_em=vista.ultimo_em,
        valor_total_brl=float(vista.valor_total),
        titulares=list(vista.titulares),
        modelos=[ModeloQueMandou(id=q.modelo_id, nome=q.nome) for q in vista.quem_mandou],
        modelo_id_sugerido=uma.modelo_id if uma is not None else None,
    )


@router.get("/chaves-pix/sugestoes")
async def get_sugestoes_de_chave_pix(
    dias: Annotated[int, Query(ge=1, le=730)] = 90,
    minimo: Annotated[int, Query(ge=2, le=100)] = MINIMO_PARA_SUGERIR,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> SugestoesDeChavePixListaResponse:
    """A fila de "de quem é esta chave?" — destinos recorrentes que o cadastro ainda não explica.

    ⚠️ **Somente leitura, e isso é o desenho.** Sugestão nunca vira cadastro sozinha (ADR-0049 §5):
    esta rota não escreve nada, e não existe rota que aceite uma sugestão em bloco. O gesto que
    resolve é o `POST /chaves-pix` de sempre, com um humano escolhendo o papel — porque o sistema
    honestamente não sabe se aquela chave é a conta nova da modelo, um fornecedor ou um golpe.

    Não há tabela de sugestões: a fila é derivada de `comprovantes_do_grupo`. Por isso a linha some
    no instante em que a chave é cadastrada, sem nenhuma invalidação — o critério "classificar pelo
    painel some com a sugestão e passa a valer na hora" cai de graça.

    `minimo=2` é o corte do ticket: a PRIMEIRA aparição já teve o ⚠️ no grupo, e a fila existe para
    a chave que **voltou**. `dias` recorta a janela — sem ela, uma chave aposentada há um ano
    continuaria pedindo classificação para sempre.
    """
    # UTC, e nao BRT: a janela e de 90 dias e um dia de fuso nao muda quem entra nela. O que
    # importa e ser deterministico — `date.today()` depende do fuso do processo.
    desde = datetime.now(UTC).date() - timedelta(days=dias)
    vistas = await grupo_financeiro_repo.destinos_vistos_em_comprovantes(conn, desde=desde)
    registro = await grupo_financeiro_repo.registro_de_chaves(conn)
    fila = sugestoes_de_cadastro(vistas, registro, minimo=minimo)
    return SugestoesDeChavePixListaResponse(items=[_sugestao_response(v) for v in fila])


@router.post("/chaves-pix", status_code=201)
async def post_chave_pix(
    body: ChavePixCriar,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ChavePixResponse:
    """Cadastra a chave com o papel declarado. `padrao=true` (so em `casa`) move a padrao.

    409 quando a chave ja existe — inclusive digitada com outra pontuacao, porque o UNIQUE e sobre
    a forma normalizada, que e a mesma com que o OCR compara.
    """
    try:
        chave_id = await grupo_financeiro_repo.criar_chave_pix(
            conn,
            chave=body.chave.strip(),
            papel=body.papel,
            modelo_id=body.modelo_id,
            vendedor_id=body.vendedor_id,
            titular=_texto_ou_none(body.titular),
            descricao=_texto_ou_none(body.descricao),
        )
    except UniqueViolation as exc:
        raise _traduzir_chave_duplicada(exc) from exc
    if body.padrao:
        await grupo_financeiro_repo.definir_chave_pix_padrao(conn, chave_id)
    criada = await grupo_financeiro_repo.obter_chave_pix(conn, chave_id)
    assert criada is not None
    return _chave_response(criada)


@router.patch("/chaves-pix/{chave_id}")
async def patch_chave_pix(
    chave_id: UUID,
    body: ChavePixPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> ChavePixResponse:
    """Classifica, marca a padrao e inativa — os tres gestos da aba, num PATCH parcial.

    ⚠️ **Papel e dono viajam juntos.** Mandar `papel` reescreve `modelo_id`/`vendedor_id` com o que
    veio no MESMO corpo (ausente = nulo). Sem essa regra, promover a chave de uma modelo a `casa`
    deixaria o `modelo_id` antigo para tras, a linha teria dois donos discordando e a constraint
    do banco estouraria um 500 sem explicacao.

    ⚠️ **A ordem de `padrao` e `ativo` importa.** `padrao=false` e a inativacao da propria padrao
    limpam a marca ANTES do UPDATE, porque o CHECK exige que a padrao esteja viva; `padrao=true`
    marca DEPOIS, porque o indice unico so admite uma e a antiga precisa ter saido.
    """
    atual = await grupo_financeiro_repo.obter_chave_pix(conn, chave_id)
    if atual is None:
        raise NaoEncontrado("Chave Pix")

    campos: dict[str, Any] = body.model_dump(exclude_unset=True)
    padrao = campos.pop("padrao", None)

    if "papel" in campos:
        papel: PapelDaChavePix = campos["papel"]
        campos["modelo_id"] = body.modelo_id
        campos["vendedor_id"] = body.vendedor_id
    else:
        papel = atual.papel
        modelo_id = campos.get("modelo_id", atual.modelo_id)
        vendedor_id = campos.get("vendedor_id", atual.vendedor_id)
        try:
            validar_papel_x_dono_da_chave(papel, modelo_id, vendedor_id)
        except ValueError as exc:
            raise EntradaInvalida(str(exc)) from exc

    if "chave" in campos and campos["chave"] is not None:
        campos["chave"] = campos["chave"].strip()
    for texto in ("titular", "descricao"):
        if texto in campos:
            campos[texto] = _texto_ou_none(campos[texto])
    # `None` so e apagamento nas colunas nullable. Em `chave`, `papel` e `ativo` ele e lixo do
    # cliente, e grava-lo violaria o NOT NULL.
    campos = {
        coluna: valor
        for coluna, valor in campos.items()
        if valor is not None or coluna in ("titular", "descricao", "modelo_id", "vendedor_id")
    }

    # ⚠️ Sempre guardado por `atual.padrao`: `definir_chave_pix_padrao(None)` limpa a marca do
    # BANCO INTEIRO, e um `padrao=false` mandado numa chave que nunca foi padrao apagaria a marca
    # de OUTRA linha, calada — a tela de quem estivesse olhando so veria a estrela sumir.
    virou_inativa = campos.get("ativo") is False
    if atual.padrao and (padrao is False or virou_inativa):
        await grupo_financeiro_repo.definir_chave_pix_padrao(conn, None)

    if campos:
        try:
            existe = await grupo_financeiro_repo.atualizar_chave_pix(conn, chave_id, campos)
        except UniqueViolation as exc:
            raise _traduzir_chave_duplicada(exc) from exc
        if not existe:
            raise NaoEncontrado("Chave Pix")

    if padrao is True:
        if papel != "casa":
            raise EntradaInvalida("So chave da casa pode ser a padrao.")
        if campos.get("ativo") is False or (not atual.ativo and "ativo" not in campos):
            raise EntradaInvalida("Chave inativa nao pode ser a padrao da casa.")
        await grupo_financeiro_repo.definir_chave_pix_padrao(conn, chave_id)

    atualizada = await grupo_financeiro_repo.obter_chave_pix(conn, chave_id)
    assert atualizada is not None
    return _chave_response(atualizada)


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


def _agora_iso() -> str:
    """O carimbo de "Gerado em". A planilha é foto, não snapshot gravado (ADR-0045 §7)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(texto: str) -> str:
    """Nome de arquivo ASCII. `Content-Disposition` sem RFC 5987 não carrega acento com segurança,
    e "Balneário" viraria mojibake no nome do download em parte dos navegadores."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpo = "".join(c if c.isalnum() else "-" for c in sem_acento.lower())
    return "-".join(p for p in limpo.split("-") if p) or "sem-nome"


def _planilha_response(filename: str, linhas: list[list[Any]]) -> StreamingResponse:
    """Planilha RETANGULAR em CSV: toda linha é preenchida até a largura máxima do arquivo.

    O preenchimento não é estética. O detector de separador do Google Sheets olha as primeiras
    linhas: com um título de uma célula só no topo, ele às vezes decide que o arquivo tem uma
    coluna e joga tudo numa. Padding tira a ambiguidade e o arquivo abre nos dois programas sem
    ninguém escolher separador na mão — que é o quarto critério do ticket.

    Mesma convenção de `_csv_response`: BOM UTF-8 (Excel BR reconhece a acentuação) e `;`.
    """
    largura = max((len(linha) for linha in linhas), default=1)

    def _stream() -> Iterator[bytes]:
        buf = StringIO()
        buf.write("\ufeff")
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        for linha in linhas:
            writer.writerow([*linha, *([""] * (largura - len(linha)))])
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate()

    return StreamingResponse(
        _stream(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
