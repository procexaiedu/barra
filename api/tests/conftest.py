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
    """Pula `needs_key` sem chave da Anthropic e `needs_db` sem TEST_DATABASE_URL.

    Os dois gates sao independentes: a suite padrao e a CI nao tocam a API nem o banco.
    """
    pular_key = not _tem_chave_anthropic()
    pular_db = not os.environ.get("TEST_DATABASE_URL")
    skip_key = pytest.mark.skip(reason="sem chave da Anthropic: pulando testes needs_key")
    skip_db = pytest.mark.skip(reason="sem TEST_DATABASE_URL: pulando testes needs_db")
    for item in items:
        if pular_key and "needs_key" in item.keywords:
            item.add_marker(skip_key)
        if pular_db and "needs_db" in item.keywords:
            item.add_marker(skip_db)
