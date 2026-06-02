"""Testes puros de `core.janela.resolver_janela` — foco no período "tudo" ancorado."""

from datetime import date, datetime

from barra.core.janela import BRT, resolver_janela


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
