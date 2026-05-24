"""Regressão: POST /v1/modelos/{id}/pausar não pode dar 500 'Erro inesperado'.

Causa raiz: `_evento_modelo` passava um dict Python cru como parâmetro de uma
coluna jsonb. psycopg não adapta dict e levanta ProgrammingError, derrubando a
transação inteira -> 500 -> toast "Erro inesperado" no painel.

O FakeConn abaixo valida a adaptabilidade de cada parâmetro (como o banco real
faria), então um dict cru reproduz o 500 no seam da rota — sem isso o fake
mascararia o bug e o teste daria falso positivo.
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from psycopg.adapt import Transformer

from barra.api.deps import get_conn
from barra.core.evolution import EvolutionClient
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _assert_adaptavel(params: object) -> None:
    """Reproduz a borda do psycopg: um parâmetro %s sem dumper (dict cru) levanta
    ProgrammingError. É o que diferencia este fake de um que só guarda params."""
    if params is None:
        return
    tx = Transformer()
    for p in params:  # type: ignore[union-attr]
        tx.as_literal(p)


class FakeConnPausar:
    def __init__(self, *, status: str, com_coordenacao: bool) -> None:
        self.status = status
        self.com_coordenacao = com_coordenacao
        self.modelo_id = uuid4()
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        _assert_adaptavel(params)
        self.executes.append((query, params))
        if "FROM barravips.modelos" in query and "WHERE id" in query:
            return _Result(
                [
                    {
                        "id": self.modelo_id,
                        "nome": "Lara",
                        "status": self.status,
                        "evolution_instance_id": "inst-1",
                        "coordenacao_chat_id": "55219@g.us" if self.com_coordenacao else None,
                    }
                ]
            )
        if "count(*)" in query:
            return _Result([{"count": 0}])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def test_pausar_sem_evolution_retorna_200() -> None:
    """(a) Caso reportado: modelo ativa sem grupo de coordenação. O INSERT de
    evento precisa serializar o payload jsonb — antes dava 500."""
    fake = FakeConnPausar(status="ativa", com_coordenacao=False)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            r = client.post(f"/v1/modelos/{fake.modelo_id}/pausar", headers=_token())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pausada"
        assert body["card_enviado"] is False
        assert any("INSERT INTO barravips.eventos" in q for q, _ in fake.executes)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_modelo_nao_ativa_retorna_409() -> None:
    """(b) Modelo já pausada -> 409 com mensagem clara, nunca 'Erro inesperado'."""
    fake = FakeConnPausar(status="pausada", com_coordenacao=False)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            r = client.post(f"/v1/modelos/{fake.modelo_id}/pausar", headers=_token())
        assert r.status_code == 409
        assert r.json()["error"]["message"] == "Modelo nao esta ativa."
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_com_evolution_falhando_ainda_pausa(monkeypatch) -> None:
    """(c) Card é best-effort: Evolution fora do ar não pode travar a pausa
    (CONTEXT.md). card_enviado=False, mas a operação conclui em 200."""
    fake = FakeConnPausar(status="ativa", com_coordenacao=True)
    monkeypatch.setattr(app.state.settings, "evolution_base_url", "http://evo.local")

    async def _boom(self, **kwargs):
        raise httpx.ConnectError("evolution fora do ar")

    monkeypatch.setattr(EvolutionClient, "enviar_texto", _boom)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            r = client.post(f"/v1/modelos/{fake.modelo_id}/pausar", headers=_token())
        assert r.status_code == 200, r.text
        assert r.json()["card_enviado"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)
