"""Aceite: custo BRL por turno (docs/agente/03 §4.2; meta <=0.12 BRL/turno).

Cobre:
- calcular_custo_brl: funcao pura, le usage_metadata, aplica tabela Sonnet 4.6 + cotacao.
- Robustez: usage_metadata=None retorna 0 (defesa, igual _instrumentar_tokens).
- Integracao: o no llm observa o Histogram AGENTE_CUSTO_TURNO_BRL ao processar a AIMessage.
"""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from _fakes import FakeRuntime
from langchain_core.messages import AIMessage, BaseMessage
from prometheus_client import REGISTRY

from barra.agente._custo import (
    PRECO_USD_PER_MTOK,
    calcular_custo_brl,
    input_nao_cacheado,
)
from barra.agente.contexto import ContextAgente
from barra.agente.nos.llm import no_llm

COTACAO = 5.50


def test_calcular_custo_brl_combina_4_componentes() -> None:
    # input fresco=1k, output=500, cache_read=10k, cache_write_1h=2k. langchain-anthropic reporta
    # input_tokens como o TOTAL (fresco + read + write) = 13k; o custo desconta read/write e cobra
    # so 1k a preco cheio. USD = 1k*3/1M + 500*15/1M + 10k*0.3/1M + 2k*6/1M = 0.0255. BRL = *5.5.
    um: dict[str, Any] = {
        "input_tokens": 13_000,
        "output_tokens": 500,
        "input_token_details": {
            "cache_read": 10_000,
            "ephemeral_1h_input_tokens": 2000,
            "ephemeral_5m_input_tokens": 0,
        },
    }
    custo = calcular_custo_brl(um, COTACAO)
    esperado_usd = (
        1000 * PRECO_USD_PER_MTOK["input"]
        + 500 * PRECO_USD_PER_MTOK["output"]
        + 10_000 * PRECO_USD_PER_MTOK["cache_read"]
        + 2000 * PRECO_USD_PER_MTOK["cache_write_1h"]
    ) / 1_000_000
    assert custo == pytest.approx(esperado_usd * COTACAO)


def test_calcular_custo_brl_so_cache_read_quase_zero() -> None:
    # Turno todo lendo do cache (steady state ideal): input_tokens (total) == cache_read, fresco=0.
    # Paga so 0.1x p/ os 5k cacheados: 5k*0.3/1M = 0.0015 USD = ~0.008 BRL. Bem abaixo da meta 0.12.
    um: dict[str, Any] = {
        "input_tokens": 5000,
        "output_tokens": 0,
        "input_token_details": {"cache_read": 5000},
    }
    assert calcular_custo_brl(um, COTACAO) == pytest.approx(5000 * 0.30 / 1_000_000 * COTACAO)


def test_input_nao_cacheado_desconta_read_e_write() -> None:
    # input_tokens (total langchain) = base 331 + cache_read 16855 + write 457 -> fresco 331.
    um: dict[str, Any] = {
        "input_tokens": 331 + 16855 + 457,
        "input_token_details": {"cache_read": 16855, "ephemeral_5m_input_tokens": 457},
    }
    assert input_nao_cacheado(um) == 331


def test_calcular_custo_brl_turno_quente_nao_dobra_o_cache() -> None:
    # Regressao do bug de medicao 5x: turno quente real (Langfuse). O prefixo cacheado (16855 read)
    # NAO pode ser cobrado a preco de input cheio. input_tokens = 331+16855+457 = 17643 (total).
    # USD correto = 331*3/1M + 2*15/1M + 16855*0.3/1M + 457*3.75/1M ≈ 0.00779.
    um: dict[str, Any] = {
        "input_tokens": 17_643,
        "output_tokens": 2,
        "input_token_details": {"cache_read": 16_855, "ephemeral_5m_input_tokens": 457},
    }
    esperado_usd = (
        331 * PRECO_USD_PER_MTOK["input"]
        + 2 * PRECO_USD_PER_MTOK["output"]
        + 16_855 * PRECO_USD_PER_MTOK["cache_read"]
        + 457 * PRECO_USD_PER_MTOK["cache_write_5m"]
    ) / 1_000_000
    assert calcular_custo_brl(um, COTACAO) == pytest.approx(esperado_usd * COTACAO)
    # Sanidade: bem abaixo do que daria a contagem dobrada (input_tokens cru a 3/1M ~ 5x).
    assert calcular_custo_brl(um, COTACAO) < 0.05


def test_calcular_custo_brl_none_devolve_zero() -> None:
    # AIMessage sem usage_metadata (resp mockada/teste) -> sem custo, sem quebrar.
    assert calcular_custo_brl(None, COTACAO) == 0.0


def test_calcular_custo_brl_sem_detalhes_usa_so_input_output() -> None:
    # input_token_details ausente: cai pra contagem nua (sem cache).
    um: dict[str, Any] = {"input_tokens": 100, "output_tokens": 50}
    esperado_usd = (
        100 * PRECO_USD_PER_MTOK["input"] + 50 * PRECO_USD_PER_MTOK["output"]
    ) / 1_000_000
    assert calcular_custo_brl(um, COTACAO) == pytest.approx(esperado_usd * COTACAO)


# --- integracao: o no llm observa o Histogram --------------------------------------------


class _FakeBound:
    def __init__(self, resp: BaseMessage) -> None:
        self._resp = resp

    async def ainvoke(self, messages: Any) -> BaseMessage:
        return self._resp


class _FakeChat:
    def __init__(self, resp: BaseMessage, *, model: str) -> None:
        self._resp = resp
        self.model = model

    def bind_tools(self, tools: Any) -> _FakeBound:
        return _FakeBound(self._resp)


def _runtime() -> FakeRuntime:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return FakeRuntime(ctx)


def test_no_llm_observa_custo_brl_no_histogram() -> None:
    # Label `modelo` (nome Anthropic) com nonce p/ isolar a serie do teste. Pos-turno: o
    # Histogram tem >= 1 sample no bucket "+Inf" (count cresce); o sample _sum cresce do que
    # observamos. Comparacao por delta (antes vs depois) p/ nao depender do estado global.
    modelo = f"test-sonnet-{uuid4().hex}"
    um = {
        "input_tokens": 4600,  # total langchain = 100 fresco + 4000 read + 500 write
        "output_tokens": 50,
        "total_tokens": 4650,
        "input_token_details": {"cache_read": 4000, "ephemeral_1h_input_tokens": 500},
    }
    resp = AIMessage(content="oi", usage_metadata=um)  # type: ignore[arg-type]

    antes = REGISTRY.get_sample_value("agente_custo_turno_brl_count", {"modelo": modelo}) or 0.0
    asyncio.run(no_llm(_FakeChat(resp, model=modelo), [])({"messages": []}, _runtime()))
    depois = REGISTRY.get_sample_value("agente_custo_turno_brl_count", {"modelo": modelo}) or 0.0
    assert depois - antes == 1.0, "1 observe por turno"
