"""GET/DELETE /v1/atendimentos/tipos-local — listar, contar e deletar tipo_local."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(
        self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

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


class FakeConnContagem:
    def __init__(self, total: int) -> None:
        self.total = total
        self.params: list[Any] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        assert "COUNT(*)" in query
        assert "WHERE tipo_local = %s" in query
        # SQL parametrizado: o valor entra por params, nunca interpolado na query.
        self.params = list(params or [])
        return _Result(rows=[{"total": self.total}])


def test_contar_tipos_local_zero() -> None:
    conn = FakeConnContagem(total=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos/tipos-local/hotle/contagem", headers=_token()
            )
        assert response.status_code == 200
        assert response.json() == {"contagem": 0}
        assert conn.params == ["hotle"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_contar_tipos_local_varios() -> None:
    conn = FakeConnContagem(total=3)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos/tipos-local/hotel/contagem", headers=_token()
            )
        assert response.status_code == 200
        assert response.json() == {"contagem": 3}
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnDelete:
    def __init__(self, afetados: int) -> None:
        self.afetados = afetados
        self.query = ""
        self.params: list[Any] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.query = query
        self.params = list(params or [])
        return _Result(rowcount=self.afetados)


def test_deletar_tipo_local_zero_atendimentos() -> None:
    # Tipo sem atendimentos: o UPDATE roda mesmo assim e afeta 0 linhas.
    conn = FakeConnDelete(afetados=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.delete(
                "/v1/atendimentos/tipos-local/hotle", headers=_token()
            )
        assert response.status_code == 200
        assert response.json() == {"afetados": 0}
        assert "SET tipo_local = NULL" in conn.query
        assert conn.params == ["hotle"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_deletar_tipo_local_com_substituto() -> None:
    conn = FakeConnDelete(afetados=5)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.delete(
                "/v1/atendimentos/tipos-local/hotle?substituto=hotel",
                headers=_token(),
            )
        assert response.status_code == 200
        assert response.json() == {"afetados": 5}
        assert "SET tipo_local = %s" in conn.query
        # parametrizado: substituto e nome entram por params, nessa ordem.
        assert conn.params == ["hotel", "hotle"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_deletar_tipo_local_sem_substituto_limpa() -> None:
    conn = FakeConnDelete(afetados=4)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.delete(
                "/v1/atendimentos/tipos-local/hotle", headers=_token()
            )
        assert response.status_code == 200
        assert response.json() == {"afetados": 4}
        assert "SET tipo_local = NULL" in conn.query
        assert conn.params == ["hotle"]
    finally:
        app.dependency_overrides.pop(get_conn, None)
