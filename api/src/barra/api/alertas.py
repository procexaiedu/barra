"""Relay Alertmanager → WhatsApp: canal DEV de alertas da stack (OBS-02 + piloto).

O Alertmanager agrupa os alertas do Prometheus (alert.rules.yml) e entrega aqui por webhook;
este endpoint formata um resumo curto e manda por WhatsApp (Evolution sendText direto) ao número
de DEV configurado. É o "cano final" que o receiver noop do alertmanager.yml sempre esperou —
inclui o gatilho de rollback do piloto (`barra_rollback_gatilho == 1`).

Segurança: montado FORA do /v1 (sem sessão de usuário — quem chama é o Alertmanager); a porta é
um token estático em query string (`?token=`), comparado em tempo constante. Sem token
configurado o endpoint responde 403 sempre (desligado). Não persiste em `envios_evolution`
(alerta interno de infra, não evento operacional de atendimento — os CHECKs de contexto/tipo lá
são da operação) nem toca banco.

Falha de entrega devolve 502: o Alertmanager retenta sozinho (repeat_interval), então não há
fila própria aqui.
"""

import logging
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from barra.core.errors import ErroDominio
from barra.core.evolution import EvolutionClient
from barra.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_ALERTAS = 10
_MAX_CHARS = 3000

_EMOJI_STATUS = {"firing": "🚨", "resolved": "✅"}


def formatar_alertas(payload: dict[str, Any]) -> str:
    """Resumo WhatsApp do webhook do Alertmanager (PURA). Payload vazio/sem alertas -> ''."""
    alertas = payload.get("alerts") or []
    if not alertas:
        return ""
    status = str(payload.get("status") or "firing")
    emoji = _EMOJI_STATUS.get(status, "🚨")
    linhas = [f"{emoji} *barra-vips*: {len(alertas)} alerta(s) {status.upper()}"]
    for a in alertas[:_MAX_ALERTAS]:
        labels = a.get("labels") or {}
        annotations = a.get("annotations") or {}
        nome = labels.get("alertname", "alerta")
        severidade = labels.get("severity", "")
        resumo = annotations.get("summary", "")
        sufixo = f" [{severidade}]" if severidade else ""
        linhas.append(f"\n• *{nome}*{sufixo}\n{resumo}".rstrip())
    if len(alertas) > _MAX_ALERTAS:
        linhas.append(f"\n(+{len(alertas) - _MAX_ALERTAS} alertas no Grafana)")
    return "\n".join(linhas)[:_MAX_CHARS]


@router.post("/alertmanager")
async def receber_alertmanager(request: Request, token: str = Query(default="")) -> dict[str, Any]:
    settings = get_settings()
    esperado = settings.alertas_webhook_token
    if not esperado or not secrets.compare_digest(token, esperado):
        raise HTTPException(status_code=403, detail="token invalido")

    payload = await request.json()
    texto = formatar_alertas(payload if isinstance(payload, dict) else {})
    if not texto:
        return {"ok": True, "entregue": False}

    jid = settings.alertas_whatsapp_jid
    if not jid or not settings.evolution_base_url:
        # Aceita (200) e loga: sem destino configurado o Alertmanager não deve ficar
        # retentando — o alerta continua visível em log/Grafana.
        logger.warning("alerta recebido sem destino WhatsApp configurado: %s", texto)
        return {"ok": True, "entregue": False}

    try:
        await EvolutionClient(settings).enviar_texto_sem_registro(
            instance_id=settings.evolution_instancia,
            remote_jid=jid,
            texto=texto,
        )
    except (httpx.HTTPError, ErroDominio) as exc:
        # 502 -> o Alertmanager retenta na próxima janela de agrupamento.
        logger.error("alerta nao entregue no WhatsApp: %s", exc)
        raise HTTPException(status_code=502, detail="falha ao entregar no WhatsApp") from exc
    logger.info("alerta entregue no WhatsApp (%d chars)", len(texto))
    return {"ok": True, "entregue": True}
