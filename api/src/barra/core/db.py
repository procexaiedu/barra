"""Pool psycopg3 compartilhado pela aplicacao."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def _configurar_conexao(conn: AsyncConnection[Any]) -> None:
    # PgBouncer em transaction mode (Supabase pooler) reusa conexoes fisicas
    # entre clientes e nao suporta prepared statements nomeados — desabilita.
    conn.prepare_threshold = None


async def criar_pool(
    database_url: str,
    *,
    max_size: int | None = None,
    autocommit: bool = False,
) -> AsyncConnectionPool[Any] | None:
    # Defaults preservam o comportamento da API (chama sem kwargs): autocommit=False e
    # tamanho de pool padrao do psycopg_pool. O worker ARQ passa max_size=20, autocommit=True
    # (07 §2). `configure=_configurar_conexao` (prepare_threshold=None) e OBRIGATORIO no
    # Supavisor transaction mode (ADR-0002) — nunca inlinar um AsyncConnectionPool sem ele.
    if not database_url:
        return None
    extra: dict[str, Any] = {}
    if max_size is not None:
        extra["max_size"] = max_size
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        database_url,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": autocommit},
        configure=_configurar_conexao,
        **extra,
    )
    await pool.open()
    return pool


async def fechar_pool(pool: AsyncConnectionPool[Any] | None) -> None:
    if pool is not None:
        await pool.close()


@asynccontextmanager
async def conexao(pool: AsyncConnectionPool[Any]) -> AsyncIterator[AsyncConnection[Any]]:
    async with pool.connection() as conn:
        yield conn
