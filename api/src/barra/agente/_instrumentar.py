"""Instrumentacao de tokens/custo por CHAMADA de LLM em Prometheus (03 §4.2).

Fonte unica compartilhada pelo no llm (chat #1 + extracao forcada barata) e pelo output_guard
(LLM-judge de AUP). Antes vivia privada no nos/llm.py e so o chat era instrumentado -- o judge
queimava tokens a cada bolha sem aparecer em AGENTE_TURNO_TOKENS/AGENTE_CUSTO_TURNO_BRL. Extraida
p/ ca para os dois leitores chamarem a MESMA logica (incl. a reinjecao de cache do DeepSeek-direct),
sem duplicar nem criar dependencia no<->no.

`_custo.py` segue PURO (sem metrica): este modulo e a camada de telemetria que o consome.
"""

from typing import Any

from barra.core.metrics import AGENTE_CUSTO_TURNO_BRL, AGENTE_TURNO_TOKENS
from barra.settings import get_settings

from ._custo import cache_read_deepseek, calcular_custo_brl


def instrumentar_tokens(resp: Any, modelo: str) -> None:
    """Incrementa AGENTE_TURNO_TOKENS nas 4 series {input,output,cache_read,cache_write} (03 §4.2)
    e observa AGENTE_CUSTO_TURNO_BRL para UMA resposta de LLM.

    WRITE vem de `ephemeral_5m+ephemeral_1h`, NUNCA de `cache_creation` (no langchain-anthropic
    1.4.3 esse campo vem sempre 0 -- spike 2026-05-24). Sob DeepSeek essas chaves Anthropic ausentam
    no usage_metadata -> write=0, que e o valor CORRETO (o DeepSeek nao cobra escrita de cache; so o
    cache_read importa, reinjetado abaixo). `modelo` e o nome do modelo (claude-sonnet-4-6,
    claude-haiku-4-5, deepseek-v4-flash, id OpenRouter), nao o modelo_id da agencia: misturar quebra
    o tripwire de write-rate. `getattr` porque usage_metadata so existe em AIMessage, nao em
    BaseMessage -- e deixa o duck-typing servir o judge (raw do structured output) sem import de langchain.
    """
    um = getattr(resp, "usage_metadata", None)
    if not um:
        return
    # DeepSeek-direct reporta o cache-hit so em token_usage.prompt_cache_hit_tokens -- o langchain-openai
    # nao mapeia p/ input_token_details.cache_read. Reinjeta antes de medir/cobrar: sem isso a metrica
    # cache_read e o custo BRL (aqui E no coordenador, que le este MESMO objeto no canal `messages`)
    # tratam todo o prefixo como input cheio (~10x). Mutacao in-place de `um` (= resp.usage_metadata)
    # propaga aos dois leitores. Idempotente: so injeta quando o mapeamento padrao veio zerado.
    # Anthropic/OpenRouter -> hit=0, no-op.
    hit = cache_read_deepseek(getattr(resp, "response_metadata", None))
    if hit:
        det_ds = dict(um.get("input_token_details") or {})
        if not det_ds.get("cache_read"):
            det_ds["cache_read"] = hit
            um["input_token_details"] = det_ds
    det = um.get("input_token_details") or {}
    read = det.get("cache_read", 0)
    write = det.get("ephemeral_5m_input_tokens", 0) + det.get("ephemeral_1h_input_tokens", 0)
    AGENTE_TURNO_TOKENS.labels(modelo, "input").inc(um["input_tokens"])
    AGENTE_TURNO_TOKENS.labels(modelo, "output").inc(um["output_tokens"])
    AGENTE_TURNO_TOKENS.labels(modelo, "cache_read").inc(read)
    AGENTE_TURNO_TOKENS.labels(modelo, "cache_write").inc(write)
    # Custo BRL: tabela do PROPRIO modelo (`calcular_custo_brl` despacha por `modelo`) + cotacao
    # USD/BRL (settings). Observado pelo Histogram AGENTE_CUSTO_TURNO_BRL (meta em settings.custo_alvo_brl).
    AGENTE_CUSTO_TURNO_BRL.labels(modelo).observe(
        calcular_custo_brl(um, get_settings().usd_brl_cotacao, model_name=modelo)
    )
