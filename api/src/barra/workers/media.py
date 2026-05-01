"""Limpeza idempotente de objetos de midia vencidos."""

from typing import Any

from psycopg import AsyncConnection

from barra.core.metrics import JOBS

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]


async def limpar_midias_vencidas(
    conn: AsyncConnection[Any],
    minio: Minio | None,
    *,
    bucket: str = "media",
) -> int:
    result = await conn.execute(
        """
        SELECT msg.media_object_key
          FROM barravips.mensagens msg
          JOIN barravips.atendimentos a ON a.id = msg.atendimento_id
         WHERE msg.media_object_key IS NOT NULL
           AND a.estado IN ('Fechado', 'Perdido')
           AND a.updated_at < now() - interval '90 days'
        """
    )
    rows = await result.fetchall()
    apagados = 0
    if minio is not None:
        for row in rows:
            minio.remove_object(bucket, row["media_object_key"])
            apagados += 1
    else:
        apagados = len(rows)
    JOBS.labels("limpeza_midia", "sucesso").inc()
    return apagados
