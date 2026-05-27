"""ARQ WorkerSettings — registra cron jobs determinísticos.

Cron:
  - timeout_longo (24h sem cliente): a cada 5 min
  - timeout_interno (45 min sem foto portaria, contado do aviso de saida): a cada minuto
  - confirmar_em_execucao (bloqueio.inicio <= now): a cada minuto
  - cobrar_valor_final (Lembrete de fechamento, ADR-0007; fim do atendimento): a cada minuto
  - reengajar_silenciosos (toque proativo apos cotacao; default off): a cada 5 min
  - limpar_midias_vencidas (90d em estados terminais): diário 03:00

Idempotência: dedupe_key = (conversa_id, turno_id, chunk_idx) consultada antes do envio.
"""

import asyncio
import sys
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings
from arq.cron import CronJob
from openai import AsyncOpenAI

from barra.agente.graph import build_graph
from barra.core.db import criar_pool, fechar_pool
from barra.core.evolution import EvolutionClient
from barra.core.storage import criar_minio
from barra.settings import Settings, get_settings
from barra.workers.coordenador import processar_turno
from barra.workers.envio import enviar_card, enviar_turno
from barra.workers.lembrete_valor import cobrar_valor_final
from barra.workers.media import limpar_midias_vencidas, rotear_imagem
from barra.workers.pix import validar_pix
from barra.workers.timeouts import (
    aplicar_timeout_interno,
    aplicar_timeout_longo,
    confirmar_em_execucao,
    reengajar_silenciosos,
)

# psycopg async no Windows (dev local) precisa do selector loop antes do loop do worker subir,
# senao PoolTimeout (09 §4.10; main.py:20 faz o mesmo). Producao e Linux. Como o startup roda
# JA dentro do loop, o guard tem que ficar no import do modulo.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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


async def cron_cobrar_valor_final(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    evolution = ctx.get("evolution")
    settings = ctx.get("settings")
    if pool is None or evolution is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await cobrar_valor_final(conn, evolution, settings)


async def cron_reengajar(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    redis = ctx.get("redis")
    settings = ctx.get("settings")
    if pool is None or redis is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await reengajar_silenciosos(conn, redis, settings)


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
    # max_size=20/autocommit=True para o turno (07 §2). NAO criar ctx["redis"]: o ARQ ja injeta
    # a ArqRedis em ctx["redis"] antes do startup — sobrescrever mataria enqueue_job.
    ctx["db_pool"] = await criar_pool(settings.database_url, max_size=20, autocommit=True)
    ctx["minio"] = criar_minio(settings)
    ctx["evolution"] = EvolutionClient(settings)
    ctx["graph"] = build_graph()  # SEM checkpointer no P0 (01 §6.7)
    # Cliente de vision para validar_pix (06 §0 item 4 + §2.3): OpenAI-compatível apontado para
    # OpenRouter; instanciado uma vez e reutilizado entre invocações.
    ctx["vision_client"] = AsyncOpenAI(
        api_key=settings.openrouter_api_key or "",
        base_url="https://openrouter.ai/api/v1",
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("db_pool")
    if pool is not None:
        await fechar_pool(pool)
    vision_client = ctx.get("vision_client")
    if vision_client is not None:
        await vision_client.close()


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
    # keep_result=0 SO p/ processar_turno (09 §4.9): o keep_result=3600 global quebra o
    # re-enqueue do drain (_job_id estatico) por 1h apos o termino (arq#416/#432).
    functions: ClassVar[list[Any]] = [
        func(processar_turno, keep_result=0),
        func(enviar_card),  # cards no grupo (05 §6); keep_result default (global 3600)
        func(enviar_turno),  # humanização do turno (05 §1/§4); keep_result default (global 3600)
        func(rotear_imagem),  # roteamento de imagem sob lock:conv (06 §2.1)
        func(validar_pix),  # validação de comprovante (06 §2.2); keep_result default
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(cron_timeout_interno, name="timeout_interno"),
        cron(cron_confirmar_em_execucao, name="confirmar_em_execucao"),
        cron(cron_cobrar_valor_final, name="cobrar_valor_final"),
        cron(
            cron_timeout_longo,
            name="timeout_longo",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(
            cron_reengajar,
            name="reengajar_silenciosos",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(cron_limpar_midias, name="limpar_midias", hour={3}, minute={0}),
    ]
    keep_result = 3600  # global; processar_turno sobrescreve p/ 0 via func(...) acima
    max_jobs = 10
    job_timeout = 400  # so a rede externa: cobre MAX_DRAIN x (60s graph + overhead) (07 §2)
