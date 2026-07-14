"""Inbox do rig de feedback — ingestão automática da skill `/processar-feedbacks` (issue #93).

O grupo de feedback (Fernando comenta o teste do agente) vive numa instância de teste cujo
webhook já chega à barra (o router `procex-shared` faz fan-out sem filtrar JID). Em vez de o dev
"colar o feedback na sessão", o webhook captura cada mensagem do grupo e a deposita como um
**inbox no Langfuse** — a skill lê de lá. Isso resolve LEITURA + ÁUDIO de uma vez: o áudio chega
em base64 no payload do webhook (`midia_inbound_base64_evolution`) e o STT roda dev-time na skill.

Por que Langfuse e não o banco: o `#reset` do rig apaga o estado operacional entre sessões (mesma
razão da âncora, `core/ancora_feedback`); os traces do Langfuse são append-only. E a âncora já lê
o Langfuse, então inbox + âncora + marcador de idempotência ficam todos no mesmo lugar.

`montar_inbox_payload` é puro (sem I/O) — o Seam testável. `emitir_feedback_inbox` é o glue com o
cliente Langfuse: best-effort e idempotente (o `trace_id` é derivado do `message_id`, então uma
redelivery multi-device re-upserta o mesmo trace em vez de duplicar). Falha de emissão NUNCA pode
quebrar o ack do webhook — é ferramenta de dev sobre a borda de ingestão de prod.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TRACE_NAME_INBOX = "feedback_rig_inbox"


def montar_inbox_payload(
    *,
    message_id: str,
    remote_jid: str,
    autor: str | None,
    tipo: str,
    texto: str,
    caption: str | None,
    media_base64: str | None,
    media_mimetype: str | None,
) -> dict[str, Any]:
    """Reduz a mensagem do grupo de feedback ao payload que a skill precisa pra montar o draft.

    Vai inteiro no `input` do trace (não em metadata): o base64 é grande e o comentário do Fernando
    é PT-BR/longo — a metadata do Langfuse é só p/ dimensões ASCII curtas de agregação. O `ts` do
    feedback NÃO viaja aqui: é o `timestamp` do próprio trace (emitido no recebimento ≈ hora do
    feedback), lido pela skill como `ts_feedback` da âncora.
    """
    return {
        "message_id": message_id,
        "remote_jid": remote_jid,
        "autor": autor,
        "tipo": tipo,
        "texto": texto,
        "caption": caption,
        "media_base64": media_base64,
        "media_mimetype": media_mimetype,
    }


def emitir_feedback_inbox(payload: dict[str, Any], *, message_id: str) -> str | None:
    """Deposita o payload como trace `feedback_rig_inbox` no Langfuse; devolve o `trace_id` ou None.

    Guard pelo handler (tracing off — ex.: pytest/local sem chaves — vira no-op silencioso, igual a
    `registrar_modelos_langfuse`). `create_trace_id(seed=message_id)` dá idempotência determinística:
    redelivery da mesma mensagem re-emite sob o mesmo `trace_id`. Tudo best-effort: qualquer erro é
    log-e-segue — a captura de feedback jamais derruba o ack de um webhook de prod.
    """
    from barra.core.tracing import langfuse_handler

    if langfuse_handler() is None:
        return None

    from langfuse import Langfuse, get_client, propagate_attributes

    trace_id = Langfuse.create_trace_id(seed=message_id)
    try:
        client = get_client()
        # Payload no `input` da observação (não em `set_current_trace_io`, deprecated no v4);
        # `propagate_attributes` fixa nome + tag do trace, o que a skill filtra via MCP fetch_traces.
        with client.start_as_current_observation(
            name=TRACE_NAME_INBOX,
            input=payload,
            trace_context={"trace_id": trace_id},
        ):
            with propagate_attributes(trace_name=TRACE_NAME_INBOX, tags=[TRACE_NAME_INBOX]):
                pass
        client.flush()
    except Exception:  # best-effort: emissão de inbox jamais quebra o ack do webhook de prod
        logger.warning("feedback_rig_inbox_emit_falhou message_id=%s", message_id, exc_info=True)
        return None
    return trace_id
