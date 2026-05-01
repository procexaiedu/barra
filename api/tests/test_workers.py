import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from barra.workers.timeouts import aplicar_timeout_longo


class _Result:
    async def fetchall(self):
        return [{"atendimento_id": uuid4()}]


class FakeConn:
    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str):
        assert "auto_timeout" in query
        return _Result()


def test_timeout_longo_marca_perdido() -> None:
    total = asyncio.run(aplicar_timeout_longo(FakeConn()))
    assert total == 1
