"""Integração da rota /v1/crm/clientes/mapa — cor por desfecho (MAPA-3) +
última data / recorrência (MAPA-5) + filtro desfecho/motivo (MAPA-8), ADR 0008."""

from contextlib import asynccontextmanager
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


class FakeConnMapa:
    """Mock do `mapa_clientes`: responde a query do endpoint com as linhas configuradas.
    Guarda a última query/params para inspeção dos filtros aplicados (MAPA-8)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_query: str | None = None
        self.last_params: object = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.clientes" in query and "LATERAL" in query and "geo.estado" in query:
            self.last_query = query
            self.last_params = params
            return _Result(self.rows)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _ponto(
    estado: str,
    cliente_id: UUID | None = None,
    ultima_data: str = "2026-05-20T10:00:00",
    total_fechados: int = 0,
    motivo_perda: str | None = None,
) -> dict[str, Any]:
    return {
        "id": cliente_id or uuid4(),
        "nome": f"Cliente {estado}",
        "perfis_preferidos": [],
        "latitude": -22.97,
        "longitude": -43.18,
        "bairro": "Copacabana",
        "endereco_formatado": "Av. Atlântica, 1000",
        "estado": estado,
        "motivo_perda": motivo_perda,
        "ultima_data": ultima_data,
        "total_atendimentos": 1,
        "total_fechados": total_fechados,
        "valor_total": 0,
    }


def test_mapa_clientes_propaga_estado_fechado() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Fechado"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_perdido() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Perdido")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Perdido"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_em_andamento() -> None:
    # "em andamento" não é um valor único do enum: qualquer estado não-terminal
    # cabe (Triagem/Qualificado/Aguardando_confirmacao/Confirmado/Em_execucao).
    # MAPA-3 colore esses três grupos como verde/vermelho/âmbar — basta garantir
    # que o estado bruto chega ao payload para o frontend mapear a cor.
    async def _override():
        yield FakeConnMapa([_ponto("Em_execucao")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Em_execucao"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_ultima_data() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", ultima_data="2026-04-15T08:30:00")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["ultima_data"] == "2026-04-15T08:30:00"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_recorrente_com_dois_ou_mais_fechados() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", total_fechados=3)])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["recorrente"] is True
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_nao_recorrente_com_um_fechado() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", total_fechados=1)])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["recorrente"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-8: filtro por desfecho + motivo de perda
# O FakeConn devolve as linhas configuradas sem aplicar o filtro do SQL — os
# testes verificam (a) que o filtro foi inserido no WHERE corretamente e (b)
# que `motivo_perda` chega ao payload.


def test_mapa_clientes_filtra_por_desfecho_perdido() -> None:
    fake = FakeConnMapa([_ponto("Perdido", motivo_perda="fora_de_area")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=Perdido", headers=_token()
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado = 'Perdido'" in fake.last_query
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Perdido"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_filtra_por_motivo_perda_or() -> None:
    fake = FakeConnMapa(
        [
            _ponto("Perdido", motivo_perda="fora_de_area"),
            _ponto("Perdido", motivo_perda="indisponibilidade"),
        ]
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=Perdido"
                "&motivo_perda=fora_de_area&motivo_perda=indisponibilidade",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert (
            "geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])"
            in fake.last_query
        )
        # OR é representado pelo array passado como parâmetro do ANY.
        assert isinstance(fake.last_params, list)
        assert ["fora_de_area", "indisponibilidade"] in fake.last_params
        pontos = response.json()["pontos"]
        motivos = {p["motivo_perda"] for p in pontos}
        assert motivos == {"fora_de_area", "indisponibilidade"}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_motivo_perda_no_payload() -> None:
    async def _override():
        yield FakeConnMapa(
            [
                _ponto("Fechado", motivo_perda=None),
                _ponto("Perdido", motivo_perda="preco"),
            ]
        )

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 2
        # Ordem preservada do mock: Fechado primeiro, Perdido depois.
        assert pontos[0]["motivo_perda"] is None
        assert pontos[1]["motivo_perda"] == "preco"
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-9: lente "Demanda não atendida"
# A lente é UI-only (no frontend, sobrescreve desfecho/motivo no fetch). No
# backend ela vira a mesma querystring do MAPA-8 — este teste deixa explícito o
# vínculo de aceite da lente ao endpoint: a querystring acordada retorna apenas
# Perdidos com motivos `indisponibilidade` ou `fora_de_area`.


def test_mapa_clientes_lente_demanda_nao_atendida() -> None:
    """Cenário da lente MAPA-9: 5 rows variados; o FakeConn devolve só as 2 que
    o WHERE da MAPA-8 deixaria passar (Perdido + indisp/fora_de_area). Verifica
    que a querystring da lente bate no SQL e que motivos não-oportunidade não
    vazam para o payload."""
    fake = FakeConnMapa(
        [
            _ponto("Perdido", motivo_perda="indisponibilidade"),
            _ponto("Perdido", motivo_perda="fora_de_area"),
        ]
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?desfecho=Perdido"
                "&motivo_perda=indisponibilidade"
                "&motivo_perda=fora_de_area",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado = 'Perdido'" in fake.last_query
        assert (
            "geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])"
            in fake.last_query
        )
        # OR via ANY: o array passa exatamente os 2 motivos da lente, na ordem da UI.
        assert isinstance(fake.last_params, list)
        assert ["indisponibilidade", "fora_de_area"] in fake.last_params
        pontos = response.json()["pontos"]
        assert len(pontos) == 2
        motivos = {p["motivo_perda"] for p in pontos}
        assert motivos == {"indisponibilidade", "fora_de_area"}
        # Nenhum Fechado/em andamento/Perdido por outro motivo no payload.
        assert all(p["estado"] == "Perdido" for p in pontos)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_desfecho_andamento_exclui_perdido_e_fechado() -> None:
    fake = FakeConnMapa([_ponto("Em_execucao")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=andamento", headers=_token()
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado NOT IN ('Fechado', 'Perdido')" in fake.last_query
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Em_execucao"
    finally:
        app.dependency_overrides.pop(get_conn, None)
