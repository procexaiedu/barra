"""SEC-10 — o tracing LangSmith só ativa com PII mascarada (hard gate)."""

import logging
from typing import ClassVar

import pytest

from barra.core import tracing
from barra.settings import Settings


class _FakeClient:
    """Captura os kwargs passados ao Client (anonymizer/hide_metadata) sem tocar a rede."""

    instancias: ClassVar[list["_FakeClient"]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        _FakeClient.instancias.append(self)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.instancias = []
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    # isola o cliente global e os env vars que setup_tracing mexe
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", None, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "")


def _settings(tracing_on: bool) -> Settings:
    return Settings(langchain_tracing_v2=tracing_on, langchain_api_key="k", langchain_project="p")


def test_payload_com_pix_e_endereco_sai_mascarado() -> None:
    client = tracing.setup_tracing(_settings(tracing_on=True))
    assert client is _FakeClient.instancias[-1]

    anonymizer = client.kwargs["anonymizer"]
    payload = {
        "chave_pix": "12345678900",
        "titular": "Ana Maria",
        "endereco": "Rua das Flores 123, Sao Paulo",
        "remoteJid": "5511999998888@s.whatsapp.net",
        "valor": "100.00",
    }
    mascarado = anonymizer(payload)

    assert mascarado["chave_pix"] == tracing._MASCARA
    assert mascarado["titular"] == tracing._MASCARA
    assert mascarado["endereco"] == tracing._MASCARA
    assert mascarado["remoteJid"] == tracing._MASCARA
    # campo não-PII sobrevive (o trace continua útil)
    assert mascarado["valor"] == "100.00"
    # o mesmo anonymizer cobre metadata
    assert client.kwargs["hide_metadata"] is anonymizer


def test_tracing_desligado_nao_constroi_client() -> None:
    client = tracing.setup_tracing(_settings(tracing_on=False))
    assert client is None
    assert _FakeClient.instancias == []


def test_hard_gate_sem_anonymizer_forca_false_e_avisa(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _explode(_replacer: object) -> object:
        raise RuntimeError("anonymizer indisponível")

    monkeypatch.setattr(tracing, "create_anonymizer", _explode)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    with caplog.at_level(logging.WARNING):
        client = tracing.setup_tracing(_settings(tracing_on=True))

    assert client is None
    assert _FakeClient.instancias == []  # nunca subiu tracing cru
    import os

    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert any("anonymizer" in r.message for r in caplog.records)
