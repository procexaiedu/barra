"""Aceite: custo BRL por turno (docs/agente/03 §4.2; meta <=0.12 BRL/turno).

Cobre:
- calcular_custo_brl: funcao pura, le usage_metadata, aplica a tabela DeepSeek + cotacao.
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
    PRECO_DEEPSEEK_USD_PER_MTOK,
    cache_read_deepseek,
    calcular_custo_brl,
    input_nao_cacheado,
)
from barra.agente.contexto import ContextAgente
from barra.agente.nos.llm import no_llm

COTACAO = 5.50


def test_calcular_custo_brl_combina_os_componentes() -> None:
    # input fresco=1k, output=500, cache_read=10k, write=2k. O wrapper langchain reporta
    # input_tokens como o TOTAL (fresco + read + write) = 13k; o custo desconta read/write e cobra
    # so 1k a preco cheio. O DeepSeek NAO tarifa escrita de cache -> a parcela de write fica 0.
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
        1000 * PRECO_DEEPSEEK_USD_PER_MTOK["input"]
        + 500 * PRECO_DEEPSEEK_USD_PER_MTOK["output"]
        + 10_000 * PRECO_DEEPSEEK_USD_PER_MTOK["cache_read"]
    ) / 1_000_000
    assert custo == pytest.approx(esperado_usd * COTACAO)


def test_calcular_custo_brl_sem_tarifa_de_write_nao_estoura_keyerror() -> None:
    # A tabela do DeepSeek é só input/output/cache_read (o provider não cobra ESCRITA de cache).
    # calcular_custo_brl não pode estourar KeyError ao acessar as chaves de write — `.get(..., 0.0)`
    # zera a parcela. Modelo desconhecido cai na mesma tabela (default: um provider só).
    um: dict[str, Any] = {
        "input_tokens": 4600,  # total = 100 fresco + 4000 read + 500 write
        "output_tokens": 50,
        "input_token_details": {"cache_read": 4000, "ephemeral_1h_input_tokens": 500},
    }
    custo = calcular_custo_brl(um, COTACAO, model_name="modelo-desconhecido")
    esperado_usd = (100 * 0.14 + 50 * 0.28 + 4000 * 0.0028) / 1_000_000  # write a 0.0
    assert custo == pytest.approx(esperado_usd * COTACAO)


def test_calcular_custo_brl_deepseek_direct_usa_tabela_com_cache() -> None:
    # O DeepSeek-direct (api.deepseek.com) reporta `model_name="deepseek-v4-flash"` e e tarifado a
    # input $0.14, output $0.28, cache_read $0.0028: input fresco=943, cache_read=11008, output=24 —
    # o mesmo turno real do trace 33f01d3a (92% cache hit), ~R$0,001.
    um: dict[str, Any] = {
        "input_tokens": 11_951,  # total = 943 fresco + 11008 read
        "output_tokens": 24,
        "input_token_details": {"cache_read": 11_008},
    }
    custo = calcular_custo_brl(um, COTACAO, model_name="deepseek-v4-flash")
    esperado_usd = (943 * 0.14 + 24 * 0.28 + 11_008 * 0.0028) / 1_000_000
    assert custo == pytest.approx(esperado_usd * COTACAO)
    # sem model_name cai no MESMO default (um provider so) -> mesmo custo.
    assert calcular_custo_brl(um, COTACAO) == pytest.approx(custo)


def test_cache_read_deepseek_extrai_hit_do_token_usage() -> None:
    # DeepSeek-direct reporta o cache so em token_usage.prompt_cache_hit_tokens (campo proprio,
    # preservado pelo SDK OpenAI extra='allow'); o langchain-openai NAO o mapeia p/ cache_read.
    rm = {"token_usage": {"prompt_tokens": 11_951, "prompt_cache_hit_tokens": 11_008}}
    assert cache_read_deepseek(rm) == 11_008


def test_cache_read_deepseek_ausente_retorna_zero() -> None:
    # Provider sem essa chave -> 0 (no-op). None/sem token_usage -> 0.
    assert cache_read_deepseek(None) == 0
    assert cache_read_deepseek({}) == 0
    assert cache_read_deepseek({"token_usage": {"prompt_tokens": 100}}) == 0
    assert cache_read_deepseek({"token_usage": {"prompt_cache_hit_tokens": 0}}) == 0


def test_custo_brl_com_cache_reinjetado_bate_o_direct() -> None:
    # Pipeline do fix: o usage do DeepSeek-direct chega SEM cache_read (langchain-openai le
    # `prompt_tokens_details.cached_tokens`, que o DeepSeek manda como None). Apos reinjetar o hit do
    # token_usage em input_token_details.cache_read, calcular_custo_brl cobra o prefixo a $0.0028
    # (read), nao a $0.14 (miss) — fim da super-estimativa ~10x. Mesmo turno do trace 33f01d3a.
    hit = cache_read_deepseek({"token_usage": {"prompt_cache_hit_tokens": 11_008}})
    um: dict[str, Any] = {
        "input_tokens": 11_951,  # total = 943 miss + 11008 hit
        "output_tokens": 24,
        "input_token_details": {"cache_read": hit},
    }
    custo = calcular_custo_brl(um, COTACAO, model_name="deepseek-v4-flash")
    esperado_usd = (943 * 0.14 + 24 * 0.28 + 11_008 * 0.0028) / 1_000_000
    assert custo == pytest.approx(esperado_usd * COTACAO)
    # sem o reinject (cache_read=0) o mesmo turno cobraria todo o input como miss -> ~10x maior.
    sem_fix: dict[str, Any] = {**um, "input_token_details": {}}
    assert calcular_custo_brl(sem_fix, COTACAO, model_name="deepseek-v4-flash") > custo * 5


def test_calcular_custo_brl_so_cache_read_quase_zero() -> None:
    # Turno todo lendo do cache (steady state ideal): input_tokens (total) == cache_read, fresco=0.
    # Paga so a tarifa de cache-hit p/ os 5k cacheados (50x mais barata que o miss) — irrisorio.
    um: dict[str, Any] = {
        "input_tokens": 5000,
        "output_tokens": 0,
        "input_token_details": {"cache_read": 5000},
    }
    assert calcular_custo_brl(um, COTACAO) == pytest.approx(5000 * 0.0028 / 1_000_000 * COTACAO)


def test_input_nao_cacheado_desconta_read_e_write() -> None:
    # input_tokens (total langchain) = base 331 + cache_read 16855 + write 457 -> fresco 331.
    um: dict[str, Any] = {
        "input_tokens": 331 + 16855 + 457,
        "input_token_details": {"cache_read": 16855, "ephemeral_5m_input_tokens": 457},
    }
    assert input_nao_cacheado(um) == 331


def test_calcular_custo_brl_turno_quente_nao_dobra_o_cache() -> None:
    # Regressao do bug de medicao 5x: turno quente real (Langfuse). O prefixo cacheado (16855 read)
    # NAO pode ser cobrado a preco de input cheio. input_tokens = 331+16855+457 = 17643 (total);
    # o write nao e tarifado pelo DeepSeek, entao so entram fresco + output + cache_read.
    um: dict[str, Any] = {
        "input_tokens": 17_643,
        "output_tokens": 2,
        "input_token_details": {"cache_read": 16_855, "ephemeral_5m_input_tokens": 457},
    }
    esperado_usd = (
        331 * PRECO_DEEPSEEK_USD_PER_MTOK["input"]
        + 2 * PRECO_DEEPSEEK_USD_PER_MTOK["output"]
        + 16_855 * PRECO_DEEPSEEK_USD_PER_MTOK["cache_read"]
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
        100 * PRECO_DEEPSEEK_USD_PER_MTOK["input"] + 50 * PRECO_DEEPSEEK_USD_PER_MTOK["output"]
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
    # Label `modelo` (nome do modelo) com nonce p/ isolar a serie do teste. Pos-turno: o
    # Histogram tem >= 1 sample no bucket "+Inf" (count cresce); o sample _sum cresce do que
    # observamos. Comparacao por delta (antes vs depois) p/ nao depender do estado global.
    modelo = f"test-deepseek-{uuid4().hex}"
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


def test_no_llm_reinjeta_cache_read_deepseek_no_objeto() -> None:
    # DeepSeek-direct: o usage chega sem cache_read; o cache-hit so vem em response_metadata.
    # token_usage. O no llm reinjeta cache_read NO PROPRIO objeto da AIMessage (mutacao in-place),
    # entao tanto a metrica/custo aqui quanto a acumulacao do coordenador (que le este mesmo objeto no
    # canal `messages`) precificam o prefixo como cache, nao como input cheio.
    modelo = f"deepseek-v4-flash-{uuid4().hex}"
    um = {
        "input_tokens": 11_951,  # total = 943 miss + 11008 hit
        "output_tokens": 24,
        "total_tokens": 11_975,
        "input_token_details": {},  # langchain-openai nao mapeou (DeepSeek nao manda cached_tokens)
    }
    resp = AIMessage(
        content="oi",
        usage_metadata=um,  # type: ignore[arg-type]
        response_metadata={
            "token_usage": {"prompt_cache_hit_tokens": 11_008},
            "finish_reason": "stop",
        },
    )
    asyncio.run(no_llm(_FakeChat(resp, model=modelo), [])({"messages": []}, _runtime()))
    assert resp.usage_metadata is not None
    assert resp.usage_metadata["input_token_details"]["cache_read"] == 11_008


def test_no_llm_nao_sobrescreve_cache_read_ja_mapeado() -> None:
    # Ramo idempotente do guard `if not det_ds.get("cache_read")` (nos/llm.py): quando o
    # langchain ja mapeou cache_read (ex.: OpenRouter, ou um dia o langchain-openai passa a ler
    # prompt_tokens_details.cached_tokens), um prompt_cache_hit_tokens DIVERGENTE no token_usage
    # NAO pode sobrescrever o valor ja presente -- senao o custo/metrica do turno duplicaria/distorceria.
    modelo = f"deepseek-v4-flash-{uuid4().hex}"
    um = {
        "input_tokens": 11_951,
        "output_tokens": 24,
        "total_tokens": 11_975,
        "input_token_details": {"cache_read": 5_000},  # ja mapeado pelo langchain
    }
    resp = AIMessage(
        content="oi",
        usage_metadata=um,  # type: ignore[arg-type]
        response_metadata={
            "token_usage": {"prompt_cache_hit_tokens": 11_008},  # valor cru DIVERGENTE
            "finish_reason": "stop",
        },
    )
    asyncio.run(no_llm(_FakeChat(resp, model=modelo), [])({"messages": []}, _runtime()))
    assert resp.usage_metadata is not None
    # mantem os 5_000 ja mapeados; NAO sobrescreve com os 11_008 do campo cru
    assert resp.usage_metadata["input_token_details"]["cache_read"] == 5_000
