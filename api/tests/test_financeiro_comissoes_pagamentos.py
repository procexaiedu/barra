"""Pagamentos de Comissão de vendedor (ADR 0012) — rotas /v1/financeiro/comissoes/pagamentos.

Fecha o caminho de ESCRITA que faltava (a tabela financeiro_comissoes_pagas já era lida
pela projeção comissao_por_vendedor, mas nada a alimentava → valor_comissao_paga ficava 0).
Espelha o padrão de FakeConn de test_vendedores.py. Sem DB.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
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


def _pagamento_row(pag_id: UUID) -> dict[str, Any]:
    return {
        "id": pag_id,
        "vendedor_id": uuid4(),
        "vendedor_nome": "João",
        "data_pagamento": date(2026, 6, 20),
        "valor": Decimal("120.00"),
        "forma_pagamento": "pix",
        "observacao": None,
        "comprovante_object_key": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


class FakeConn:
    def __init__(
        self, pag_id: UUID | None = None, *, update_rowcount: int = 1, delete_rowcount: int = 1
    ) -> None:
        self.pag_id = pag_id or uuid4()
        self.update_rowcount = update_rowcount
        self.delete_rowcount = delete_rowcount
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.financeiro_comissoes_pagas" in query:
            return _Result([{"id": self.pag_id}])
        if "UPDATE barravips.financeiro_comissoes_pagas" in query:
            return _Result(rowcount=self.update_rowcount)
        if "DELETE FROM barravips.financeiro_comissoes_pagas" in query:
            return _Result(rowcount=self.delete_rowcount)
        if "FROM barravips.financeiro_comissoes_pagas p" in query:  # obter / listar
            return _Result([_pagamento_row(self.pag_id)])
        return _Result([])


def test_criar_comissao_pagamento_retorna_201() -> None:
    pid = uuid4()
    conn = FakeConn(pid)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/comissoes/pagamentos",
                json={
                    "vendedor_id": str(uuid4()),
                    "data_pagamento": "2026-06-20",
                    "valor": "120.00",
                    "forma_pagamento": "pix",
                },
                headers=_token(),
            )
        assert r.status_code == 201
        assert r.json()["id"] == str(pid)
        insert = next(
            q for q, _ in conn.executes if "INSERT INTO barravips.financeiro_comissoes_pagas" in q
        )
        assert "vendedor_id" in insert and "created_by" in insert
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_forma_invalida_retorna_422() -> None:
    # FormaPagamentoRepasse = pix/dinheiro/outro (paga-se a pessoa, nunca cartão).
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/comissoes/pagamentos",
                json={
                    "vendedor_id": str(uuid4()),
                    "data_pagamento": "2026-06-20",
                    "valor": "120.00",
                    "forma_pagamento": "cartao",
                },
                headers=_token(),
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_comissao_pagamentos_le_a_tabela() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/financeiro/comissoes/pagamentos", headers=_token())
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1
        select = next(
            q for q, _ in conn.executes if "FROM barravips.financeiro_comissoes_pagas p" in q
        )
        assert "JOIN barravips.vendedores v" in select
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_pagamento_inexistente_404() -> None:
    conn = FakeConn(update_rowcount=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(
                f"/v1/financeiro/comissoes/pagamentos/{uuid4()}",
                json={"valor": "200.00"},
                headers=_token(),
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_excluir_pagamento_inexistente_404() -> None:
    conn = FakeConn(delete_rowcount=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.delete(f"/v1/financeiro/comissoes/pagamentos/{uuid4()}", headers=_token())
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)
