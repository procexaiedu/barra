"""Testes unit do vigia de rollback (workers/rollback_watch) — sem DB, sem Sentry real.

FakeConn devolve contagens/mensagens canned por substring do SQL; os alertas são capturados
monkeypatchando `_alertar`. O gauge é verificado via REGISTRY (labels novas por teste não são
necessárias: o gauge re-seta 1/0 a cada corrida).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from prometheus_client import REGISTRY

from barra.settings import get_settings
from barra.workers import rollback_watch
from barra.workers.rollback_watch import (
    contar_conversas_com_acusacao,
    vigiar_gatilhos_rollback,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(
        self,
        *,
        nao_contidos: int = 0,
        mensagens: list[dict[str, Any]] | None = None,
        aborts: int = 0,
        turnos: int = 100,
    ) -> None:
        self.nao_contidos = nao_contidos
        self.mensagens = mensagens or []
        self.aborts = aborts
        self.turnos = turnos
        self.sqls: list[str] = []

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        # Os 4 SQLs juntam com `conversas` (recorte de cliente real, sem o rig `@g.us`), então o
        # roteamento casa pela tabela-ALVO — `j.rastro_llm` separa os dois de julgamentos_turno.
        self.sqls.append(sql)
        assert "@g.us" in sql, f"SQL sem recorte de cliente real: {sql}"
        if "j.rastro_llm" in sql:
            return _Result([{"n": self.nao_contidos}])
        if "FROM barravips.mensagens" in sql:
            return _Result(self.mensagens)
        if "FROM barravips.escaladas" in sql:
            return _Result([{"n": self.aborts}])
        if "FROM barravips.julgamentos_turno" in sql:
            return _Result([{"n": self.turnos}])
        raise AssertionError(f"SQL inesperado: {sql}")


def _settings(**over: Any) -> Any:
    return get_settings().model_copy(update={"rollback_watch_ativo": True, **over})


def _capturar_alertas(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    alertas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        rollback_watch, "_alertar", lambda gatilho, detalhe: alertas.append((gatilho, detalhe))
    )
    return alertas


def _gauge(gatilho: str) -> float | None:
    return REGISTRY.get_sample_value("barra_rollback_gatilho", {"gatilho": gatilho})


# --- detector puro de acusação-padrão -----------------------------------------------------------


def test_acusacao_disclosure_casa_com_e_sem_acento() -> None:
    msgs = [
        {"conversa_id": "c1", "conteudo": "vc é robô?"},
        {"conversa_id": "c2", "conteudo": "voce e um bot"},
    ]
    assert contar_conversas_com_acusacao(msgs) == 2


def test_acusacao_prova_impossivel_casa() -> None:
    msgs = [{"conversa_id": "c1", "conteudo": "me manda um audio agora pra provar"}]
    assert contar_conversas_com_acusacao(msgs) == 1


def test_fala_normal_nao_e_acusacao() -> None:
    msgs = [
        {"conversa_id": "c1", "conteudo": "e ia te chamar mais tarde amor"},
        {"conversa_id": "c2", "conteudo": "quanto fica a hora?"},
        {"conversa_id": "c3", "conteudo": "me manda uma foto sua"},
    ]
    assert contar_conversas_com_acusacao(msgs) == 0


def test_conversa_conta_uma_vez() -> None:
    msgs = [
        {"conversa_id": "c1", "conteudo": "vc é robô?"},
        {"conversa_id": "c1", "conteudo": "fala a verdade, é bot?"},
    ]
    assert contar_conversas_com_acusacao(msgs) == 1


# --- gatilhos ------------------------------------------------------------------------------------


def test_flag_off_nao_vigia(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    total = asyncio.run(
        vigiar_gatilhos_rollback(FakeConn(nao_contidos=9), _settings(rollback_watch_ativo=False))
    )
    assert total == 0 and alertas == []


def test_semana_saudavel_zera_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(), _settings()))
    assert total == 0 and alertas == []
    assert _gauge("nao_contidos") == 0.0
    assert _gauge("acusacoes") == 0.0
    assert _gauge("taxa_gate") == 0.0


def test_nao_contidos_no_limiar_dispara(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(nao_contidos=2), _settings()))
    assert total == 1
    assert alertas[0][0] == "nao_contidos" and "2 incidentes" in alertas[0][1]
    assert _gauge("nao_contidos") == 1.0


def test_acusacoes_no_limiar_dispara(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    msgs = [{"conversa_id": f"c{i}", "conteudo": "vc é robô?"} for i in range(3)]
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(mensagens=msgs), _settings()))
    assert total == 1 and alertas[0][0] == "acusacoes"


def test_taxa_gate_acima_de_20pct_dispara(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    # 30 aborts / (70 julgados + 30 aborts) = 30% > 20%
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(aborts=30, turnos=70), _settings()))
    assert total == 1 and alertas[0][0] == "taxa_gate"
    assert "30%" in alertas[0][1]


def test_taxa_gate_sem_julgamento_nao_dispara(monkeypatch: pytest.MonkeyPatch) -> None:
    # Judge caído na janela: o universo vira só aborts e a taxa sobe a 100% — mediria a saúde do
    # judge, não a do gate. Só dispara com julgamento na janela.
    alertas = _capturar_alertas(monkeypatch)
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(aborts=30, turnos=0), _settings()))
    assert total == 0 and alertas == []
    assert _gauge("taxa_gate") == 0.0


def test_taxa_gate_alerta_carrega_julgados(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    asyncio.run(vigiar_gatilhos_rollback(FakeConn(aborts=30, turnos=70), _settings()))
    assert "70 julgados" in alertas[0][1]


def test_taxa_gate_com_pouco_trafego_nao_dispara(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3 aborts / 10 turnos = 30%, mas denominador < mínimo: semana fraca não é sinal de rollback
    alertas = _capturar_alertas(monkeypatch)
    total = asyncio.run(vigiar_gatilhos_rollback(FakeConn(aborts=3, turnos=7), _settings()))
    assert total == 0 and alertas == []


def test_multiplos_gatilhos_somam(monkeypatch: pytest.MonkeyPatch) -> None:
    alertas = _capturar_alertas(monkeypatch)
    msgs = [{"conversa_id": f"c{i}", "conteudo": "e bot?"} for i in range(4)]
    total = asyncio.run(
        vigiar_gatilhos_rollback(
            FakeConn(nao_contidos=5, mensagens=msgs, aborts=30, turnos=70), _settings()
        )
    )
    assert total == 3
    assert {a[0] for a in alertas} == {"nao_contidos", "acusacoes", "taxa_gate"}
