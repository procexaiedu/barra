"""Integração da rota /v1/agenda/bloqueios — sobreposição retorna 409."""

from contextlib import asynccontextmanager
from datetime import date, time
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg.errors import ExclusionViolation, ForeignKeyViolation

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnSobreposto:
    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "INSERT INTO barravips.bloqueios" in query:
            raise ExclusionViolation("conflito de horário")
        return _Result([])


class FakeConnOk:
    def __init__(self) -> None:
        self.bloqueio = {
            "id": uuid4(),
            "modelo_id": uuid4(),
            "estado": "bloqueado",
        }

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "INSERT INTO barravips.bloqueios" in query:
            return _Result([self.bloqueio])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _body() -> dict[str, str]:
    return {
        "modelo_id": str(uuid4()),
        "inicio": "2026-04-30T22:00:00-03:00",
        "fim": "2026-04-30T23:00:00-03:00",
        "observacao": "Bloqueio manual",
    }


async def _override_sobreposto():
    yield FakeConnSobreposto()


async def _override_ok():
    yield FakeConnOk()


def test_bloqueio_sobreposto_retorna_409() -> None:
    app.dependency_overrides[get_conn] = _override_sobreposto
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "CONFLITO_ESTADO"
        assert "sobreposto" in body["error"]["message"].lower()
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_sem_conflito_retorna_201() -> None:
    app.dependency_overrides[get_conn] = _override_ok
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 201
        assert response.json()["estado"] == "bloqueado"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_intervalo_invalido_retorna_422() -> None:
    app.dependency_overrides[get_conn] = _override_ok
    try:
        body = _body()
        body["fim"] = body["inicio"]
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnAgendamento:
    """Grava as queries executadas para inspecionar o back-link da FK circular."""

    def __init__(
        self,
        *,
        atendimento_modelo_id: UUID | None = None,
        atendimento_existe: bool = True,
        fk_violation: bool = False,
    ) -> None:
        self.atendimento_modelo_id = atendimento_modelo_id
        self.atendimento_existe = atendimento_existe
        self.fk_violation = fk_violation
        self.bloqueio_id = uuid4()
        self.execucoes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.execucoes.append((query, params))
        if "SELECT modelo_id FROM barravips.atendimentos" in query:
            if not self.atendimento_existe:
                return _Result([])
            return _Result([{"modelo_id": self.atendimento_modelo_id}])
        if "INSERT INTO barravips.bloqueios" in query:
            if self.fk_violation:
                raise ForeignKeyViolation("modelo inexistente")
            assert isinstance(params, (list, tuple))
            return _Result(
                [
                    {
                        "id": self.bloqueio_id,
                        "modelo_id": params[0],
                        "atendimento_id": params[4],
                        "estado": "bloqueado",
                    }
                ]
            )
        return _Result([])


def test_agendamento_preenche_back_link_no_atendimento() -> None:
    modelo_id = uuid4()
    atendimento_id = uuid4()
    fake = FakeConnAgendamento(atendimento_modelo_id=modelo_id)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        body = _body()
        body["modelo_id"] = str(modelo_id)
        body["atendimento_id"] = str(atendimento_id)
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 201
        back_links = [
            params
            for query, params in fake.execucoes
            if "UPDATE barravips.atendimentos SET bloqueio_id = %s" in query
        ]
        assert back_links == [(fake.bloqueio_id, atendimento_id)]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_agendamento_atendimento_de_outra_modelo_retorna_409() -> None:
    fake = FakeConnAgendamento(atendimento_modelo_id=uuid4())

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        body = _body()
        body["modelo_id"] = str(uuid4())
        body["atendimento_id"] = str(uuid4())
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLITO_ESTADO"
        # Nao deve ter inserido nem mexido na FK quando a posse nao bate.
        assert not any("INSERT INTO barravips.bloqueios" in q for q, _ in fake.execucoes)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_agendamento_atendimento_inexistente_retorna_404() -> None:
    fake = FakeConnAgendamento(atendimento_existe=False)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        body = _body()
        body["atendimento_id"] = str(uuid4())
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_modelo_inexistente_retorna_404() -> None:
    fake = FakeConnAgendamento(fk_violation=True)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RECURSO_NAO_ENCONTRADO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnFora:
    """Modelo com regra de disponibilidade que NÃO cobre o horário do _body() (fora do período)."""

    def __init__(self) -> None:
        self.bloqueio = {"id": uuid4(), "modelo_id": uuid4(), "estado": "bloqueado"}
        self.execucoes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.execucoes.append((query, params))
        if "FROM barravips.modelo_disponibilidade" in query:
            # Período só em junho/2026; o bloqueio do _body() é em 30/04 -> fora.
            return _Result(
                [
                    {
                        "data_inicio": date(2026, 6, 1),
                        "data_fim": date(2026, 6, 30),
                        "dia_semana": 0,
                        "hora_inicio": time(0, 0),
                        "hora_fim": time(23, 0),
                    }
                ]
            )
        if "INSERT INTO barravips.bloqueios" in query:
            return _Result([self.bloqueio])
        return _Result([])


def test_bloqueio_fora_disponibilidade_retorna_409() -> None:
    fake = FakeConnFora()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=_body(), headers=_token())
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "CONFLITO_ESTADO"
        assert body["error"]["details"]["campo"] == "confirmar_fora_disponibilidade"
        # Não inseriu: a trava barra antes do INSERT.
        assert not any("INSERT INTO barravips.bloqueios" in q for q, _ in fake.execucoes)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_bloqueio_fora_disponibilidade_com_confirmar_retorna_201() -> None:
    fake = FakeConnFora()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        body = _body()
        body["confirmar_fora_disponibilidade"] = True
        with TestClient(app) as client:
            response = client.post("/v1/agenda/bloqueios", json=body, headers=_token())
        assert response.status_code == 201
        # Override: pula a trava e insere.
        assert any("INSERT INTO barravips.bloqueios" in q for q, _ in fake.execucoes)
    finally:
        app.dependency_overrides.pop(get_conn, None)
