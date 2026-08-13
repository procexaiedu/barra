"""Factories de cliente do chat (docs/agente/03 §6.2).

criar_chat_deepseek(): wrapper langchain-openai (ChatOpenAI) DIRETO na API DeepSeek
    (api.deepseek.com) — o ÚNICO provider dos caminhos de texto do agente (chat #1,
    extração forçada #2, judge de AUP #3). O chat #1 roda THINKING (`reasoning_effort`, default
    "low"); extração e judge ficam travados em disabled (thinking corromperia o structured
    output). Mesma interface a jusante (bind_tools/with_structured_output/ainvoke). Única
    factory de chat do projeto.

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


def nomear_run(runnable: Any, nome: str) -> Any:
    """Batiza a observation que este runnable gera no trace (`run_name` do LangChain).

    Sem isso TODA chamada de LLM do turno aparece no Langfuse como uma generation "ChatOpenAI" — a
    fala, a extração forçada e a regen do guard indistinguíveis a olho, e `fetch_observations(name=)`
    inútil. Com nome, cada caminho é filtrável direto.

    Tolerante por desenho: os fakes de chat dos testes implementam só `bind_tools`/`ainvoke`, não a
    interface Runnable inteira. Sem `with_config`, devolve o objeto como veio — o nome é
    observabilidade e nunca pode ser motivo de o grafo não montar.
    """
    with_config = getattr(runnable, "with_config", None)
    return with_config({"run_name": nome}) if callable(with_config) else runnable


def nome_modelo(chat: Any) -> str:
    """Nome do modelo do chat: `ChatOpenAI` expõe `.model_name` (o `.model` cobre fakes/wrappers
    que só o definem). Usado nos labels de métrica (token/custo por modelo)."""
    return getattr(chat, "model", None) or getattr(chat, "model_name", None) or ""


class _ChatDeepSeekThinking(ChatOpenAI):
    """ChatOpenAI + compat de thinking do DeepSeek-direct. É a classe do chat #1 de PROD desde
    11/08/2026 (`settings.deepseek_thinking_chat` default "low") e dos rigs; só some do caminho
    quando alguém volta o regime para "disabled" pelo Env.

    Dois gaps do langchain-openai que o endpoint exige em modo thinking (doc oficial
    guides/thinking_mode): (1) `reasoning_content` da resposta não é extraído pelo wrapper
    ("use a provider-specific subclass", doc do pacote) -> captura p/ additional_kwargs;
    (2) o campo precisa VOLTAR nas mensagens assistant do loop de tool call ABERTO, senão
    HTTP 400 -> reinjeção no payload. Cobre só o caminho não-streaming (ainvoke), o único
    que o agente usa.

    Contrato REAL da API (sondado em 2026-08-10 contra api.deepseek.com): o 400 "The
    `reasoning_content` in the thinking mode must be passed back" dispara quando QUALQUER
    assistant COM tool_calls do loop de tool aberto (assistant+tool no rabo das messages)
    vai sem o campo; assistant de texto puro do histórico e loops já fechados passam sem
    ele, e `reasoning_content: ""` é aceito em todas as posições. O provider às vezes
    devolve rc vazio/ausente numa iteração do loop (típico após ToolMessage) — sem
    placeholder, a iteração seguinte reenviava essa assistant(tool_calls) sem o campo e o
    turno morria em 400 (braço B do A/B, conversas multi-turno/longas). Por isso a
    reinjeção garante o campo em TODA assistant com tool_calls: o capturado quando houver,
    `""` quando não.
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
            if destino.get("role") != "assistant":
                continue
            rc = getattr(fonte, "additional_kwargs", {}).get("reasoning_content")
            if rc:
                destino["reasoning_content"] = rc
            elif destino.get("tool_calls"):
                # assistant(tool_calls) sem rc capturado (provider devolveu vazio/ausente na
                # iteração, ou mensagem re-hidratada sem additional_kwargs): a API exige o campo
                # no loop aberto (400 sem ele) e aceita "" -> placeholder vazio.
                destino["reasoning_content"] = ""
        return payload


def tentativas_que_cabem_no_turno(settings: Settings, *, teto: int = 2) -> int:
    """`max_retries` que o ORÇAMENTO DO TURNO comporta — 0 quando só cabe uma tentativa.

    O `timeout` do httpx é POR TENTATIVA, e o cliente OpenAI retenta timeout por conta própria. Com
    `max_retries=2` fixo (estado até 12/08/2026), um endpoint pendurado custava até 3 x 40s num
    único `ainvoke` e o `asyncio.wait_for(turno_timeout_s)` do coordenador matava o turno POR FORA
    do grafo — `timeout_grafo` -> handoff terminal, cliente sem bolha —, que é exatamente o modo de
    falha que o `llm_timeout_s < turno_timeout_s` da r3 existe para eliminar. A desigualdade valia
    para UMA chamada e as retentativas a desfaziam em silêncio.

    Derivado dos dois settings em vez de literal para que o invariante sobreviva a quem mexer nos
    números: com 40/60 cabe uma tentativa (`max_retries=0`), e baixar o `llm_timeout_s` devolve as
    retentativas sozinho. `teto` mantém o comportamento histórico como limite superior — isto aperta
    o pior caso, nunca o afrouxa.

    Cabe uma tentativa a MENOS do que a conta pura permitiria porque o SDK dorme entre elas
    (backoff) e o resto do turno (nós determinísticos, DB, guard) também consome do mesmo teto.
    """
    cabem = int(settings.turno_timeout_s // settings.llm_timeout_s)
    return max(0, min(teto, cabem - 2))  # -1 pela tentativa inicial, -1 de margem


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
    quente (chat: BP_GERAL global; judge: o system aup_saida.md repetido a cada turno), ~98%
    mais barato no hit; (2) crava modelo/quantização, sem a roleta de FP4 do load-balance.

    `modelo` (default settings.deepseek_model_chat = `deepseek-v4-flash`) é o id único do V4 Flash;
    os aliases legados `deepseek-chat`/`deepseek-reasoner` foram aposentados em 2026-07-24 15:59 UTC
    (hoje HTTP 400). O id **não fixa snapshot** — em 2026-07-31 o provider promoveu o V4 Flash oficial
    (`DeepSeek-V4-Flash-0731`, mesma arquitetura, post-training novo) atrás do mesmo id, e não existe
    id datado para pinar: mudança de peso chega sem deploy nosso, então deriva de conduta se mede por
    eval, não por diff. O id cru
    tem **thinking LIGADO por default** (doc oficial: "the thinking toggle defaults to enabled"),
    e o default `thinking="disabled"` DESTA factory trava non-thinking via extra_body para quem
    chama sem argumento — extração #2 e judge #3, onde thinking corromperia o structured output.
    Não usa `reasoning_off` nem `provider`/`quantizations` (conceitos do OpenRouter, não do
    endpoint direto). `temperature` honrada (non-thinking); None = OMITE o campo do payload, isto e,
    vale o default do PROVIDER (DeepSeek ~1.0) — omissao NAO e determinismo: quem quer veredito
    reprodutivel (extracao #2, judge de AUP #3, judge pos-envio) passa
    `temperature=settings.judge_temperature` (0.0 por default).

    `timeout` (httpx, por chamada) sai de `settings.llm_timeout_s` e tem de ficar ESTRITAMENTE
    abaixo de `settings.turno_timeout_s` (teto do grafo, no coordenador): com os dois iguais — 60.0
    literais nos dois lugares ate 12/08/2026 — a chamada pendurada estourava o TURNO por fora do
    grafo (`timeout_grafo` -> handoff terminal, cliente sem bolha) em vez de morrer dentro dele,
    onde o fallback deterministico do guard existe. O timeout é por TENTATIVA, então quem fecha o
    invariante é o par com `max_retries`: ele vem de `tentativas_que_cabem_no_turno` (ver lá), não
    do `2` fixo que multiplicava o pior caso por três.

    `thinking` != "disabled" ("low"/"high"/"max" = `reasoning_effort` do provider) devolve
    `_ChatDeepSeekThinking` (compat de `reasoning_content` + teto de tokens próprio) e OMITE a
    temperatura (o provider a ignora em thinking — doc oficial). Só o chat #1 passa o parâmetro,
    lendo `settings.deepseek_thinking_chat` — default "low", isto é, PROD roda thinking desde
    11/08/2026; o raciocínio capturado vira observável no trace via
    `agente._texto_turno.raciocinio_do_turno`.
    """
    modelo = modelo or settings.deepseek_model_chat
    if thinking != "disabled":
        return _ChatDeepSeekThinking(
            model=modelo,
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
            # Teto PRÓPRIO do thinking (`llm_max_tokens_thinking`): em thinking o `max_tokens` cobre
            # a saída inteira — raciocínio + fala —, então o teto pensado só para a fala cortaria a
            # bolha no meio do raciocínio (`finish_reason=length` -> turno truncado/vazio).
            max_tokens=settings.llm_max_tokens_thinking,
            max_retries=tentativas_que_cabem_no_turno(settings),
            timeout=settings.llm_timeout_s,
            extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": thinking},
        )
    return ChatOpenAI(
        model=modelo,
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_tokens=settings.llm_max_tokens,
        temperature=temperature,
        max_retries=tentativas_que_cabem_no_turno(settings),
        timeout=settings.llm_timeout_s,
        # thinking disabled explícito: o id cru `deepseek-v4-flash` liga thinking por default.
        extra_body={"thinking": {"type": "disabled"}},
    )
