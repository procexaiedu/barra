"""Integração da rota /v1/crm/clientes/mapa — perfil físico declarado (MAPA-10, ADR 0006).

A parte CALCULADA (breakdown cross-modelo do ADR 0006) nunca entra no payload do mapa —
exporia agregação cross-modelo numa rota que, mesmo painel-only, alimenta o frontend. Só
a parte DECLARADA (`clientes.perfis_preferidos`) vai. Filtro `perfis` usa overlap (OR).
"""

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
    """Mock que devolve as linhas configuradas e captura a última query/params."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_query: str | None = None
        self.last_params: object = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.last_query = query
        self.last_params = params
        if "FROM barravips.clientes" in query and "LATERAL" in query and "geo.estado" in query:
            return _Result(self.rows)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _ponto(perfis: list[str], cliente_id: UUID | None = None) -> dict[str, Any]:
    # Fixture inclui todas as chaves que `mapa_clientes` lê do row — `ultima_data` e
    # `total_fechados` vêm do MAPA-5; `motivo_perda` do MAPA-8. Sem elas, o endpoint
    # estoura KeyError antes de chegar aos asserts deste arquivo.
    return {
        "id": cliente_id or uuid4(),
        "nome": "Cliente",
        "perfis_preferidos": perfis,
        "latitude": -22.97,
        "longitude": -43.18,
        "bairro": "Copacabana",
        "endereco_formatado": "Av. Atlântica, 1000",
        "estado": "Fechado",
        "motivo_perda": None,
        "ultima_data": "2026-05-20T10:00:00",
        "total_atendimentos": 1,
        "total_fechados": 0,
        "valor_total": 0,
    }


def _get_pontos(
    rows: list[dict[str, Any]], query: str = ""
) -> tuple[list[dict[str, Any]], FakeConnMapa]:
    fake = FakeConnMapa(rows)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/clientes/mapa{query}", headers=_token())
        assert response.status_code == 200
        return response.json()["pontos"], fake
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_perfis_vazio() -> None:
    pontos, _ = _get_pontos([_ponto([])])
    assert len(pontos) == 1
    assert pontos[0]["perfis"] == []


def test_mapa_clientes_perfis_um() -> None:
    pontos, _ = _get_pontos([_ponto(["loira"])])
    assert len(pontos) == 1
    assert pontos[0]["perfis"] == ["loira"]


def test_mapa_clientes_perfis_tres() -> None:
    # Cliente declarou 3 perfis. A ordem do array é a do banco — preservada porque o
    # frontend usa o primeiro como cor (decisão do PR MAPA-10).
    pontos, _ = _get_pontos([_ponto(["loira", "morena", "ruiva"])])
    assert len(pontos) == 1
    assert pontos[0]["perfis"] == ["loira", "morena", "ruiva"]


def test_mapa_clientes_perfis_aceita_literal_array_do_postgres() -> None:
    # psycopg pode entregar enum[] como literal '{a,b}' dependendo da config; o helper
    # `_array_text` em routes.py cobre ambos. Garante que o endpoint sobrevive ao caso.
    pontos, _ = _get_pontos([_ponto("{loira,morena}")])  # type: ignore[arg-type]
    assert pontos[0]["perfis"] == ["loira", "morena"]


def test_mapa_clientes_filtro_perfis_or_repassa_lista_ao_sql() -> None:
    # Filtro `perfis` (overlap, ADR 0006): query string `?perfis=loira&perfis=negra`
    # tem que virar lista no params do SQL (operador `&&` aplica OR via overlap).
    pontos, fake = _get_pontos([_ponto(["loira"])], query="?perfis=loira&perfis=negra")
    assert len(pontos) == 1
    assert "perfis_preferidos && %s" in (fake.last_query or "")
    assert isinstance(fake.last_params, list)
    assert ["loira", "negra"] in fake.last_params
