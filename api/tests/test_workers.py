import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from barra.workers.timeouts import aplicar_timeout_interno, aplicar_timeout_longo


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


class _CapturaConn:
    def __init__(self) -> None:
        self.query = ""

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str):
        self.query = query
        return _Result()


def test_timeout_longo_marca_perdido() -> None:
    total = asyncio.run(aplicar_timeout_longo(FakeConn()))
    assert total == 1


def _assert_cancela_bloqueio(query: str) -> None:
    assert "barravips.bloqueios" in query
    assert "'cancelado'" in query
    assert "alvo.bloqueio_id" in query
    assert "NOT IN ('em_atendimento', 'concluido')" in query


def test_timeout_longo_cancela_bloqueio_vinculado() -> None:
    conn = _CapturaConn()
    asyncio.run(aplicar_timeout_longo(conn))
    _assert_cancela_bloqueio(conn.query)


def test_timeout_interno_cancela_bloqueio_vinculado() -> None:
    conn = _CapturaConn()
    asyncio.run(aplicar_timeout_interno(conn))
    _assert_cancela_bloqueio(conn.query)


def _assert_emite_transicao(query: str) -> None:
    # alinha timeouts com kanban + escaladas/service.py: toda transicao p/ Perdido
    # emite tambem transicao_estado {de, para} (alem de perdido_registrado).
    assert "transicao_estado" in query
    assert "jsonb_build_object" in query
    assert "'para', 'Perdido'" in query


def test_timeout_longo_emite_transicao_estado() -> None:
    conn = _CapturaConn()
    asyncio.run(aplicar_timeout_longo(conn))
    _assert_emite_transicao(conn.query)


def test_timeout_interno_emite_transicao_estado() -> None:
    conn = _CapturaConn()
    asyncio.run(aplicar_timeout_interno(conn))
    _assert_emite_transicao(conn.query)
