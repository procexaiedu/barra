"""POST /v1/atendimentos/{id}/pausar — handoff manual por operador (ADR-0032).

Mesmo padrao de FakeConn dos demais testes de rota do painel (test_atendimentos.py,
test_atendimentos_excluir.py): sem DB real, so verifica a fiacao do endpoint (auth,
payload, mapeamento de erro). A logica de `aplicar_comando`/`abrir_handoff` (idempotencia,
motivo/tipo de escalada, guard de estado finalizado) e coberta contra banco real em
tests/integracao/test_pausar_ia.py.
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


class FakeConn:
    """Simula o ciclo de `aplicar_comando`: busca (FOR UPDATE) -> INSERT escaladas -> UPDATE
    atendimentos -> INSERT eventos."""

    def __init__(self, *, atendimento: dict[str, Any] | None) -> None:
        self.atendimento = atendimento
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FOR UPDATE OF a" in query:
            return _Result([self.atendimento] if self.atendimento else [])
        if "INSERT INTO barravips.escaladas" in query:
            return _Result([], rowcount=1)  # escalada aberta (nao havia uma ja aberta)
        return _Result([])


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def _atendimento(*, estado: str = "Qualificado", ia_pausada: bool = False) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "estado": estado,
        "ia_pausada": ia_pausada,
        "pix_status": "nao_solicitado",
        "percentual_repasse": None,
    }


def test_pausar_atendimento_retorna_ia_pausada_true() -> None:
    atendimento = _atendimento()
    conn = FakeConn(atendimento=atendimento)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/atendimentos/{atendimento['id']}/pausar",
                json={"observacao": "resposta ruim, assumindo"},
                headers=_token(),
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == str(atendimento["id"])
        assert body["estado"] == "Qualificado"
        assert body["ia_pausada"] is True
        assert any("INSERT INTO barravips.escaladas" in q for q in conn.queries)
        assert any(
            q.strip().startswith("UPDATE barravips.atendimentos") and "ia_pausada = true" in q
            for q in conn.queries
        )
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_atendimento_inexistente_retorna_404() -> None:
    conn = FakeConn(atendimento=None)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/atendimentos/{uuid4()}/pausar",
                json={},
                headers=_token(),
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_atendimento_finalizado_retorna_409() -> None:
    atendimento = _atendimento(estado="Fechado")
    conn = FakeConn(atendimento=atendimento)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/atendimentos/{atendimento['id']}/pausar",
                json={},
                headers=_token(),
            )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(get_conn, None)
