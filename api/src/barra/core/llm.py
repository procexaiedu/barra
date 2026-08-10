"""Factories de cliente do chat (docs/agente/03 §6.2).

criar_chat_deepseek(): wrapper langchain-openai (ChatOpenAI) DIRETO na API DeepSeek
    (api.deepseek.com) — o ÚNICO provider dos caminhos de texto do agente (chat #1,
    extração forçada #2, judge de AUP #3), com thinking travado em disabled. Mesma interface a
    jusante (bind_tools/with_structured_output/ainvoke). Única factory de chat do projeto.

A montagem do prefixo (BP_GERAL persona+regras+FAQ + BP_MODELO identidade/programas) vive em
agente/llm.py (`build_system_messages`): SystemMessages de string pura, que o DeepSeek cacheia
automaticamente no provider — sem cache_control.
"""

from typing import Any

from langchain_openai import ChatOpenAI

from barra.settings import Settings

# Motivo de parada provider-aware: `finish_reason` (OpenAI/DeepSeek) ou `stop_reason` (vocabulário
# legado, mantido porque fakes/fixtures antigas ainda o emitem). Os dois conjuntos abaixo unificam
# os vocabulários para todos os caminhos de texto.
# - TRUNCADA: a resposta foi cortada (args de tool podem vir incompletos -> não despachar).
# - INSEGURA: além de truncada, recusa do provider -> veredito do judge não é confiável
#   (default seguro: bloqueia+escala). `content_filter`/`refusal` são as recusas do provider.
PARADA_TRUNCADA = frozenset({"max_tokens", "model_context_window_exceeded", "length"})
# RECUSA: safety filter do provider -> `refusal` (Anthropic) / `content_filter` (OpenAI/OpenRouter).
# Vocabulario canonico unico: lido pelo no llm E pelo coordenador (reclassificacao de exaustao),
# sempre via motivo_parada (provider-agnostico), nunca pelo campo cru stop_reason/finish_reason.
PARADA_RECUSA = frozenset({"refusal", "content_filter"})
PARADA_INSEGURA = PARADA_TRUNCADA | PARADA_RECUSA


def motivo_parada(response_metadata: dict[str, Any] | None) -> str | None:
    """Motivo de parada provider-agnóstico: `finish_reason` (OpenAI/DeepSeek) ou `stop_reason`.

    Lê o que existir no `response_metadata` da AIMessage. None quando nenhum dos dois está
    presente (fake de teste / resposta sem metadata) — o caller trata como "não inseguro".
    """
    meta = response_metadata or {}
    return meta.get("stop_reason") or meta.get("finish_reason")


def nome_modelo(chat: Any) -> str:
    """Nome do modelo do chat: `ChatOpenAI` expõe `.model_name` (o `.model` cobre fakes/wrappers
    que só o definem). Usado nos labels de métrica (token/custo por modelo)."""
    return getattr(chat, "model", None) or getattr(chat, "model_name", None) or ""


class _ChatDeepSeekThinking(ChatOpenAI):
    """ChatOpenAI + compat de thinking do DeepSeek-direct. SÓ o braço B do A/B de evals usa
    (.scratch/ab-thinking-chat); prod roda thinking:disabled e nunca instancia esta classe.

    Dois gaps do langchain-openai que o endpoint exige em modo thinking (doc oficial
    guides/thinking_mode): (1) `reasoning_content` da resposta não é extraído pelo wrapper
    ("use a provider-specific subclass", doc do pacote) -> captura p/ additional_kwargs;
    (2) o campo precisa VOLTAR nas mensagens assistant dos turnos seguintes do loop de tool
    call, senão HTTP 400 -> reinjeção no payload. Cobre só o caminho não-streaming (ainvoke),
    o único que o agente usa.
    """

    def _create_chat_result(
        self, response: Any, generation_info: dict[str, Any] | None = None
    ) -> Any:
        result = super()._create_chat_result(response, generation_info)
        bruto = response if isinstance(response, dict) else response.model_dump()
        # strict=False: em recusa/erro o provider pode devolver menos choices que generations.
        for ger, choice in zip(result.generations, bruto.get("choices") or [], strict=False):
            rc = (choice.get("message") or {}).get("reasoning_content")
            if rc:
                ger.message.additional_kwargs["reasoning_content"] = rc
        return result

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        fontes = self._convert_input(input_).to_messages()
        # strict=False: a conversao para payload e 1:1 hoje, mas um desalinhamento futuro nao
        # deve estourar o turno — no pior caso o campo nao volta e o provider acusa 400.
        for fonte, destino in zip(fontes, payload.get("messages") or [], strict=False):
            rc = getattr(fonte, "additional_kwargs", {}).get("reasoning_content")
            if rc and destino.get("role") == "assistant":
                destino["reasoning_content"] = rc
        return payload


def criar_chat_deepseek(
    settings: Settings,
    *,
    modelo: str | None = None,
    temperature: float | None = None,
    thinking: str = "disabled",
) -> ChatOpenAI:
    """Wrapper do ChatOpenAI apontado DIRETO p/ a API DeepSeek (api.deepseek.com), OpenAI-compatível.

    Único provider dos 3 caminhos de texto do agente ao vivo (chat #1, extração forçada #2 e judge
    de AUP #3): vai direto no DeepSeek (não no pool do OpenRouter) por dois motivos que pesam em escala
    — (1) o cache automático de prefixo só existe no endpoint oficial, e o prefixo byte-idêntico fica
    quente (chat: BP_GERAL global; judge: o system aup_saida.md repetido antes de cada bolha), ~98%
    mais barato no hit; (2) crava modelo/quantização, sem a roleta de FP4 do load-balance.

    `modelo` (default settings.deepseek_model_chat = `deepseek-v4-flash`) é o id único do V4 Flash;
    os aliases legados `deepseek-chat`/`deepseek-reasoner` foram aposentados em 2026-07-24 15:59 UTC
    (hoje HTTP 400). O id **não fixa snapshot** — em 2026-07-31 o provider promoveu o V4 Flash oficial
    (`DeepSeek-V4-Flash-0731`, mesma arquitetura, post-training novo) atrás do mesmo id, e não existe
    id datado para pinar: mudança de peso chega sem deploy nosso, então deriva de conduta se mede por
    eval, não por diff. O id cru
    tem **thinking LIGADO por default** (doc oficial: "the thinking toggle defaults to enabled"),
    então o default `thinking="disabled"` trava non-thinking via extra_body — thinking ligado
    corromperia o structured output (extração #2/judge #3), ignoraria a `temperature` (chat #1) e
    tomaria HTTP 400 nas tool calls sem a compat de `reasoning_content`. Não usa `reasoning_off`
    nem `provider`/`quantizations` (conceitos do OpenRouter, não do endpoint direto).
    `temperature` honrada (non-thinking); None = omite.

    `thinking` != "disabled" ("low"/"high"/"max" = `reasoning_effort` do provider) é o braço B do
    A/B de evals (.scratch/ab-thinking-chat): devolve `_ChatDeepSeekThinking` (compat de
    `reasoning_content`) e OMITE a temperatura (o provider a ignora em thinking — doc oficial).
    Nenhum caminho de prod passa o parâmetro; só o chat #1 o lê de
    `settings.deepseek_thinking_chat` (default "disabled").
    """
    modelo = modelo or settings.deepseek_model_chat
    if thinking != "disabled":
        return _ChatDeepSeekThinking(
            model=modelo,
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
            max_tokens=settings.llm_max_tokens,
            max_retries=2,
            timeout=60.0,
            extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": thinking},
        )
    return ChatOpenAI(
        model=modelo,
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_tokens=settings.llm_max_tokens,
        temperature=temperature,
        max_retries=2,
        timeout=60.0,
        # thinking disabled explícito: o id cru `deepseek-v4-flash` liga thinking por default.
        extra_body={"thinking": {"type": "disabled"}},
    )
