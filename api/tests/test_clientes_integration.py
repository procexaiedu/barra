"""Integração da rota /v1/crm/clientes — listagem, detalhe, edição."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
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


class FakeConnComCliente:
    def __init__(self, cliente_id: UUID) -> None:
        self.cliente_id = cliente_id
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.clientes" in query and "WHERE id" in query and "UPDATE" not in query:
            return _Result(
                [
                    {
                        "id": self.cliente_id,
                        "nome": "Joao",
                        "telefone": "5521999998888",
                        "perfis_preferidos": [],
                        "primeiro_contato_modelo_id": uuid4(),
                        "arquivado_em": None,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }
                ]
            )
        if "FROM barravips.conversas cv" in query and "JOIN barravips.modelos" in query:
            return _Result([])
        if "ag.total_atendimentos" in query:
            return _Result(
                [
                    {
                        "id": self.cliente_id,
                        "nome": "Joao",
                        "telefone": "5521999998888",
                        "primeiro_contato_modelo_id": uuid4(),
                        "arquivado_em": None,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                        "total_atendimentos": 0,
                        "total_fechados": 0,
                        "valor_total": 0,
                        "ultima_atividade": None,
                        "modelos_distintas": 0,
                        "modelo_predominante_nome": None,
                    }
                ]
            )
        return _Result([])


class FakeConnVazio:
    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def test_listar_clientes_vazio_retorna_200() -> None:
    async def _override():
        yield FakeConnVazio()

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["next_cursor"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnPaginacao:
    """3 clientes com o MESMO updated_at (import em lote grava todos na mesma
    transação) — o cursor precisa desempatar por id ou a página 2 pula todos."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, object]] = []
        ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
        self.rows = [
            {
                "id": UUID(int=n),
                "nome": f"Cliente {n}",
                "telefone": f"55199999000{n}",
                "primeiro_contato_modelo_id": None,
                "arquivado_em": None,
                "created_at": ts,
                "updated_at": ts,
                "total_atendimentos": 0,
                "total_fechados": 0,
                "valor_total": 0,
                "ultima_atividade": None,
                "modelos_distintas": 0,
                "modelo_predominante_nome": None,
            }
            for n in (3, 2, 1)
        ]

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "ag.total_atendimentos" in query:
            return _Result(self.rows)
        return _Result([])


def test_listar_clientes_cursor_desempata_por_id_com_updated_at_igual() -> None:
    fake = FakeConnPaginacao()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes?limit=2", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        # cursor vem da última linha EXIBIDA (não da linha extra do limit+1)
        # e carrega o id para desempate
        assert body["next_cursor"] is not None
        _ts, sep, cid = body["next_cursor"].partition("|")
        assert sep == "|"
        assert cid == str(UUID(int=2))

        with TestClient(app) as client:
            response2 = client.get(
                f"/v1/crm/clientes?limit=2&cursor={body['next_cursor']}",
                headers=_token(),
            )
        assert response2.status_code == 200
        query, params = next(
            (q, p) for q, p in fake.executes if "ag.total_atendimentos" in q and p and len(p) > 2
        )
        assert "(c.updated_at, c.id) < (%s::timestamptz, %s::uuid)" in query
        assert str(UUID(int=2)) in [str(p) for p in params]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_obter_cliente_inexistente_retorna_404() -> None:
    async def _override():
        yield FakeConnVazio()

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/clientes/{uuid4()}", headers=_token())
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_obter_cliente_existente_mascara_telefone() -> None:
    cliente_id = uuid4()

    async def _override():
        yield FakeConnComCliente(cliente_id)

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/clientes/{cliente_id}", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["cliente"]["telefone_mascarado"].startswith("552")
        assert "*****" in body["cliente"]["telefone_mascarado"]
        assert body["conversas"] == []
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_editar_cliente_atualiza_nome() -> None:
    cliente_id = uuid4()
    fake = FakeConnComCliente(cliente_id)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/crm/clientes/{cliente_id}",
                json={"nome": "Joao da Silva"},
                headers=_token(),
            )
        assert response.status_code == 200
        update_executado = any(
            "UPDATE barravips.clientes" in q and "SET nome" in q for q, _ in fake.executes
        )
        assert update_executado
    finally:
        app.dependency_overrides.pop(get_conn, None)
