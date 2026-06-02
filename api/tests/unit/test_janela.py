"""Testes puros de `core.janela` — período "tudo" ancorado e extração do piso."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from barra.core.janela import BRT, piso_operacao, resolver_janela


def _hoje() -> date:
    return datetime.now(BRT).date()


def test_tudo_ancora_no_piso_informado() -> None:
    """Com `piso_tudo`, a borda esquerda é o 1º registro real, não 2020."""
    piso = date(2024, 3, 15)
    janela = resolver_janela("tudo", None, None, piso_tudo=piso)
    assert janela.de == piso
    assert janela.ate == _hoje()


def test_tudo_sem_piso_cai_no_fallback_2020() -> None:
    """Banco vazio (piso None) mantém o fallback histórico de 2020-01-01."""
    janela = resolver_janela("tudo", None, None, piso_tudo=None)
    assert janela.de == date(2020, 1, 1)
    assert janela.ate == _hoje()


def test_presets_ignoram_piso() -> None:
    """`piso_tudo` só afeta "tudo"; presets normais não mudam."""
    hoje = _hoje()
    janela = resolver_janela("hoje", None, None, piso_tudo=date(2024, 1, 1))
    assert janela.de == hoje
    assert janela.ate == hoje


class _FakeCursor:
    def __init__(self, row: Any) -> None:
        self._row = row

    async def fetchone(self) -> Any:
        return self._row


class _FakeConn:
    """Conexão fake que devolve uma `dict_row` (como core/db.py)."""

    def __init__(self, row: Any) -> None:
        self._row = row

    async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        return _FakeCursor(self._row)


@pytest.mark.asyncio
async def test_piso_operacao_extrai_de_dict_row() -> None:
    """Regressão: conexões usam dict_row, então `row[0]` quebrava com KeyError.
    O piso deve sair do 1º valor do dict, convertido para data BRT."""
    conn = _FakeConn({"min": datetime(2026, 5, 1, 12, 0, tzinfo=UTC)})
    assert await piso_operacao(conn, "SELECT MIN(x)") == date(2026, 5, 1)


@pytest.mark.asyncio
async def test_piso_operacao_sem_registro_retorna_none() -> None:
    conn = _FakeConn(None)
    assert await piso_operacao(conn, "SELECT MIN(x)") is None
