"""Setup LangSmith — projeto barra-vips-{ambiente}, tags por conversa_id/modelo_id.

Hard gate de PII: o tracing só sobe com um anonymizer construível mascarando inputs/outputs/
metadata (chave/titular Pix, telefone/JID, nome, endereço, conteúdo livre). Sem anonymizer,
forçamos LANGCHAIN_TRACING_V2=false — nunca subimos tracing cru (PII vazaria para o LangSmith).
"""

import logging
import os
import re
from collections.abc import Callable
from types import ModuleType
from typing import Any

import langsmith.run_trees as run_trees
from langsmith import Client
from langsmith.anonymizer import create_anonymizer

from barra.settings import Settings

try:
    import sentry_sdk as _sentry_sdk
except ModuleNotFoundError:  # pragma: no cover
    sentry_sdk: ModuleType | None = None
else:
    sentry_sdk = _sentry_sdk

logger = logging.getLogger(__name__)

# Chaves cujo valor é PII e nunca pode ir para o LangSmith (match por substring, case-insensitive
# no último segmento do path). Cobre identidade da modelo/cliente, Pix, geo e o conteúdo livre da
# conversa (mensagens carregam nome/endereço/Pix que regex não pega de forma confiável).
_CHAVES_PII = (
    "telefone",
    "phone",
    "msisdn",
    "jid",
    "remotejid",
    "pushname",
    "nome",
    "name",
    "endereco",
    "endereço",
    "address",
    "logradouro",
    "rua",
    "cep",
    "latitude",
    "longitude",
    "chave",
    "pix",
    "titular",
    "cpf",
    "cnpj",
    "rg",
    "content",
    "conteudo",
    "conteúdo",
    "texto",
    "text",
    "mensagem",
    "message",
    "body",
    "caption",
    "transcricao",
    "transcrição",
    "transcript",
)

# Backstop por valor: identificadores estruturados (JID, E.164, CPF, e-mail) que possam aparecer
# sob chaves inócuas.
_VALOR_PII = re.compile(
    r"\d+@[\w.]+"  # JID WhatsApp (5511...@s.whatsapp.net)
    r"|\+?\d{10,13}\b"  # E.164 / telefone só dígitos (com ou sem DDI 55)
    r"|\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"  # CPF
    r"|[\w.+-]+@[\w-]+\.[\w.-]+",  # e-mail
)

_MASCARA = "[PII]"

# Chave OTel gen_ai p/ a "conversa" do trace. No domínio do agente a conversa de um turno é o
# Atendimento (uma negociação cliente-modelo), não a Conversa cliente — o LangSmith agrupa o
# thread por este campo. Ver CONTEXT.md "Atendimento" / "Conversa cliente".
_GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"

# IDs internos opacos (UUID) que escopam o trace (OBS-09/10) — nunca PII. Allowlist por chave
# porque o backstop _VALOR_PII casaria um UUID cujo último grupo de 12 hex é todo-dígito (~0.9%),
# mascarando o discriminador do trace; isentamos por chave para o ID sobreviver ao egress.
_CHAVES_ID_TRACE = frozenset({"modelo_id", "atendimento_id", "cliente_id", _GEN_AI_CONVERSATION_ID})


def _mascarar(valor: str, caminho: list[str | int]) -> str:
    chave = str(caminho[-1]).lower() if caminho else ""
    if chave in _CHAVES_ID_TRACE:
        return valor
    if any(k in chave for k in _CHAVES_PII):
        return _MASCARA
    if _VALOR_PII.search(valor):
        return _MASCARA
    return valor


def setup_tracing(settings: Settings) -> Client | None:
    """Liga o tracing LangSmith só com PII mascarada; instala o Client anonimizador como o
    cliente global que o langchain usa. Retorna o Client ativo, ou None se desligado/sem gate.

    Hard gate: tracing ligado mas anonymizer não construível → força LANGCHAIN_TRACING_V2=false
    e emite warning, em vez de subir tracing cru.
    """
    if not settings.langchain_tracing_v2:
        return None
    try:
        anonymizer: Callable[[Any], Any] = create_anonymizer(_mascarar)
        client = Client(
            api_key=settings.langchain_api_key,
            anonymizer=anonymizer,  # mascara inputs e outputs
            hide_metadata=anonymizer,  # o anonymizer de inputs/outputs não cobre metadata
        )
    except Exception:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.warning(
            "tracing_desligado_sem_anonymizer: anonymizer de PII não construível; "
            "tracing forçado para false (não subimos tracing cru)",
            exc_info=True,
        )
        return None
    # langchain roteia o tracing pelo cliente global cacheado (get_client → run_trees._CLIENT).
    # Setá-lo aqui garante que todo run passe pelo anonymizer antes de ir ao LangSmith.
    run_trees._CLIENT = client
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    return client


# Handler do Langfuse setado por `setup_langfuse` (prod, ADR 0019) e lido por `langfuse_handler()`
# (o coordenador anexa aos callbacks do `graph.ainvoke`). Fica None por padrão -- o pytest NUNCA
# chama setup_langfuse, então o tracing Langfuse não liga sozinho nos testes (que importam Settings
# com as chaves do .env).
_LANGFUSE_HANDLER: Any | None = None


def _ligar_langfuse_handler(settings: Settings) -> Any | None:
    """Núcleo de `setup_langfuse`: faz a ponte das chaves p/ o `os.environ` (o SDK lê de lá;
    pydantic-settings carrega do .env mas não exporta), valida o auth e cacheia o `CallbackHandler`
    no global. `setdefault` não sobrescreve env real já presente. No-op (None) sem chaves, sem o
    pacote, ou se o auth falhar."""
    global _LANGFUSE_HANDLER
    if not settings.langfuse_public_key:
        logger.warning(
            "langfuse_prod: chave ausente; tracing langfuse off "
            "(pode ser o redeploy git que zera o Env do stack)"
        )
        return None
    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        logger.warning("langfuse_prod: pacote langfuse ausente; tracing langfuse off")
        return None
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key or "")
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
    client = get_client()
    if not client.auth_check():
        logger.warning("langfuse_prod: auth_check falhou; tracing langfuse off")
        return None
    _LANGFUSE_HANDLER = CallbackHandler()
    return _LANGFUSE_HANDLER


def setup_langfuse(settings: Settings) -> Any | None:
    """Liga o tracing Langfuse self-hosted de PRODUÇÃO (ADR 0019) e cacheia o CallbackHandler.

    Substitui o `setup_tracing` (LangSmith + anonymizer) no `main.py`/worker. SEM masking: com o
    Langfuse na infra própria (mesmo perímetro de confiança do banco que já guarda a PII), o trace
    volta a ser legível e a proteção de PII migra do masking-no-egress p/ o controle de acesso ao
    Langfuse. O handler fica num global que o coordenador anexa aos callbacks do `graph.ainvoke`.

    Sem chaves, sem o pacote, ou com auth falhando: com `langfuse_obrigatorio` (Env de prod,
    piloto de produção assistida) LEVANTA RuntimeError — derrubar o boot é o grito visível na hora
    do deploy, em vez de rodar cego depois de um redeploy git que zerou o Env do stack. Sem a
    trava, segue no-op (None) e o turno roda sem tracing (dev/teste). O gauge
    `barra_tracing_langfuse_ligado` (0/1) espelha o estado p/ o dashboard nos dois casos.
    """
    from barra.core.metrics import TRACING_LANGFUSE_LIGADO

    handler = _ligar_langfuse_handler(settings)
    TRACING_LANGFUSE_LIGADO.set(1 if handler is not None else 0)
    if handler is None and settings.langfuse_obrigatorio:
        raise RuntimeError(
            "langfuse_obrigatorio=true e o tracing Langfuse nao subiu (chave ausente ou auth "
            "falhou) — provavel Env do stack zerado por redeploy git. Restaure LANGFUSE_PUBLIC_KEY/"
            "LANGFUSE_SECRET_KEY no Env do Portainer antes de subir (runbook infra/)."
        )
    if handler is not None:
        logger.info(
            "langfuse_prod_ligado host=%s (self-hosted; PII na infra propria, sem masking)",
            settings.langfuse_host,
        )
    return handler


def langfuse_handler() -> Any | None:
    """CallbackHandler do Langfuse (prod, ADR 0019) p/ o coordenador anexar aos callbacks do
    `graph.ainvoke`; None se `setup_langfuse` não foi chamado (default — ex.: pytest), garantindo
    que o Langfuse nunca traça fora do boot de main.py/worker."""
    return _LANGFUSE_HANDLER


def metadata_trace_turno(modelo_id: str, atendimento_id: str, cliente_id: str) -> dict[str, Any]:
    """Fragmento de config (metadata + tags) que escopa o trace do turno por modelo/atendimento/cliente.

    Merge no config do `graph.ainvoke` (ex.: `config |= metadata_trace_turno(...)`): os IDs
    viajam como metadata/tags do RunTree do LangSmith — filtra/agrupa traces por modelo, por
    cliente, e por atendimento, este último como `gen_ai.conversation.id` (convenção OTel gen_ai).
    `cliente_id` é UUID opaco do banco (não o telefone E.164), tratado como ID-de-escopo igual aos
    outros — mesmo perímetro de confiança do Langfuse self-hosted (ADR 0019).

    Invariante de cache: estes IDs vão SÓ no nível de config (metadata/tags), nunca no conteúdo
    de mensagem/system. O prefixo cacheado (`tools→system→messages`) é montado em
    `agente/prepare_context` a partir do `state`, não do config — logo metadata/tags não tocam o
    prefixo e não invalidam o cache (agente/CLAUDE.md "Prompt caching"). Por isso são dado por-turno
    legítimo aqui, e não no BP_MODELO.

    Recebe `str` (não `ContextAgente`): `core/` não importa de `agente/` (direção de deps).
    """
    tags = [
        f"modelo_id:{modelo_id}",
        f"atendimento_id:{atendimento_id}",
        f"cliente_id:{cliente_id}",
    ]
    return {
        "metadata": {
            "modelo_id": modelo_id,
            "atendimento_id": atendimento_id,
            "cliente_id": cliente_id,
            _GEN_AI_CONVERSATION_ID: atendimento_id,
            # Langfuse (ADR 0019): agrupa os turnos da jornada por atendimento e replica as tags no
            # nível do trace; o CallbackHandler lê estas chaves do metadata do config.
            "langfuse_session_id": atendimento_id,
            "langfuse_tags": tags,
        },
        "tags": tags,
    }


def registrar_feedback_online(trace_id: str | None, name: str, score: float) -> None:
    """Anexa um score determinístico (não-PII) ao trace do Langfuse (EVAL-11 online → trace).

    Só `name` (rubrica) + `score` 0/1 — NUNCA conteúdo de mensagem. Com o Langfuse self-hosted o
    conteúdo do trace já é legível (ADR 0019); este score é o veredito por-turno de um invariante
    determinístico, visível no trace e agregável no painel. Best-effort: no-op sem o handler global
    (tracing desligado — ex.: pytest) ou sem `trace_id`. Síncrono — o caller roda fora do event loop
    (`asyncio.to_thread`) e nunca deixa a telemetria derrubar o turno.
    """
    if _LANGFUSE_HANDLER is None or trace_id is None:
        return
    try:
        from langfuse import get_client

        get_client().create_score(trace_id=trace_id, name=name, value=score)
    except Exception:  # best-effort: telemetria nunca quebra o turno
        logger.debug("feedback_online_falhou name=%s", name, exc_info=True)


def resumir_trace_turno(
    span: Any,
    *,
    entrada: list[str],
    resposta: str,
    desfecho: dict[str, Any],
    level: str = "DEFAULT",
) -> None:
    """Popula input/output/metadata/level do trace do turno p/ leitura de relance (ADR 0019).

    Sem isto o trace nasce com `input`/`output` nulos: quem opera (Claude Code via MCP, ou o
    painel) e obrigado a abrir as ~20 observations do LangChain e garimpar a msg do cliente, a
    resposta e a mecanica (extracao/erro/reoferta). Aqui o ROOT span vira autossuficiente: a
    msg do cliente no `input`, a resposta + o `desfecho` (de `desfecho_do_turno`) no `output`, e
    `level=WARNING` nos turnos com erro de extracao/recusa -- filtravel.

    `span` e o LangfuseSpan ativo (`None` quando o tracing esta off -> no-op) e e o ROOT
    observation do trace: o Langfuse deriva o input/output do TRACE do root span, entao um
    `update` aqui ja popula o nivel de trace que o painel/MCP leem (sem o `set_trace_io` legado,
    deprecado no SDK 4.x). Conteudo de mensagem so entra aqui pq o Langfuse self-hosted ja e o
    perimetro de PII do projeto (ADR 0019, sem masking) -- o mesmo texto ja vive nas observations
    do grafo. Best-effort: a telemetria nunca derruba o turno.
    """
    if span is None:
        return
    try:
        span.update(
            input=entrada,
            output={"resposta_ia": resposta, "desfecho": desfecho},
            metadata={"desfecho": desfecho},
            level=level,
        )
    except Exception:  # best-effort: telemetria nunca quebra o turno
        logger.debug("resumir_trace_turno_falhou", exc_info=True)


def registrar_score_agregado(nome: str, valor: float, *, janela: str = "") -> None:
    """Anexa um score AGREGADO (ex.: JSD do sensor de fluxo) a um trace sintético do Langfuse.

    Diferente do `registrar_feedback_online` (score por-turno num trace existente), aqui não há turno:
    cria-se um trace determinístico por (nome, janela) via `create_trace_id(seed=...)` — reexecução na
    mesma janela sobrescreve o mesmo ponto —, daí o `create_score`. O time-series de scores vira o
    dashboard de deriva no Langfuse. Best-effort: no-op sem o handler global (tracing off — ex.: pytest).
    """
    if _LANGFUSE_HANDLER is None:
        return
    try:
        from langfuse import Langfuse, get_client

        client = get_client()
        trace_id = Langfuse.create_trace_id(seed=f"{nome}:{janela}")
        with client.start_as_current_observation(
            as_type="span", name=f"{nome} {janela}".strip(), trace_context={"trace_id": trace_id}
        ):
            pass
        client.create_score(name=nome, value=float(valor), trace_id=trace_id, data_type="NUMERIC")
    except Exception:  # best-effort: telemetria nunca quebra o job
        logger.debug("score_agregado_falhou name=%s", nome, exc_info=True)


def garantir_dataset(nome: str) -> None:
    """Cria o dataset do Langfuse se faltar (idempotente por nome). Best-effort."""
    if _LANGFUSE_HANDLER is None:
        return
    try:
        from langfuse import get_client

        get_client().create_dataset(name=nome)
    except Exception:  # best-effort: já existe ou tracing off
        logger.debug("garantir_dataset_falhou nome=%s", nome, exc_info=True)


def upsert_item_dataset(dataset: str, item_id: str, metadata: dict[str, Any]) -> None:
    """Upsert (por `id`) de um item num dataset do Langfuse — sem conteúdo PII além do que o trace já
    guarda (self-hosted, ADR 0019). Best-effort: no-op sem handler. Exige `garantir_dataset` antes."""
    if _LANGFUSE_HANDLER is None:
        return
    try:
        from langfuse import get_client

        get_client().create_dataset_item(dataset_name=dataset, id=item_id, metadata=metadata)
    except Exception:  # best-effort: telemetria nunca quebra o job
        logger.debug("upsert_dataset_falhou dataset=%s", dataset, exc_info=True)


def linkar_item_run(
    dataset: str,
    item_id: str,
    run_name: str,
    trace_id: str | None,
    *,
    observation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Amarra um item↔trace dentro de um dataset-RUN nomeado — a peça que faltava do trio:
    `garantir_dataset` cria o dataset, `upsert_item_dataset` cria o item, ISTO vincula item, run e o
    trace de UMA execução (run_name agrupa a corrida). Os scores do judge já vivem no trace
    (`registrar_feedback_online`/`pontuar_no_langfuse`); aqui só ligamos o trace ao run. Best-effort:
    no-op sem handler (tracing off — ex.: pytest/.env vazio) ou sem `trace_id` (turno sem escopo).
    Exige `garantir_dataset` + `upsert_item_dataset` antes (o item precisa existir)."""
    if _LANGFUSE_HANDLER is None or trace_id is None:
        return
    try:
        from langfuse import get_client

        get_client().api.dataset_run_items.create(
            run_name=run_name,
            dataset_item_id=item_id,
            trace_id=trace_id,
            observation_id=observation_id,
            metadata=metadata,
        )
    except Exception:  # best-effort: telemetria nunca quebra o job
        logger.debug("linkar_item_run_falhou dataset=%s run=%s", dataset, run_name, exc_info=True)


def _tag_turno_id(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """before_send do Sentry: promove o `turno_id` a tag do evento (OBS-04).

    A exceção não-tratada do pipeline da IA propaga pelo frame de `processar_turno`, que carrega
    `turno_id` (= ContextAgente.turno_id) como local; expomos como tag para filtrar/agrupar no
    Sentry. Best-effort: percorre o traceback procurando o local e nunca depende dele existir.
    """
    exc_info = hint.get("exc_info")
    if exc_info is None:
        return event
    tb = exc_info[2]
    turno_id: str | None = None
    while tb is not None:
        valor = tb.tb_frame.f_locals.get("turno_id")
        if isinstance(valor, str):
            turno_id = valor
        tb = tb.tb_next
    if turno_id is not None:
        tags = event.get("tags") or {}
        tags["turno_id"] = turno_id
        event["tags"] = tags
    return event


def init_sentry(settings: Settings) -> bool:
    """Inicializa o Sentry no boot da api (main.py) e do worker (workers/settings.py) — OBS-04.

    No-op sem DSN configurado (ou sem o SDK instalado): nunca quebra o boot. No worker, a
    integração arq do Sentry (auto-enabled) captura as exceções do turno; `_tag_turno_id`
    (before_send) anexa a tag `turno_id`. Retorna True se o Sentry foi inicializado.
    """
    if not settings.sentry_dsn or sentry_sdk is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.ambiente,
        before_send=_tag_turno_id,
        # PII hard-gate (mesma regra do anonymizer do LangSmith): sem isso o SDK serializa
        # os f_locals de cada frame do traceback — vazando `msg` (telefone E.164, conteudo
        # cru do cliente, media_url com token) e, no worker, chave Pix/titular da modelo.
        include_local_variables=False,
        send_default_pii=False,
    )
    return True
