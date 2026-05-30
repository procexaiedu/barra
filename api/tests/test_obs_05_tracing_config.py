"""OBS-05 — guarda da fonte ÚNICA da config de tracing.

Investigação (2026-05-30): SEC-10 (PR #53, commit beddaed) já consolidou a config de
tracing em `settings.py` numa única fonte de verdade. Não há campo duplicado nem morto
para remover: os três campos `langchain_*` existem e cada um é lido exatamente uma vez em
`barra.core.tracing`. Estes testes pinam esse invariante para impedir regressão (reintrodução
de um campo de tracing duplicado/morto) e cobrem o que o teste do SEC-10 não cobre:
`langchain_project` e `langchain_api_key` como fonte consumida.
"""

import inspect
import os
from typing import ClassVar

import pytest

from barra.core import tracing
from barra.settings import Settings

# Os campos de config de tracing que devem existir — e SÓ eles. Qualquer campo extra cujo nome
# remeta a tracing (langchain/langsmith/trace) indica duplicata ou fonte morta reintroduzida.
_CAMPOS_TRACING = frozenset({"langchain_tracing_v2", "langchain_api_key", "langchain_project"})


class _FakeClient:
    """Captura os kwargs do Client (api_key) sem tocar a rede."""

    instancias: ClassVar[list["_FakeClient"]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        _FakeClient.instancias.append(self)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.instancias = []
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", None, raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "")


def test_setup_tracing_consome_project_e_api_key_de_settings() -> None:
    """A única fonte de `project`/`api_key` é o campo de settings — não há mirror duplicado."""
    settings = Settings(
        langchain_tracing_v2=True, langchain_api_key="key-abc", langchain_project="proj-xyz"
    )

    client = tracing.setup_tracing(settings)

    assert client is _FakeClient.instancias[-1]
    assert client.kwargs["api_key"] == "key-abc"
    assert os.environ["LANGCHAIN_PROJECT"] == "proj-xyz"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_settings_expoe_apenas_os_campos_de_tracing_consolidados() -> None:
    """Não existe campo de tracing duplicado/morto além dos três consolidados pelo SEC-10."""
    relacionados = {
        nome
        for nome in Settings.model_fields
        if any(t in nome for t in ("langchain", "langsmith", "trace"))
    }
    assert relacionados == _CAMPOS_TRACING


def test_cada_campo_de_tracing_e_lido_em_core_tracing() -> None:
    """Nenhum dos campos é morto: cada um é consumido em barra.core.tracing."""
    fonte = inspect.getsource(tracing)
    for campo in _CAMPOS_TRACING:
        assert f"settings.{campo}" in fonte, f"campo de tracing nao-lido (morto?): {campo}"
