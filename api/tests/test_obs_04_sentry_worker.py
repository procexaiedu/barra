"""OBS-04: Sentry sobe no worker e a exceção do turno carrega a tag turno_id.

- `init_sentry` é chamado no startup do worker ARQ (o agente roda lá).
- Sem DSN o boot não quebra (no-op).
- `_tag_turno_id` (before_send) promove o `turno_id` do frame do turno a tag do evento —
  é o caminho que faz a exceção do pipeline da IA aparecer no Sentry filtrável por turno_id.

Sem DSN/rede: sentry_sdk é mockado; nada é enviado.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from barra.core import tracing
from barra.settings import Settings
from barra.workers import settings as worker_settings


@pytest.fixture
def _stub_recursos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_settings, "criar_pool", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(worker_settings, "criar_minio", MagicMock())
    monkeypatch.setattr(worker_settings, "EvolutionClient", MagicMock())
    monkeypatch.setattr(worker_settings, "build_graph", MagicMock())
    monkeypatch.setattr(worker_settings, "preaquecer_prefixo_global", AsyncMock())
    monkeypatch.setattr(worker_settings, "setup_langfuse", MagicMock())
    monkeypatch.setattr("prometheus_client.start_http_server", MagicMock())


async def test_startup_do_worker_chama_init_sentry(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    monkeypatch.setattr(worker_settings, "get_settings", lambda: Settings(ambiente="teste"))
    fake_init = MagicMock()
    monkeypatch.setattr(worker_settings, "init_sentry", fake_init)
    await worker_settings.startup({})
    fake_init.assert_called_once()


def test_init_sentry_no_op_sem_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sentry = MagicMock()
    monkeypatch.setattr(tracing, "sentry_sdk", fake_sentry)
    assert tracing.init_sentry(Settings(sentry_dsn=None)) is False
    fake_sentry.init.assert_not_called()


def test_init_sentry_registra_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sentry = MagicMock()
    monkeypatch.setattr(tracing, "sentry_sdk", fake_sentry)
    assert tracing.init_sentry(Settings(sentry_dsn="https://x@example/1")) is True
    _, kwargs = fake_sentry.init.call_args
    assert kwargs["before_send"] is tracing._tag_turno_id


def test_excecao_do_turno_recebe_tag_turno_id() -> None:
    """Reproduz o caminho do turno: um frame com `turno_id` local que levanta."""

    def processar_turno_fake() -> None:
        turno_id = "turno-abc-123"  # noqa: F841 — lido do frame pelo before_send
        raise RuntimeError("graph_erro")

    try:
        processar_turno_fake()
    except RuntimeError as exc:
        exc_info = (type(exc), exc, exc.__traceback__)

    event = tracing._tag_turno_id({}, {"exc_info": exc_info})
    assert event["tags"]["turno_id"] == "turno-abc-123"


def test_before_send_sem_exc_info_nao_quebra() -> None:
    event = tracing._tag_turno_id({}, {})
    assert "tags" not in event
