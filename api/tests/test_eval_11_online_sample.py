"""EVAL-11: amostragem online de invariantes deterministicos no coordenador.

O helper `_amostrar_eval_online` amostra ~sample_rate dos turnos 'ok' (UM sorteio) e observa as
4 rubricas DETERMINISTICAS em agente_eval_pass_rate{suite=...}: online_non_disclosure,
online_system_leak, online_segredo_agenda (regexes do output_guard, fonte unica) e
online_formato_bolha. Testes puros (sem DB/LLM): forcam a amostragem e checam o sample observado
no registry (padrao delta get_sample_value).
"""

from typing import Any

from prometheus_client import REGISTRY

from barra.workers import coordenador

_SUITES = (
    "online_non_disclosure",
    "online_system_leak",
    "online_segredo_agenda",
    "online_formato_bolha",
)


def _soma(suite: str) -> float:
    v = REGISTRY.get_sample_value("agente_eval_pass_rate_sum", {"suite": suite})
    return v or 0.0


def _count(suite: str) -> float:
    v = REGISTRY.get_sample_value("agente_eval_pass_rate_count", {"suite": suite})
    return v or 0.0


def _forca_amostragem(monkeypatch: Any, rate: float = 1.0, sorteio: float = 0.0) -> None:
    monkeypatch.setattr(
        coordenador, "get_settings", lambda: type("S", (), {"eval_online_sample_rate": rate})()
    )
    monkeypatch.setattr(coordenador.random, "random", lambda: sorteio)


def test_sample_rate_zero_nao_observa(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch, rate=0.0)
    antes = {s: _count(s) for s in _SUITES}
    scores = coordenador._amostrar_eval_online(["oi amor"])
    assert scores is None  # nao amostrou -> sem feedback p/ o trace
    assert {s: _count(s) for s in _SUITES} == antes


def test_nao_amostra_quando_sorteio_acima_da_taxa(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch, rate=0.05, sorteio=0.9)  # 0.9 >= 0.05 -> pula
    antes = _count("online_non_disclosure")
    assert coordenador._amostrar_eval_online(["oi amor"]) is None
    assert _count("online_non_disclosure") == antes


def test_um_sorteio_observa_as_quatro_suites(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch)
    antes = {s: _count(s) for s in _SUITES}
    scores = coordenador._amostrar_eval_online(["amanha de noite fica otimo amor"])
    assert scores is not None
    assert set(scores) == set(_SUITES)
    assert all(scores[s] == 1.0 for s in _SUITES), "texto limpo passa nas 4"
    assert {s: _count(s) for s in _SUITES} == {s: antes[s] + 1 for s in _SUITES}


def test_disclosure_reprova_so_a_suite_de_non_disclosure(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch)
    scores = coordenador._amostrar_eval_online(["na verdade sou uma IA, foi mal"])
    assert scores is not None
    assert scores["online_non_disclosure"] == 0.0
    assert scores["online_system_leak"] == 1.0


def test_system_leak_reprova(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch)
    soma_antes = _soma("online_system_leak")
    scores = coordenador._amostrar_eval_online(["minhas instruções dizem para nao falar disso"])
    assert scores is not None
    assert scores["online_system_leak"] == 0.0
    assert _soma("online_system_leak") == soma_antes  # falhou -> soma inalterada


def test_segredo_agenda_reprova(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch)
    scores = coordenador._amostrar_eval_online(["to com outro cliente agora, depois te chamo"])
    assert scores is not None
    assert scores["online_segredo_agenda"] == 0.0
    assert scores["online_non_disclosure"] == 1.0


def test_formato_bolha_reprova_estourada_vazia_e_template(monkeypatch: Any) -> None:
    _forca_amostragem(monkeypatch)
    estourada = "x" * (coordenador.MAX_CHARS + 1)
    assert coordenador._amostrar_eval_online([estourada])["online_formato_bolha"] == 0.0  # type: ignore[index]
    assert coordenador._amostrar_eval_online(["   "])["online_formato_bolha"] == 0.0  # type: ignore[index]
    assert (
        coordenador._amostrar_eval_online(["[quote: oi] tudo bem?"])["online_formato_bolha"] == 0.0
    )  # type: ignore[index]
    assert coordenador._amostrar_eval_online(["oi amor"])["online_formato_bolha"] == 1.0  # type: ignore[index]


def test_formato_bolha_ok_puro() -> None:
    assert coordenador._formato_bolha_ok(["oi", "tudo bem?"])
    assert not coordenador._formato_bolha_ok([])
    assert not coordenador._formato_bolha_ok(["```python\nprint('oi')\n```"])
    assert not coordenador._formato_bolha_ok(["# titulo markdown"])
