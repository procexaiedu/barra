"""Cliente HTTP Evolution e registro transacional de outbound."""

from typing import Any, cast
from uuid import UUID

import httpx
from psycopg import AsyncConnection

from barra.core.errors import ErroDominio
from barra.core.metrics import ENVIOS_EVOLUTION
from barra.settings import Settings


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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            payload,
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
