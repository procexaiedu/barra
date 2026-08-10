"""Custo estimado por turno em BRL (docs/agente/03 §4.2).

O ALVO de custo por turno tem fonte unica em `settings.custo_alvo_brl` (CUSTO-06) — este modulo
so calcula o custo realizado; nao repete o numero do alvo. Funcao pura
`calcular_custo_brl(usage_metadata, cotacao_usd_brl)` consumida pelo no llm para
observar o Histogram `AGENTE_CUSTO_TURNO_BRL`. Preco em USD/MTok = constante de modulo (nao
settings — preco muda raro e queremos controle de versao no repo); atualizar aqui quando o
provedor mexer na tarifa.

Os 3 caminhos de texto do agente (chat #1, extracao #2, judge #3) rodam em DeepSeek V4 Flash
direto -> ha UMA tabela de chat (`PRECO_DEEPSEEK_USD_PER_MTOK`, com cache), usada tambem como
default para modelo desconhecido. Vision (Pix) e STT tem tabelas proprias mais abaixo.
"""

from collections.abc import Sequence
from typing import Any

# USD por milhao de tokens — DeepSeek V4 Flash DIRETO (api.deepseek.com), usado pelos 3 caminhos de
# texto do agente: chat #1, extracao forcada #2 e judge de AUP #3. A API reporta
# `model_name="deepseek-v4-flash"` (sem prefixo de provider; idem com o alias legado `deepseek-chat`,
# que aposenta 2026-07-24). Tarifa oficial V4 Flash (deepseek.com 2026-06): input cache-miss $0.14, output $0.28,
# cache-hit $0.0028 (50x mais barato que o miss). O cache do DeepSeek-direct e automatico; a parcela
# cacheada chega em `input_token_details.cache_read` APOS a reinjecao de `cache_read_deepseek` (ver
# abaixo: o langchain-openai nao mapeia o campo nativo do DeepSeek) — `calcular_custo_brl`
# desconta o cache_read do input cheio (input_nao_cacheado) e o cobra a `cache_read`. Sem chaves de
# write (ephemeral_*): o DeepSeek nao cobra escrita de cache.
PRECO_DEEPSEEK_USD_PER_MTOK: dict[str, float] = {
    "input": 0.14,
    "output": 0.28,
    "cache_read": 0.0028,
}


def cache_read_deepseek(response_metadata: dict[str, Any] | None) -> int:
    """Tokens de cache-hit do DeepSeek-direct que o langchain-openai NAO mapeia p/ usage_metadata.

    O DeepSeek-direct (api.deepseek.com) reporta o cache so em `token_usage.prompt_cache_hit_tokens`
    (campo proprio), NUNCA no `prompt_tokens_details.cached_tokens` que `ChatOpenAI._create_usage_metadata`
    le -> `usage_metadata.input_token_details.cache_read` chega ZERADO no caminho DeepSeek-direct e
    `calcular_custo_brl` cobraria 100% do input como miss ($0.14), super-estimando ~10x a parcela de
    input (o "92% cache hit" do Langfuse, que le o `token_usage` cru, divergiria do nosso BRL). O SDK
    OpenAI preserva o campo extra (CompletionUsage.model_config extra='allow'), entao ele sobrevive em
    `response_metadata["token_usage"]`. Provider sem essa chave -> 0 (no-op)."""
    tu = (response_metadata or {}).get("token_usage") or {}
    valor = tu.get("prompt_cache_hit_tokens", 0)
    return int(valor) if valor else 0


def _tabela_preco(model_name: str | None) -> dict[str, float]:
    """Tabela de preco USD/MTok do chat. Existe UM provider de texto (DeepSeek V4 Flash direto),
    entao a tabela DeepSeek serve tanto o caso conhecido quanto o default (`model_name=None` ou
    modelo desconhecido). Mantida como funcao para o dia em que voltar a haver mais de um."""
    del model_name  # um provider so; o parametro sobrevive na assinatura publica de calcular_custo_brl
    return PRECO_DEEPSEEK_USD_PER_MTOK


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
#  - PRECO_STT_USD_PER_MTOK: o STT tambem roteia pelo OpenRouter, por chat completions com
#    `input_audio` (settings.openrouter_model_audio_transcribe; default "google/gemini-3.1-flash-lite"
#    em media.py) — faturado por TOKEN, nao por minuto de audio. Tabela publica do Gemini 3.1 Flash
#    Lite: audio de entrada $0.50 / output $1.50. Se o operador fixar outro modelo, ajustar aqui.
PRECO_VISION_USD_PER_MTOK: dict[str, float] = {
    "input": 0.50,
    "output": 3.00,
}
PRECO_STT_USD_PER_MTOK: dict[str, float] = {
    "input": 0.50,
    "output": 1.50,
}


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


def calcular_custo_stt_brl(usage: Any, cotacao_usd_brl: float) -> float:
    """Custo em BRL de UMA transcricao a partir do `usage` do chat completions do OpenRouter.

    Mesma forma do vision (o STT tambem e' chat completions, com um content part `input_audio`):
    `usage=None` (fake de teste sem usage) -> 0.0. Os tokens de audio entram no `prompt_tokens`.
    """
    if usage is None:
        return 0.0
    prompt_t: int = getattr(usage, "prompt_tokens", 0) or 0
    completion_t: int = getattr(usage, "completion_tokens", 0) or 0
    usd: float = (
        prompt_t * PRECO_STT_USD_PER_MTOK["input"] + completion_t * PRECO_STT_USD_PER_MTOK["output"]
    ) / 1_000_000
    return usd * cotacao_usd_brl


def custo_por_atendimento_brl(chat_brl: float, stt_brl: float, vision_brl: float) -> float:
    """Custo total de IA de um atendimento: soma chat + STT + vision (CUSTO-02).

    Funcao pura para o bloco ROI do dashboard (CUSTO-01) compor o custo_IA_por_fechado a partir
    dos tres componentes ja agregados por atendimento_id. Cada parcela e >= 0.
    """
    return chat_brl + stt_brl + vision_brl


def custo_chat_turno_brl(messages: Sequence[Any], cotacao_usd_brl: float) -> float:
    """Custo de chat do TURNO em BRL: soma `calcular_custo_brl` sobre as AIMessages
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
    """Nome do modelo da AIMessage (`response_metadata.model_name`, com fallback `model`), p/
    `custo_chat_turno_brl` precificar cada chamada do turno pela tabela do SEU modelo. Hoje ha um
    provider so (DeepSeek). Duck-typing (sem import de langchain); None -> tabela default."""
    meta = getattr(m, "response_metadata", None) or {}
    return meta.get("model_name") or meta.get("model")


def input_nao_cacheado(usage_metadata: dict[str, Any]) -> int:
    """Tokens de input FRESCO (preco cheio), separados da parcela cacheada.

    O wrapper langchain reporta `usage_metadata["input_tokens"]` como o TOTAL — base + cache_read
    (+ cache_creation, quando o provider a marca). Logo o fresco e o resto apos descontar a leitura
    de cache e a escrita (chaves `ephemeral_5m/1h`, hoje sempre 0 no DeepSeek, que nao cobra escrita
    de cache). Cobrar o `input_tokens` cru a preco de input cheio dobra a conta do prefixo cacheado
    (~5x/turno).
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

    `model_name` escolhe a tabela de preco (`_tabela_preco`); com um provider so (DeepSeek) ela e
    sempre a mesma — o parametro sobrevive na assinatura para o dia em que voltar a haver escolha.

    Le `input_token_details`: `input_tokens` vem como o TOTAL (inclui cache_read + a escrita, quando
    o provider a marca em `ephemeral_5m/1h`), entao a parcela de input cheio e `input_nao_cacheado`
    — o resto, ja descontados read/write; o cache entra so nas suas proprias tarifas.

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
    # input/output existem em toda tabela; as chaves de escrita de cache não (o DeepSeek não cobra
    # escrita — o cache dele é automático no provider). `.get(..., 0.0)` evita KeyError e zera a
    # parcela quando o modelo não a tarifa.
    usd: float = (
        input_t * preco["input"]
        + output_t * preco["output"]
        + cache_write_1h * preco.get("cache_write_1h", 0.0)
        + cache_write_5m * preco.get("cache_write_5m", 0.0)
        + cache_read * preco.get("cache_read", 0.0)
    ) / 1_000_000
    return usd * cotacao_usd_brl


def modelos_para_langfuse() -> list[dict[str, Any]]:
    """Definicoes de modelo p/ o Langfuse (ADR 0019) precificar o `total_cost` de cada generation.

    Sem elas o Langfuse nao casa o `deepseek-v4-flash` que o CallbackHandler reporta -> `model_id`
    nulo e `total_cost=0` em TODO trace (o usage/tokens ja chega certo, ate o cache_read separado;
    falta so o pricing). Os precos DERIVAM das tabelas `PRECO_*` acima (fonte unica) -> sem drift:
    mexeu na tarifa la em cima, o registro do Langfuse acompanha. Precos em USD por TOKEN
    (as tabelas sao USD/MTok).

    So `input`/`output`: o endpoint publico de modelo do Langfuse (`api.models.create`) nao aceita
    preco por usage-type custom, entao o `input_cache_read` do DeepSeek fica NAO-precificado (parcela
    ~3-4% do turno, 50x mais barata que o miss — o Langfuse a trata como gratis). O custo BRL PRECISO
    (com cache) segue no Prometheus / `atendimentos.custo_ia_brl` via `calcular_custo_brl`; o
    `total_cost` do Langfuse e o espelho de relance, nao a contabilidade.

    Vision (Pix) e STT NAO entram: rodam fora do grafo, sem o CallbackHandler -> nao viram generation
    no trace, logo registrar seus modelos seria pricing morto. Consumida no boot do worker e nos rigs
    via `core.tracing.registrar_modelos_langfuse` (dado puro: `core/` nao importa `agente/`)."""
    return [
        {
            "model_name": "deepseek-v4-flash",
            # alias legado `deepseek-chat` aposenta 2026-07-24 (settings) — o pattern cobre ate la.
            "match_pattern": r"(?i)^(deepseek-v4-flash|deepseek-chat)$",
            "input_price": PRECO_DEEPSEEK_USD_PER_MTOK["input"] / 1_000_000,
            "output_price": PRECO_DEEPSEEK_USD_PER_MTOK["output"] / 1_000_000,
        },
    ]
