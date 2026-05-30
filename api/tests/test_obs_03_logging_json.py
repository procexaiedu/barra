"""OBS-03 — logging estruturado JSON com turno_id/atendimento_id.

Verifica que:
  - `setup_logging` configura structlog/stdlib p/ emitir JSON em stdout no nível log_level,
    e que ids vinculados via `structlog.contextvars` (turno_id/atendimento_id) saem como
    campos do JSON — inclusive em logs do stdlib (o caso do coordenador);
  - o setup é chamado nos DOIS entrypoints de produção: build_app (API) e startup (worker).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog

from barra.core.logging import setup_logging


def _settings_stub(log_level: str = "INFO") -> Any:
    return SimpleNamespace(
        log_level=log_level,
        ambiente="teste",
        sentry_dsn=None,
        langchain_tracing_v2=False,
        openrouter_api_key=None,
        openai_api_key=None,
        preaquecer_cache_no_startup=False,
        database_url="postgresql://x",
    )


@pytest.fixture
def _logging_isolado() -> Iterator[None]:
    """Salva/restaura o root logger e limpa os contextvars (setup_logging muta global)."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        root.handlers, root.level = handlers, level
        structlog.contextvars.clear_contextvars()


def test_setup_logging_emite_json_com_ids(
    _logging_isolado: None, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_logging(_settings_stub())
    structlog.contextvars.bind_contextvars(turno_id="turno-123", atendimento_id="atend-456")

    # stdlib logger — o caminho do coordenador (logging.getLogger(__name__)).
    logging.getLogger("barra.test").info("turno_processado")

    linha = capsys.readouterr().out.strip()
    registro = json.loads(linha)  # falha se não for JSON
    assert registro["event"] == "turno_processado"
    assert registro["turno_id"] == "turno-123"
    assert registro["atendimento_id"] == "atend-456"
    assert registro["level"] == "info"


def test_setup_logging_respeita_log_level(
    _logging_isolado: None, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_logging(_settings_stub(log_level="WARNING"))
    logging.getLogger("barra.test").info("abaixo_do_nivel")
    assert capsys.readouterr().out.strip() == ""


def test_setup_logging_encaminha_arq_pelo_json(
    _logging_isolado: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """O handler de texto que a CLI do arq instala no logger 'arq' é removido: os logs do
    worker saem só uma vez, em JSON, pelo root — sem duplicar em texto plano."""
    arq_logger = logging.getLogger("arq")
    handlers_orig = arq_logger.handlers[:]
    arq_logger.addHandler(logging.StreamHandler())  # simula default_log_config do arq
    try:
        setup_logging(_settings_stub())
        assert arq_logger.handlers == []  # handler de texto do arq removido

        arq_logger.info("job_complete")
        linhas = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(linhas) == 1  # emissão única
        assert json.loads(linhas[0])["event"] == "job_complete"
    finally:
        arq_logger.handlers = handlers_orig


def test_build_app_chama_setup_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    import barra.main as main

    chamado: dict[str, Any] = {}
    monkeypatch.setattr(main, "setup_logging", lambda s: chamado.setdefault("ok", s))

    main.build_app()

    assert "ok" in chamado


@pytest.mark.anyio
async def test_worker_startup_chama_setup_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import barra.workers.settings as ws

    async def _async_ret(*_a: Any, **_k: Any) -> Any:
        return MagicMock()

    monkeypatch.setattr(ws, "get_settings", _settings_stub)
    monkeypatch.setattr(ws, "init_sentry", lambda s: None)
    monkeypatch.setattr(ws, "setup_tracing", lambda s: None)
    monkeypatch.setattr(ws, "criar_pool", _async_ret)
    monkeypatch.setattr(ws, "criar_minio", lambda s: MagicMock())
    monkeypatch.setattr(ws, "EvolutionClient", lambda s: MagicMock())
    monkeypatch.setattr(ws, "build_graph", lambda: MagicMock())

    chamado: dict[str, Any] = {}
    monkeypatch.setattr(ws, "setup_logging", lambda s: chamado.setdefault("ok", s))

    await ws.startup({})

    assert "ok" in chamado
