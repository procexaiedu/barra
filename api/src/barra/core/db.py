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


async def criar_pool(database_url: str) -> AsyncConnectionPool[Any] | None:
    if not database_url:
        return None
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        database_url,
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": False},
        configure=_configurar_conexao,
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
