"""Auto-ingestao do runner -> rodada de calibracao no banco REAL (needs_db).

Prova que `runner.ingerir_conversas` materializa as conversas geradas pelo gate como uma rodada +
falas nas tabelas `barravips.calibracao_*` -- a aba /calibracao as exibe prontas p/ rotular. Postgres
real com ROLLBACK sempre (a escrita commitada de verdade so acontece em `main`, sob --ingerir-calibracao).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

_RUNNER = Path(__file__).resolve().parents[2] / "evals" / "runners" / "runner.py"


def _carregar_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_runner", _RUNNER)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


runner = _carregar_runner()


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


_TURNOS = [
    {"papel": "cliente", "texto": "quanto e 1h?"},
    {"papel": "ia", "texto": "900 amor", "estado": "Qualificado", "tools": ["registrar_extracao"]},
    {"papel": "cliente", "texto": "fechado"},
    {"papel": "ia", "texto": "te espero amor", "estado": "Qualificado", "tools": []},
]


@pytest.mark.needs_db
async def test_ingerir_conversas_cria_rodada_e_falas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # 2 amostras da mesma fixture (K=2) -> 2 conversas distintas, 4 falas geradas no total.
    conversas = [
        runner.serializar_conversa("canonicos.venda.001", 0, _TURNOS),
        runner.serializar_conversa("canonicos.venda.001", 1, _TURNOS),
    ]
    resumo = await runner.ingerir_conversas(conn, "gate-teste-001", conversas)

    assert resumo.nome == "gate-teste-001"
    assert resumo.total_falas == 4  # 2 bolhas geradas x 2 amostras

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.calibracao_rodadas WHERE id = %s", (resumo.id,)
    )
    assert (await res.fetchone())["n"] == 1
    res = await conn.execute(
        "SELECT fala_id, texto_resposta FROM barravips.calibracao_falas "
        "WHERE rodada_id = %s ORDER BY ordem",
        (resumo.id,),
    )
    rows = await res.fetchall()
    # as duas amostras viram fala_ids distintos (#k0/#k1) -> Fernando/socia veem a variacao run-a-run.
    assert [r["fala_id"] for r in rows] == [
        "canonicos.venda.001#k0::0",
        "canonicos.venda.001#k0::1",
        "canonicos.venda.001#k1::0",
        "canonicos.venda.001#k1::1",
    ]
    assert {r["texto_resposta"] for r in rows} == {"900 amor", "te espero amor"}
