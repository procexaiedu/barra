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
_CHAVES_ID_TRACE = frozenset({"modelo_id", "atendimento_id", _GEN_AI_CONVERSATION_ID})


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


def setup_tracing_sim(settings: Settings, *, projeto: str = "barra-vips-sim") -> Client | None:
    """Tracing do SIMULADOR de evals -- SEM anonymizer, conteúdo LEGÍVEL para root-cause do flywheel.

    Diferente de `setup_tracing` (produção, hard-gate de anonymizer obrigatório): aqui o conteúdo das
    mensagens vai cru ao LangSmith porque os dados são SINTÉTICOS -- modelo/cliente do seed do
    `runner._seed_entidades` ("Modelo Eval", telefone `eval-tel-*`) e falas roteirizadas das conversas
    reais JÁ anonimizadas (`docs/agente/conversas-reais`). NUNCA chamar de `main.py`/worker: lá os
    dados são reais (PII de cliente/modelo) e o caminho é `setup_tracing`.

    Aponta um projeto SEPARADO (`barra-vips-sim`), para os traces do sim não se misturarem com os de
    produção. Retorna None (sem ligar) se não houver `langchain_api_key` -- aí o diagnóstico cai no
    `conversas.jsonl` enriquecido (C5a), que não depende do LangSmith.
    """
    if not settings.langchain_api_key:
        return None
    # Guard de não-produção: o nome do projeto carrega o sufixo `-sim`; se alguém passar um projeto
    # sem ele, forçamos -- o sim nunca escreve no projeto de produção.
    if not projeto.endswith("-sim"):
        projeto = f"{projeto}-sim"
    client = Client(api_key=settings.langchain_api_key)  # SEM anonymizer: dados sintéticos
    run_trees._CLIENT = client
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = projeto
    logger.info("tracing_sim_ligado projeto=%s (sem anonymizer; dados sinteticos)", projeto)
    return client


# Handler do Langfuse-sim, setado por `setup_langfuse_sim` (entrypoint CLI do sim) e lido pelo site
# de ainvoke da jornada. Fica None por padrão -- o pytest NUNCA chama setup_langfuse_sim, então o
# tracing Langfuse não liga sozinho nos testes (que importam Settings com as chaves do .env).
_LANGFUSE_HANDLER: Any | None = None


def setup_langfuse_sim(settings: Settings) -> Any | None:
    """Liga o tracing Langfuse do SIMULADOR (avaliação vs LangSmith) e cacheia o CallbackHandler.

    Mesma filosofia (e mesmas travas) do `setup_tracing_sim`: conteúdo LEGÍVEL porque os dados são
    SINTÉTICOS. NUNCA chamar de `main.py`/worker (PII real) nem de teste -- só dos entrypoints CLI do
    sim. O handler fica num global que o site de ainvoke da jornada anexa aos callbacks; sem esta
    chamada (caso default, ex.: pytest), `langfuse_handler()` devolve None e o Langfuse não traça.

    No-op (retorna None) se `langfuse` não instalado (é dep de dev, ausente em prod), chaves ausentes,
    ou auth falha -- aí a jornada só traça no LangSmith-sim.
    """
    global _LANGFUSE_HANDLER
    if not settings.langfuse_public_key:
        return None
    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        logger.warning("langfuse_sim: pacote langfuse ausente (dep de dev); tracing langfuse off")
        return None
    # O SDK do Langfuse lê as chaves do os.environ (get_client monta o singleton). pydantic-settings
    # carrega do .env mas não exporta p/ os.environ -- ponte aqui, no padrão do setup_tracing (que já
    # seta LANGCHAIN_* no environ). setdefault: não sobrescreve um env real já presente.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key or "")
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
    client = get_client()
    if not client.auth_check():
        logger.warning("langfuse_sim: auth_check falhou; tracing langfuse off")
        return None
    _LANGFUSE_HANDLER = CallbackHandler()
    logger.info(
        "langfuse_sim_ligado host=%s (sem masking; dados sinteticos)", settings.langfuse_host
    )
    return _LANGFUSE_HANDLER


def langfuse_handler() -> Any | None:
    """CallbackHandler do Langfuse-sim p/ anexar aos callbacks do ainvoke da jornada; None se
    `setup_langfuse_sim` não foi chamado (default — ex.: pytest), garantindo que o Langfuse nunca
    traça fora do entrypoint CLI explícito do sim."""
    return _LANGFUSE_HANDLER


def metadata_trace_turno(modelo_id: str, atendimento_id: str) -> dict[str, Any]:
    """Fragmento de config (metadata + tags) que escopa o trace do turno por modelo/atendimento.

    Merge no config do `graph.ainvoke` (ex.: `config |= metadata_trace_turno(...)`): os IDs
    viajam como metadata/tags do RunTree do LangSmith — filtra/agrupa traces por modelo e por
    atendimento, este último como `gen_ai.conversation.id` (convenção OTel gen_ai).

    Invariante de cache: estes IDs vão SÓ no nível de config (metadata/tags), nunca no conteúdo
    de mensagem/system. O prefixo cacheado (`tools→system→messages`) é montado em
    `agente/prepare_context` a partir do `state`, não do config — logo metadata/tags não tocam o
    prefixo e não invalidam o cache (agente/CLAUDE.md "Prompt caching"). Por isso são dado por-turno
    legítimo aqui, e não no BP_MODELO.

    Recebe `str` (não `ContextAgente`): `core/` não importa de `agente/` (direção de deps).
    """
    return {
        "metadata": {
            "modelo_id": modelo_id,
            "atendimento_id": atendimento_id,
            _GEN_AI_CONVERSATION_ID: atendimento_id,
        },
        "tags": [f"modelo_id:{modelo_id}", f"atendimento_id:{atendimento_id}"],
    }


def registrar_feedback_online(run_id: str | None, key: str, score: float) -> None:
    """Anexa um feedback determinístico (não-PII) ao run do LangSmith (EVAL-11 online → trace).

    Só `key` (nome da rubrica) + `score` 0/1 — NUNCA conteúdo de mensagem. O conteúdo de prod já
    vai ao LangSmith mascarado (`setup_tracing` força o anonymizer); este feedback é o jeito de ter
    o veredito de um invariante determinístico VISÍVEL no trace mesmo com o texto `[PII]` (que
    cegaria um evaluator que lesse o conteúdo do trace). Best-effort: no-op sem client global
    (tracing desligado) ou sem `run_id`. Síncrono (POST no Client) — o caller roda fora do event
    loop (`asyncio.to_thread`) e nunca deixa a telemetria derrubar o turno.
    """
    client = run_trees._CLIENT
    if client is None or run_id is None:
        return
    try:
        client.create_feedback(run_id, key=key, score=score)
    except Exception:  # best-effort: telemetria nunca quebra o turno
        logger.debug("feedback_online_falhou key=%s", key, exc_info=True)


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
