"""Camada de Modelos no Mapa (ADR 0010) — rota GET /v1/modelos/mapa.

Plota a geo OPERACIONAL das modelos (painel-only); modelo sem lat/lng cai no contador
`total_sem_localizacao_operacional`. Sem DB: FakeConn por substring de query. Garante
que campos PII/painel-only (rg/cpf/endereço residencial/percentual_repasse) NUNCA saem
no payload do mapa, conforme o contrato do ADR.
"""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

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

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.modelos" in query:
            return _Result(self.rows)
        return _Result([])


def test_mapa_modelos_plota_com_geo_conta_sem_geo_e_nao_vaza_pii() -> None:
    rows = [
        {
            "id": uuid4(),
            "nome": "Ana",
            "status": "ativa",
            "tipo_fisico": "ruiva",
            "tipo_atendimento_aceito": ["interno", "externo"],
            "latitude": -23.5,
            "longitude": -46.6,
        },
        {
            "id": uuid4(),
            "nome": "Bia",
            "status": "pausada",
            "tipo_fisico": None,
            "tipo_atendimento_aceito": ["remoto"],
            "latitude": -22.9,
            "longitude": -43.2,
        },
        {
            "id": uuid4(),
            "nome": "Duda",
            "status": "inativa",
            "tipo_fisico": None,
            "tipo_atendimento_aceito": [],
            "latitude": None,  # geo operacional ausente -> contador, não vira ponto
            "longitude": None,
        },
    ]
    conn = FakeConn(rows)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/modelos/mapa", headers=_token())
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2  # só as 2 com geo
        assert body["total_sem_localizacao_operacional"] == 1
        # Contrato exato do item (ADR 0010): só o não-sensível.
        assert set(body["items"][0]) == {
            "id",
            "nome",
            "status",
            "tipo_fisico",
            "tipo_atendimento_aceito",
            "latitude",
            "longitude",
        }
        # Nenhum campo PII/painel-only sensível no payload inteiro.
        blob = r.text
        for proibido in ("rg", "cpf", "percentual_repasse", "endereco_residencial"):
            assert proibido not in blob
    finally:
        app.dependency_overrides.pop(get_conn, None)
