"""GET /v1/atendimentos/resumo (agregado financeiro) e filtro estado=todos."""

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


class FakeConnResumo:
    """Roteia as duas queries do resumo (por estado / por modelo) por substring."""

    def __init__(
        self,
        por_estado: list[dict[str, Any]],
        por_modelo: list[dict[str, Any]],
    ) -> None:
        self._por_estado = por_estado
        self._por_modelo = por_modelo
        self.queries: list[str] = []
        self.params: list[Any] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if params is not None:
            self.params = list(params)
        if "JOIN barravips.modelos m" in query and "GROUP BY m.id" in query:
            return _Result(self._por_modelo)
        if "GROUP BY a.estado" in query:
            return _Result(self._por_estado)
        return _Result([])


class FakeConnLista:
    """Captura a query principal da listagem para inspecionar o WHERE."""

    def __init__(self) -> None:
        self.last_query: str | None = None

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.atendimentos a" in query and "JOIN barravips.clientes" in query:
            self.last_query = query
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override_factory(fake: object):
    async def _override():
        yield fake

    return _override


def test_resumo_agrega_faturamento_e_ticket() -> None:
    modelo_a = uuid4()
    modelo_b = uuid4()
    fake = FakeConnResumo(
        por_estado=[
            {"estado": "Fechado", "total": 3, "faturamento_bruto_brl": 900.0},
            {"estado": "Perdido", "total": 1, "faturamento_bruto_brl": 0.0},
        ],
        por_modelo=[
            {
                "modelo_id": modelo_a,
                "modelo_nome": "Vitória",
                "fechados": 2,
                "faturamento_bruto_brl": 700.0,
            },
            {
                "modelo_id": modelo_b,
                "modelo_nome": "Manu",
                "fechados": 1,
                "faturamento_bruto_brl": 200.0,
            },
        ],
    )
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos/resumo?estado=todos", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert body["fechados"] == 3
        assert body["faturamento_bruto_brl"] == 900.0
        assert body["ticket_medio_brl"] == 300.0
        assert body["por_modelo"][0]["modelo_nome"] == "Vitória"
        assert body["por_modelo"][0]["ticket_medio_brl"] == 350.0
        assert {e["estado"] for e in body["por_estado"]} == {"Fechado", "Perdido"}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_resumo_sem_fechados_ticket_nulo() -> None:
    fake = FakeConnResumo(
        por_estado=[{"estado": "Triagem", "total": 2, "faturamento_bruto_brl": 0.0}],
        por_modelo=[
            {
                "modelo_id": uuid4(),
                "modelo_nome": "Babi",
                "fechados": 0,
                "faturamento_bruto_brl": 0.0,
            }
        ],
    )
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos/resumo", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["fechados"] == 0
        assert body["faturamento_bruto_brl"] == 0.0
        assert body["ticket_medio_brl"] is None
        assert body["por_modelo"][0]["ticket_medio_brl"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_estado_todos_inclui_terminais() -> None:
    fake = FakeConnLista()
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos?estado=todos", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        # estado=todos não aplica filtro de estado: nem o default de terminais,
        # nem a igualdade a.estado = %s.
        assert "a.estado NOT IN ('Fechado', 'Perdido')" not in fake.last_query
        assert "a.estado = %s" not in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_estado_default_exclui_terminais() -> None:
    fake = FakeConnLista()
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "a.estado NOT IN ('Fechado', 'Perdido')" in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)
