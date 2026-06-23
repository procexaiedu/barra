"""Módulo de Tarefas (ADR 0017) — rotas /v1/tarefas com FakeConn.

Cobre criação, validação do responsável polimórfico, filtro de prazo em BRT,
sincronização de concluida_em, 404 e o universo do seletor (usuarios + modelos +
vendedores, ADR 0012).
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


def _tarefa_row(
    tarefa_id: UUID, *, status: str = "a_fazer", atribuido: bool = True
) -> dict[str, Any]:
    return {
        "id": tarefa_id,
        "titulo": "Carregar telefones",
        "descricao": None,
        "status": status,
        "prioridade": "media",
        "prazo": None,
        "criado_por_tipo": "usuario",
        "criado_por_id": uuid4(),
        "atribuido_tipo": "modelo" if atribuido else None,
        "atribuido_id": uuid4() if atribuido else None,
        "concluida_em": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "criado_por_nome": "Fernando",
        "atribuido_nome": "Aline" if atribuido else None,
    }


class FakeConn:
    """Fake conn configurável: registra os executes e responde por substring."""

    def __init__(
        self, tarefa_id: UUID | None = None, *, update_rowcount: int = 1, delete_rowcount: int = 1
    ) -> None:
        self.tarefa_id = tarefa_id or uuid4()
        self.update_rowcount = update_rowcount
        self.delete_rowcount = delete_rowcount
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.tarefas" in query:
            return _Result([{"id": self.tarefa_id}])
        if "UPDATE barravips.tarefas SET" in query:
            return _Result(rowcount=self.update_rowcount)
        if "DELETE FROM barravips.tarefas" in query:
            return _Result(rowcount=self.delete_rowcount)
        if "FROM barravips.tarefas t" in query:  # _SELECT_BASE (obter/listar)
            return _Result([_tarefa_row(self.tarefa_id)])
        if "barravips.usuarios" in query and "UNION ALL" in query:  # listar_responsaveis
            return _Result(
                [
                    {"tipo": "usuario", "id": uuid4(), "nome": "Fernando"},
                    {"tipo": "modelo", "id": uuid4(), "nome": "Aline"},
                    {"tipo": "vendedor", "id": uuid4(), "nome": "João"},
                ]
            )
        return _Result([])


def test_criar_tarefa_retorna_201() -> None:
    tid = uuid4()
    conn = FakeConn(tid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post("/v1/tarefas", json={"titulo": "Carregar telefones"}, headers=_token())
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == str(tid)
        assert body["criado_por"]["tipo"] == "usuario"
        insert = next(q for q, _ in conn.executes if "INSERT INTO barravips.tarefas" in q)
        assert "criado_por_tipo" in insert
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_tarefa_atribuido_inconsistente_retorna_422() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/tarefas",
                json={"titulo": "x", "atribuido_tipo": "modelo"},  # sem atribuido_id
                headers=_token(),
            )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ATRIBUIDO_INCONSISTENTE"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_prazo_hoje_filtra_por_brt() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/tarefas?prazo=hoje", headers=_token())
        assert r.status_code == 200
        select = next(q for q, _ in conn.executes if "FROM barravips.tarefas t" in q)
        assert "America/Sao_Paulo" in select
        assert "t.prazo =" in select
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_status_feita_seta_concluida_em() -> None:
    tid = uuid4()
    conn = FakeConn(tid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(f"/v1/tarefas/{tid}", json={"status": "feita"}, headers=_token())
        assert r.status_code == 200
        update = next(q for q, _ in conn.executes if "UPDATE barravips.tarefas SET" in q)
        assert "concluida_em = now()" in update
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_reabrir_zera_concluida_em() -> None:
    tid = uuid4()
    conn = FakeConn(tid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(f"/v1/tarefas/{tid}", json={"status": "a_fazer"}, headers=_token())
        assert r.status_code == 200
        update = next(q for q, _ in conn.executes if "UPDATE barravips.tarefas SET" in q)
        assert "concluida_em = NULL" in update
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_excluir_inexistente_retorna_404() -> None:
    conn = FakeConn(delete_rowcount=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.delete(f"/v1/tarefas/{uuid4()}", headers=_token())
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_responsaveis_inclui_vendedores() -> None:
    # ADR 0012: a tabela vendedores existe → o seletor oferta usuario + modelo + vendedor.
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/tarefas/responsaveis", headers=_token())
        assert r.status_code == 200
        tipos = {item["tipo"] for item in r.json()["items"]}
        assert tipos == {"usuario", "modelo", "vendedor"}
        query = next(q for q, _ in conn.executes if "UNION ALL" in q)
        assert "barravips.vendedores" in query
    finally:
        app.dependency_overrides.pop(get_conn, None)
