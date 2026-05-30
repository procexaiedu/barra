"""OBS-01: o startup do worker expoe as metricas do prometheus_client em :9091.

Guard por ambiente (settings.ambiente != "teste"): scrapeavel em producao/desenvolvimento,
silencioso na suite. Mocka os recursos pesados do startup (pool, minio, evolution, grafo,
preaquecimento) p/ isolar a decisao do guard sem tocar DB nem a API da Anthropic.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from barra.settings import Settings
from barra.workers import settings as worker_settings


@pytest.fixture
def _stub_recursos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_settings, "criar_pool", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(worker_settings, "criar_minio", MagicMock())
    monkeypatch.setattr(worker_settings, "EvolutionClient", MagicMock())
    monkeypatch.setattr(worker_settings, "build_graph", MagicMock())
    monkeypatch.setattr(worker_settings, "preaquecer_prefixo_global", AsyncMock())


async def _roda_startup(monkeypatch: pytest.MonkeyPatch, ambiente: str) -> MagicMock:
    monkeypatch.setattr(worker_settings, "get_settings", lambda: Settings(ambiente=ambiente))
    fake_start = MagicMock()
    monkeypatch.setattr("prometheus_client.start_http_server", fake_start)
    await worker_settings.startup({})
    return fake_start


async def test_startup_expoe_metrics_fora_de_teste(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    fake_start = await _roda_startup(monkeypatch, "producao")
    fake_start.assert_called_once_with(9091)


async def test_startup_nao_expoe_metrics_em_teste(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    fake_start = await _roda_startup(monkeypatch, "teste")
    fake_start.assert_not_called()
