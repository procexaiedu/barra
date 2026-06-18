"""Factories de cliente do chat (docs/agente/03 §6.2).

criar_chat_anthropic(): wrapper langchain-anthropic 1.x (ChatAnthropic) usado pelo nó llm —
    thinking disabled + effort=low (suportado pelo Sonnet 4.6).
criar_chat_openrouter(): wrapper langchain-openai (ChatOpenAI) apontado p/ o OpenRouter, usado
    pelas chamadas baratas que podem sair da Anthropic (extração forçada #2, judge de AUP #3)
    quando o provider correspondente está em `openrouter`. Mesma interface a jusante
    (bind_tools/with_structured_output/ainvoke), formato de saída diferente no metadata.
criar_anthropic_client(): raw SDK anthropic 0.97 (dispensável no P0; vision do Pix vai por OpenRouter).

A montagem dos 4 breakpoints de cache_control vive em agente/llm.py:
    - BP_TOOLS: `build_tools_para_bind` (cache_control na ultima tool)
    - BP_GERAL: `build_system_messages` (persona+regras+FAQ fundidos)
    - BP_MODELO: `build_system_messages` (identidade+programas por-modelo, opcional)
    - BP_JANELA: `marcar_cache_na_penultima` (cache na penultima msg da janela)
"""

from typing import Any

from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from barra.settings import Settings

# Motivo de parada provider-aware: a Anthropic reporta `stop_reason`, OpenAI/OpenRouter
# `finish_reason`. Os dois conjuntos abaixo unificam os dois vocabulários para os caminhos que
# trocam de provider (#2 extração forçada, #3 judge de AUP); a #1 (Sonnet) segue lendo
# `stop_reason` direto no nó llm.
# - TRUNCADA: a resposta foi cortada (args de tool podem vir incompletos -> não despachar).
# - INSEGURA: além de truncada, recusa do provider -> veredito do judge não é confiável
#   (default seguro: bloqueia+escala). `content_filter`/`refusal` são as recusas OpenAI/Anthropic.
PARADA_TRUNCADA = frozenset({"max_tokens", "model_context_window_exceeded", "length"})
PARADA_INSEGURA = PARADA_TRUNCADA | frozenset({"refusal", "content_filter"})


def motivo_parada(response_metadata: dict[str, Any] | None) -> str | None:
    """Motivo de parada provider-agnóstico: `stop_reason` (Anthropic) ou `finish_reason` (OpenAI).

    Lê o que existir no `response_metadata` da AIMessage. None quando nenhum dos dois está
    presente (fake de teste / resposta sem metadata) — o caller trata como "não inseguro".
    """
    meta = response_metadata or {}
    return meta.get("stop_reason") or meta.get("finish_reason")


def nome_modelo(chat: Any) -> str:
    """Nome do modelo do chat, tolerando os dois wrappers: ChatAnthropic expõe `.model`,
    ChatOpenAI expõe `.model_name`. Usado nos labels de métrica (token/custo por modelo)."""
    return getattr(chat, "model", None) or getattr(chat, "model_name", None) or ""


def criar_chat_anthropic(
    settings: Settings, *, modelo: str | None = None, com_effort: bool = True
) -> ChatAnthropic:
    """Wrapper LangChain do ChatAnthropic usado pelo grafo (nó llm).

    Sonnet 4.6 com thinking desabilitado e effort=low (03 §6.1/§6.2): tom e tamanho da
    resposta vêm da persona/few-shot, não do effort — cujo default no 4.6 é high (mais
    latência/custo). max_tokens é guard-rail (~1024). Retry de 429/5xx/timeout fica a
    cargo do SDK (max_retries), sem wrapper manual (decisão M0).

    `com_effort=False` p/ modelos que NÃO aceitam o parâmetro `effort` (ex.: Haiku 4.5, usado
    no LLM-judge de AUP do output_guard) — a langchain só envia `effort` quando truthy, então
    `effort=None` o omite e evita o 400. Sonnet 4.6 mantém o default.
    """
    modelo = modelo or settings.anthropic_modelo_principal
    return ChatAnthropic(
        model=modelo,  # campo canônico no langchain-anthropic 1.x (alias model_name é só de escrita)
        api_key=settings.anthropic_api_key,
        max_tokens=settings.anthropic_max_tokens,
        thinking={"type": settings.anthropic_thinking},
        effort=settings.anthropic_effort if com_effort else None,
        max_retries=2,
        timeout=60.0,
    )


def criar_chat_openrouter(
    settings: Settings,
    *,
    modelo: str,
    require_parameters: bool = True,
    reasoning_off: bool = False,
    temperature: float | None = None,
    quantizations: list[str] | None = None,
) -> ChatOpenAI:
    """Wrapper LangChain do ChatOpenAI apontado p/ o OpenRouter (base_url OpenAI-compatível).

    Espelha `criar_chat_anthropic` para as chamadas que podem trocar de provider (chat #1,
    extração forçada #2, judge de AUP #3): mesma interface a jusante (bind_tools,
    with_structured_output, ainvoke). NÃO aceita `thinking`/`effort` (parâmetros Anthropic) —
    omitidos.

    `require_parameters` (default True): `provider.require_parameters=true` (via extra_body,
    espelha pix.py) força o roteamento dinâmico do OpenRouter a um provider que honra
    tool_choice/json_schema, em vez de cair num provider que os ignora silenciosamente. As
    chamadas baratas #2/#3 dependem disso. **Alguns modelos não têm provider que satisfaça o
    flag** (ex.: `deepseek-v4-flash` → 404 "no endpoints" sempre, mesmo honrando tool_choice):
    para o chat #1 nesses modelos, passar `require_parameters=False`.

    `reasoning_off` (default False): quando True, desliga o reasoning do modelo via
    `reasoning.enabled=false` (campo unificado do OpenRouter) — espelha o `effort=low` deliberado
    do Sonnet no chat (a voz vem da persona, não do reasoning; corta latência/custo de modelos
    de raciocínio como o DeepSeek V4 Flash).

    `temperature` (default None): quando setada, vai pro request; None omite (default do provider).
    Só o chat #1 passa um valor (1.3, recomendação DeepSeek p/ chat) — as chamadas baratas #2/#3
    chamam sem, ficando determinísticas. **Só tem efeito com `reasoning_off=True`**: o thinking mode
    do DeepSeek ignora temperature/top_p (langchain omite o campo quando None).

    `quantizations` (default None): piso de qualidade do roteamento OpenRouter — restringe os
    provedores aos níveis de quantização listados (`provider.quantizations`, ex.: ["fp8"]). O
    `deepseek-v4-flash` é servido em FP4/FP8/Unknown por ~18 provedores; sem piso, o roteamento pode
    cair num FP4 que degrada a voz/structured output de forma imprevisível. None = sem restrição.

    `modelo` é obrigatório (o id OpenRouter do candidato): a factory só é chamada quando o
    provider correspondente está em `openrouter`, e o settings valida que o id está setado.
    """
    provider: dict[str, Any] = {}
    if require_parameters:
        provider["require_parameters"] = True
    if quantizations:
        provider["quantizations"] = list(quantizations)
    extra_body: dict[str, Any] = {}
    if provider:
        extra_body["provider"] = provider
    if reasoning_off:
        extra_body["reasoning"] = {"enabled": False}
    return ChatOpenAI(
        model=modelo,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        max_tokens=settings.anthropic_max_tokens,
        temperature=temperature,  # None -> langchain omite (default do provider)
        max_retries=2,
        timeout=60.0,
        extra_body=extra_body,
    )


def criar_chat_deepseek(
    settings: Settings, *, modelo: str | None = None, temperature: float | None = None
) -> ChatOpenAI:
    """Wrapper do ChatOpenAI apontado DIRETO p/ a API DeepSeek (api.deepseek.com), OpenAI-compatível.

    Usado pelo chat #1 (llm_chat_provider=deepseek) e pelo judge de AUP (output_guard_provider=
    deepseek): vai direto no DeepSeek (não no pool do OpenRouter) por dois motivos que pesam em escala
    — (1) o cache automático de prefixo só existe no endpoint oficial, e o prefixo byte-idêntico fica
    quente (chat: BP_GERAL global; judge: o system aup_saida.md repetido antes de cada bolha), ~98%
    mais barato no hit; (2) crava modelo/quantização, sem a roleta de FP4 do load-balance.

    `modelo` (default settings.deepseek_model_chat = `deepseek-chat`) já é o modo non-thinking do V4
    Flash — então NÃO precisa de `reasoning_off` nem do `extra_body` de provider/quant (conceitos do
    OpenRouter); evita o thinking que corromperia structured output (judge) e ignoraria temperature
    (chat). ⚠️ `deepseek-chat` é alias legado (aposenta 2026-07-24); depois usar `deepseek-v4-flash`
    com parâmetro explícito de non-thinking. `temperature` honrada (non-thinking); None = omite.
    """
    return ChatOpenAI(
        model=modelo or settings.deepseek_model_chat,
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_tokens=settings.anthropic_max_tokens,
        temperature=temperature,
        max_retries=2,
        timeout=60.0,
    )


def criar_anthropic_client(settings: Settings) -> AsyncAnthropic:
    """Stub reservado p/ P1. Sem consumidor no P0: o chat usa criar_chat_anthropic e o
    vision do Pix vai por OpenRouter (06 §2.3). Materializar quando houver vision
    Anthropic-native (03 §6.2)."""
    raise NotImplementedError("criar_anthropic_client é reservado p/ P1 (sem consumidor no P0)")
