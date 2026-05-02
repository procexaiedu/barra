"""Job de envio Evolution com registro em envios_evolution."""

from typing import Any

from psycopg import AsyncConnection

from barra.core.errors import ErroDominio
from barra.core.evolution import EvolutionClient


async def enviar_texto_job(
    conn: AsyncConnection[Any],
    client: EvolutionClient,
    *,
    instance_id: str,
    remote_jid: str,
    texto: str,
    contexto: str,
    tipo: str,
    payload: dict[str, Any] | None = None,
) -> str:
    if not instance_id:
        raise ErroDominio("EVOLUTION_NAO_PAREADA", "Evolution nao pareada.", status_code=409)
    return await client.enviar_texto(
        conn=conn,
        instance_id=instance_id,
        remote_jid=remote_jid,
        texto=texto,
        contexto=contexto,
        tipo=tipo,
        payload=payload or {},
    )
