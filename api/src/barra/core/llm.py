"""Factories de cliente do chat (docs/agente/03 §6.2).

criar_chat_deepseek(): wrapper langchain-openai (ChatOpenAI) DIRETO na API DeepSeek
    (api.deepseek.com) — o ÚNICO provider dos 3 caminhos de texto do agente ao vivo (chat #1,
    extração forçada #2, judge de AUP #3), com thinking travado em disabled. Mesma interface a
    jusante (bind_tools/with_structured_output/ainvoke).
criar_chat_anthropic(): wrapper langchain-anthropic 1.x (ChatAnthropic). NÃO serve o agente ao
    vivo (DeepSeek-only); sobra para o LLM-judge dos evals (api/evals/).
criar_anthropic_client(): raw SDK anthropic 0.97 (dispensável no P0; vision do Pix vai por OpenRouter).

A montagem do prefixo (BP_GERAL persona+regras+FAQ + BP_MODELO identidade/programas) vive em
agente/llm.py (`build_system_messages`): SystemMessages de string pura, que o DeepSeek cacheia
automaticamente no provider — sem cache_control.
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
# RECUSA: safety filter do provider -> `refusal` (Anthropic) / `content_filter` (OpenAI/OpenRouter).
# Vocabulario canonico unico: lido pelo no llm E pelo coordenador (reclassificacao de exaustao),
# sempre via motivo_parada (provider-agnostico), nunca pelo campo cru stop_reason/finish_reason.
PARADA_RECUSA = frozenset({"refusal", "content_filter"})
PARADA_INSEGURA = PARADA_TRUNCADA | PARADA_RECUSA


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


def criar_chat_deepseek(
    settings: Settings, *, modelo: str | None = None, temperature: float | None = None
) -> ChatOpenAI:
    """Wrapper do ChatOpenAI apontado DIRETO p/ a API DeepSeek (api.deepseek.com), OpenAI-compatível.

    Único provider dos 3 caminhos de texto do agente ao vivo (chat #1, extração forçada #2 e judge
    de AUP #3): vai direto no DeepSeek (não no pool do OpenRouter) por dois motivos que pesam em escala
    — (1) o cache automático de prefixo só existe no endpoint oficial, e o prefixo byte-idêntico fica
    quente (chat: BP_GERAL global; judge: o system aup_saida.md repetido antes de cada bolha), ~98%
    mais barato no hit; (2) crava modelo/quantização, sem a roleta de FP4 do load-balance.

    `modelo` (default settings.deepseek_model_chat = `deepseek-v4-flash`) é o id atual do V4 Flash;
    os aliases legados `deepseek-chat`/`deepseek-reasoner` aposentam 2026-07-24 15:59 UTC. O id cru
    tem **thinking LIGADO por default** (doc oficial: "the thinking toggle defaults to enabled"),
    então a factory passa SEMPRE `extra_body={"thinking": {"type": "disabled"}}` p/ travar
    non-thinking — sem isso o thinking corromperia o structured output (extração #2/judge #3),
    ignoraria a `temperature` (chat #1) e ainda arriscaria HTTP 400 nas tool calls (o provider exige
    devolver `reasoning_content` nos turnos seguintes, que o langchain-openai não conhece). Não usa
    `reasoning_off` nem `provider`/`quantizations` (conceitos do OpenRouter, não do endpoint direto).
    `temperature` honrada (non-thinking); None = omite.
    """
    return ChatOpenAI(
        model=modelo or settings.deepseek_model_chat,
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_tokens=settings.anthropic_max_tokens,
        temperature=temperature,
        max_retries=2,
        timeout=60.0,
        # thinking disabled explícito: o id cru `deepseek-v4-flash` liga thinking por default.
        extra_body={"thinking": {"type": "disabled"}},
    )


def criar_anthropic_client(settings: Settings) -> AsyncAnthropic:
    """Stub reservado p/ P1. Sem consumidor no P0: o chat usa criar_chat_anthropic e o
    vision do Pix vai por OpenRouter (06 §2.3). Materializar quando houver vision
    Anthropic-native (03 §6.2)."""
    raise NotImplementedError("criar_anthropic_client é reservado p/ P1 (sem consumidor no P0)")
