"""Integração da rota /v1/eventos — timeline + filtros."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_query: str | None = None
        self.last_params: object = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.last_query = query
        self.last_params = params
        return _Result(self.rows)


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _evento(atendimento_id: object | None = None) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "atendimento_id": atendimento_id or uuid4(),
        "tipo": "transicao_estado",
        "origem": "agente",
        "autor": "IA",
        "payload": {"de": "Novo", "para": "Triagem"},
        "created_at": datetime.now(UTC),
    }


def test_listar_eventos_vazio_retorna_200() -> None:
    fake = FakeConn([])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/eventos", headers=_token())
        assert response.status_code == 200
        assert response.json() == {"items": [], "next_cursor": None}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_eventos_filtra_por_atendimento() -> None:
    atendimento_id = uuid4()
    fake = FakeConn([_evento(atendimento_id), _evento(atendimento_id)])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/eventos",
                params={"atendimento_id": str(atendimento_id), "tipo": "transicao_estado"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert "e.atendimento_id = %s" in fake.last_query
        assert "e.tipo = %s" in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_eventos_paginacao_devolve_cursor() -> None:
    eventos = [_evento() for _ in range(3)]
    fake = FakeConn(eventos)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/eventos", params={"limit": 2}, headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is not None
    finally:
        app.dependency_overrides.pop(get_conn, None)
