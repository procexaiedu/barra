"""As duas ações do painel que movem dinheiro (ticket 05): o vale e o fechamento da temporada.

Divisão: `temporada_repo` escreve, `razao_repo` lê, `razao.apurar` (puro) soma, e aqui só se
orquestra. A única aritmética deste arquivo é `max(falta_pagar, 0)` — a frase do ADR-0045 §7 ("a
diferença contra o já pago aparece como 'falta pagar R$ X'") lida para o lado da casa.

⚠️ **O fechamento não é snapshot** (ADR-0045 §7). `montar_fechamento` apura AGORA, sobre os fatos
de agora, e `registrar_fechamento` devolve exatamente o mesmo DTO recalculado depois de escrever.
Um comprovante de R$ 600 que chegar depois de a temporada estar paga muda o número na próxima
leitura e a diferença aparece em `saldo.falta_pagar_brl`. Não existe reabertura porque nunca houve
congelamento — e é por isso que não há função `reabrir_temporada` aqui.

⚠️ **Fechar é ação do painel, nunca frase no grupo** (ADR-0045 §8): a modelo está dentro do grupo.
Nada em `agente_financeiro/` importa este módulo, e nada deve passar a importar.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.dominio.financeiro import razao_repo, razao_service, temporada_repo
from barra.dominio.financeiro.razao_repo import Recorte, TemporadaLida
from barra.dominio.financeiro.schemas import (
    FechamentoDaTemporadaResponse,
    FecharTemporadaBody,
    LancamentoManualCriar,
    LancamentoManualResponse,
    TemporadaCriar,
    TemporadaResponse,
)
from barra.dominio.financeiro.temporada_repo import LancamentoManualLido


async def abrir_temporada(
    conn: AsyncConnection[Any], body: TemporadaCriar, user_id: UUID | None
) -> TemporadaResponse:
    """Abre a temporada da modelo. Recusa sobreposição com outra temporada viva dela.

    A sobreposição não é proibida pelo banco (a migration explica por quê), mas é erro de
    operação com consequência cara: a mesma venda entraria nas duas temporadas e seria paga duas
    vezes. Aqui ela vira 409 com os ids que colidiram, para o gestor corrigir a data.
    """
    identidade = await razao_repo.identidade_da_modelo(conn, body.modelo_id)
    if identidade is None:
        raise NaoEncontrado("Modelo")

    colisoes = await temporada_repo.temporadas_sobrepostas(
        conn,
        modelo_id=body.modelo_id,
        data_inicio=body.data_inicio,
        data_fim=body.data_fim,
    )
    if colisoes:
        raise ConflitoEstado(
            "A modelo ja tem temporada neste periodo.",
            {"temporadas": [str(t) for t in colisoes]},
        )

    temporada_id = await temporada_repo.criar_temporada(
        conn,
        modelo_id=body.modelo_id,
        cidade=body.cidade.strip(),
        data_inicio=body.data_inicio,
        data_fim=body.data_fim,
        observacao=body.observacao,
        user_id=user_id,
    )
    return await _temporada_response(conn, temporada_id)


async def montar_fechamento(
    conn: AsyncConnection[Any], temporada_id: UUID
) -> FechamentoDaTemporadaResponse:
    """A tela de fechar temporada: saldo, o que já foi pago, os vales e as PENDÊNCIAS abertas.

    As pendências vêm para serem lidas antes de confirmar, e não travam nada — o gestor decide
    fechar assim mesmo (é o que a US 32 pede, com essas palavras).
    """
    temporada = await razao_repo.obter_temporada(conn, temporada_id)
    if temporada is None:
        raise NaoEncontrado("Temporada")
    return await _fechamento(conn, temporada)


async def registrar_fechamento(
    conn: AsyncConnection[Any],
    temporada_id: UUID,
    body: FecharTemporadaBody,
    user_id: UUID | None,
) -> FechamentoDaTemporadaResponse:
    """Grava o pagamento feito (fato, com data) e marca a temporada — nesta ordem.

    O pagamento vem primeiro porque ele é o fato; a marca de `fechada` é rotina. Se a marca
    falhasse, o dinheiro pago continuaria contado no saldo, que é o comportamento seguro.

    Chamar de novo depois — quando um comprovante atrasado mudou a conta — registra a diferença
    como mais um pagamento da mesma temporada. Não é reabertura: nada tinha sido congelado.
    """
    temporada = await razao_repo.obter_temporada(conn, temporada_id)
    if temporada is None:
        raise NaoEncontrado("Temporada")
    if temporada.estado == "cancelada":
        raise ConflitoEstado("Temporada cancelada: a viagem nao aconteceu, nao ha o que pagar.")

    if body.valor is not None:
        await temporada_repo.criar_pagamento_da_temporada(
            conn,
            modelo_id=temporada.modelo_id,
            temporada_id=temporada.id,
            data_pagamento=body.data_pagamento or _hoje(),
            valor=body.valor,
            forma_pagamento=body.forma_pagamento,
            observacao=body.observacao,
            comprovante_object_key=body.comprovante_object_key,
            user_id=user_id,
        )

    if body.marcar_fechada:
        await temporada_repo.marcar_temporada_fechada(conn, temporada.id)

    atual = await razao_repo.obter_temporada(conn, temporada.id)
    assert atual is not None
    return await _fechamento(conn, atual)


async def lancar_no_razao(
    conn: AsyncConnection[Any], body: LancamentoManualCriar, user_id: UUID | None
) -> LancamentoManualResponse:
    """O vale adiantado pelo painel. Debita a modelo e passa a aparecer no extrato dela."""
    if await razao_repo.identidade_da_modelo(conn, body.modelo_id) is None:
        raise NaoEncontrado("Modelo")

    if body.temporada_id is not None:
        temporada = await razao_repo.obter_temporada(conn, body.temporada_id)
        if temporada is None:
            raise NaoEncontrado("Temporada")
        if temporada.modelo_id != body.modelo_id:
            raise ConflitoEstado("A temporada informada e de outra modelo.")

    lancamento_id = await temporada_repo.criar_lancamento_manual(
        conn,
        modelo_id=body.modelo_id,
        tipo=body.tipo,
        sentido=body.sentido,
        valor=body.valor,
        data=body.data,
        descricao=body.descricao,
        temporada_id=body.temporada_id,
        user_id=user_id,
    )
    lido = await temporada_repo.obter_lancamento_manual(conn, lancamento_id)
    assert lido is not None
    return _lancamento_response(lido)


async def anular_lancamento(
    conn: AsyncConnection[Any], lancamento_id: UUID
) -> LancamentoManualResponse:
    """Estorna o vale digitado errado. Estado com rastro, nunca DELETE."""
    lido = await temporada_repo.obter_lancamento_manual(conn, lancamento_id)
    if lido is None:
        raise NaoEncontrado("Lancamento")
    if lido.anulado_em is None:
        await temporada_repo.anular_lancamento_manual(conn, lancamento_id)
        lido = await temporada_repo.obter_lancamento_manual(conn, lancamento_id)
        assert lido is not None
    return _lancamento_response(lido)


# =============================================================================
# Montagem
# =============================================================================


async def _fechamento(
    conn: AsyncConnection[Any], temporada: TemporadaLida
) -> FechamentoDaTemporadaResponse:
    recorte = Recorte(
        modelo_id=temporada.modelo_id,
        de=temporada.data_inicio,
        ate=temporada.data_fim,
        temporada_id=temporada.id,
    )
    extrato = await razao_service.montar_extrato(conn, recorte)
    if extrato is None:  # pragma: no cover - a FK da temporada garante a modelo
        raise NaoEncontrado("Modelo")

    vales = await temporada_repo.lancamentos_manuais(
        conn,
        modelo_id=temporada.modelo_id,
        de=temporada.data_inicio,
        ate=temporada.data_fim,
    )
    return FechamentoDaTemporadaResponse(
        temporada=_response_de(temporada),
        saldo=extrato.saldo,
        sugestao_de_pagamento_brl=max(extrato.saldo.falta_pagar_brl, 0.0),
        vendas=extrato.conferencia.vendas,
        vendido_brl=extrato.conferencia.vendido_brl,
        pendencias=extrato.pendencias,
        divergencias=extrato.divergencias,
        pagamentos=extrato.pagamentos,
        vales=[_lancamento_response(vale) for vale in vales],
    )


async def _temporada_response(conn: AsyncConnection[Any], temporada_id: UUID) -> TemporadaResponse:
    temporada = await razao_repo.obter_temporada(conn, temporada_id)
    assert temporada is not None
    return _response_de(temporada)


def _response_de(temporada: TemporadaLida) -> TemporadaResponse:
    return TemporadaResponse(
        id=temporada.id,
        modelo_id=temporada.modelo_id,
        modelo_nome=temporada.modelo_nome,
        cidade=temporada.cidade,
        data_inicio=temporada.data_inicio,
        data_fim=temporada.data_fim,
        estado=temporada.estado,
        observacao=temporada.observacao,
        fechada_em=temporada.fechada_em.isoformat() if temporada.fechada_em else None,
    )


def _lancamento_response(lido: LancamentoManualLido) -> LancamentoManualResponse:
    return LancamentoManualResponse(
        id=lido.id,
        modelo_id=lido.modelo_id,
        tipo=lido.tipo,
        sentido=lido.sentido,
        valor_brl=_brl(lido.valor),
        data=lido.data,
        descricao=lido.descricao,
        origem=lido.origem,
        temporada_id=lido.temporada_id,
        anulado_em=lido.anulado_em.isoformat() if lido.anulado_em else None,
    )


def _brl(valor: Decimal) -> float:
    return round(float(valor), 2)


def _hoje() -> date:
    return datetime.now(UTC).date()
