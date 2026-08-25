"""Montagem das duas telas do ticket 04, sobre `razao.apurar` e `razao_repo`.

Divisão: `razao_repo` lê o banco e devolve `Lancamento`; `razao.apurar` (puro, em
`dominio/grupo_financeiro/razao.py`) soma; aqui só se monta o DTO. Nenhuma conta de dinheiro
nasce neste arquivo — a única aritmética é `saldo - pago`, que é a frase do ADR-0045 §7 ("a
diferença contra o já pago aparece como 'falta pagar R$ X'"), e a soma de `pago`.

⚠️ **Comissão de telefonista não aparece em lugar nenhum daqui** (ADR-0048, última consequência):
o extrato é da modelo, ela lê a tela junto com o gestor, e a comissão do vendedor é outra conta,
de outra pessoa. Quem for somá-la (ticket 22) faz isso noutra rota.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.dominio.financeiro import razao_repo
from barra.dominio.financeiro.razao_repo import (
    LancamentoLido,
    PagamentoLido,
    Recorte,
    TemporadaLida,
)
from barra.dominio.financeiro.schemas import (
    ConferenciaFormaLinha,
    ConferenciaPorFormaResponse,
    ExtratoDaModeloResponse,
    LinhaDoExtrato,
    PagamentoDaModeloLinha,
    SaldoDoRazao,
    SinalizacaoDoExtrato,
    TemporadaLinha,
    TemporadasListaResponse,
)
from barra.dominio.grupo_financeiro.razao import ZERO, Razao, apurar

TEMPORADAS_POR_PAGINA_MAX = 100


async def montar_extrato(
    conn: AsyncConnection[Any], recorte: Recorte
) -> ExtratoDaModeloResponse | None:
    """O "financeiro individual" da ficha da modelo. `None` = modelo inexistente."""
    identidade = await razao_repo.identidade_da_modelo(conn, recorte.modelo_id)
    if identidade is None:
        return None
    nome, percentual = identidade

    temporada = (
        await razao_repo.obter_temporada(conn, recorte.temporada_id)
        if recorte.temporada_id is not None
        else None
    )

    lidos = await razao_repo.lancamentos_do_razao(conn, recorte)
    pagamentos = await razao_repo.pagamentos_da_modelo(conn, recorte)
    razao = apurar(lido.lancamento for lido in lidos)

    return ExtratoDaModeloResponse(
        modelo_id=recorte.modelo_id,
        modelo_nome=nome,
        percentual_repasse=_brl(percentual) if percentual is not None else None,
        de=recorte.de,
        ate=recorte.ate,
        temporada_id=recorte.temporada_id,
        temporada_cidade=temporada.cidade if temporada else None,
        temporada_estado=temporada.estado if temporada else None,
        saldo=_saldo(razao, pagamentos),
        conferencia=await montar_conferencia(
            conn, de=recorte.de, ate=recorte.ate, modelo_ids=[recorte.modelo_id]
        ),
        linhas=_linhas(lidos),
        pagamentos=[
            PagamentoDaModeloLinha(
                id=pago.id,
                data=pago.data,
                valor_brl=_brl(pago.valor),
                forma_pagamento=pago.forma_pagamento,
                observacao=pago.observacao,
                temporada_id=pago.temporada_id,
            )
            for pago in pagamentos
        ],
        pendencias=[
            SinalizacaoDoExtrato(
                tipo=item.tipo, quantidade=item.quantidade, valor_brl=_brl(item.valor)
            )
            for item in await razao_repo.pendencias_do_extrato(conn, recorte)
        ],
        divergencias=[
            SinalizacaoDoExtrato(
                tipo=item.tipo, quantidade=item.quantidade, valor_brl=_brl(item.valor)
            )
            for item in await razao_repo.divergencias_do_extrato(conn, recorte)
        ],
    )


async def montar_conferencia(
    conn: AsyncConnection[Any],
    *,
    de: date | None,
    ate: date | None,
    modelo_ids: list[UUID] | None,
) -> ConferenciaPorFormaResponse:
    """A conferência por forma de pagamento e o vendido que ela soma."""
    totais = await razao_repo.conferencia_por_forma(conn, de=de, ate=ate, modelo_ids=modelo_ids)
    return ConferenciaPorFormaResponse(
        de=de,
        ate=ate,
        formas=[
            ConferenciaFormaLinha(
                forma=total.forma, vendas=total.vendas, valor_brl=_brl(total.valor)
            )
            for total in totais
        ],
        vendas=sum(total.vendas for total in totais),
        vendido_brl=_brl(sum((total.valor for total in totais), ZERO)),
    )


async def montar_temporadas(
    conn: AsyncConnection[Any],
    *,
    estado: str | None,
    modelo_ids: list[UUID] | None,
    limit: int,
) -> TemporadasListaResponse:
    """O "financeiro dos telefonistas": as temporadas com o saldo de cada modelo num lugar só.

    O saldo de cada linha é recalculado a cada leitura, de propósito: a Temporada não guarda
    saldo, fechamento nem snapshot (ADR-0045 §7), e um comprovante que chegar depois de "fechada"
    tem que mudar o número aqui sem ninguém reabrir nada. O preço é uma leitura por temporada —
    aceitável na escala da operação (poucas modelos), e é por isso que `limit` é pequeno.
    """
    temporadas = await razao_repo.listar_temporadas(
        conn, estado=estado, modelo_ids=modelo_ids, limit=limit
    )
    items = [await _linha_da_temporada(conn, temporada) for temporada in temporadas]
    return TemporadasListaResponse(
        items=items,
        total_a_casa_deve_brl=round(sum(item.saldo.a_casa_deve_brl for item in items), 2),
        total_ela_deve_brl=round(sum(item.saldo.ela_deve_brl for item in items), 2),
        total_falta_pagar_brl=round(sum(item.saldo.falta_pagar_brl for item in items), 2),
    )


async def _linha_da_temporada(
    conn: AsyncConnection[Any], temporada: TemporadaLida
) -> TemporadaLinha:
    recorte = Recorte(
        modelo_id=temporada.modelo_id,
        de=temporada.data_inicio,
        ate=temporada.data_fim,
        temporada_id=temporada.id,
    )
    lidos = await razao_repo.lancamentos_do_razao(conn, recorte)
    pagamentos = await razao_repo.pagamentos_da_modelo(conn, recorte)
    conferencia = await montar_conferencia(
        conn, de=recorte.de, ate=recorte.ate, modelo_ids=[temporada.modelo_id]
    )
    pendencias = await razao_repo.pendencias_do_extrato(conn, recorte)
    return TemporadaLinha(
        id=temporada.id,
        modelo_id=temporada.modelo_id,
        modelo_nome=temporada.modelo_nome,
        cidade=temporada.cidade,
        data_inicio=temporada.data_inicio,
        data_fim=temporada.data_fim,
        estado=temporada.estado,
        observacao=temporada.observacao,
        fechada_em=temporada.fechada_em.isoformat() if temporada.fechada_em else None,
        vendas=conferencia.vendas,
        vendido_brl=conferencia.vendido_brl,
        saldo=_saldo(apurar(lido.lancamento for lido in lidos), pagamentos),
        pendencias=sum(item.quantidade for item in pendencias),
    )


def _saldo(razao: Razao, pagamentos: list[PagamentoLido]) -> SaldoDoRazao:
    pago = sum((pagamento.valor for pagamento in pagamentos), ZERO)
    return SaldoDoRazao(
        debitos_brl=_brl(razao.debitos),
        creditos_brl=_brl(razao.creditos),
        saldo_brl=_brl(razao.saldo),
        a_casa_deve_brl=_brl(razao.a_casa_deve),
        ela_deve_brl=_brl(razao.ela_deve),
        pago_brl=_brl(pago),
        falta_pagar_brl=_brl(razao.saldo - pago),
    )


def _linhas(lidos: list[LancamentoLido]) -> list[LinhaDoExtrato]:
    """Uma linha do extrato por linha do razão, com a procedência colada de volta.

    `apurar` roda uma vez por lançamento só para saber QUAIS linhas ele gerou (uma venda no bolso
    dela gera duas; um deslocamento de efeito zero gera nenhuma). É a mesma função pura que soma o
    todo — somar por partes e somar tudo dá o mesmo número, porque não há arredondamento entre
    lançamentos.
    """
    linhas: list[LinhaDoExtrato] = []
    for lido in lidos:
        for linha in apurar([lido.lancamento]).linhas:
            linhas.append(
                LinhaDoExtrato(
                    tipo=lido.rotulo or linha.tipo,
                    origem=lido.origem,
                    origem_id=lido.origem_id,
                    data=lido.data,
                    descricao=lido.descricao,
                    debito_brl=_brl(linha.debito),
                    credito_brl=_brl(linha.credito),
                )
            )
    return linhas


def _brl(valor: Decimal) -> float:
    return round(float(valor), 2)
