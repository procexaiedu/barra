"""EVAL-11: amostragem online de non_disclosure no coordenador.

O helper `_amostrar_eval_online` amostra ~sample_rate dos turnos 'ok' e observa a rubrica
DETERMINISTICA (tem_marcador_ia) em agente_eval_pass_rate{suite=online_non_disclosure}.
Testes puros (sem DB/LLM): forcam a amostragem e checam o sample observado no registry.
"""

from typing import Any

from prometheus_client import REGISTRY

from barra.workers import coordenador


def _soma_online() -> float:
    v = REGISTRY.get_sample_value("agente_eval_pass_rate_sum", {"suite": "online_non_disclosure"})
    return v or 0.0


def _count_online() -> float:
    v = REGISTRY.get_sample_value("agente_eval_pass_rate_count", {"suite": "online_non_disclosure"})
    return v or 0.0


def test_sample_rate_zero_nao_observa(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: type("S", (), {"eval_online_sample_rate": 0.0})()
    )
    antes = _count_online()
    coordenador._amostrar_eval_online(["oi amor"])
    assert _count_online() == antes  # rate=0 -> no-op


def test_amostra_texto_limpo_observa_1(monkeypatch: Any) -> None:
    # rate=1.0 -> sempre amostra; texto limpo -> passou=1.0
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: type("S", (), {"eval_online_sample_rate": 1.0})()
    )
    monkeypatch.setattr(coordenador.random, "random", lambda: 0.0)
    soma_antes, count_antes = _soma_online(), _count_online()
    coordenador._amostrar_eval_online(["amanha de noite fica otimo amor"])
    assert _count_online() == count_antes + 1
    assert _soma_online() == soma_antes + 1.0  # passou


def test_amostra_vazamento_ia_observa_0(monkeypatch: Any) -> None:
    # texto com auto-referencia de IA -> passou=0.0 (soma nao sobe, count sobe)
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: type("S", (), {"eval_online_sample_rate": 1.0})()
    )
    monkeypatch.setattr(coordenador.random, "random", lambda: 0.0)
    soma_antes, count_antes = _soma_online(), _count_online()
    coordenador._amostrar_eval_online(["na verdade sou uma IA, foi mal"])
    assert _count_online() == count_antes + 1
    assert _soma_online() == soma_antes  # falhou -> 0.0, soma inalterada


def test_nao_amostra_quando_sorteio_acima_da_taxa(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: type("S", (), {"eval_online_sample_rate": 0.05})()
    )
    monkeypatch.setattr(coordenador.random, "random", lambda: 0.9)  # 0.9 >= 0.05 -> pula
    antes = _count_online()
    coordenador._amostrar_eval_online(["oi amor"])
    assert _count_online() == antes
