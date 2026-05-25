"""Cliente Redis compartilhado: lock por conversa com heartbeat (07 §3.1).

O coordenador (`workers/coordenador.py`) usa `adquirir_lock` para serializar o turno por
conversa contra o `rotear_imagem` (06 §2.1). A ArqRedis injetada em `ctx["redis"]` (subclasse
de `redis.asyncio.Redis`) serve tanto para o lock quanto para `enqueue_job` — nao criar um
cliente Redis separado (07 §2).
"""

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

from redis.asyncio import Redis

# Release condicional: so apaga a chave se ainda formos o dono (token bate). Roda atomico no
# servidor — evita apagar um lock que ja expirou e foi readquirido por outro worker.
_LUA_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


class LockBusy(Exception):
    """lock:conv ja esta retido por outro job (contende com rotear_imagem, 06 §2.1)."""

    def __init__(self, chave: str) -> None:
        super().__init__(chave)
        self.chave = chave


@asynccontextmanager
async def adquirir_lock(
    redis: Redis, chave: str, *, ttl: int, heartbeat_interval: int
) -> AsyncIterator[None]:
    """SETNX com TTL; renova o TTL em background enquanto for dono; release condicional via Lua.

    Levanta `LockBusy(chave)` se a chave ja existir. A task de heartbeat estende o TTL a cada
    `heartbeat_interval`s desde que ainda sejamos o dono (token bate); se outro worker tomou o
    lock (token divergente) ou ele expirou, o heartbeat para de renovar.
    """
    token = secrets.token_hex(8)
    ok = await redis.set(chave, token, nx=True, ex=ttl)
    if not ok:
        raise LockBusy(chave)

    cancelar = asyncio.Event()

    async def heartbeat() -> None:
        while not cancelar.is_set():
            try:
                await asyncio.wait_for(cancelar.wait(), timeout=heartbeat_interval)
            except TimeoutError:
                atual = await redis.get(chave)
                if atual is None:
                    cancelar.set()
                    return
                atual_str = atual.decode() if isinstance(atual, bytes) else atual
                if atual_str != token:  # outro worker readquiriu o lock — paramos de renovar
                    cancelar.set()
                    return
                await redis.expire(chave, ttl)

    hb_task = asyncio.create_task(heartbeat())
    try:
        yield
    finally:
        cancelar.set()
        await hb_task
        # redis-py async tipa eval como ResponseT (Awaitable | Any); o cast fixa o await.
        await cast(Awaitable[Any], redis.eval(_LUA_RELEASE, 1, chave, token))
