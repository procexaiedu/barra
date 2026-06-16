"""Configuracao compartilhada de testes pytest."""

import asyncio
import os
import sys
from collections.abc import Generator
from pathlib import Path

# psycopg async no Windows precisa do selector loop, senao PoolTimeout (memoria
# backend-windows-selector-loop); main.py e o worker aplicam o mesmo guard. Tem que
# rodar ANTES de qualquer event loop ser criado (asyncio.run dos testes / pytest-asyncio).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("AMBIENTE", "teste")
os.environ["DATABASE_URL"] = ""
os.environ["REDIS_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# `api/` no path -> o pacote de harness de evals (api/evals/) importa como `from evals.x import y`
# tanto na suite (gate de seguranca, Camada 1) quanto nos scripts de shadow (Camada 2).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _evolution_offline() -> Generator[None, None, None]:
    """Rede de seguranca (§0): nenhum teste pode POSTar no Evolution de prod. O `.env` carregado
    pelo pydantic-settings traz `evolution_base_url` real (`make test` roda com ele presente), e a
    Fase 2 passou a enviar confirmacoes/erros de comando de volta ao grupo. Zera o `base_url` do
    singleton de settings por padrao -> todo `enviar_texto` levanta antes da rede e os call sites
    best-effort viram no-op. Testes que exercem envio mockam respx ou setam um host fake explicito
    (que sobrepoe este default e e revertido pelo monkeypatch ao fim)."""
    try:
        from barra.settings import get_settings

        settings = get_settings()
    except Exception:
        yield
        return
    original = settings.evolution_base_url
    settings.evolution_base_url = ""
    try:
        yield
    finally:
        settings.evolution_base_url = original


def _tem_chave_anthropic() -> bool:
    """Chave da Anthropic disponivel? Checa o env var e, como fallback, settings (le `.env`),
    p/ `uv run pytest` com a chave so no `.env` nao pular os needs_key por engano (falso verde)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from barra.settings import get_settings

        return bool(get_settings().anthropic_api_key)
    except Exception:
        return False


def _optou_por_credito() -> bool:
    """Opt-in explicito p/ gastar credito Anthropic real nos `needs_key` (§0).

    So `make test-llm` e `make evals` setam `RUN_LLM_TESTS`. Ter a chave no `.env` NAO basta:
    sem este opt-in, nenhuma selecao ad-hoc de pytest (`-m needs_db`, um arquivo, um diretorio)
    dispara a API por engano. Memoria: needs_db_sozinho_gasta_credito."""
    return bool(os.environ.get("RUN_LLM_TESTS"))


def pytest_configure(config: pytest.Config) -> None:
    # --strict-markers esta ligado (pyproject addopts): registrar os markers aqui evita erro.
    config.addinivalue_line(
        "markers",
        "needs_key: requer chave da Anthropic (chama a API real); pulado quando ausente.",
    )
    config.addinivalue_line(
        "markers",
        "needs_db: requer Postgres real via TEST_DATABASE_URL; pulado quando ausente.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Pula `needs_key` e `needs_db` quando o pre-requisito de cada um nao esta presente.

    Os dois gates sao independentes: a suite padrao e a CI nao tocam a API nem o banco.

    `needs_key` exige DUAS condicoes p/ rodar: chave da Anthropic E o opt-in `RUN_LLM_TESTS`
    (so `make test-llm`/`make evals` setam). Ter a chave no `.env` NAO basta — assim nenhuma
    selecao ad-hoc (`-m needs_db`, um arquivo, um diretorio) gasta credito por engano (§0).
    """
    sem_chave = not _tem_chave_anthropic()
    sem_optin = not _optou_por_credito()
    pular_db = not os.environ.get("TEST_DATABASE_URL")
    skip_sem_chave = pytest.mark.skip(reason="sem chave da Anthropic: pulando testes needs_key")
    skip_sem_optin = pytest.mark.skip(
        reason="needs_key gasta credito Anthropic real (§0): defina RUN_LLM_TESTS=1 "
        "(make test-llm / make evals) para rodar de proposito"
    )
    skip_db = pytest.mark.skip(reason="sem TEST_DATABASE_URL: pulando testes needs_db")
    for item in items:
        if "needs_key" in item.keywords:
            if sem_chave:
                item.add_marker(skip_sem_chave)
            elif sem_optin:
                item.add_marker(skip_sem_optin)
        if pular_db and "needs_db" in item.keywords:
            item.add_marker(skip_db)
