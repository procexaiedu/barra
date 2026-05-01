"""Integração da rota /v1/agenda/bloqueios — sobreposição retorna 409."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.errors import ExclusionViolation

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnSobreposto:
    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "INSERT INTO barravips.bloqueios" in query:
            raise ExclusionViolation("conflito de horário")
        return _Result([])


class FakeConnOk:
    def __init__(self) -> None:
        self.bloqueio = {
            "id": uuid4(),
            "modelo_id": uuid4(),
            "estado": "bloqueado",
        }

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "INSERT INTO barravips.bloqueios" in query:
            return _Result([self.bloqueio])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _body() -> dict[str, str]:
    return {
        "modelo_id": str(uuid4()),
        "inicio": "2026-04-30T22:00:00-03:00",
        "fim": "2026-04-30T23:00:00-03:00",
        "observacao": "Bloqueio manual",
    }


async def _override_sobreposto():
    yield FakeConnSobreposto()


async def _override_ok():
    yield FakeConnOk()


def test_bloqueio_sobreposto_retorna_409() -> None:
    app.dependency_overrides[get_conn] = _override_sobreposto
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "CONFLITO_ESTADO"
        assert "sobreposto" in body["error"]["message"].lower()
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_sem_conflito_retorna_201() -> None:
    app.dependency_overrides[get_conn] = _override_ok
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 201
        assert response.json()["estado"] == "bloqueado"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_intervalo_invalido_retorna_422() -> None:
    app.dependency_overrides[get_conn] = _override_ok
    try:
        body = _body()
        body["fim"] = body["inicio"]
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)
