"""`_card_loc_pin`: falha da Evolution DESFAZ o SETNX de idempotência.

O renderer marca "enviado" (SETNX, TTL 24h) ANTES de enviar. Sem o rollback, uma falha da
Evolution deixaria a chave armada e todo replay (ARQ ou re-transição do atendimento) retornaria
mudo — o cliente ficaria 24h+ sem o ponto de encontro, sem nenhum sinal, e não há reconciliador
para este tipo de card (`reconciliar_cards_escalada` cobre só escalada). Achado da revisão
LangGraph da rodada 1 do loop de massa (12/08/2026).

Sem DB: pool/conn fakes; o SELECT devolve uma row com geo preenchida.
"""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from barra.workers.envio import _card_loc_pin

_ATENDIMENTO_ID = "00000000-0000-0000-0000-00000000c001"

_ROW = {
    "evolution_chat_id": "5511999990000@s.whatsapp.net",
    "conversa_id": "00000000-0000-0000-0000-00000000c002",
    "modelo_nome": "Modelo Teste",
    "nome_local": None,
    "latitude": -23.55,
    "longitude": -46.63,
    "endereco_formatado": "Rua Teste, 1",
    "evolution_instance_id": "00000000-0000-0000-0000-00000000c003",
}


_PADRAO: Any = object()  # sentinela: `row=None` significa "o SELECT nao achou a linha"


class _Pool:
    def __init__(self, row: Any = _PADRAO, erro: Exception | None = None) -> None:
        self.row = dict(_ROW) if row is _PADRAO else row
        self.erro = erro

    @asynccontextmanager
    async def connection(self) -> Any:
        conn = AsyncMock()
        res = AsyncMock()
        res.fetchone = AsyncMock(return_value=self.row)
        conn.execute = AsyncMock(side_effect=self.erro, return_value=res)
        yield conn


def _ctx(redis: Any, evolution: Any, pool: _Pool | None = None) -> dict[str, Any]:
    return {"db_pool": pool or _Pool(), "redis": redis, "evolution": evolution}


async def test_falha_da_evolution_desfaz_o_setnx_e_propaga() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)  # SETNX venceu: primeira passagem
    redis.delete = AsyncMock()
    evolution = AsyncMock()
    evolution.enviar_localizacao = AsyncMock(side_effect=RuntimeError("evolution fora"))

    with pytest.raises(RuntimeError):
        await _card_loc_pin(_ctx(redis, evolution), atendimento_id=_ATENDIMENTO_ID)

    chave = f"card:loc_pin:{_ATENDIMENTO_ID}"
    redis.set.assert_awaited_once()
    redis.delete.assert_awaited_once_with(chave)


async def test_sucesso_mantem_o_setnx() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    evolution = AsyncMock()
    evolution.enviar_localizacao = AsyncMock(return_value=None)

    await _card_loc_pin(_ctx(redis, evolution), atendimento_id=_ATENDIMENTO_ID)

    evolution.enviar_localizacao.assert_awaited_once()
    redis.delete.assert_not_awaited()


async def test_replay_com_chave_armada_sai_mudo_sem_tocar_evolution() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=None)  # SETNX perdeu: já enviado
    evolution = AsyncMock()
    evolution.enviar_localizacao = AsyncMock()

    await _card_loc_pin(_ctx(redis, evolution), atendimento_id=_ATENDIMENTO_ID)

    evolution.enviar_localizacao.assert_not_awaited()


# --- a marca só é gasta por quem chegou ao envio (revisão LangGraph, loop-massa r3) -------------
# O SETNX passou a ser armado DEPOIS de a linha ser lida e validada. Antes disso ele era a primeira
# instrução do job, e três caminhos que nunca entregaram o pin queimavam a chave por 24h: erro
# transitório de banco no SELECT (o retry do ARQ voltava mudo), atendimento não encontrado e modelo
# ainda sem lat/long — esta última é a que mais dói, porque a geo entra no cadastro DEPOIS.


async def test_erro_de_banco_no_select_nao_arma_a_chave() -> None:
    """O retry do ARQ tem que voltar a ter chance: sem a chave armada, a próxima tentativa
    reexecuta o job inteiro."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    evolution = AsyncMock()

    with pytest.raises(RuntimeError):
        await _card_loc_pin(
            _ctx(redis, evolution, _Pool(erro=RuntimeError("db fora"))),
            atendimento_id=_ATENDIMENTO_ID,
        )

    redis.set.assert_not_awaited()
    redis.delete.assert_not_awaited()
    evolution.enviar_localizacao.assert_not_awaited()


async def test_modelo_sem_geo_nao_gasta_a_chave() -> None:
    """A modelo ganha latitude/longitude no cadastro depois; com a chave queimada aqui, o pin
    nunca mais sairia para este atendimento."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    evolution = AsyncMock()
    sem_geo = {**_ROW, "latitude": None, "longitude": None}

    await _card_loc_pin(_ctx(redis, evolution, _Pool(row=sem_geo)), atendimento_id=_ATENDIMENTO_ID)

    redis.set.assert_not_awaited()
    evolution.enviar_localizacao.assert_not_awaited()


async def test_atendimento_sumido_nao_gasta_a_chave() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    evolution = AsyncMock()

    await _card_loc_pin(_ctx(redis, evolution, _Pool(row=None)), atendimento_id=_ATENDIMENTO_ID)

    redis.set.assert_not_awaited()
    evolution.enviar_localizacao.assert_not_awaited()
