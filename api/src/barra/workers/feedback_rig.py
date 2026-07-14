"""Ack de registro do rig de feedback (issue #93): resposta curta com debounce de ~2 min.

Job ARQ deferido, coalescido por grupo (`_job_id=ack_fb:{remote_jid}`, SET NX first-wins): o 1º
feedback da rajada arma o timer, os seguintes na janela não duplicam. Ao disparar, a lucia responde
UMA vez citando a 1ª mensagem — sinal pro Rossi de que o feedback foi registrado. Best-effort: nunca
levanta (é sinalização, não pode derrubar o worker) e não persiste em `envios_evolution` (fora do
domínio, via `enviar_texto_avulso`).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_TEXTO_ACK = "anotei aqui 🙌"
_TEXTO_DESENVOLVIDO = "✅ isso aqui já foi desenvolvido e tá no ar 🚀"


async def enviar_ack_feedback_rig(
    ctx: dict[str, Any],
    *,
    remote_jid: str,
    instance_id: str,
    quoted_message_id: str,
    quoted_text: str,
) -> None:
    evolution = ctx.get("evolution")
    settings = ctx.get("settings")
    if evolution is None or settings is None or not settings.feedback_rig_ack:
        return
    try:
        await evolution.enviar_texto_avulso(
            instance_id=instance_id,
            remote_jid=remote_jid,
            texto=_TEXTO_ACK,
            quoted_message_id=quoted_message_id,
            quoted_text=quoted_text,
        )
    except Exception:
        logger.warning("feedback_rig_ack_falhou remote_jid=%s", remote_jid, exc_info=True)


async def enviar_aviso_desenvolvido(
    ctx: dict[str, Any],
    *,
    remote_jid: str,
    instance_id: str,
    quoted_message_id: str,
    quoted_text: str,
) -> None:
    """Aviso de 'desenvolvido' — disparado pelo fecho de uma issue com rodapé `feedback-rig`. A lucia
    responde citando a mensagem original do Rossi, fechando o loop. Best-effort (mesma regra do ack).
    Sem gate próprio: o webhook do GitHub (secret) já é o gate; aqui só confirmamos o grupo ligado.
    """
    evolution = ctx.get("evolution")
    settings = ctx.get("settings")
    if evolution is None or settings is None or settings.feedback_rig_grupo_jid is None:
        return
    try:
        await evolution.enviar_texto_avulso(
            instance_id=instance_id,
            remote_jid=remote_jid,
            texto=_TEXTO_DESENVOLVIDO,
            quoted_message_id=quoted_message_id,
            quoted_text=quoted_text,
        )
    except Exception:
        logger.warning("feedback_rig_desenvolvido_falhou remote_jid=%s", remote_jid, exc_info=True)
