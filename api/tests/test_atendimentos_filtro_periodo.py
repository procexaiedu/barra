"""Integração de GET /v1/atendimentos — filtro de período por created_at."""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
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


def _linha(numero: int, created_at: datetime) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "numero_curto": numero,
        "estado": "Novo",
        "tipo_atendimento": "interno",
        "urgencia": "normal",
        "ia_pausada": False,
        "ia_pausada_motivo": None,
        "responsavel_atual": "ia",
        "motivo_escalada": None,
        "proxima_acao_esperada": None,
        "sinais_qualificacao": None,
        "valor_acordado": None,
        "valor_final": None,
        "updated_at": created_at,
        "cliente_id": uuid4(),
        "cliente_nome": f"Cliente {numero}",
        "cliente_telefone": "5521999998888",
        "modelo_id": uuid4(),
        "modelo_nome": "Modelo X",
        "programa_principal_nome": None,
    }


class FakeConnAtendimentos:
    """Captura a query SELECT principal e filtra rows in-memory pelo created_at."""

    def __init__(self, rows: list[tuple[dict[str, Any], date]]) -> None:
        # rows: lista de (linha-resultado, data-considerada-para-filtro)
        self._rows = rows
        self.last_query: str | None = None
        self.last_params: list[Any] | None = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.atendimentos a" in query and "JOIN barravips.clientes" in query:
            self.last_query = query
            self.last_params = list(params) if params is not None else []
            # Extrai os parâmetros date na ordem em que aparecem; cruza com a presença
            # dos predicados >= / <= no SQL para descobrir qual é inicio e qual é fim.
            datas = [
                p
                for p in self.last_params
                if isinstance(p, date) and not isinstance(p, datetime)
            ]
            tem_inicio = "::date >= %s" in query
            tem_fim = "::date <= %s" in query
            data_inicio: date | None = None
            data_fim: date | None = None
            if tem_inicio and tem_fim and len(datas) >= 2:
                data_inicio, data_fim = datas[0], datas[1]
            elif tem_inicio and datas:
                data_inicio = datas[0]
            elif tem_fim and datas:
                data_fim = datas[0]
            filtradas = [
                linha
                for (linha, dt) in self._rows
                if (data_inicio is None or dt >= data_inicio)
                and (data_fim is None or dt <= data_fim)
            ]
            return _Result(filtradas)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _dataset_dias_distintos() -> list[tuple[dict[str, Any], date]]:
    # Três atendimentos em três dias distintos (BRT)
    dt1 = datetime(2026, 5, 10, 14, 0, tzinfo=UTC)  # 2026-05-10 BRT
    dt2 = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
    dt3 = datetime(2026, 5, 12, 14, 0, tzinfo=UTC)
    return [
        (_linha(1, dt1), date(2026, 5, 10)),
        (_linha(2, dt2), date(2026, 5, 11)),
        (_linha(3, dt3), date(2026, 5, 12)),
    ]


def _override_factory(fake: FakeConnAtendimentos):
    async def _override():
        yield fake

    return _override


def test_lista_sem_periodo_retorna_todos() -> None:
    fake = FakeConnAtendimentos(_dataset_dias_distintos())
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/atendimentos", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 3
        # query principal não deve conter o predicado de período
        assert fake.last_query is not None
        assert "AT TIME ZONE 'America/Sao_Paulo'" not in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_com_data_inicio_filtra_corretamente() -> None:
    fake = FakeConnAtendimentos(_dataset_dias_distintos())
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos",
                params={"data_inicio": "2026-05-11"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        # Apenas atendimentos dos dias 11 e 12
        numeros = sorted(item["numero_curto"] for item in body["items"])
        assert numeros == [2, 3]
        assert fake.last_query is not None
        assert (
            "(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s"
            in fake.last_query
        )
        assert date(2026, 5, 11) in (fake.last_params or [])
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_com_data_fim_filtra_corretamente() -> None:
    fake = FakeConnAtendimentos(_dataset_dias_distintos())
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos",
                params={"data_fim": "2026-05-11"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        # Apenas atendimentos dos dias 10 e 11
        numeros = sorted(item["numero_curto"] for item in body["items"])
        assert numeros == [1, 2]
        assert fake.last_query is not None
        assert (
            "(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s"
            in fake.last_query
        )
        assert date(2026, 5, 11) in (fake.last_params or [])
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_com_intervalo_dia_unico() -> None:
    fake = FakeConnAtendimentos(_dataset_dias_distintos())
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos",
                params={"data_inicio": "2026-05-11", "data_fim": "2026-05-11"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        numeros = [item["numero_curto"] for item in body["items"]]
        assert numeros == [2]
        assert fake.last_query is not None
        assert (
            "(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s"
            in fake.last_query
        )
        assert (
            "(a.created_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s"
            in fake.last_query
        )
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_lista_data_inicio_maior_que_data_fim_retorna_vazio() -> None:
    fake = FakeConnAtendimentos(_dataset_dias_distintos())
    app.dependency_overrides[get_conn] = _override_factory(fake)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/atendimentos",
                params={"data_inicio": "2026-05-12", "data_fim": "2026-05-10"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["next_cursor"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)
