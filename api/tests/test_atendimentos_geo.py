"""Round-trip de geo do atendimento: PATCH /dados grava e GET detalhe recupera.

Reflete a decisão de que o geo do atendimento representa o endereço do cliente
(foco externo). Atendimento legado sem lat/lng continua válido. Padrão FakeConn,
sem banco — exercita o builder genérico do UPDATE e o SELECT a.* do detalhe.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app

_ENDERECO = "Av. Paulista, 1000 - Bela Vista, São Paulo - SP, Brasil"
_PLACE_ID = "ChIJ0WGkg4FEzpQRrlsz_test"


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


class FakeConnEditar:
    """SELECT id confirma existência; captura UPDATE/INSERT em self.executes."""

    def __init__(self, atendimento_id: UUID) -> None:
        self.atendimento_id = atendimento_id
        self.executes: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "SELECT id FROM barravips.atendimentos" in query:
            return _Result([{"id": self.atendimento_id}])
        return _Result([])

    def update(self) -> tuple[str, list[Any]]:
        for query, params in self.executes:
            if "UPDATE barravips.atendimentos SET" in query:
                return query, list(params)
        raise AssertionError("UPDATE não emitido")


def _set_map(query: str, params: list[Any]) -> dict[str, Any]:
    """Mapeia coluna -> valor a partir do SET (mesma ordem do builder)."""
    set_part = query.split("SET", 1)[1].split("WHERE", 1)[0]
    colunas = [trecho.split("=")[0].strip() for trecho in set_part.split(",")]
    # params traz um item a mais (o id do WHERE); zip para na menor lista de propósito.
    return dict(zip(colunas, params, strict=False))


def test_editar_dados_grava_geo() -> None:
    atendimento_id = uuid4()
    conn = FakeConnEditar(atendimento_id)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.patch(
                f"/v1/atendimentos/{atendimento_id}/dados",
                json={
                    "endereco": _ENDERECO,
                    "endereco_formatado": _ENDERECO,
                    "latitude": -23.5505,
                    "longitude": -46.6333,
                    "place_id": _PLACE_ID,
                    "bairro": "Bela Vista",
                },
                headers=_token(),
            )
        assert resp.status_code == 200, resp.text
        query, params = conn.update()
        mapa = _set_map(query, params)
        assert mapa["endereco_formatado"] == _ENDERECO
        assert mapa["place_id"] == _PLACE_ID
        assert float(mapa["latitude"]) == -23.5505
        assert float(mapa["longitude"]) == -46.6333
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_editar_dados_legado_sem_geo_continua_valido() -> None:
    atendimento_id = uuid4()
    conn = FakeConnEditar(atendimento_id)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.patch(
                f"/v1/atendimentos/{atendimento_id}/dados",
                json={"endereco": "Rua Sem Geo, 123", "bairro": "Centro"},
                headers=_token(),
            )
        assert resp.status_code == 200, resp.text
        query, _ = conn.update()
        assert "endereco = %s" in query
        for coluna in ("latitude", "longitude", "place_id", "endereco_formatado"):
            assert coluna not in query
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnDetalhe:
    """Detalhe (SELECT a.*) devolve a linha com geo; demais queries vazias."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.atendimentos a" in query:
            return _Result([self.row])
        return _Result([])


def _detalhe_row(atendimento_id: UUID) -> dict[str, Any]:
    return {
        "id": atendimento_id,
        "cliente_id": uuid4(),
        "cliente_nome": "Cliente X",
        "cliente_telefone": "5521900000000",
        "modelo_id": uuid4(),
        "modelo_nome": "Aurora",
        "conversa_id": uuid4(),
        "conversa_recorrente": False,
        "conversa_observacoes": None,
        "conversa_ultimo_motivo_perda": None,
        "bloqueio_id": None,
        "endereco": _ENDERECO,
        "bairro": "Bela Vista",
        "endereco_formatado": _ENDERECO,
        "latitude": Decimal("-23.5505000"),
        "longitude": Decimal("-46.6333000"),
        "place_id": _PLACE_ID,
    }


def test_obter_atendimento_recupera_geo() -> None:
    atendimento_id = uuid4()
    conn = FakeConnDetalhe(_detalhe_row(atendimento_id))
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get(f"/v1/atendimentos/{atendimento_id}", headers=_token())
        assert resp.status_code == 200, resp.text
        at = resp.json()["atendimento"]
        assert at["endereco_formatado"] == _ENDERECO
        assert at["place_id"] == _PLACE_ID
        assert float(at["latitude"]) == -23.5505
        assert float(at["longitude"]) == -46.6333
    finally:
        app.dependency_overrides.pop(get_conn, None)
