"""REL-04: o vision_client (validar_pix) sobe com timeout/retries finitos.

Sem timeout, um request de vision do Pix pendurado segura o slot do worker ate o
`job_timeout=400s`. O construtor tem de espelhar o `openai_client` (timeout 60s + 3 retries),
para que o SDK aborte sozinho bem antes do teto do ARQ.
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
    monkeypatch.setattr(worker_settings, "setup_langfuse", MagicMock())
    monkeypatch.setattr(worker_settings, "init_sentry", MagicMock())


async def test_vision_client_tem_timeout_e_retries(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    monkeypatch.setattr(
        worker_settings,
        "get_settings",
        lambda: Settings(ambiente="teste", openrouter_api_key="sk-test"),
    )
    ctx: dict[str, object] = {}
    await worker_settings.startup(ctx)

    vision_client = ctx["vision_client"]
    assert vision_client is not None
    assert vision_client.timeout == 60.0  # type: ignore[attr-defined]
    assert vision_client.max_retries == 3  # type: ignore[attr-defined]


async def test_vision_client_espelha_openai_client(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    # Os dois clientes do worker (vision via OpenRouter, STT via OpenAI) devem ter a mesma
    # politica de timeout/retry — nenhum pode pendurar o slot do worker ate o job_timeout.
    monkeypatch.setattr(
        worker_settings,
        "get_settings",
        lambda: Settings(ambiente="teste", openrouter_api_key="sk-vision", openai_api_key="sk-stt"),
    )
    ctx: dict[str, object] = {}
    await worker_settings.startup(ctx)

    vision_client = ctx["vision_client"]
    openai_client = ctx["openai_client"]
    assert vision_client.timeout == openai_client.timeout  # type: ignore[attr-defined]
    assert vision_client.max_retries == openai_client.max_retries  # type: ignore[attr-defined]
