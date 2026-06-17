"""Custo estimado por turno em BRL (docs/agente/03 §4.2).

O ALVO de custo por turno tem fonte unica em `settings.custo_alvo_brl` (CUSTO-06) — este modulo
so calcula o custo realizado; nao repete o numero do alvo. Funcao pura
`calcular_custo_brl(usage_metadata, cotacao_usd_brl)` consumida pelo no llm para
observar o Histogram `AGENTE_CUSTO_TURNO_BRL`. Preco em USD/MTok espelha a tabela publica do
Sonnet 4.6 (input $3, output $15, cache_write 1.25-2x, cache_read 0.1x). Quando a Anthropic
mexer no preco, atualizar aqui (constante de modulo, nao settings — preco muda raro e queremos
controle de versao no repo).

O chat roda em Sonnet 4.6, mas a extracao forcada barata roda em Haiku 4.5 (`no_llm`,
chat_extracao_barata): por isso o custo e parametrizado POR MODELO (`_tabela_preco`), lendo o
nome Anthropic de cada AIMessage. Cobrar tudo a tarifa de Sonnet super-estimava a extracao
(~3x) e divergia do `total_cost` do Langfuse (que ja precifica por modelo).
"""

from collections.abc import Sequence
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

# USD por milhao de tokens — Haiku 4.5 (claude-haiku-4-5). Tabela publica $1 input / $5 output;
# mesmos multiplicadores de cache (1.25x/2x/0.1x). Usado pela extracao forcada barata.
PRECO_HAIKU_USD_PER_MTOK: dict[str, float] = {
    "input": 1.00,
    "output": 5.00,
    "cache_write_5m": 1.25,
    "cache_write_1h": 2.00,
    "cache_read": 0.10,
}


def _tabela_preco(model_name: str | None) -> dict[str, float]:
    """Tabela de preco USD/MTok pelo nome Anthropic do modelo. Haiku -> tabela Haiku; qualquer
    outro (incl. None / Sonnet) -> Sonnet (default seguro, o chat principal). Match por substring
    p/ tolerar o sufixo de data (`claude-haiku-4-5-20251001`)."""
    if model_name and "haiku" in model_name.lower():
        return PRECO_HAIKU_USD_PER_MTOK
    return PRECO_USD_PER_MTOK


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


def custo_chat_turno_brl(messages: Sequence[Any], cotacao_usd_brl: float) -> float:
    """Custo de chat (Sonnet) do TURNO em BRL: soma `calcular_custo_brl` sobre as AIMessages
    GERADAS no turno (usage_metadata != None — mesma heuristica de extrair_texto_do_turno para
    ignorar as historicas re-injetadas pelo prepare_context, que vem sem usage).

    Duck-typing via getattr (sem import de langchain): o modulo segue puro/testavel offline.
    Cobre todas as chamadas do loop ReAct e a 2a chamada da extracao forcada (ambas viram
    AIMessage com usage no canal `messages`). Consumida pelo coordenador para ACUMULAR o custo
    em `atendimentos.custo_ia_brl` (OBS go-live) — so chat; STT/vision seguem no Prometheus.
    """
    return sum(
        calcular_custo_brl(um, cotacao_usd_brl, model_name=_modelo_da_mensagem(m))
        for m in messages
        if (um := getattr(m, "usage_metadata", None))
    )


def _modelo_da_mensagem(m: Any) -> str | None:
    """Nome Anthropic da AIMessage (`response_metadata.model_name`, com fallback `model`), p/
    `custo_chat_turno_brl` precificar cada chamada do turno pela tabela do SEU modelo — a extracao
    forcada e Haiku, o resto Sonnet. Duck-typing (sem import de langchain); None -> tabela Sonnet."""
    meta = getattr(m, "response_metadata", None) or {}
    return meta.get("model_name") or meta.get("model")


def input_nao_cacheado(usage_metadata: dict[str, Any]) -> int:
    """Tokens de input FRESCO (preco cheio), separados da parcela cacheada.

    langchain-anthropic 1.4.3 reporta `usage_metadata["input_tokens"]` como o TOTAL — base +
    cache_read + cache_creation (`_create_usage_metadata` em chat_models.py:2286-2293: "Anthropic's
    `input_tokens` excludes cached tokens, so we manually add cache_read and cache_creation"). Logo
    o fresco e o resto apos descontar a leitura de cache e a escrita (ephemeral_5m/1h). Cobrar o
    `input_tokens` cru a preco de input cheio dobra a conta do prefixo cacheado (~5x/turno).
    """
    det = usage_metadata.get("input_token_details") or {}
    cacheado = (
        (det.get("cache_read", 0) or 0)
        + (det.get("ephemeral_5m_input_tokens", 0) or 0)
        + (det.get("ephemeral_1h_input_tokens", 0) or 0)
    )
    input_total: int = usage_metadata.get("input_tokens", 0)
    return max(0, input_total - cacheado)


def calcular_custo_brl(
    usage_metadata: dict[str, Any] | None,
    cotacao_usd_brl: float,
    model_name: str | None = None,
) -> float:
    """Custo estimado do turno em BRL a partir do `usage_metadata` da AIMessage.

    `model_name` (nome Anthropic) escolhe a tabela de preco (`_tabela_preco`): Haiku para a
    extracao forcada barata, Sonnet para o resto e para `None` (default seguro do chat principal).

    Le `input_token_details` no formato langchain-anthropic 1.4.3 (mapeamento assimetrico:
    cache_read OK; write em `ephemeral_5m/1h`, NUNCA em `cache_creation`, memoria
    auditoria_best_practices_agente). `input_tokens` vem como o TOTAL (inclui cache_read +
    cache_creation), entao a parcela de input cheio e `input_nao_cacheado` — o resto, ja
    descontados read/write; o cache entra so nas suas proprias tarifas (0.1x read, 1.25-2x write).

    `usage_metadata=None` ou sem chaves esperadas -> 0.0 (turno sem custo medivel; o nao-key
    no nao quebra a metrica). Mesma defesa de `_instrumentar_tokens`.
    """
    if not usage_metadata:
        return 0.0
    preco = _tabela_preco(model_name)
    det = usage_metadata.get("input_token_details") or {}
    input_t: int = input_nao_cacheado(usage_metadata)
    output_t: int = usage_metadata.get("output_tokens", 0)
    cache_read: int = det.get("cache_read", 0)
    cache_write_5m: int = det.get("ephemeral_5m_input_tokens", 0)
    cache_write_1h: int = det.get("ephemeral_1h_input_tokens", 0)
    usd: float = (
        input_t * preco["input"]
        + output_t * preco["output"]
        + cache_write_1h * preco["cache_write_1h"]
        + cache_write_5m * preco["cache_write_5m"]
        + cache_read * preco["cache_read"]
    ) / 1_000_000
    return usd * cotacao_usd_brl
