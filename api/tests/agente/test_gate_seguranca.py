"""Gate de seguranca (Camada 1, BLOCKING) — o veredito determinristico do cutover Vendedor->IA.

Carrega as fixtures de `api/evals/seguranca/**/*.jsonl`, roda cada uma K vezes (`pass^K`: 0
vazamento em K/K — re-roll mascara flake, 08 §4) sobre o grafo REAL com DB real + ROLLBACK, e
aplica os graders determinristicos de `evals.checks`. Sem LLM-judge (ADR 0015 rejeitou): o
veredito e 100% deterministico.

Das 4 fixtures, so a de ISOLAMENTO chama o modelo (a IA da modelo A responde de fato). As de AUP
(jailbreak escala direto; disclosure usa negacao canned) e a de maquina de estados (ia_pausada =
early exit) NAO atingem a Anthropic — gate quase sem credito (§0). `EVALS_K` (env) controla K;
default 1 para a suite local, 5 no gate de cutover.

needs_key + needs_db (igual test_fixtures_leitura_decisao.py): a suite padrao e a CI nao tocam.
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from evals.checks import auditar_canary, avaliar
from evals.harness import habilitar_tracing, rodar_turno, seedar
from evals.relatorio import registrar
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.graph import build_graph

_SEGURANCA = Path(__file__).resolve().parents[2] / "evals" / "seguranca"
_K = int(os.environ.get("EVALS_K", "1"))


def _carregar_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for arquivo in sorted(_SEGURANCA.glob("**/*.jsonl")):
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                fixtures.append(json.loads(linha))
    return fixtures


_FIXTURES = _carregar_fixtures()


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


@pytest.mark.needs_key
@pytest.mark.needs_db
@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
async def test_gate_seguranca(
    conn: AsyncConnection[dict[str, Any]], fixture: dict[str, Any]
) -> None:
    habilitar_tracing()  # trace Langfuse por turno quando LANGFUSE_* estiver no ambiente (no-op senao)
    graph = build_graph()
    checks = fixture.get("checks", {})
    categoria = str(fixture.get("categoria", ""))
    falhas_por_run: list[str] = []

    for run in range(_K):
        cen = await seedar(conn, fixture)
        resultado = await rodar_turno(
            conn, cen, turno_cliente=fixture["turno_cliente"], graph=graph
        )
        falhas = avaliar(resultado, checks)
        if checks.get("canary_ausente") and cen.canary:
            falhas += auditar_canary(resultado, cen.canary)
        registrar(
            fixture_id=fixture["id"],
            categoria=categoria,
            run=run,
            falhas=falhas,
            resultado=resultado,
        )
        if falhas:
            falhas_por_run.append(f"run {run}: {falhas}")

    assert not falhas_por_run, (
        f"{fixture['id']} ({fixture.get('categoria')}) reprovou em {len(falhas_por_run)}/{_K} runs:\n"
        + "\n".join(falhas_por_run)
    )
