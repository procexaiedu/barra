"""GET /v1/crm/clientes/mapa — propagação do perfil físico DECLARADO (MAPA-10, ADR 0006).

Garante que o payload expõe `perfis` (lista declarada) por ponto e que o filtro
`?perfis=...` aplica overlap (semântica OR do ADR 0006) — sem nunca tocar no breakdown
calculado (cross-modelo, fica fora do P0 e fora da IA por modelo).

Padrão FakeConn (sem banco), igual aos outros testes do contexto.
"""

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
    """Devolve as linhas pre-montadas para qualquer SELECT do endpoint mapa_clientes,
    capturando os params para a inspeção do filtro OR."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executes: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        return _Result(self.rows)


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def _ponto(
    *,
    cliente_id: UUID,
    nome: str,
    perfis: list[str] | str,
    lat: float | None = -23.55,
    lng: float | None = -46.63,
) -> dict[str, Any]:
    return {
        "id": cliente_id,
        "nome": nome,
        "perfis_preferidos": perfis,
        "latitude": lat,
        "longitude": lng,
        "bairro": "Centro",
        "endereco_formatado": "Rua X, 1",
        "total_atendimentos": 2,
        "valor_total": 500,
    }


def test_mapa_propaga_perfis_declarados_por_ponto() -> None:
    """0/1/3 perfis declarados — todos chegam no payload como `perfis: list[str]`."""
    rows = [
        _ponto(cliente_id=uuid4(), nome="Sem", perfis=[]),
        _ponto(cliente_id=uuid4(), nome="Um", perfis=["loira"]),
        _ponto(cliente_id=uuid4(), nome="Tres", perfis=["ruiva", "morena", "asiatica"]),
    ]
    conn = FakeConnMapa(rows)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert resp.status_code == 200, resp.text
        pontos = resp.json()["pontos"]
        assert len(pontos) == 3
        por_nome = {p["nome"]: p for p in pontos}
        assert por_nome["Sem"]["perfis"] == []
        assert por_nome["Um"]["perfis"] == ["loira"]
        assert por_nome["Tres"]["perfis"] == ["ruiva", "morena", "asiatica"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_aceita_perfis_em_formato_literal_de_array() -> None:
    """psycopg pode devolver enum[] como literal '{a,b}'; _array_text cobre isso."""
    rows = [_ponto(cliente_id=uuid4(), nome="Literal", perfis="{loira,morena}")]
    conn = FakeConnMapa(rows)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert resp.status_code == 200, resp.text
        pontos = resp.json()["pontos"]
        assert pontos[0]["perfis"] == ["loira", "morena"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_filtro_perfis_aplica_overlap_OR() -> None:
    """`?perfis=loira&perfis=ruiva` injeta WHERE com overlap (`&&`) e passa a lista
    como param — semântica OR do ADR 0006."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/v1/crm/clientes/mapa?perfis=loira&perfis=ruiva",
                headers=_token(),
            )
        assert resp.status_code == 200, resp.text
        assert len(conn.executes) == 1
        query, params = conn.executes[0]
        assert "c.perfis_preferidos && %s::barravips.perfil_fisico_enum[]" in query
        # O primeiro params é a lista de perfis selecionados, na ordem da querystring.
        assert params[0] == ["loira", "ruiva"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_sem_filtro_perfis_nao_emite_clausula_overlap() -> None:
    """Sem ?perfis a query não deve incluir o predicado de overlap."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert resp.status_code == 200, resp.text
        query, _ = conn.executes[0]
        assert "perfis_preferidos &&" not in query
    finally:
        app.dependency_overrides.pop(get_conn, None)
