"""Vendedor (ADR 0012) — rotas /v1/vendedores com FakeConn (sem DB).

Cobre criação, validação do nível, filtro ativo/inativo, desativação por PATCH
(soft-delete) e 404. Espelha o padrão de `test_tarefas.py`.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(
        self, rows: list[dict[str, Any]] | None = None, rowcount: int | None = None
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount if rowcount is not None else len(self.rows)

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def _vendedor_row(
    vid: UUID, *, nome: str = "João", nivel: str = "iniciante", ativo: bool = True
) -> dict[str, Any]:
    return {
        "id": vid,
        "nome": nome,
        "nivel": nivel,
        "ativo": ativo,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


class FakeConn:
    def __init__(self, vid: UUID | None = None, *, update_rowcount: int = 1) -> None:
        self.vid = vid or uuid4()
        self.update_rowcount = update_rowcount
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.vendedores" in query:
            return _Result([{"id": self.vid}])
        if "UPDATE barravips.vendedores SET" in query:
            return _Result(rowcount=self.update_rowcount)
        if "FROM barravips.vendedores v" in query:
            return _Result([_vendedor_row(self.vid)])
        return _Result([])


def test_criar_vendedor_retorna_201() -> None:
    vid = uuid4()
    conn = FakeConn(vid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/vendedores",
                json={"nome": "João", "nivel": "avancado"},
                headers=_token(),
            )
        assert r.status_code == 201
        assert r.json()["id"] == str(vid)
        insert = next(q for q, _ in conn.executes if "INSERT INTO barravips.vendedores" in q)
        assert "nivel" in insert and "created_by" in insert
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_nivel_invalido_retorna_422() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/vendedores", json={"nome": "X", "nivel": "mestre"}, headers=_token()
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_so_ativos_por_default() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/vendedores", headers=_token())
        assert r.status_code == 200
        select = next(q for q, _ in conn.executes if "FROM barravips.vendedores v" in q)
        assert "WHERE v.ativo" in select
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_incluir_inativos_remove_filtro() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/vendedores?incluir_inativos=true", headers=_token())
        assert r.status_code == 200
        select = next(q for q, _ in conn.executes if "FROM barravips.vendedores v" in q)
        assert "WHERE v.ativo" not in select
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_desativar_via_patch_ativo_false() -> None:
    vid = uuid4()
    conn = FakeConn(vid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(f"/v1/vendedores/{vid}", json={"ativo": False}, headers=_token())
        assert r.status_code == 200
        update = next(q for q, _ in conn.executes if "UPDATE barravips.vendedores SET" in q)
        assert "ativo = %s" in update
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_inexistente_retorna_404() -> None:
    conn = FakeConn(update_rowcount=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(f"/v1/vendedores/{uuid4()}", json={"nome": "Z"}, headers=_token())
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)
