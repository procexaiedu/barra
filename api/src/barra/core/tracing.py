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
    )
    return True
