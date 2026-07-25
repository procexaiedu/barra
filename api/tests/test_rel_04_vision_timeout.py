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


async def test_audio_client_compartilha_o_cliente_do_vision(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    # Vision (Pix) e STT falam com o MESMO endpoint OpenRouter — um cliente so, entao a politica
    # de timeout/retry nao pode divergir entre eles (nenhum pendura o slot ate o job_timeout).
    monkeypatch.setattr(
        worker_settings,
        "get_settings",
        lambda: Settings(ambiente="teste", openrouter_api_key="sk-openrouter"),
    )
    ctx: dict[str, object] = {}
    await worker_settings.startup(ctx)

    assert ctx["audio_client"] is ctx["vision_client"]


async def test_sem_chave_openrouter_nao_ha_cliente_de_audio_nem_vision(
    monkeypatch: pytest.MonkeyPatch, _stub_recursos: None
) -> None:
    # Sem chave, o SDK rejeitaria api_key vazia no construtor: os dois ficam None e os jobs
    # degradam (Pix em_revisao, STT falha definitiva) em vez de derrubar o boot do worker.
    monkeypatch.setattr(
        worker_settings,
        "get_settings",
        lambda: Settings(ambiente="teste", openrouter_api_key=None),
    )
    ctx: dict[str, object] = {}
    await worker_settings.startup(ctx)

    assert ctx["vision_client"] is None
    assert ctx["audio_client"] is None
