"""Vínculo modelo x fetiche grava o PREÇO do extra (ADR-0030, revisão de 11/08/2026 — pendência 1).

O painel voltou a digitar o valor: `preco` no body é o extra cobrado, fixo, e `null`/ausente é
incluso. Acabou o sentinel `Decimal("1")` que a API gravava só para dizer "pago". Quem LÊ continua
tolerando as linhas legadas com o sentinel (piso `PRECO_FETICHE_CADASTRADO_MINIMO` em
dominio/atendimentos/service.py) — só a escrita mudou.
"""

from datetime import UTC, datetime
from decimal import Decimal
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


def _fetiche_row(fetiche_id: Any, *, cobra_por_pessoa: bool = False) -> dict[str, Any]:
    return {
        "id": fetiche_id,
        "nome": "Beijo grego",
        "ordem": 0,
        "cobra_por_pessoa": cobra_por_pessoa,
        "created_at": datetime.now(UTC),
    }


class FakeConn:
    def __init__(
        self,
        modelo_id: Any,
        fetiche_id: Any,
        preco_gravado: Any = None,
        *,
        cobra_por_pessoa: bool = False,
    ) -> None:
        self.modelo_id = modelo_id
        self.fetiche_id = fetiche_id
        self.cobra_por_pessoa = cobra_por_pessoa
        # Preço já persistido, para o GET (linha legada com sentinel, incluso, ou preço real).
        self.preco_gravado = preco_gravado
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.modelos WHERE id" in query:
            return _Result([_modelo_row(self.modelo_id)])
        if "FROM barravips.fetiches WHERE id" in query:
            return _Result([_fetiche_row(self.fetiche_id, cobra_por_pessoa=self.cobra_por_pessoa)])
        if "INSERT INTO barravips.modelo_fetiches" in query:
            _, _, preco = params  # type: ignore[misc]
            return _Result([{"fetiche_id": self.fetiche_id, "preco": preco}])
        if "UPDATE barravips.modelo_fetiches" in query:
            preco = params[0]  # type: ignore[index]
            return _Result([{"fetiche_id": self.fetiche_id, "preco": preco}])
        if "SELECT mf.fetiche_id" in query:
            return _Result(
                [
                    {
                        "fetiche_id": self.fetiche_id,
                        "preco": self.preco_gravado,
                        "nome": "Beijo grego",
                        "cobra_por_pessoa": self.cobra_por_pessoa,
                    }
                ]
            )
        return _Result([])


def _override(fake: FakeConn) -> None:
    async def _gen():
        yield fake

    app.dependency_overrides[get_conn] = _gen


def _preco_do_insert(fake: FakeConn) -> Any:
    _, params = next(
        (q, p) for q, p in fake.executes if "INSERT INTO barravips.modelo_fetiches" in q
    )
    _, _, preco = params  # type: ignore[misc]
    return preco


def test_vincular_fetiche_com_preco_grava_o_valor_digitado() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "preco": 250},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["preco"] == 250.0
        assert body["pago"] is True
        assert _preco_do_insert(fake) == Decimal("250")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_vincular_fetiche_sem_preco_grava_nulo_incluso() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id)},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["preco"] is None
        assert body["pago"] is False
        assert _preco_do_insert(fake) is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_vincular_fetiche_com_preco_negativo_e_422() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "preco": -1},
                headers=_token(),
            )
        assert response.status_code == 422, response.text
        assert not [q for q, _ in fake.executes if "INSERT INTO barravips.modelo_fetiches" in q]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_vincular_fetiche_com_preco_zero_grava_nulo() -> None:
    # Zero é "grátis" = incluso. Gravar Decimal("0") deixaria a coluna NOT NULL (logo "pago" para
    # esta API) mas falsy no `{% if f.preco %}` de agente/prompts/fetiches.md.j2 — estado torto.
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "preco": 0},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        assert response.json()["preco"] is None
        assert _preco_do_insert(fake) is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_atualizar_fetiche_troca_o_preco_cadastrado() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                json={"preco": 400},
                headers=_token(),
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "fetiche_id": str(fetiche_id),
                "nome": "Beijo grego",
                "preco": 400.0,
                "pago": True,
                "cobra_por_pessoa": False,
            }

            # `null` explícito devolve o fetiche para incluso.
            incluso = client.patch(
                f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                json={"preco": None},
                headers=_token(),
            )
            assert incluso.status_code == 200, incluso.text
            assert incluso.json()["preco"] is None
            assert incluso.json()["pago"] is False

            # Preço negativo é recusado antes de tocar o banco.
            assert (
                client.patch(
                    f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                    json={"preco": -50},
                    headers=_token(),
                ).status_code
                == 422
            )
            # E `preco` é obrigatório no PATCH — body vazio não zera o cadastro sem querer.
            assert (
                client.patch(
                    f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                    json={},
                    headers=_token(),
                ).status_code
                == 422
            )
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_fetiches_modelo_expoe_preco_para_o_form() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id, preco_gravado=Decimal("350.00"))
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/modelos/{modelo_id}/fetiches", headers=_token())
        assert response.status_code == 200, response.text
        item = response.json()[0]
        assert item["preco"] == 350.0
        assert item["pago"] is True
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_fetiches_modelo_incluso_vem_com_preco_nulo() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id, preco_gravado=None)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/modelos/{modelo_id}/fetiches", headers=_token())
        assert response.status_code == 200, response.text
        item = response.json()[0]
        assert item["preco"] is None
        assert item["pago"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)


# --- faixa do sentinel: a API não aceita preço que a leitura reinterpreta como flag ----------
#
# `preco_cadastrado_de_fetiche` (dominio/atendimentos/service.py) trata qualquer número abaixo de
# PRECO_FETICHE_CADASTRADO_MINIMO como o sentinel legado de "pago sem valor" e cai no extra
# DERIVADO — a linha de 1 HORA do programa (ADR-0038). Um R$5 digitado no painel viraria um extra
# do tamanho da 1h dela — em silêncio. A escrita fecha a porta; `None`/`0` (incluso) e `>= piso`
# seguem valendo.


def test_vincular_fetiche_na_faixa_do_sentinel_e_422() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "preco": 5},
                headers=_token(),
            )
        assert response.status_code == 422, response.text
        assert "sentinel" in response.text
        assert "R$10" in response.text
        assert not [q for q, _ in fake.executes if "INSERT INTO barravips.modelo_fetiches" in q]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_vincular_fetiche_no_piso_do_sentinel_passa() -> None:
    """R$10 é o primeiro valor que a leitura enxerga como PREÇO, não como flag: entra."""
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/modelos/{modelo_id}/fetiches",
                json={"fetiche_id": str(fetiche_id), "preco": 10},
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        assert _preco_do_insert(fake) == Decimal("10")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_atualizar_fetiche_na_faixa_do_sentinel_e_422() -> None:
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            recusado = client.patch(
                f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                json={"preco": 9.99},
                headers=_token(),
            )
            assert recusado.status_code == 422, recusado.text
            assert not [q for q, _ in fake.executes if "UPDATE barravips.modelo_fetiches" in q]

            # O piso passa, e zero continua virando NULL (incluso) como antes.
            assert (
                client.patch(
                    f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                    json={"preco": 10},
                    headers=_token(),
                ).status_code
                == 200
            )
            zerado = client.patch(
                f"/v1/modelos/{modelo_id}/fetiches/{fetiche_id}",
                json={"preco": 0},
                headers=_token(),
            )
            assert zerado.status_code == 200, zerado.text
            assert zerado.json()["preco"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_fetiches_modelo_expoe_cobra_por_pessoa_para_o_aviso() -> None:
    """ADR-0035: o painel precisa saber que o valor digitado é POR PESSOA (a IA cobra em dobro)."""
    modelo_id, fetiche_id = uuid4(), uuid4()
    fake = FakeConn(modelo_id, fetiche_id, preco_gravado=Decimal("700"), cobra_por_pessoa=True)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/modelos/{modelo_id}/fetiches", headers=_token())
        assert response.status_code == 200, response.text
        assert response.json()[0]["cobra_por_pessoa"] is True
    finally:
        app.dependency_overrides.pop(get_conn, None)
