"""Teste unit do sensor de fluxo (workers/fluxo_drift) — sem DB, sem crédito, sem Langfuse real.

`FakeConn` devolve linhas canned conforme o SQL (referência corpus vs. agente); os 3 helpers de
Langfuse são monkeypatchados para capturar as chamadas. Espelha o `asyncio.run(...)` de test_workers.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from barra.settings import get_settings
from barra.workers import fluxo_drift


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Roteia o SQL: corpus.turnos -> referência; senão -> bolhas da IA por origem (params[0])."""

    def __init__(self, ref: list[dict[str, Any]], agente: dict[str, list[dict[str, Any]]]) -> None:
        self._ref = ref
        self._agente = agente

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        if "corpus.turnos" in sql:
            return _Result(self._ref)
        origem = params[0] if params else ""
        return _Result(self._agente.get(origem, []))


def _settings(**over: Any) -> Any:
    base = {"fluxo_drift_ativo": True, "fluxo_drift_janela_dias": 7}
    base.update(over)
    return get_settings().model_copy(update=base)


def _ref_rows() -> list[dict[str, Any]]:
    # Duas threads humanas com transições saudacao->sondagem->cotacao->logistica.
    linhas = []
    for jid in ("a", "b"):
        for texto, midia in [
            ("oi amor tudo bem?", False),
            ("seria hoje? 🥰", False),
            ("400 a hora", False),
            ("me manda o pix", False),
        ]:
            linhas.append(
                {"texto": texto, "tem_midia": midia, "instancia": "eb01", "remote_jid": jid}
            )
    return linhas


def _instrumentar(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    chamadas: dict[str, list[Any]] = {"dataset": [], "item": [], "score": []}
    monkeypatch.setattr(
        fluxo_drift, "garantir_dataset", lambda nome: chamadas["dataset"].append(nome)
    )
    monkeypatch.setattr(
        fluxo_drift,
        "upsert_item_dataset",
        lambda ds, item_id, meta: chamadas["item"].append((ds, item_id, meta)),
    )
    monkeypatch.setattr(
        fluxo_drift,
        "registrar_score_agregado",
        lambda nome, valor, *, janela="": chamadas["score"].append((nome, valor, janela)),
    )
    return chamadas


def test_flag_off_nao_faz_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    conn = FakeConn(
        _ref_rows(), {"prod": [{"conversa_id": "x", "conteudo": "oi", "tipo": "texto"}]}
    )
    total = asyncio.run(fluxo_drift.medir_fluxo_drift(conn, _settings(fluxo_drift_ativo=False)))
    assert total == 0
    assert chamadas == {"dataset": [], "item": [], "score": []}


def test_sem_conversa_do_agente_nao_pontua(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    conn = FakeConn(_ref_rows(), {})  # nenhuma origem tem bolha da IA
    total = asyncio.run(fluxo_drift.medir_fluxo_drift(conn, _settings()))
    assert total == 0
    assert chamadas["dataset"] == ["fluxo-conversas"]  # dataset garantido mesmo sem dado
    assert chamadas["item"] == []
    assert chamadas["score"] == []


def test_computa_jsd_e_escreve_dataset_e_score(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _instrumentar(monkeypatch)
    agente = {
        "prod": [
            {"conversa_id": "c1", "conteudo": "oi tudo bem?", "tipo": "texto"},
            {"conversa_id": "c1", "conteudo": "400 a hora amor", "tipo": "texto"},
            {"conversa_id": "c1", "conteudo": "me manda o pix", "tipo": "texto"},
        ]
    }
    total = asyncio.run(fluxo_drift.medir_fluxo_drift(FakeConn(_ref_rows(), agente), _settings()))

    assert total == 1  # uma conversa de prod
    assert chamadas["dataset"] == ["fluxo-conversas"]
    # 1 item, id prefixado pela origem, com a sequência de atos rotulada
    assert len(chamadas["item"]) == 1
    ds, item_id, meta = chamadas["item"][0]
    assert ds == "fluxo-conversas" and item_id == "prod:c1"
    assert meta["origem"] == "prod" and meta["atos"] == ["saudacao", "cotacao", "logistica"]
    # score do JSD de prod, valor em [0,1]
    nomes = {c[0] for c in chamadas["score"]}
    assert "fluxo_jsd_prod" in nomes and "fluxo_n_conversas_prod" in nomes
    jsd = next(v for n, v, _ in chamadas["score"] if n == "fluxo_jsd_prod")
    assert 0.0 <= jsd <= 1.0
