"""M3a — _executar_idempotente contra o Postgres real (04 §3, 02 §8.2).

Prova a garantia de idempotencia das tools de escrita: a 1a chamada com uma chave
`(turno_id, tool_name, call_idx)` roda o executor; a 2a com a MESMA chave NAO o roda
de novo e devolve o resultado da 1a (retry do ARQ / replay do turno nao duplica efeito).

Espelha o padrao needs_db de test_repo_integracao.py (TEST_DATABASE_URL, autocommit=False,
dict_row, prepare_threshold=None, ROLLBACK SEMPRE no teardown — nada commita no banco de
prod self-hosted). Um `SELECT 1` ANTES do helper abre a transacao externa do fixture, de
modo que o `conn.transaction()` interno do helper vira um SAVEPOINT — o ROLLBACK desfaz tudo.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas._idempotencia import _executar_idempotente


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


@pytest.mark.needs_db
async def test_helper(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Abre a transacao externa do fixture ANTES do helper: o conn.transaction() interno
    # vira SAVEPOINT (released no fim), e o ROLLBACK do teardown desfaz tudo.
    await conn.execute("SELECT 1")

    turno_id = str(uuid4())
    payload = {"x": 42, "tag": "apresentacao"}
    chamadas = 0

    async def executor(c: AsyncConnection[Any], p: dict[str, Any]) -> dict[str, Any]:
        nonlocal chamadas
        chamadas += 1
        return {"ok": True, "eco": p["x"], "n": chamadas}

    # (a) chave nova -> executor roda 1x e retorna o proprio resultado.
    r1 = await _executar_idempotente(conn, turno_id, "registrar_extracao", 0, payload, executor)
    assert chamadas == 1
    assert r1 == {"ok": True, "eco": 42, "n": 1}

    # (b) MESMA (turno_id, tool_name, call_idx) -> executor NAO roda; devolve o resultado da 1a.
    r2 = await _executar_idempotente(conn, turno_id, "registrar_extracao", 0, payload, executor)
    assert chamadas == 1  # nao incrementou: o efeito colateral nao foi reexecutado
    assert r2 == r1
