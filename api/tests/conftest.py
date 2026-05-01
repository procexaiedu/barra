"""Configuracao compartilhada de testes pytest."""

import os
import sys
from pathlib import Path

os.environ.setdefault("AMBIENTE", "teste")
os.environ["DATABASE_URL"] = ""
os.environ["REDIS_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
