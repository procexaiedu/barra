"""Integração do endpoint /v1/crm/clientes/mapa — payload dos pontos.

Cobre os campos do MAPA-5 (ultima_data, recorrente) além dos já existentes.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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


def _ponto_row(
    cliente_id: UUID,
    *,
    nome: str,
    lat: float | None,
    lng: float | None,
    bairro: str | None,
    endereco: str | None,
    total_atendimentos: int,
    total_fechados: int,
    valor_total: Decimal,
    ultima_data: datetime | None,
) -> dict[str, Any]:
    return {
        "id": cliente_id,
        "nome": nome,
        "latitude": Decimal(str(lat)) if lat is not None else None,
        "longitude": Decimal(str(lng)) if lng is not None else None,
        "bairro": bairro,
        "endereco_formatado": endereco,
        "ultima_data": ultima_data,
        "total_atendimentos": total_atendimentos,
        "total_fechados": total_fechados,
        "valor_total": valor_total,
    }


class FakeConnMapa:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        return _Result(self.rows)


def test_mapa_clientes_expõe_ultima_data_e_recorrente() -> None:
    cliente_a = uuid4()
    cliente_b = uuid4()
    cliente_sem_geo = uuid4()
    agora = datetime.now(UTC)
    ontem = agora - timedelta(days=1)

    rows = [
        # Recorrente: 3 fechados → recorrente=True.
        _ponto_row(
            cliente_a,
            nome="Ana",
            lat=-22.97,
            lng=-43.18,
            bairro="Barra",
            endereco="Av. das Américas, 500",
            total_atendimentos=4,
            total_fechados=3,
            valor_total=Decimal("12400.00"),
            ultima_data=agora,
        ),
        # Não-recorrente: 1 fechado → recorrente=False.
        _ponto_row(
            cliente_b,
            nome="Bruno",
            lat=-23.55,
            lng=-46.63,
            bairro="Jardins",
            endereco="Rua Oscar Freire, 200",
            total_atendimentos=1,
            total_fechados=1,
            valor_total=Decimal("850.00"),
            ultima_data=ontem,
        ),
        # Sem geo: não vira ponto e entra no total_sem_localizacao.
        _ponto_row(
            cliente_sem_geo,
            nome="Caio",
            lat=None,
            lng=None,
            bairro=None,
            endereco=None,
            total_atendimentos=0,
            total_fechados=0,
            valor_total=Decimal("0"),
            ultima_data=None,
        ),
    ]

    async def _override():
        yield FakeConnMapa(rows)

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["total_sem_localizacao"] == 1
        assert len(body["pontos"]) == 2

        ana = next(p for p in body["pontos"] if p["nome"] == "Ana")
        assert ana["ultima_data"] is not None
        assert ana["ultima_data"].startswith(agora.strftime("%Y-%m-%d"))
        assert ana["recorrente"] is True

        bruno = next(p for p in body["pontos"] if p["nome"] == "Bruno")
        assert bruno["ultima_data"].startswith(ontem.strftime("%Y-%m-%d"))
        assert bruno["recorrente"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)
