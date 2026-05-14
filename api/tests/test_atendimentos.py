"""POST /v1/atendimentos — criacao manual via painel."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

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
    """Conn fake que simula o ciclo cliente -> modelo -> conversa upsert -> atendimento."""

    def __init__(
        self,
        *,
        cliente_id: UUID | None,
        cliente_arquivado: bool,
        modelo_id: UUID | None,
        atendimento_existente_id: UUID | None,
    ) -> None:
        self.cliente_id = cliente_id
        self.cliente_arquivado = cliente_arquivado
        self.modelo_id = modelo_id
        self.atendimento_existente_id = atendimento_existente_id
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.clientes WHERE id" in query:
            if self.cliente_id is None:
                return _Result([])
            return _Result(
                [
                    {
                        "id": self.cliente_id,
                        "telefone": "5521900000000",
                        "arquivado_em": datetime.now(UTC) if self.cliente_arquivado else None,
                    }
                ]
            )
        if "FROM barravips.modelos WHERE id" in query:
            if self.modelo_id is None:
                return _Result([])
            return _Result([{"id": self.modelo_id}])
        if "INSERT INTO barravips.conversas" in query:
            return _Result([{"id": uuid4()}])
        if "SELECT id, numero_curto, estado::text" in query and "barravips.atendimentos" in query:
            if self.atendimento_existente_id is None:
                return _Result([])
            return _Result(
                [
                    {
                        "id": self.atendimento_existente_id,
                        "numero_curto": 42,
                        "estado": "Novo",
                        "cliente_id": self.cliente_id,
                        "modelo_id": self.modelo_id,
                        "conversa_id": uuid4(),
                    }
                ]
            )
        if "INSERT INTO barravips.atendimentos" in query:
            return _Result(
                [
                    {
                        "id": uuid4(),
                        "numero_curto": 99,
                        "estado": "Novo",
                        "cliente_id": self.cliente_id,
                        "modelo_id": self.modelo_id,
                        "conversa_id": uuid4(),
                    }
                ]
            )
        return _Result([])


def test_criar_atendimento_retorna_201() -> None:
    cliente_id = uuid4()
    modelo_id = uuid4()
    conn = FakeConn(
        cliente_id=cliente_id,
        cliente_arquivado=False,
        modelo_id=modelo_id,
        atendimento_existente_id=None,
    )
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/atendimentos",
                json={"cliente_id": str(cliente_id), "modelo_id": str(modelo_id)},
                headers=_token(),
            )
        assert response.status_code == 201
        body = response.json()
        assert body["numero_curto"] == 99
        assert body["estado"] == "Novo"
        assert body["cliente_id"] == str(cliente_id)
        assert body["modelo_id"] == str(modelo_id)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_atendimento_cliente_inexistente_retorna_404() -> None:
    conn = FakeConn(
        cliente_id=None,
        cliente_arquivado=False,
        modelo_id=uuid4(),
        atendimento_existente_id=None,
    )
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/atendimentos",
                json={"cliente_id": str(uuid4()), "modelo_id": str(uuid4())},
                headers=_token(),
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_atendimento_modelo_inexistente_retorna_404() -> None:
    cliente_id = uuid4()
    conn = FakeConn(
        cliente_id=cliente_id,
        cliente_arquivado=False,
        modelo_id=None,
        atendimento_existente_id=None,
    )
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/atendimentos",
                json={"cliente_id": str(cliente_id), "modelo_id": str(uuid4())},
                headers=_token(),
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_atendimento_cliente_arquivado_retorna_409() -> None:
    cliente_id = uuid4()
    modelo_id = uuid4()
    conn = FakeConn(
        cliente_id=cliente_id,
        cliente_arquivado=True,
        modelo_id=modelo_id,
        atendimento_existente_id=None,
    )
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/atendimentos",
                json={"cliente_id": str(cliente_id), "modelo_id": str(modelo_id)},
                headers=_token(),
            )
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["message"] == "cliente_arquivado"
        assert body["error"]["details"]["cliente_id"] == str(cliente_id)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_atendimento_aberto_existente_retorna_409() -> None:
    cliente_id = uuid4()
    modelo_id = uuid4()
    atendimento_existente = uuid4()
    conn = FakeConn(
        cliente_id=cliente_id,
        cliente_arquivado=False,
        modelo_id=modelo_id,
        atendimento_existente_id=atendimento_existente,
    )
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/atendimentos",
                json={"cliente_id": str(cliente_id), "modelo_id": str(modelo_id)},
                headers=_token(),
            )
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["message"] == "atendimento_aberto_existente"
        assert body["error"]["details"]["atendimento_id"] == str(atendimento_existente)
    finally:
        app.dependency_overrides.pop(get_conn, None)
