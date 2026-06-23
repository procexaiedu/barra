"""Teste unit do coletor de baixo score (workers/revisao_baixo_score) — sem DB, sem Langfuse real.

`FakeConn` devolve linhas canned (turnos reprovados); os 3 helpers de Langfuse são monkeypatchados
para capturar as chamadas. Espelha o estilo de `test_fluxo_drift`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from barra.settings import get_settings
from barra.workers import revisao_baixo_score


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Query única (_SQL_RUINS): devolve sempre as linhas canned."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        return _Result(self._rows)


def _settings(**over: Any) -> Any:
    base = {"baixo_score_ativo": True, "baixo_score_janela_dias": 7}
    base.update(over)
    return get_settings().model_copy(update=base)


def _ruim_rows() -> list[dict[str, Any]]:
    return [
        {
            "resposta_ia_id": "11111111-1111-4111-8111-111111111111",
            "conversa_id": "22222222-2222-4222-8222-222222222222",
            "modelo_id": "33333333-3333-4333-8333-333333333333",
            "ia_conteudo": "te encaixo amanhã",
            "cliente_conteudo": "quanto fica a hora?",
            "nota": 2,
            "comentario": "o Vendedor cotaria na hora",
            "avaliado_em": datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        }
    ]


def _instrumentar(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    chamadas: dict[str, list[Any]] = {"dataset": [], "item": [], "score": []}
    monkeypatch.setattr(
        revisao_baixo_score, "garantir_dataset", lambda nome: chamadas["dataset"].append(nome)
    )
    monkeypatch.setattr(
        revisao_baixo_score,
        "upsert_item_dataset",
        lambda ds, item_id, meta: chamadas["item"].append((ds, item_id, meta)),
    )
    monkeypatch.setattr(
        revisao_baixo_score,
        "registrar_score_agregado",
        lambda nome, valor, *, janela="": chamadas["score"].append((nome, valor, janela)),
    )
    return chamadas


def test_flag_off_nao_faz_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    total = asyncio.run(
        revisao_baixo_score.coletar_baixo_score(
            FakeConn(_ruim_rows()), _settings(baixo_score_ativo=False)
        )
    )
    assert total == 0
    assert chamadas == {"dataset": [], "item": [], "score": []}


def test_sem_reprovados_nao_garante_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    total = asyncio.run(revisao_baixo_score.coletar_baixo_score(FakeConn([]), _settings()))
    assert total == 0
    # janela vazia: sai antes de garantir o dataset (nada a regredir)
    assert chamadas == {"dataset": [], "item": [], "score": []}


def test_upserta_turno_reprovado_no_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    total = asyncio.run(
        revisao_baixo_score.coletar_baixo_score(FakeConn(_ruim_rows()), _settings())
    )

    assert total == 1
    assert chamadas["dataset"] == ["revisao-baixo-score"]
    assert len(chamadas["item"]) == 1
    ds, item_id, meta = chamadas["item"][0]
    assert ds == "revisao-baixo-score"
    assert item_id == "baixo-score:11111111-1111-4111-8111-111111111111"
    # identidade só por UUID opaco — nunca telefone/nome do cliente
    assert meta["resposta_ia_id"] == "11111111-1111-4111-8111-111111111111"
    assert meta["ia_conteudo"] == "te encaixo amanhã"
    assert meta["cliente_conteudo"] == "quanto fica a hora?"
    assert meta["nota"] == 2 and meta["comentario"] == "o Vendedor cotaria na hora"
    assert meta["avaliado_em"] == "2026-06-22T12:00:00+00:00"
    assert "telefone" not in meta and "cliente_nome" not in meta
    # score agregado da contagem
    assert ("baixo_score_n_turnos", 1.0, "") in chamadas["score"]
