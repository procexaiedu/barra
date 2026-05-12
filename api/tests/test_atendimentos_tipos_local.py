"""GET /v1/atendimentos/tipos-local — valores distintos de tipo_local."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "SELECT DISTINCT tipo_local FROM barravips.atendimentos" in query:
            return _Result(self.rows)
        return _Result([])


def test_listar_tipos_local_banco_vazio_retorna_items_vazio() -> None:
    conn = FakeConn(rows=[])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos/tipos-local", headers=_token())
        assert response.status_code == 200
        assert response.json() == {"items": []}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_tipos_local_retorna_valores_distintos_ordenados() -> None:
    # SELECT DISTINCT ... ORDER BY tipo_local entrega apenas valores unicos ja ordenados;
    # o teste simula esse retorno do banco.
    conn = FakeConn(rows=[{"tipo_local": "casa"}, {"tipo_local": "hotel"}])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos/tipos-local", headers=_token())
        assert response.status_code == 200
        assert response.json() == {"items": ["casa", "hotel"]}
    finally:
        app.dependency_overrides.pop(get_conn, None)
