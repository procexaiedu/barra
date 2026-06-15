"""GET /v1/crm/clientes/resumo — agregado financeiro cross-modelo do recorte."""

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


class FakeConn:
    """Roteia as duas queries (totais / por modelo) por substring."""

    def __init__(self, totais: dict[str, Any], por_modelo: list[dict[str, Any]]) -> None:
        self._totais = totais
        self._por_modelo = por_modelo

    async def execute(self, query: str, params: object = None) -> _Result:
        if "JOIN barravips.modelos m" in query and "GROUP BY m.id" in query:
            return _Result(self._por_modelo)
        if "ag.total_fechados >= 2" in query:
            return _Result([self._totais])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override_factory(fake: object):
    async def _override():
        yield fake

    return _override


def test_resumo_clientes_financeiro_e_ticket() -> None:
    modelo = uuid4()
    fake = FakeConn(
        totais={
            "total_clientes": 10,
            "recorrentes": 3,
            "com_fechamento": 8,
            "faturamento_bruto_brl": 4000.0,
        },
        por_modelo=[
            {
                "modelo_id": modelo,
                "modelo_nome": "Vitória",
                "fechados": 8,
                "faturamento_bruto_brl": 4000.0,
            }
        ],
    )
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/resumo", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["total_clientes"] == 10
        assert body["recorrentes"] == 3
        assert body["faturamento_bruto_brl"] == 4000.0
        assert body["ticket_medio_brl"] == 500.0  # 4000 / 8 com_fechamento
        assert body["por_modelo"][0]["ticket_medio_brl"] == 500.0
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_resumo_clientes_sem_fechamento_ticket_nulo() -> None:
    fake = FakeConn(
        totais={
            "total_clientes": 5,
            "recorrentes": 0,
            "com_fechamento": 0,
            "faturamento_bruto_brl": 0.0,
        },
        por_modelo=[],
    )
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/resumo", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["ticket_medio_brl"] is None
        assert body["por_modelo"] == []
    finally:
        app.dependency_overrides.pop(get_conn, None)
