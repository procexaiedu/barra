"""Setup LangSmith — projeto barra-vips-{ambiente}, tags por conversa_id/modelo_id.

Hard gate de PII: o tracing só sobe com um anonymizer construível mascarando inputs/outputs/
metadata (chave/titular Pix, telefone/JID, nome, endereço, conteúdo livre). Sem anonymizer,
forçamos LANGCHAIN_TRACING_V2=false — nunca subimos tracing cru (PII vazaria para o LangSmith).
"""

import logging
import os
import re
from collections.abc import Callable
from typing import Any

import langsmith.run_trees as run_trees
from langsmith import Client
from langsmith.anonymizer import create_anonymizer

from barra.settings import Settings

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


def _mascarar(valor: str, caminho: list[str | int]) -> str:
    chave = str(caminho[-1]).lower() if caminho else ""
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
