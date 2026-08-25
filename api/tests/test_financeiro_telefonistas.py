"""Aba Telefonistas: cadastro e percentual de comissao (ADR-0048) — /v1/financeiro/telefonistas.

Sem DB: espelha o FakeConn de `test_financeiro_comissoes_pagamentos.py`. As colunas
`vendedores.percentual_comissao` e `vendedores.whatsapp_jid` nascem numa migration escrita e ainda
nao aplicada, entao o que se prova aqui e o SQL que sai e a traducao HTTP — nao o banco.
"""

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


class FakeConn:
    def __init__(self, telefonista_id: UUID | None = None, *, update_rowcount: int = 1) -> None:
        self.telefonista_id = telefonista_id or uuid4()
        self.update_rowcount = update_rowcount
        self.executes: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.vendedores" in query:
            return _Result([{"id": self.telefonista_id}])
        if "UPDATE barravips.vendedores" in query:
            return _Result(rowcount=self.update_rowcount)
        if "FROM barravips.vendedores v" in query:
            return _Result(
                [
                    {
                        "id": self.telefonista_id,
                        "nome": "Rodrigo",
                        "percentual_comissao": Decimal("7.00"),
                        "ativo": True,
                        "whatsapp_jid": "5511999999999@s.whatsapp.net",
                    }
                ]
            )
        return _Result([])

    def _sql(self, trecho: str) -> str:
        return next(q for q, _ in self.executes if trecho in q)

    def _params(self, trecho: str) -> Any:
        return next(p for q, p in self.executes if trecho in q)


def test_listar_traz_o_percentual_e_esconde_inativos_por_default() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/financeiro/telefonistas", headers=_token())
        assert r.status_code == 200
        item = r.json()["items"][0]
        assert item["percentual_comissao"] == 7.0
        assert item["whatsapp_jid"] == "5511999999999@s.whatsapp.net"
        select = conn._sql("FROM barravips.vendedores v")
        assert "v.percentual_comissao" in select
        assert "WHERE v.ativo" in select
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_listar_com_incluir_inativos_nao_filtra() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.get("/v1/financeiro/telefonistas?incluir_inativos=true", headers=_token())
        assert r.status_code == 200
        assert "WHERE v.ativo" not in conn._sql("FROM barravips.vendedores v")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_sem_percentual_usa_os_7_por_cento_de_referencia() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/telefonistas",
                json={"nome": "  Rodrigo  "},
                headers=_token(),
            )
        assert r.status_code == 201
        params = conn._params("INSERT INTO barravips.vendedores")
        assert params[0] == "Rodrigo"  # nome vem sem os espacos que o gestor digitou
        assert params[1] == Decimal("7.00")
        assert params[2] is None  # JID vazio e NULL, nunca '' (indice unico parcial)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_com_jid_em_branco_grava_null() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/telefonistas",
                json={"nome": "Rodrigo", "whatsapp_jid": "   "},
                headers=_token(),
            )
        assert r.status_code == 201
        assert conn._params("INSERT INTO barravips.vendedores")[2] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_percentual_fora_da_faixa_operacional_e_aceito() -> None:
    """1-10% e faixa operacional, nao invariante (ADR-0048): quem avisa e a tela, nao um 422."""
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/telefonistas",
                json={"nome": "Rodrigo", "percentual_comissao": "15"},
                headers=_token(),
            )
        assert r.status_code == 201
        assert conn._params("INSERT INTO barravips.vendedores")[1] == Decimal("15")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_percentual_acima_do_check_do_banco_e_422() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/v1/financeiro/telefonistas",
                json={"nome": "Rodrigo", "percentual_comissao": "150"},
                headers=_token(),
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_toca_so_a_coluna_enviada() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(
                f"/v1/financeiro/telefonistas/{conn.telefonista_id}",
                json={"percentual_comissao": "9.5"},
                headers=_token(),
            )
        assert r.status_code == 200
        update = conn._sql("UPDATE barravips.vendedores")
        assert "percentual_comissao = %s" in update
        assert "nome" not in update and "ativo" not in update
        assert conn._params("UPDATE barravips.vendedores")[0] == Decimal("9.5")
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_ignora_nome_nulo_mas_apaga_jid_nulo() -> None:
    """`null` so e gesto em `whatsapp_jid`; nos demais campos e "nao mexa"."""
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(
                f"/v1/financeiro/telefonistas/{conn.telefonista_id}",
                json={"nome": None, "whatsapp_jid": None},
                headers=_token(),
            )
        assert r.status_code == 200
        update = conn._sql("UPDATE barravips.vendedores")
        assert "whatsapp_jid = %s" in update
        assert "nome = %s" not in update
        assert conn._params("UPDATE barravips.vendedores")[0] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_desativa_sem_delete() -> None:
    conn = FakeConn()
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(
                f"/v1/financeiro/telefonistas/{conn.telefonista_id}",
                json={"ativo": False},
                headers=_token(),
            )
        assert r.status_code == 200
        assert "ativo = %s" in conn._sql("UPDATE barravips.vendedores")
        assert not any("DELETE FROM barravips.vendedores" in q for q, _ in conn.executes)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_patch_em_id_inexistente_e_404() -> None:
    conn = FakeConn(update_rowcount=0)
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            r = client.patch(
                f"/v1/financeiro/telefonistas/{uuid4()}",
                json={"nome": "Rodrigo Silva"},
                headers=_token(),
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_conn, None)
