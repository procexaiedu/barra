"""Camada Modelos do Mapa de clientes (MAPA-15, ADR 0010).

Cobre o endpoint `GET /v1/modelos/mapa`:
- modelo com geo vira pin;
- modelo sem geo entra em `total_sem_localizacao_operacional`;
- payload **NÃO** expõe PII da ficha cadastral (ADR 0007).
"""

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


def _override(conn: object) -> None:
    async def _gen():
        yield conn

    app.dependency_overrides[get_conn] = _gen


def _modelo_com_geo(modelo_id: UUID) -> dict[str, Any]:
    return {
        "id": modelo_id,
        "nome": "Aurora",
        "latitude": Decimal("-22.9711"),
        "longitude": Decimal("-43.1822"),
        "status": "ativa",
        "tipo_fisico": "ruiva",
        "tipo_atendimento_aceito": ["interno", "externo"],
    }


def _modelo_sem_geo(modelo_id: UUID) -> dict[str, Any]:
    return {
        "id": modelo_id,
        "nome": "Bianca",
        "latitude": None,
        "longitude": None,
        "status": "pausada",
        "tipo_fisico": None,
        "tipo_atendimento_aceito": ["interno"],
    }


class FakeConnMapa:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.modelos" in query:
            return _Result(self.rows)
        return _Result([])


def test_mapa_modelos_separa_com_e_sem_geo() -> None:
    modelo_com = uuid4()
    modelo_sem = uuid4()
    fake = FakeConnMapa([_modelo_com_geo(modelo_com), _modelo_sem_geo(modelo_sem)])
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/modelos/mapa", headers=_token())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_sem_localizacao_operacional"] == 1
        assert len(body["pontos"]) == 1
        ponto = body["pontos"][0]
        assert ponto["id"] == str(modelo_com)
        assert ponto["nome"] == "Aurora"
        assert ponto["latitude"] == -22.9711
        assert ponto["longitude"] == -43.1822
        assert ponto["status"] == "ativa"
        assert ponto["tipo_fisico"] == "ruiva"
        assert ponto["tipo_atendimento_aceito"] == ["interno", "externo"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_modelos_payload_nao_expoe_pii() -> None:
    """ADR 0007: rg/cpf/endereço residencial/percentual de repasse/telefone
    são PII e NUNCA podem vazar no payload do Mapa (painel ou não)."""
    modelo_id = uuid4()
    fake = FakeConnMapa([_modelo_com_geo(modelo_id)])
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/modelos/mapa", headers=_token())
        assert response.status_code == 200, response.text
        body = response.json()
        ponto = body["pontos"][0]
        for chave_pii in (
            "rg",
            "cpf",
            "endereco_residencial",
            "endereco_residencial_formatado",
            "place_id_residencial",
            "percentual_repasse",
            "telefone",
            "numero_whatsapp",
            "chave_pix",
            "titular_chave",
        ):
            assert chave_pii not in ponto, f"PII '{chave_pii}' vazou no payload do mapa"
            assert chave_pii not in body, f"PII '{chave_pii}' vazou no envelope do mapa"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_modelos_select_nao_le_colunas_pii() -> None:
    """Defesa em profundidade: além de o payload não expor PII, a própria query
    NÃO seleciona as colunas sensíveis — evita até a leitura do banco."""
    fake = FakeConnMapa([])
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/modelos/mapa", headers=_token())
        assert response.status_code == 200, response.text
        select_query = next(
            q for q, _ in fake.executes if "FROM barravips.modelos" in q
        )
        for coluna_pii in (
            "rg",
            "cpf",
            "endereco_residencial",
            "place_id_residencial",
            "percentual_repasse",
            "chave_pix",
            "titular_chave",
            "numero_whatsapp",
        ):
            assert coluna_pii not in select_query, (
                f"SELECT do /modelos/mapa lê coluna PII '{coluna_pii}'"
            )
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_modelos_vazio_retorna_estrutura_minima() -> None:
    fake = FakeConnMapa([])
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/modelos/mapa", headers=_token())
        assert response.status_code == 200, response.text
        assert response.json() == {"pontos": [], "total_sem_localizacao_operacional": 0}
    finally:
        app.dependency_overrides.pop(get_conn, None)
