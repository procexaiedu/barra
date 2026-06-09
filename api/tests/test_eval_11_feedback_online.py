"""EVAL-11 (online → trace): `registrar_feedback_online` anexa o veredito determinístico como
score no trace do Langfuse (ADR 0019).

Best-effort e não-PII: só name + score. Testes puros (sem rede) — substituem o client global do
Langfuse por um fake e checam que o score só sai com o handler ligado + trace_id, e que erro do
client é engolido.
"""

from typing import Any

import langfuse
import pytest

from barra.core import tracing


class _FakeClient:
    """Captura as chamadas de create_score sem tocar a rede."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.erro: Exception | None = None

    def create_score(self, *, name: str, value: float, trace_id: str | None = None) -> None:
        if self.erro is not None:
            raise self.erro
        self.chamadas.append({"trace_id": trace_id, "name": name, "value": value})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    cliente = _FakeClient()
    monkeypatch.setattr(langfuse, "get_client", lambda: cliente)
    return cliente


@pytest.fixture(autouse=True)
def _handler_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    # default: simula tracing LIGADO (handler global não-None); o teste de "desligado" sobrescreve.
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", object(), raising=False)


def test_sem_handler_global_no_op(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    # tracing desligado (_LANGFUSE_HANDLER None) -> no-op silencioso, mesmo com trace_id.
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None, raising=False)
    tracing.registrar_feedback_online("trace-1", "online_non_disclosure", 1.0)  # não levanta
    assert fake.chamadas == []


def test_sem_trace_id_no_op(fake: _FakeClient) -> None:
    tracing.registrar_feedback_online(None, "online_non_disclosure", 1.0)
    assert fake.chamadas == []


def test_emite_score_com_handler_e_trace_id(fake: _FakeClient) -> None:
    tracing.registrar_feedback_online("trace-42", "online_non_disclosure", 0.0)
    assert fake.chamadas == [
        {"trace_id": "trace-42", "name": "online_non_disclosure", "value": 0.0}
    ]


def test_erro_do_client_e_engolido(fake: _FakeClient) -> None:
    # best-effort: telemetria nunca derruba o turno.
    fake.erro = RuntimeError("langfuse fora do ar")
    tracing.registrar_feedback_online("trace-7", "online_non_disclosure", 1.0)  # não propaga
