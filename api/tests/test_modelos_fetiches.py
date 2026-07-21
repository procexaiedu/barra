"""Vínculo modelo x fetiche vira toggle incluso/pago (ADR-0030, ticket 02): o endpoint para de
aceitar um preço numérico livre e passa a aceitar só o booleano `pago`. O valor do extra nunca é
lido por aqui — é sempre calculado no momento do atendimento (ver test_fetiche_preco_calculado.py).
"""

from datetime import UTC, datetime
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


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _modelo_row(modelo_id: Any) -> dict[str, Any]:
    return {"id": modelo_id, "nome": "Aurora"}


def _fetiche_row(fetiche_id: Any) -> dict[str, Any]:
    return {"id": fetiche_id, "nome": "Beijo grego", "ordem": 0, "created_at": datetime.now(UTC)}


class FakeConn:
    def __init__(self, modelo_id: Any, fetiche_id: Any) -> None:
        self.modelo_id = modelo_id
        self.fetiche_id = fetiche_id
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.modelos WHERE id" in query:
            return _Result([_modelo_row(self.modelo_id)])
        if "FROM barravips.fetiches WHERE id" in query:
            return _Result([_fetiche_row(self.fetiche_id)])
        if "INSERT INTO barravips.modelo_fetiches" in query:
            _, _, preco = params  # type: ignore[misc]
            return _Result([{"fetiche_id": self.fetiche_id, "preco": preco}])
        if "UPDATE barravips.modelo_fetiches" in query:
            preco = params[0]  # type: ignore[index]
            return _Result([{"fetiche_id": self.fetiche_id, "preco": preco}])
        if "SELECT mf.fetiche_id" in query:
            return _Result([{"fetiche_id": self.fetiche_id, "preco": None, "nome": "Beijo grego"}])
        return _Result([])


def _override(fake: FakeConn) -> None:
    async def _gen():
        yield fake

    app.dependency_overrides[get_conn] = _gen


def test_vincular_fetiche_pago_true_grava_preco_nao_nulo() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "pago": True},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["pago"] is True
        assert "preco" not in body
        _, insert_params = next(
            (q, p) for q, p in fake.executes if "INSERT INTO barravips.modelo_fetiches" in q
        )
        _, _, preco_gravado = insert_params  # type: ignore[misc]
        assert preco_gravado is not None
        # Truthy, não só not-None: agente/prompts/fetiches.md.j2 checa `{% if f.preco %}` — um
        # sentinel falsy (ex.: Decimal("0")) inverteria a cotação da IA para "incluso".
        assert preco_gravado
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_vincular_fetiche_pago_false_grava_preco_nulo() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "pago": False},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        assert response.json()["pago"] is False
        _, insert_params = next(
            (q, p) for q, p in fake.executes if "INSERT INTO barravips.modelo_fetiches" in q
        )
        _, _, preco_gravado = insert_params  # type: ignore[misc]
        assert preco_gravado is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_atualizar_fetiche_aceita_flag_pago_sem_preco_numerico() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                json={"pago": True},
                headers=_token(),
            )
        assert response.status_code == 200, response.text
        assert response.json()["pago"] is True
        # API não aceita mais um preço numérico livre — só o booleano.
        rejeitado = client.patch(
            f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
            json={"preco": 400},
            headers=_token(),
        )
        assert rejeitado.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_fetiches_modelo_expoe_flag_pago() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/modelos/{modelo_id}/fetiches", headers=_token())
        assert response.status_code == 200, response.text
        item = response.json()[0]
        assert item["pago"] is False
        assert "preco" not in item
    finally:
        app.dependency_overrides.pop(get_conn, None)
