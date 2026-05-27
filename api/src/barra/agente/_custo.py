"""Custo estimado por turno em BRL (docs/agente/03 §4.2).

Funcao pura `calcular_custo_brl(usage_metadata, cotacao_usd_brl)` consumida pelo no llm para
observar o Histogram `AGENTE_CUSTO_TURNO_BRL`. Preco em USD/MTok espelha a tabela publica do
Sonnet 4.6 (input $3, output $15, cache_write 1.25-2x, cache_read 0.1x). Quando a Anthropic
mexer no preco, atualizar aqui (constante de modulo, nao settings — preco muda raro e queremos
controle de versao no repo).

Nao tem fallback de modelo: o chat roda so em Sonnet 4.6 (decisao M0), entao um unico mapa
basta. Se algum dia entrar Opus/Haiku, parametrizar por `modelo` aqui.
"""

from typing import Any

# USD por milhao de tokens — Sonnet 4.6 (claude-sonnet-4-6).
# Multiplicadores 1.25x (5m write), 2x (1h write), 0.1x (read) seguem a tabela oficial de
# prompt caching (`build-with-claude/prompt-caching`).
PRECO_USD_PER_MTOK: dict[str, float] = {
    "input": 3.00,
    "output": 15.00,
    "cache_write_5m": 3.75,
    "cache_write_1h": 6.00,
    "cache_read": 0.30,
}


def calcular_custo_brl(
    usage_metadata: dict[str, Any] | None, cotacao_usd_brl: float
) -> float:
    """Custo estimado do turno em BRL a partir do `usage_metadata` da AIMessage.

    Le `input_token_details` no formato langchain-anthropic 1.4.3 (mapeamento assimetrico:
    cache_read OK; write em `ephemeral_5m/1h`, NUNCA em `cache_creation`, memoria
    auditoria_best_practices_agente). `input_tokens` aqui ja vem como o RESTO nao-cacheado
    (a Anthropic separa cache_read/cache_creation do input_tokens nu).

    `usage_metadata=None` ou sem chaves esperadas -> 0.0 (turno sem custo medivel; o nao-key
    no nao quebra a metrica). Mesma defesa de `_instrumentar_tokens`.
    """
    if not usage_metadata:
        return 0.0
    det = usage_metadata.get("input_token_details") or {}
    input_t: int = usage_metadata.get("input_tokens", 0)
    output_t: int = usage_metadata.get("output_tokens", 0)
    cache_read: int = det.get("cache_read", 0)
    cache_write_5m: int = det.get("ephemeral_5m_input_tokens", 0)
    cache_write_1h: int = det.get("ephemeral_1h_input_tokens", 0)
    usd: float = (
        input_t * PRECO_USD_PER_MTOK["input"]
        + output_t * PRECO_USD_PER_MTOK["output"]
        + cache_write_1h * PRECO_USD_PER_MTOK["cache_write_1h"]
        + cache_write_5m * PRECO_USD_PER_MTOK["cache_write_5m"]
        + cache_read * PRECO_USD_PER_MTOK["cache_read"]
    ) / 1_000_000
    return usd * cotacao_usd_brl
