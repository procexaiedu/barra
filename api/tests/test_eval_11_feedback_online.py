"""EVAL-11 (online → trace): `registrar_feedback_online` anexa o veredito determinístico ao run
do LangSmith.

Best-effort e não-PII: só key + score. Testes puros (sem rede) — substituem o Client global por
um fake e checam que o feedback sai só com client + run_id, e que erro do Client é engolido.
"""

from typing import Any

import pytest

from barra.core import tracing


class _FakeClient:
    """Captura as chamadas de create_feedback sem tocar a rede."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.erro: Exception | None = None

    def create_feedback(self, run_id: Any, *, key: str, score: float) -> None:
        if self.erro is not None:
            raise self.erro
        self.chamadas.append({"run_id": run_id, "key": key, "score": score})


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", None, raising=False)


def test_sem_client_global_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    # tracing desligado (_CLIENT None) -> no-op silencioso, sem erro.
    tracing.registrar_feedback_online("run-1", "online_non_disclosure", 1.0)  # não levanta


def test_sem_run_id_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", fake, raising=False)
    tracing.registrar_feedback_online(None, "online_non_disclosure", 1.0)
    assert fake.chamadas == []


def test_emite_feedback_com_client_e_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", fake, raising=False)
    tracing.registrar_feedback_online("run-42", "online_non_disclosure", 0.0)
    assert fake.chamadas == [{"run_id": "run-42", "key": "online_non_disclosure", "score": 0.0}]


def test_erro_do_client_e_engolido(monkeypatch: pytest.MonkeyPatch) -> None:
    # best-effort: telemetria nunca derruba o turno.
    fake = _FakeClient()
    fake.erro = RuntimeError("langsmith fora do ar")
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", fake, raising=False)
    tracing.registrar_feedback_online("run-7", "online_non_disclosure", 1.0)  # não propaga
