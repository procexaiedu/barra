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
        quoted_message_id: str | None = None,
        quoted_text: str | None = None,
    ) -> str:
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )

        body: dict[str, Any] = {"number": remote_jid, "text": texto}
        if quoted_message_id:
            # Evolution v2.3.6 (cliente evolution_api_v3) NAO faz lookup da mensagem
            # citada pelo `key.id`: ela ecoa literalmente o `quoted.message.conversation`
            # que mandamos para o `contextInfo.quotedMessage`. O `key.id` casa o reply
            # (a setinha aponta certo), mas o TEXTO do balao de citacao no WhatsApp do
            # cliente vem desse campo — vazio aqui = balao de reply vazio (verificado
            # 2026-05-30). Por isso enviamos o conteudo real da mensagem citada.
            body["quoted"] = {
                "key": {"id": quoted_message_id},
                "message": {"conversation": quoted_text or ""},
            }
        url = f"{self.settings.evolution_base_url.rstrip('/')}/message/sendText/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        evolution_message_id = _extrair_message_id(data)
        if not evolution_message_id:
            ENVIOS_EVOLUTION.labels("falha").inc()
            raise ErroDominio(
                "EVOLUTION_RESPOSTA_INVALIDA", "Evolution nao retornou id.", status_code=502
            )

        await registrar_envio(
            conn,
            evolution_message_id=evolution_message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            # Marcador do caller (ex.: {"card_kind": ...}) MESCLA sobre a resposta da Evolution,
            # nao a substitui: a auditoria preserva o payload completo (texto reconstrutivel) e
            # ainda carrega o marcador queryavel. `payload or data` puro perdia o `data` (#7).
            payload={**data, **payload} if payload else data,
        )
        ENVIOS_EVOLUTION.labels("sucesso").inc()
        return evolution_message_id

    async def enviar_midia(
        self,
        *,
        conn: AsyncConnection[Any],
        instance_id: str,
        remote_jid: str,
        url: str,
        caption: str | None,
        media_type: str,
        contexto: str,
        tipo: str,
        view_once: bool = False,
        atendimento_id: UUID | None = None,
        conversa_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        quoted_message_id: str | None = None,
        quoted_text: str | None = None,
    ) -> str:
        """Espelha enviar_texto para mídia: POST /message/sendMedia → registra em
        envios_evolution → devolve evolution_message_id. O kwarg `view_once` (Mídia
        exclusiva, 01 §6.13) é ACEITO mas NÃO entra no body: a Evolution v2 self-host
        ainda não expõe o campo no sendMedia — ignorado até o suporte chegar.

        `quoted_text` segue a mesma regra do enviar_texto: a Evolution v2.3.6 ecoa
        `quoted.message.conversation` (não faz lookup pelo id), então sem ele o balão
        de citação sai vazio no cliente."""
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )

        body: dict[str, Any] = {"number": remote_jid, "mediatype": media_type, "media": url}
        if caption:
            body["caption"] = caption
        if quoted_message_id:
            body["quoted"] = {
                "key": {"id": quoted_message_id},
                "message": {"conversation": quoted_text or ""},
            }
        endpoint = f"{self.settings.evolution_base_url.rstrip('/')}/message/sendMedia/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        evolution_message_id = _extrair_message_id(data)
        if not evolution_message_id:
            ENVIOS_EVOLUTION.labels("falha").inc()
            raise ErroDominio(
                "EVOLUTION_RESPOSTA_INVALIDA", "Evolution nao retornou id.", status_code=502
            )

        await registrar_envio(
            conn,
            evolution_message_id=evolution_message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            # Marcador do caller (ex.: {"card_kind": ...}) MESCLA sobre a resposta da Evolution,
            # nao a substitui: a auditoria preserva o payload completo (texto reconstrutivel) e
            # ainda carrega o marcador queryavel. `payload or data` puro perdia o `data` (#7).
            payload={**data, **payload} if payload else data,
        )
        ENVIOS_EVOLUTION.labels("sucesso").inc()
        return evolution_message_id

    async def marcar_lida(
        self,
        *,
        instance_id: str,
        remote_jid: str,
        message_ids: list[str],
    ) -> None:
        """Read receipt das mensagens do cliente (humano lê antes de responder, 05 §4.2).
        NÃO entra em envios_evolution — é recibo de leitura, não outbound de mensagem.
        Evolution v2.3.6 self-host (verificado 2026-05-27) exige `readMessages` em camelCase;
        snake_case retorna 400 Bad Request."""
        if not self.settings.evolution_base_url:
            raise ErroDominio(
                "EVOLUTION_INDISPONIVEL", "Evolution nao configurado.", status_code=503
            )
        body = {
            "readMessages": [
                {"remoteJid": remote_jid, "fromMe": False, "id": mid} for mid in message_ids
            ]
        }
        url = f"{self.settings.evolution_base_url.rstrip('/')}/chat/markMessageAsRead/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()

    async def set_presence(
        self,
        *,
        instance_id: str,
        remote_jid: str,
        presence: str,
        delay_ms: int,
    ) -> None:
        """Indicador "digitando…"/"gravando…" antes do envio (05 §4). Best-effort: o
        sendPresence do Baileys é notoriamente instável (05 §4.1) — falha de rede loga e
        segue, nunca estoura o turno de envio. Não grava nada."""
        if not self.settings.evolution_base_url:
            return
        body = {"number": remote_jid, "presence": presence, "delay": delay_ms}
        url = f"{self.settings.evolution_base_url.rstrip('/')}/chat/sendPresence/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning("evolution_set_presence_falhou instance=%s erro=%s", instance_id, exc)

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
        """POST /instance/create. Sucesso (2xx) já devolve o QR no corpo
        (`qrcode.base64`). Só tratamos 403 ("This name is already in use") como
        idempotente — a instância existe e o connect seguinte recupera o QR. Um
        401 aqui NÃO é "já existe": significa que a EVOLUTION_API_KEY não tem
        permissão de create (ex.: um token de instância no lugar da chave
        global/admin). Nesse caso falhamos alto, com mensagem clara, em vez de
        mascarar e deixar o connect seguinte estourar um 404 enganoso. O webhook
        vai no body para a Evolution já começar a postar
        CONNECTION_UPDATE/QRCODE_UPDATED sem POST /webhook/instance separado."""
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
        if response.status_code == 403:
            # "This name is already in use" — a instância já existe; o connect
            # seguinte recupera o QR.
            _logger.info("evolution_instance_create_ja_existe instance=%s", instance_id)
            return {"status": "exists", "instance_id": instance_id}
        if response.status_code == 401:
            _logger.error(
                "evolution_instance_create_sem_permissao instance=%s body=%s",
                instance_id,
                response.text[:300],
            )
            raise ErroDominio(
                "EVOLUTION_CHAVE_SEM_CREATE",
                "A chave da Evolution não tem permissão para criar instâncias "
                "(401). Confirme que EVOLUTION_API_KEY é a chave global/admin, "
                "não um token de instância.",
                status_code=502,
            )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def definir_webhook(self, instance_id: str) -> bool:
        """POST /webhook/set/{id}. Registra/atualiza o webhook numa instância que
        já existe. Necessário porque o POST /instance/create só grava o webhook
        quando CRIA a instância — quando ela já existe (403 idempotente), o
        webhook nunca é reescrito e a Evolution para de postar
        CONNECTION_UPDATE/MESSAGES_UPSERT. Best-effort: loga e segue em falha; o
        pareamento não deve travar por causa do webhook. Devolve False (sem
        chamar a Evolution) quando não há callback configurado."""
        webhook = self._webhook_config()
        if not self.settings.evolution_base_url or webhook is None:
            return False
        url = f"{self.settings.evolution_base_url.rstrip('/')}/webhook/set/{instance_id}"
        headers = {"apikey": self.settings.evolution_api_key}
        body = {"webhook": {**webhook, "enabled": True}}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=body, headers=headers)
            if response.status_code in {200, 201}:
                return True
            _logger.warning(
                "evolution_webhook_set_inesperado instance=%s status=%s body=%s",
                instance_id,
                response.status_code,
                response.text[:200],
            )
            return False
        except httpx.HTTPError as exc:
            _logger.warning("evolution_webhook_set_falhou instance=%s erro=%s", instance_id, exc)
            return False

    async def estado_conexao(self, instance_id: str) -> str:
        """GET /instance/connectionState/{id}. Retorna 'open' | 'connecting' |
        'close' | 'unknown'. Idempotente: 404 vira 'unknown' para callers que
        só querem checar status sem se preocupar com criação."""
        if not self.settings.evolution_base_url:
            return "unknown"
        url = (
            f"{self.settings.evolution_base_url.rstrip('/')}/instance/connectionState/{instance_id}"
        )
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
