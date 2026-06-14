"""Validacao da extracao de PerfilCaso do corpus (evals/e2e/extracao.py).

needs_db (le corpus.threads/turnos via TEST_DATABASE_URL), NAO needs_key: so SELECT, sem credito.
Confirma que a extracao mecanica produz casos bem-formados — convertidos e perdidos, multi-turn,
com persona ancorada nas falas reais e a modelo sintetica.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from evals.e2e.extracao import (
    DESFECHOS_CONVERTIDOS,
    DESFECHOS_PERDIDOS,
    extrair_perfis,
)
from psycopg import AsyncConnection
from psycopg.rows import dict_row

pytestmark = pytest.mark.needs_db


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


async def test_extrai_convertidos_internos(conn: AsyncConnection[dict[str, Any]]) -> None:
    perfis = await extrair_perfis(conn, desfechos=DESFECHOS_CONVERTIDOS, tipo="interno", limite=5)

    assert perfis, "esperava casos convertidos internos no corpus"
    for p in perfis:
        assert p.abertura.strip()  # 1a fala do cliente
        assert p.roteiro_cliente  # multi-turn: ha falas alem da abertura
        assert p.desfecho_real == "convertido_provavel"
        assert p.tipo_esperado == "interno"
        assert p.modelo["nome"] == "Manu"  # modelo sintetica
        assert p.thread_ref and ":" in p.thread_ref
        # persona ancorada nas falas reais: a abertura aparece textual dentro dela
        assert p.abertura in p.persona


async def test_extrai_perdidos(conn: AsyncConnection[dict[str, Any]]) -> None:
    perfis = await extrair_perfis(conn, desfechos=DESFECHOS_PERDIDOS, tipo="interno", limite=5)

    assert perfis, "esperava casos perdidos no corpus"
    assert all(p.desfecho_real in DESFECHOS_PERDIDOS for p in perfis)
    # convertidos e perdidos sao casos distintos (chaves de thread nao colidem)
    refs = {p.thread_ref for p in perfis}
    assert len(refs) == len(perfis)
