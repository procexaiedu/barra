"""Cliente HTTP Evolution e registro transacional de outbound."""

import json
import logging
from typing import Any, cast
from uuid import UUID

import httpx
from psycopg import AsyncConnection

from barra.core.errors import ErroDominio
from barra.core.metrics import ENVIOS_EVOLUTION
from barra.settings import Settings

_logger = logging.getLogger(__name__)

# Eventos que precisamos para pareamento + ingestão de mensagens.
_EVENTOS_WEBHOOK = ["CONNECTION_UPDATE", "QRCODE_UPDATED", "MESSAGES_UPSERT"]


class EvolutionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def enviar_texto(
        self,
        *,
        conn: AsyncConnection[Any],
        instance_id: str,
        remote_jid: str,
        texto: str,
        contexto: str,
        tipo: str,
        atendimento_id: UUID | None = None,
        conversa_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        if not self.settings.evolution_base_url:
            raise ErroDominio("EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503)

        body = {"number": remote_jid, "text": texto}
        url = f"{self.settings.evolution_base_url.rstrip('/')}/message/sendText/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        evolution_message_id = _extrair_message_id(data)
        if not evolution_message_id:
            ENVIOS_EVOLUTION.labels("falha").inc()
            raise ErroDominio("EVOLUTION_RESPOSTA_INVALIDA", "Evolution nao retornou id.", status_code=502)

        await registrar_envio(
            conn,
            evolution_message_id=evolution_message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            payload=payload or data,
        )
        ENVIOS_EVOLUTION.labels("sucesso").inc()
        return evolution_message_id

    async def conectar_instancia(self, instance_id: str) -> dict[str, Any]:
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "instance_id": instance_id}
        url = f"{self.settings.evolution_base_url.rstrip('/')}/instance/connect/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            # A instância não existe e o create não pôde criá-la (chave sem
            # permissão de admin na Evolution). Caller transforma em
            # ErroDominio amigável.
            raise ErroDominio(
                "EVOLUTION_INSTANCIA_NAO_EXISTE",
                "A instância da Evolution não existe e não pôde ser criada automaticamente. "
                "Verifique se a chave da Evolution permite criar instâncias.",
                status_code=502,
            )
        response.raise_for_status()
        data = cast(dict[str, Any], response.json())
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                "evolution_connect_response instance=%s keys=%s",
                instance_id,
                sorted(data.keys()),
            )
        return data

    async def criar_instancia(
        self,
        instance_id: str,
        *,
        numero: str | None = None,
    ) -> dict[str, Any]:
        """POST /instance/create — idempotente: se a instância já existe (403)
        ou se a apikey atual só tem permissão para listar/conectar mas não para
        criar (401 em Evolution v3 com chave per-instance), segue assumindo que
        a instância existe; o connect/connectionState seguinte confirma. Inclui
        o webhook no body para que a Evolution já comece a postar
        CONNECTION_UPDATE/QRCODE_UPDATED para nós sem POST /webhook/instance
        separado."""
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "instance_id": instance_id}
        url = f"{self.settings.evolution_base_url.rstrip('/')}/instance/create"
        headers = {"apikey": self.settings.evolution_api_key}
        body: dict[str, Any] = {
            "instanceName": instance_id,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
        }
        if numero:
            digitos = "".join(ch for ch in numero if ch.isdigit())
            if digitos:
                body["number"] = digitos
        webhook = self._webhook_config()
        if webhook is not None:
            body["webhook"] = webhook
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=body, headers=headers)
        if response.status_code in {401, 403}:
            # 403 = "instance already in use"; 401 = chave sem permissão de
            # create (Evolution v3 segrega global/per-instance keys). Em ambos
            # os casos, deixamos o connect seguinte decidir se a instância
            # realmente existe — se não existir, ele devolve 404 e o caller
            # transforma em erro de domínio amigável.
            _logger.info(
                "evolution_instance_create_idempotente instance=%s status=%s",
                instance_id,
                response.status_code,
            )
            return {"status": "exists", "instance_id": instance_id}
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def estado_conexao(self, instance_id: str) -> str:
        """GET /instance/connectionState/{id}. Retorna 'open' | 'connecting' |
        'close' | 'unknown'. Idempotente: 404 vira 'unknown' para callers que
        só querem checar status sem se preocupar com criação."""
        if not self.settings.evolution_base_url:
            return "unknown"
        url = f"{self.settings.evolution_base_url.rstrip('/')}/instance/connectionState/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return "unknown"
        response.raise_for_status()
        data = response.json()
        state = data.get("instance", {}).get("state") if isinstance(data, dict) else None
        if state in {"open", "connecting", "close"}:
            return cast(str, state)
        return "unknown"

    async def logout_instancia(self, instance_id: str) -> bool:
        """DELETE /instance/logout/{id}. Mantém a instância na Evolution, só
        encerra a sessão WhatsApp. Best-effort: log e segue em falha (o caller
        já vai zerar nosso estado local independentemente)."""
        if not self.settings.evolution_base_url:
            return False
        url = f"{self.settings.evolution_base_url.rstrip('/')}/instance/logout/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.delete(url, headers=headers)
            if response.status_code in {200, 201, 404}:
                return True
            _logger.warning(
                "evolution_logout_inesperado instance=%s status=%s body=%s",
                instance_id,
                response.status_code,
                response.text[:200],
            )
            return False
        except httpx.HTTPError as exc:
            _logger.warning("evolution_logout_falhou instance=%s erro=%s", instance_id, exc)
            return False

    def _webhook_config(self) -> dict[str, Any] | None:
        """Bloco `webhook` enviado no POST /instance/create. None quando não
        temos URL pública configurada (dev sem tunnel) — nesse cenário, o
        polling do painel + auto-cure no GET /whatsapp/status garante que o
        status converge mesmo sem callback."""
        callback = self.settings.evolution_webhook_callback_url
        if not callback:
            return None
        headers: dict[str, str] = {}
        token = self.settings.evolution_webhook_token
        if token:
            headers["authorization"] = f"Bearer {token}"
        return {
            "url": callback,
            "byEvents": False,
            "base64": False,
            "events": _EVENTOS_WEBHOOK,
            "headers": headers,
        }

    async def buscar_grupo_info(self, instance_id: str, group_jid: str) -> dict[str, Any]:
        if not self.settings.evolution_base_url:
            return {"status": "not_configured", "participants": []}
        url = f"{self.settings.evolution_base_url.rstrip('/')}/group/findGroupInfos/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json={"groupJid": group_jid}, headers=headers)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())


async def registrar_envio(
    conn: AsyncConnection[Any],
    *,
    evolution_message_id: str,
    instance_id: str,
    remote_jid: str,
    contexto: str,
    tipo: str,
    atendimento_id: UUID | None,
    conversa_id: UUID | None,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.envios_evolution (
          evolution_message_id, instance_id, remote_jid, contexto, tipo,
          atendimento_id, conversa_id, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (evolution_message_id) DO NOTHING
        """,
        (
            evolution_message_id,
            instance_id,
            remote_jid,
            contexto,
            tipo,
            atendimento_id,
            conversa_id,
            json.dumps(payload, default=str),
        ),
    )


async def envio_existe(conn: AsyncConnection[Any], evolution_message_id: str) -> bool:
    result = await conn.execute(
        "SELECT 1 FROM barravips.envios_evolution WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    return await result.fetchone() is not None


def _extrair_message_id(data: dict[str, Any]) -> str | None:
    key = data.get("key")
    if isinstance(key, dict):
        value = key.get("id")
        return str(value) if value else None
    value = data.get("evolution_message_id") or data.get("messageId")
    return str(value) if value else None
