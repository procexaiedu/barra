"""Factories de cliente Anthropic do chat (docs/agente/03 §6.2).

criar_chat_anthropic(): wrapper langchain-anthropic 1.x (ChatAnthropic) usado pelo nó llm —
    thinking disabled + effort=low (suportado pelo Sonnet 4.6).
criar_anthropic_client(): raw SDK anthropic 0.97 (dispensável no P0; vision do Pix vai por OpenRouter).

A montagem dos 4 breakpoints de cache_control vive em agente/llm.py:
    - BP_TOOLS: `build_tools_para_bind` (cache_control na ultima tool)
    - BP_GERAL: `build_system_messages` (persona+regras+FAQ fundidos)
    - BP_MODELO: `build_system_messages` (identidade+programas por-modelo, opcional)
    - BP_JANELA: `marcar_cache_na_penultima` (cache na penultima msg da janela)
"""

from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic

from barra.settings import Settings


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


def criar_anthropic_client(settings: Settings) -> AsyncAnthropic:
    """Stub reservado p/ P1. Sem consumidor no P0: o chat usa criar_chat_anthropic e o
    vision do Pix vai por OpenRouter (06 §2.3). Materializar quando houver vision
    Anthropic-native (03 §6.2)."""
    raise NotImplementedError("criar_anthropic_client é reservado p/ P1 (sem consumidor no P0)")
