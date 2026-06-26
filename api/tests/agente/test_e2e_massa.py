"""Validacao offline do runner em massa de cenarios (evals/e2e/massa.py).

needs_db (DB real via TEST_DATABASE_URL, ROLLBACK sempre), NAO needs_key: graph fake, sem credito
(§0). Cobre o codigo novo mais arriscado: o pos-evento determinístico da foto de portaria
(`_disparar_foto_portaria` -> handoff de dominio -> Em_execucao + IA pausada) e o encanamento do
`rodar_massa` (seed -> conducao fake -> pos-evento -> veredito), sem tocar prod (run_tag=None).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from evals.e2e.massa import _disparar_foto_portaria, rodar_massa
from evals.harness import estado_pos_turno, seedar
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


async def test_foto_portaria_dispara_transicao(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Interno em Aguardando_confirmacao + foto de portaria -> Em_execucao, IA pausada (motivo
    modelo_em_atendimento). Evento determinístico de dominio, sem graph/worker/vision."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Manu", "tipo_atendimento_aceito": ["interno"]},
                "atendimento": {"estado": "Aguardando_confirmacao", "tipo_atendimento": "interno"},
            },
            "historico": [],
        },
    )
    await _disparar_foto_portaria(conn, cen)

    est = await estado_pos_turno(conn, cen.atendimento_id)
    assert est["estado"] == "Em_execucao", est
    assert est["ia_pausada"] is True, est


async def test_rodar_massa_foto_portaria_fake(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """rodar_massa conduz o cenario foto_portaria com graph fake e dispara o pos-evento ate
    Em_execucao. run_tag=None -> nao grava (nao toca corpus.eval_e2e). Tokens 100% do fake (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    so_foto = [c for c in cmod.cenarios() if c.nome == "foto_portaria"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_foto)

    resultados = await rodar_massa(conn, _graph_fake(), k=1, run_tag=None)

    assert len(resultados) == 1, resultados
    r = resultados[0]
    assert r["cenario"] == "foto_portaria"
    assert r["estado_final"] == "Em_execucao", r
    assert r["avaliacao"].get("estado_esperado_ok") is True, r
    assert not r["violacoes"], r


async def test_rodar_massa_agenda_borda_fora_fake(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encanamento do cenario agenda_borda_fora com graph fake: o seed de modelo_disponibilidade
    (janela 10-23h) nao quebra e o veredito traz o check `nao_confirmou_fora_ok`. O VALOR do check so
    e significativo na corrida REAL (o fake nao confirma horario); aqui guardamos o plumbing (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    so_borda = [c for c in cmod.cenarios() if c.nome == "agenda_borda_fora"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_borda)

    resultados = await rodar_massa(conn, _graph_fake(), k=1, run_tag=None)

    assert len(resultados) == 1, resultados
    r = resultados[0]
    assert r["cenario"] == "agenda_borda_fora"
    assert "nao_confirmou_fora_ok" in r["avaliacao"], r


def test_linkar_item_run_noop_sem_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fase 5: sem handler Langfuse (tracing off — pytest/.env vazio) o link e no-op puro: nao
    levanta nem toca a rede, mesmo com trace_id setado. Mesma disciplina best-effort das outras
    funcoes de dataset (garantir/upsert). Forca o handler=None (outro teste da suite pode te-lo
    ligado num global e nao restaurado) p/ o no-op ser testado de forma isolada."""
    from barra.core import tracing

    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None)
    # nao deve levantar nem retornar nada (no-op)
    assert tracing.linkar_item_run("e2e_conducao", "item-x", "run-1", "trace-abc") is None
    # tambem no-op quando falta o trace_id (turno sem escopo)
    assert tracing.linkar_item_run("e2e_conducao", "item-x", "run-1", None) is None


async def test_rodar_massa_com_dataset_run_nao_quebra_sem_handler(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fase 5: passar `dataset_run` com o tracing OFF (sem chaves Langfuse) e seguro — garantir/
    upsert/link sao no-op e a corrida roda igual. Prova que a integracao nao acopla o eval ao
    Langfuse. Graph fake, run_tag=None: sem credito e sem tocar prod (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    from barra.core import tracing

    # forca o tracing OFF (outro teste pode ter ligado o handler global): sem isso o `dataset_run`
    # tentaria criar dataset/run REAIS no Langfuse de prod.
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None)

    so_foto = [c for c in cmod.cenarios() if c.nome == "foto_portaria"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_foto)

    resultados = await rodar_massa(
        conn, _graph_fake(), k=1, run_tag=None, dataset_run="run-de-teste"
    )

    assert len(resultados) == 1, resultados
    assert resultados[0]["cenario"] == "foto_portaria"
