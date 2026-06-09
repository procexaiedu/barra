"""Custo estimado por turno em BRL (docs/agente/03 §4.2).

O ALVO de custo por turno tem fonte unica em `settings.custo_alvo_brl` (CUSTO-06) — este modulo
so calcula o custo realizado; nao repete o numero do alvo. Funcao pura
`calcular_custo_brl(usage_metadata, cotacao_usd_brl)` consumida pelo no llm para
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


# --- Vision (Pix) e STT (Whisper) -------------------------------------------------------------
# CUSTO-02: custo das outras chamadas de IA por atendimento, alem do chat.
#
# >>> TARIFAS PENDENTES DE CONFIRMACAO DO OPERADOR <<<
# Os dois numeros abaixo sao DEFAULTS PLAUSIVEIS, nunca batidos com o Fernando. Sao alvos de
# revisao (memoria pipeline_noturno: CUSTO-02 estava travado por falta da tarifa de STT).
#  - PRECO_VISION_USD_PER_MTOK: o modelo de vision do Pix roteia pelo OpenRouter
#    (settings.openrouter_model_vision_pix; default "google/gemini-3-flash-preview" em pix.py),
#    entao adotamos a tabela publica do Gemini 3 Flash (input $0.50 / output $3.00). Se o
#    operador fixar outro modelo no OpenRouter, ajustar aqui.
#  - TARIFA_STT_USD_POR_MINUTO: Whisper-1 da OpenAI e faturado por minuto de audio
#    (referencia publica $0.006/min). Confirmar a alic. real / eventual desconto antes de tratar
#    como custo fechado.
PRECO_VISION_USD_PER_MTOK: dict[str, float] = {
    "input": 0.50,
    "output": 3.00,
}
TARIFA_STT_USD_POR_MINUTO: float = 0.006


def calcular_custo_vision_brl(usage: Any, cotacao_usd_brl: float) -> float:
    """Custo em BRL de UMA chamada de vision (Pix) a partir do `usage` do SDK OpenAI-compativel.

    `usage` e o objeto `CompletionUsage` da resposta `chat.completions.create` do OpenRouter
    (atributos `prompt_tokens`/`completion_tokens`). `usage=None` (resposta inconclusiva,
    fake de teste sem usage) -> 0.0, mesma defesa de `calcular_custo_brl`. Sem cache: o vision
    e single-shot, nao reusa prefixo entre comprovantes.
    """
    if usage is None:
        return 0.0
    prompt_t: int = getattr(usage, "prompt_tokens", 0) or 0
    completion_t: int = getattr(usage, "completion_tokens", 0) or 0
    usd: float = (
        prompt_t * PRECO_VISION_USD_PER_MTOK["input"]
        + completion_t * PRECO_VISION_USD_PER_MTOK["output"]
    ) / 1_000_000
    return usd * cotacao_usd_brl


def calcular_custo_stt_brl(duracao_segundos: float, cotacao_usd_brl: float) -> float:
    """Custo em BRL de UMA transcricao Whisper a partir da duracao do audio (faturado por minuto).

    `duracao_segundos` vem do `resposta.duration` do verbose_json do Whisper-1 (ja lida em
    media.py). Duracao <= 0 (audio nao medido / fake) -> 0.0.
    """
    if duracao_segundos <= 0:
        return 0.0
    return (duracao_segundos / 60.0) * TARIFA_STT_USD_POR_MINUTO * cotacao_usd_brl


def custo_por_atendimento_brl(chat_brl: float, stt_brl: float, vision_brl: float) -> float:
    """Custo total de IA de um atendimento: soma chat + STT + vision (CUSTO-02).

    Funcao pura para o bloco ROI do dashboard (CUSTO-01) compor o custo_IA_por_fechado a partir
    dos tres componentes ja agregados por atendimento_id. Cada parcela e >= 0.
    """
    return chat_brl + stt_brl + vision_brl


def calcular_custo_brl(usage_metadata: dict[str, Any] | None, cotacao_usd_brl: float) -> float:
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
