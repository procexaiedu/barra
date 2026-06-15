"""GET /v1/modelos/resumo — contagens por situação + faturamento total do recorte."""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any]:
        return self._row


class FakeConn:
    """Roteia contagens / financeiro por substring."""

    def __init__(self, contagens: dict[str, Any], financeiro: dict[str, Any]) -> None:
        self._contagens = contagens
        self._financeiro = financeiro

    async def execute(self, query: str, params: object = None) -> _Result:
        if "JOIN barravips.atendimentos at" in query:
            return _Result(self._financeiro)
        return _Result(self._contagens)


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override_factory(fake: object):
    async def _override():
        yield fake

    return _override


def test_resumo_modelos_situacao_e_faturamento() -> None:
    fake = FakeConn(
        contagens={
            "total": 15,
            "ativas": 1,
            "pausadas": 0,
            "inativas": 14,
            "whatsapp_pendente": 14,
            "sem_nivel": 15,
        },
        financeiro={"fechados": 384, "faturamento_bruto_brl": 235080.0},
    )
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/modelos/resumo", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 15
        assert body["ativas"] == 1
        assert body["inativas"] == 14
        assert body["whatsapp_pendente"] == 14
        assert body["sem_nivel"] == 15
        assert body["fechados"] == 384
        assert body["faturamento_bruto_brl"] == 235080.0
    finally:
        app.dependency_overrides.pop(get_conn, None)
