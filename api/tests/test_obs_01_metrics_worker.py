import os
from unittest.mock import AsyncMock, MagicMock

from barra.settings import get_settings
from barra.workers.settings import startup


async def _roda_startup(monkeypatch: object, *, metrics_enabled: bool) -> MagicMock:
    get_settings.cache_clear()
    os.environ["METRICS_ENABLED"] = "true" if metrics_enabled else "false"
    get_settings.cache_clear()

    monkeypatch.setattr("barra.core.db.create_pool", AsyncMock(return_value=object()))
    fake_start = MagicMock()
    monkeypatch.setattr("prometheus_client.start_http_server", fake_start)

    await startup({})
    return fake_start


async def test_startup_expoe_metrics_quando_habilitado(monkeypatch: object) -> None:
    fake_start = await _roda_startup(monkeypatch, metrics_enabled=True)
    fake_start.assert_called_once_with(9091)


async def test_startup_nao_expoe_metrics_quando_desabilitado(monkeypatch: object) -> None:
    fake_start = await _roda_startup(monkeypatch, metrics_enabled=False)
    fake_start.assert_not_called()
