"""Integração da rota /v1/crm/clientes/mapa — cor por desfecho (MAPA-3, ADR 0008)."""

from contextlib import asynccontextmanager
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


class FakeConnMapa:
    """Mock do `mapa_clientes`: responde a query do endpoint com as linhas configuradas."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.clientes" in query and "LATERAL" in query and "geo.estado" in query:
            return _Result(self.rows)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _ponto(estado: str, cliente_id: UUID | None = None) -> dict[str, Any]:
    return {
        "id": cliente_id or uuid4(),
        "nome": f"Cliente {estado}",
        "latitude": -22.97,
        "longitude": -43.18,
        "bairro": "Copacabana",
        "endereco_formatado": "Av. Atlântica, 1000",
        "estado": estado,
        "total_atendimentos": 1,
        "valor_total": 0,
    }


def test_mapa_clientes_propaga_estado_fechado() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Fechado"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_perdido() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Perdido")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Perdido"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_em_andamento() -> None:
    # "em andamento" não é um valor único do enum: qualquer estado não-terminal
    # cabe (Triagem/Qualificado/Aguardando_confirmacao/Confirmado/Em_execucao).
    # MAPA-3 colore esses três grupos como verde/vermelho/âmbar — basta garantir
    # que o estado bruto chega ao payload para o frontend mapear a cor.
    async def _override():
        yield FakeConnMapa([_ponto("Em_execucao")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Em_execucao"
    finally:
        app.dependency_overrides.pop(get_conn, None)
