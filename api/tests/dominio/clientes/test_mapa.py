"""MAPA-11: filtros de faixa de R$ e recência no `GET /v1/crm/clientes/mapa`.

Convenção do diretório: FakeConn captura `execute()` para inspecionar a SQL emitida
(mesmo padrão de `tests/test_atendimentos_geo.py` e `tests/test_clientes_integration.py`).
Sem banco real — exercita o WHERE/HAVING do endpoint, que é onde os novos filtros vivem.
"""

from datetime import UTC, datetime, timedelta
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
    """Captura a query do `/clientes/mapa` e devolve uma lista fixa de candidatos.

    A SQL real é executada pelo Postgres em produção — aqui o teste verifica que o
    fragmento certo foi adicionado ao WHERE e que os params foram passados na ordem.
    `rows` simula o resultado pós-filtro (já reduzido), para o response refletir o
    que o cliente veria.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.captured_query: str | None = None
        self.captured_params: list[Any] | None = None

    async def execute(self, query: str, params: object = None) -> _Result:
        if "FROM barravips.clientes c" in query and "geo.latitude" in query:
            self.captured_query = query
            self.captured_params = list(params) if isinstance(params, list) else None
            return _Result(self.rows)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def _ponto(
    *,
    valor_total: float,
    data: datetime | None = None,
    cliente_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "id": cliente_id or uuid4(),
        "nome": "Cliente",
        "latitude": -22.97,
        "longitude": -43.18,
        "bairro": "Barra",
        "endereco_formatado": "Av. das Américas, 500",
        "data": data,
        "total_atendimentos": 1,
        "valor_total": valor_total,
    }


def test_mapa_valor_min_filtra_pontos_e_injeta_where() -> None:
    """`valor_min=500` adiciona WHERE em `ag.valor_total` e o response reflete o recorte."""
    # 2 clientes acima do piso, 1 sem geo — só os 2 viram pontos.
    rows = [
        _ponto(valor_total=1200),
        _ponto(valor_total=800),
    ]
    conn = FakeConnMapa(rows)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa?valor_min=500", headers=_token())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["pontos"]) == 2
        assert all(p["valor_total"] >= 500 for p in body["pontos"])
        # SQL: o filtro entrou no WHERE com o valor.
        assert conn.captured_query is not None
        assert "COALESCE(ag.valor_total, 0) >= %s" in conn.captured_query
        assert conn.captured_params == [500.0]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_valor_max_injeta_where() -> None:
    """`valor_max=1000` adiciona WHERE com teto sobre `ag.valor_total`."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa?valor_max=1000", headers=_token())
        assert resp.status_code == 200, resp.text
        assert conn.captured_query is not None
        assert "COALESCE(ag.valor_total, 0) <= %s" in conn.captured_query
        assert conn.captured_params == [1000.0]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_recencia_ativo_usa_data_do_geo_e_intervalo_padrao() -> None:
    """`recencia=ativo` (ativo_em_dias default 90) só devolve pontos com `data` ≤ 90d.

    O endpoint adiciona o filtro em SQL; aqui simulamos que o banco já filtrou e
    o response reflete só os ativos. A asserção forte é a SQL emitida.
    """
    agora = datetime.now(UTC)
    # Banco simula que já aplicou o filtro: só o ativo (10d) entra.
    rows = [_ponto(valor_total=500, data=agora - timedelta(days=10))]
    conn = FakeConnMapa(rows)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa?recencia=ativo", headers=_token())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["pontos"]) == 1
        assert conn.captured_query is not None
        # ativo_em_dias=90 é default — o INTERVAL aparece interpolado (int validado por Query).
        assert "geo.data >= NOW() - INTERVAL '90 days'" in conn.captured_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_recencia_dormente_usa_lado_oposto() -> None:
    """`recencia=dormente&ativo_em_dias=30` adiciona `geo.data < NOW() - INTERVAL '30 days'`."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/v1/crm/clientes/mapa?recencia=dormente&ativo_em_dias=30",
                headers=_token(),
            )
        assert resp.status_code == 200, resp.text
        assert conn.captured_query is not None
        assert "geo.data < NOW() - INTERVAL '30 days'" in conn.captured_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_recencia_todos_nao_injeta_filtro_de_data() -> None:
    """Default `recencia=todos` não adiciona filtro de `geo.data`."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert resp.status_code == 200, resp.text
        assert conn.captured_query is not None
        assert "geo.data" not in conn.captured_query.replace("AS data", "")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_recencia_invalida_retorna_422() -> None:
    """Valor fora de `ativo|dormente|todos` é rejeitado pelo Query pattern."""
    conn = FakeConnMapa([])
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            resp = client.get("/v1/crm/clientes/mapa?recencia=ontem", headers=_token())
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)
