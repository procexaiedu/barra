"""Instrumentacao de tokens/custo por CHAMADA de LLM em Prometheus (03 §4.2).

Fonte unica compartilhada pelo no llm (chat #1 + extracao forcada barata) e pelo output_guard
(LLM-judge de AUP). Antes vivia privada no nos/llm.py e so o chat era instrumentado -- o judge
queimava tokens a cada bolha sem aparecer em AGENTE_TURNO_TOKENS/AGENTE_CUSTO_TURNO_BRL. Extraida
p/ ca para os dois leitores chamarem a MESMA logica (incl. a reinjecao de cache do DeepSeek-direct),
sem duplicar nem criar dependencia no<->no.

`_custo.py` segue PURO (sem metrica): este modulo e a camada de telemetria que o consome.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from barra.core.metrics import (
    AGENTE_CUSTO_TURNO_BRL,
    AGENTE_LLM_DURACAO,
    AGENTE_MODELO_FINGERPRINT,
    AGENTE_NO_DURACAO,
    AGENTE_TURNO_TOKENS,
)
from barra.settings import get_settings

from ._custo import cache_read_deepseek, calcular_custo_brl


@contextmanager
def medir_no(no: str) -> Iterator[None]:
    """Cronometra UM no do grafo em `AGENTE_NO_DURACAO{no=...}`.

    Context manager usado DENTRO do corpo do no, de proposito -- e nao um decorator aplicado em
    `build_graph`. O LangGraph inspeciona a assinatura do callable para decidir se injeta
    `runtime`/`config`, e um wrapper que nao a preserve exatamente faz o no receber os argumentos
    errados em silencio (footgun ja tomado neste projeto com as factories kw-only). Um `with` no
    corpo nao tem como mexer na assinatura.

    Mede tambem o caminho que levanta: o `finally` registra a duracao mesmo quando o no estoura,
    porque um no que falha DEPOIS de 30s e exatamente o caso que precisamos enxergar.
    """
    inicio = perf_counter()
    try:
        yield
    finally:
        AGENTE_NO_DURACAO.labels(no).observe(perf_counter() - inicio)


@contextmanager
def medir_llm(caminho: str) -> Iterator[None]:
    """Cronometra UMA chamada de LLM em `AGENTE_LLM_DURACAO{caminho=...}`.

    `caminho` (chat|extracao|extracao_retry|judge_aup|regen|judge_pos_envio) e o corte que a
    label `modelo` nao da: os tres caminhos do turno rodam o MESMO `deepseek-v4-flash`, entao em
    Prometheus eram indistinguiveis -- so o Langfuse os separava, via `nomear_run`.
    """
    inicio = perf_counter()
    try:
        yield
    finally:
        AGENTE_LLM_DURACAO.labels(caminho).observe(perf_counter() - inicio)


def registrar_fingerprint(resp: Any, modelo: str) -> None:
    """Publica o `system_fingerprint` da resposta como serie de presenca (sempre 1).

    O alias do DeepSeek e movel e nao ha snapshot para pinar (a API rejeita `-0731`/`-latest`),
    entao a troca de pesos so pode ser DETECTADA depois do fato. Uma serie nova nascendo sob o
    mesmo `modelo` e o sinal; `count by (modelo)` > 1 numa janela e o alerta.
    """
    fp = (getattr(resp, "response_metadata", None) or {}).get("system_fingerprint")
    if fp:
        AGENTE_MODELO_FINGERPRINT.labels(modelo, str(fp)).set(1)


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
    # Antes do early-return: o fingerprint vale mesmo na resposta sem usage_metadata (o raw do
    # structured output do judge), e e justamente onde uma troca de build passaria despercebida.
    registrar_fingerprint(resp, modelo)
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
    # Serie `reasoning`: os tokens de raciocinio do thinking (chat #1, default "low" em prod). NAO e
    # uma parcela extra — ela ja esta DENTRO de `output_tokens` (medido ao vivo 11/08: 270 output =
    # 256 raciocinio + 14 de fala), entao o custo nao muda; a serie separada existe porque o peso do
    # raciocinio e a variavel que decide se o thinking se paga. Ausente em non-thinking -> 0.
    raciocinio = (um.get("output_token_details") or {}).get("reasoning", 0)
    if raciocinio:
        AGENTE_TURNO_TOKENS.labels(modelo, "reasoning").inc(raciocinio)
    # Custo BRL: tabela do PROPRIO modelo (`calcular_custo_brl` despacha por `modelo`) + cotacao
    # USD/BRL (settings). Observado pelo Histogram AGENTE_CUSTO_TURNO_BRL (meta em settings.custo_alvo_brl).
    AGENTE_CUSTO_TURNO_BRL.labels(modelo).observe(
        calcular_custo_brl(um, get_settings().usd_brl_cotacao, model_name=modelo)
    )
