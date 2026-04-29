from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from barra.api.v1 import router as api_v1_router
from barra.settings import get_settings
from barra.webhook.routes import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: pool Postgres, checkpointer, redis, evolution, llm.
    # AsyncConnectionPool + AsyncPostgresSaver são criados aqui (ver core/db.py e agente/graph.py).
    yield
    # Shutdown: fechar pools.


def build_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Barra Vips API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.ambiente != "producao" else None,
    )
    app.include_router(api_v1_router, prefix="/v1")
    app.include_router(webhook_router, prefix="/webhook")
    return app


app = build_app()
