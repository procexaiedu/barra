"""ARQ WorkerSettings — registra cron jobs determinísticos.

Cron:
  - timeout_longo (24h sem cliente): a cada 5 min
  - timeout_interno (30 min sem foto portaria): a cada minuto
  - confirmar_em_execucao (bloqueio.inicio <= now): a cada minuto
  - limpar_midias_vencidas (90d em estados terminais): diário 03:00

Idempotência: dedupe_key = (conversa_id, turno_id, chunk_idx) consultada antes do envio.
"""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from barra.core.db import criar_pool, fechar_pool
from barra.core.storage import criar_minio
from barra.settings import Settings, get_settings
from barra.workers.media import limpar_midias_vencidas
from barra.workers.timeouts import (
    aplicar_timeout_interno,
    aplicar_timeout_longo,
    confirmar_em_execucao,
)


async def cron_timeout_longo(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await aplicar_timeout_longo(conn)


async def cron_timeout_interno(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await aplicar_timeout_interno(conn)


async def cron_confirmar_em_execucao(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await confirmar_em_execucao(conn)


async def cron_limpar_midias(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    minio = ctx.get("minio")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await limpar_midias_vencidas(conn, minio)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["db_pool"] = await criar_pool(settings.database_url)
    ctx["minio"] = criar_minio(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("db_pool")
    if pool is not None:
        await fechar_pool(pool)


def _redis_settings(settings: Settings) -> RedisSettings:
    if settings.redis_url:
        return RedisSettings.from_dsn(settings.redis_url)
    return RedisSettings()


_settings = get_settings()


class WorkerSettings:
    """Configuração ARQ. Usar: `arq barra.workers.settings.WorkerSettings`."""

    redis_settings = _redis_settings(_settings)
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = []
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(cron_timeout_interno, name="timeout_interno"),
        cron(cron_confirmar_em_execucao, name="confirmar_em_execucao"),
        cron(
            cron_timeout_longo,
            name="timeout_longo",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(cron_limpar_midias, name="limpar_midias", hour={3}, minute={0}),
    ]
    keep_result = 3600
    max_jobs = 10
