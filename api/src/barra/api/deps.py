"""Dependencias FastAPI compartilhadas."""

from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import Depends, Request
from psycopg import AsyncConnection

from barra.core.auth import UsuarioAtual, usuario_atual
from barra.core.errors import ErroDominio
from barra.settings import Settings


def get_settings_dep(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection[Any]]:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco indisponivel.", status_code=503)
    async with pool.connection() as conn:
        yield conn


async def get_user(user: UsuarioAtual = Depends(usuario_atual)) -> UsuarioAtual:
    return user
