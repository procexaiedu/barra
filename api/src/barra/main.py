import asyncio
import logging
import re
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from barra.api.v1 import router as api_v1_router
from barra.core.db import criar_pool, fechar_pool
from barra.core.errors import instalar_handlers
from barra.core.logging import setup_logging
from barra.core.metrics import MetricsMiddleware, prometheus_response
from barra.core.storage import criar_minio, ensure_bucket
from barra.core.tracing import init_sentry, setup_tracing
from barra.settings import get_settings
from barra.webhook.routes import router as webhook_router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    dev = settings.ambiente != "producao"
    app.state.db_pool = await criar_pool(settings.database_url)
    app.state.minio = criar_minio(settings)
    # MinIO/Redis vivem no swarm; em dev a maquina pode nao alcanca-los. Fora de producao
    # toleramos a falha (sobe sem midia/ARQ) — em producao propagamos (fail-fast).
    try:
        ensure_bucket(app.state.minio, settings.minio_bucket_media)
    except Exception:
        if not dev:
            raise
        _logger.warning(
            "minio_indisponivel_dev endpoint=%s; seguindo sem bucket", settings.minio_endpoint
        )
    # Pool ARQ p/ enfileirar o turno (01 §4.2) — a MESMA conexao Redis do coordenador.
    # Sem redis_url (dev/teste) nao cria pool: o webhook so persiste a mensagem.
    app.state.arq = await _criar_arq_pool(settings.redis_url, dev)
    yield
    if app.state.arq is not None:
        await app.state.arq.aclose()
    await fechar_pool(app.state.db_pool)


def build_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    init_sentry(settings)
    setup_tracing(settings)

    app = FastAPI(
        title="Elite Baby API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.ambiente != "producao" else None,
    )
    app.state.settings = settings
    if settings.ambiente == "producao":
        regex = settings.cors_origin_regex
        # "regex amplo equivalente": testa o comportamento (casa origin arbitraria via fullmatch,
        # como o CORSMiddleware faz), nao a forma sintatica — pega ".*", ".+", "https?://.*", etc.
        regex_amplo = regex is not None and any(
            re.compile(regex).fullmatch(origem)
            for origem in ("https://origem-arbitraria.example", "http://outra.test", "null")
        )
        if any("*" in origem for origem in settings.cors_origins) or regex_amplo:
            raise RuntimeError(
                "CORS curinga proibido em producao: configure cors_origins explicitos "
                "(sem '*' nem regex que case origin arbitraria)."
            )
        # Fail-closed dos segredos: com default vazio, o gate de token do webhook
        # (routes.py) e curto-circuitado e o webhook aceita POST nao autenticado; sem o
        # jwt_secret o painel perde a verificacao de assinatura. Em producao isso e fatal.
        if not settings.evolution_webhook_token:
            raise RuntimeError(
                "EVOLUTION_WEBHOOK_TOKEN obrigatorio em producao: sem ele o /webhook/evolution "
                "fica fail-open (aceita POST nao autenticado)."
            )
        if not settings.supabase_jwt_secret:
            raise RuntimeError(
                "SUPABASE_JWT_SECRET obrigatorio em producao: sem ele o JWT do painel perde a "
                "verificacao de assinatura."
            )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Webhook-Token"],
    )
    app.add_middleware(MetricsMiddleware)

    @app.middleware("http")
    async def adicionar_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # OBS-07: request-id por requisicao (captura X-Request-ID do upstream ou gera). Vai em
        # request.state p/ o webhook propagar no job do turno e correlaciona os logs JSON
        # (OBS-03) da API ate o worker; ecoa no header da resposta. O header e dado nao-confiavel:
        # trunca p/ nao inflar o payload do job (Redis) nem o volume de log; o JSONRenderer ja
        # escapa CRLF/aspas, entao nao ha log/header splitting.
        recebido = request.headers.get("X-Request-ID")
        request_id = recebido[:128] if recebido else str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    instalar_handlers(app)
    app.include_router(api_v1_router, prefix="/v1")
    app.include_router(webhook_router, prefix="/webhook")

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    async def ready() -> dict[str, object]:
        db_ok = False
        redis_ok = False
        pool = getattr(app.state, "db_pool", None)
        if pool is not None:
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
                db_ok = True
        if settings.redis_url:
            redis_ok = await _tcp_ready(settings.redis_url)
        status = "ok"
        if (settings.database_url and not db_ok) or (settings.redis_url and not redis_ok):
            status = "degraded"
        return {"status": status, "db": db_ok, "redis": redis_ok}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Any:
        return prometheus_response()

    return app


app = build_app()


async def _criar_arq_pool(redis_url: str, dev: bool) -> Any:
    """Pool ARQ p/ enfileirar turnos. None quando sem redis_url.

    Em producao a falha de conexao propaga (fail-fast: sem ARQ o agente nao roda). Em dev
    o Redis costuma viver no swarm, inalcancavel da maquina local — toleramos a falha (retries
    curtos p/ nao pendurar) e seguimos com arq=None: o webhook so persiste a mensagem.
    """
    if not redis_url:
        return None
    redis_settings = RedisSettings.from_dsn(redis_url)
    if dev:
        redis_settings.conn_retries = 1
        redis_settings.conn_retry_delay = 0
    try:
        return await create_pool(redis_settings)
    except Exception:
        if not dev:
            raise
        _logger.warning(
            "redis_indisponivel_dev url=%s; seguindo sem ARQ (webhook so persiste)", redis_url
        )
        return None


async def _tcp_ready(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(parsed.hostname, parsed.port or 6379),
            timeout=1,
        )
        writer.close()
        await writer.wait_closed()
        _ = reader
        return True
    except OSError:
        return False
