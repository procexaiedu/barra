"""Configuracao compartilhada de testes pytest."""

import asyncio
import os
import sys
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
