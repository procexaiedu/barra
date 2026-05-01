import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from barra.api.v1 import router as api_v1_router
from barra.core.db import criar_pool, fechar_pool
from barra.core.errors import instalar_handlers
from barra.core.metrics import MetricsMiddleware, prometheus_response
from barra.core.storage import criar_minio
from barra.settings import get_settings
from barra.webhook.routes import router as webhook_router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    import sentry_sdk as _sentry_sdk
except ModuleNotFoundError:  # pragma: no cover
    sentry_sdk: ModuleType | None = None
else:
    sentry_sdk = _sentry_sdk


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    app.state.db_pool = await criar_pool(settings.database_url)
    app.state.minio = criar_minio(settings)
    yield
    await fechar_pool(app.state.db_pool)


def build_app() -> FastAPI:
    settings = get_settings()
    if settings.sentry_dsn and sentry_sdk is not None:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.ambiente)

    app = FastAPI(
        title="Barra Vips API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.ambiente != "producao" else None,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Webhook-Token"],
    )
    app.add_middleware(MetricsMiddleware)
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
