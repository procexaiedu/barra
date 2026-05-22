"""CRUD da rota /v1/crm/clientes — criar, editar, arquivar, desarquivar, listar."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

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


def _cliente_row(
    cliente_id: UUID,
    *,
    telefone: str = "5521999998888",
    arquivado_em: datetime | None = None,
    nome: str | None = "Joao",
) -> dict[str, Any]:
    return {
        "id": cliente_id,
        "nome": nome,
        "telefone": telefone,
        "primeiro_contato_modelo_id": None,
        "arquivado_em": arquivado_em,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "total_atendimentos": 0,
        "total_fechados": 0,
        "valor_total": 0,
        "ultima_atividade": None,
        "modelos_distintas": 0,
        "modelo_predominante_nome": None,
    }


class FakeConnCriar:
    """Fake conn que devolve um cliente recém-criado no INSERT."""

    def __init__(self, cliente_id: UUID, telefone: str) -> None:
        self.cliente_id = cliente_id
        self.telefone = telefone
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.clientes" in query:
            return _Result([_cliente_row(self.cliente_id, telefone=self.telefone)])
        return _Result([])


class FakeConnTelefoneDuplicado:
    """Fake conn que estoura UniqueViolation no INSERT/UPDATE de clientes."""

    def __init__(self, cliente_id: UUID | None = None) -> None:
        self.cliente_id = cliente_id

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        if self.cliente_id is not None and "SELECT id, telefone FROM barravips.clientes" in query:
            return _Result([{"id": self.cliente_id, "telefone": "5521900000000"}])
        if "INSERT INTO barravips.clientes" in query or "UPDATE barravips.clientes SET" in query:
            raise UniqueViolation("clientes_telefone_key")
        return _Result([])


class FakeConnArquivar:
    """Fake conn parametrizado pelo estado atual de arquivamento."""

    def __init__(self, cliente_id: UUID, arquivado_em: datetime | None) -> None:
        self.cliente_id = cliente_id
        self.arquivado_em = arquivado_em
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "SELECT id, arquivado_em FROM barravips.clientes" in query:
            return _Result([{"id": self.cliente_id, "arquivado_em": self.arquivado_em}])
        if "UPDATE barravips.clientes SET arquivado_em = NOW()" in query:
            self.arquivado_em = datetime.now(UTC)
            return _Result([{"id": self.cliente_id, "arquivado_em": self.arquivado_em}])
        if "UPDATE barravips.clientes SET arquivado_em = NULL" in query:
            self.arquivado_em = None
            return _Result([])
        return _Result([])


class FakeConnListar:
    """Fake conn que registra o SELECT de listagem executado para validar filtro."""

    def __init__(self, incluir_arquivado_no_resultado: bool) -> None:
        self.incluir = incluir_arquivado_no_resultado
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.clientes c" in query and "ag.total_atendimentos" in query:
            rows = [
                _cliente_row(uuid4(), nome="Ativo"),
            ]
            if self.incluir:
                rows.append(_cliente_row(uuid4(), nome="Arquivado", arquivado_em=datetime.now(UTC)))
            return _Result(rows)
        return _Result([])


class FakeConnPatchSucesso:
    """Fake conn para PATCH com nome+telefone bem-sucedido."""

    def __init__(self, cliente_id: UUID) -> None:
        self.cliente_id = cliente_id
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "SELECT id, telefone FROM barravips.clientes" in query:
            return _Result([{"id": self.cliente_id, "telefone": "5521900000000"}])
        if "SELECT id, nome, telefone, arquivado_em FROM barravips.clientes" in query:
            return _Result([
                {
                    "id": self.cliente_id,
                    "nome": "Novo Nome",
                    "telefone": "5521988887777",
                    "arquivado_em": None,
                }
            ])
        return _Result([])


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def test_criar_cliente_retorna_201_e_normaliza_telefone() -> None:
    cliente_id = uuid4()
    conn = FakeConnCriar(cliente_id, telefone="5521999998888")
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/crm/clientes",
                json={"nome": "Joao", "telefone": "+55 (21) 99999-8888"},
                headers=_token(),
            )
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == str(cliente_id)
        assert body["telefone"] == "5521999998888"
        assert "*****" in body["telefone_mascarado"]
        assert body["arquivado_em"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_cliente_telefone_duplicado_retorna_409() -> None:
    conn = FakeConnTelefoneDuplicado()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/crm/clientes",
                json={"telefone": "5521999998888"},
                headers=_token(),
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLITO_ESTADO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_cliente_telefone_invalido_retorna_422() -> None:
    conn = FakeConnCriar(uuid4(), telefone="5521999998888")
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/crm/clientes",
                json={"telefone": "123"},
                headers=_token(),
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_cliente_atualiza_nome_e_telefone() -> None:
    cliente_id = uuid4()
    conn = FakeConnPatchSucesso(cliente_id)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/crm/clientes/{cliente_id}",
                json={"nome": "Novo Nome", "telefone": "+55 21 98888-7777"},
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["telefone"] == "5521988887777"
        update_query = next(
            (q for q, _ in conn.executes if "UPDATE barravips.clientes SET" in q),
            "",
        )
        assert "nome = %s" in update_query
        assert "telefone = %s" in update_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_cliente_telefone_duplicado_retorna_409() -> None:
    cliente_id = uuid4()
    conn = FakeConnTelefoneDuplicado(cliente_id=cliente_id)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/crm/clientes/{cliente_id}",
                json={"telefone": "5521988887777"},
                headers=_token(),
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLITO_ESTADO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_arquivar_cliente_inativo_define_timestamp() -> None:
    cliente_id = uuid4()
    conn = FakeConnArquivar(cliente_id, arquivado_em=None)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/crm/clientes/{cliente_id}/arquivar",
                headers=_token(),
            )
        assert response.status_code == 200
        assert response.json()["arquivado_em"] is not None
        # 2x deve ser idempotente — não roda UPDATE de novo
        executes_antes = len(conn.executes)
        with TestClient(app) as client:
            response2 = client.post(
                f"/v1/crm/clientes/{cliente_id}/arquivar",
                headers=_token(),
            )
        assert response2.status_code == 200
        novos_updates = [
            q for q, _ in conn.executes[executes_antes:]
            if "UPDATE barravips.clientes SET arquivado_em = NOW()" in q
        ]
        assert novos_updates == []
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_arquivar_cliente_inexistente_retorna_404() -> None:
    class FakeConnVazio:
        @asynccontextmanager
        async def transaction(self):
            yield

        async def execute(self, query: str, params: object = None) -> _Result:
            return _Result([])

    app.dependency_overrides[get_conn] = _override(FakeConnVazio())
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/crm/clientes/{uuid4()}/arquivar",
                headers=_token(),
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_desarquivar_cliente_remove_timestamp() -> None:
    cliente_id = uuid4()
    conn = FakeConnArquivar(cliente_id, arquivado_em=datetime.now(UTC))
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/crm/clientes/{cliente_id}/desarquivar",
                headers=_token(),
            )
        assert response.status_code == 200
        assert response.json()["arquivado_em"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_clientes_default_filtra_arquivados() -> None:
    conn = FakeConnListar(incluir_arquivado_no_resultado=False)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes", headers=_token())
        assert response.status_code == 200
        select_query = next((q for q in conn.queries if "ag.total_atendimentos" in q), "")
        assert "c.arquivado_em IS NULL" in select_query
        body = response.json()
        assert all(item["arquivado_em"] is None for item in body["items"])
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_clientes_incluir_arquivados_remove_filtro() -> None:
    conn = FakeConnListar(incluir_arquivado_no_resultado=True)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes?incluir_arquivados=true",
                headers=_token(),
            )
        assert response.status_code == 200
        select_query = next((q for q in conn.queries if "ag.total_atendimentos" in q), "")
        assert "c.arquivado_em IS NULL" not in select_query
        body = response.json()
        assert any(item["arquivado_em"] is not None for item in body["items"])
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_clientes_retorna_agregados_por_cliente() -> None:
    """Cada item da lista carrega os agregados por cliente (todas as modelos)."""
    conn = FakeConnListar(incluir_arquivado_no_resultado=False)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes", headers=_token())
        assert response.status_code == 200
        item = response.json()["items"][0]
        # Cliente novo (sem atendimentos) aparece com agregados zerados e recorrente=false.
        assert item["total_atendimentos"] == 0
        assert item["valor_total"] == 0
        assert item["modelos_distintas"] == 0
        assert item["modelo_predominante_nome"] is None
        assert item["recorrente"] is False
        assert "telefone_mascarado" in item
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_clientes_periodo_aplica_filtro_de_atendimento() -> None:
    conn = FakeConnListar(incluir_arquivado_no_resultado=False)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes?periodo=30d", headers=_token())
        assert response.status_code == 200
        select_query = next((q for q in conn.queries if "ag.total_atendimentos" in q), "")
        assert "a.cliente_id = c.id" in select_query
        assert "INTERVAL '30 days'" in select_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_clientes_modelo_id_filtra_por_conversa() -> None:
    conn = FakeConnListar(incluir_arquivado_no_resultado=False)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/v1/crm/clientes?modelo_id={uuid4()}", headers=_token()
            )
        assert response.status_code == 200
        select_query = next((q for q in conn.queries if "ag.total_atendimentos" in q), "")
        assert "FROM barravips.conversas cv" in select_query
        assert "cv.modelo_id = %s" in select_query
    finally:
        app.dependency_overrides.pop(get_conn, None)
