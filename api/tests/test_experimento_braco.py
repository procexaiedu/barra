"""Trilho do A/B vivo (experimento_braco): `resolver_atendimento` carimba o braço SÓ com o flag
ligado; com o flag desligado a query é byte-idêntica à de sempre (segura contra o schema
pré-migration). Unit test puro (FakeConn) — NÃO toca o Postgres real de propósito: a coluna
experimento_braco não existe em prod até a migration ser aplicada (§0), então o caminho ON não é
exercitável em needs_db. Aqui validamos a FORMA da query sob os dois valores do flag.
"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from barra.workers import coordenador
from barra.workers.coordenador import resolver_atendimento


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """Captura as queries; 1ª (SELECT atendimento aberto) -> None (não há); 2ª (INSERT) -> linha."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def execute(self, query: str, params: Any = None) -> _FakeResult:
        self.queries.append(query)
        if "INSERT INTO barravips.atendimentos" in query:
            return _FakeResult({"id": uuid4(), "estado": "Novo"})
        return _FakeResult(None)


def _insert_query(conn: _FakeConn) -> str:
    inserts = [q for q in conn.queries if "INSERT INTO barravips.atendimentos" in q]
    assert len(inserts) == 1
    return inserts[0]


async def test_braco_carimbado_quando_experimento_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: SimpleNamespace(experimento_braco_ativo=True)
    )
    conn = _FakeConn()
    novo = await resolver_atendimento(conn, uuid4())  # type: ignore[arg-type]

    assert novo["estado"] == "Novo"
    insert = _insert_query(conn)
    assert "experimento_braco" in insert
    # atribuição determinística e sticky por cliente, computada em SQL (sem param extra).
    assert "get_byte(decode(md5(c.cliente_id::text), 'hex'), 0) % 2" in insert
    assert "'controle'" in insert
    assert "'tratamento'" in insert


async def test_query_inalterada_quando_experimento_desligado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: SimpleNamespace(experimento_braco_ativo=False)
    )
    conn = _FakeConn()
    await resolver_atendimento(conn, uuid4())  # type: ignore[arg-type]

    insert = _insert_query(conn)
    # Flag OFF: a coluna do experimento NÃO entra na query -> roda contra o schema pré-migration.
    assert "experimento_braco" not in insert
    assert "md5(" not in insert
