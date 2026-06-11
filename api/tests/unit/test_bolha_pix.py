"""Bug F (teste E2E ao vivo 2026-06-05): o sistema anexa chave/titular/valor do Pix de
deslocamento após o texto da IA — a tool `pedir_pix_deslocamento` mantém a chave fora do LLM.
"""

from decimal import Decimal

from barra.workers.coordenador import _formatar_bolha_pix


def test_bolha_pix_com_titular() -> None:
    bolha = _formatar_bolha_pix("12992609133", "Lucia Teste", "100")
    assert "chave pix: 12992609133" in bolha
    assert "em nome de Lucia Teste" in bolha
    assert "R$100" in bolha


def test_bolha_pix_sem_titular() -> None:
    bolha = _formatar_bolha_pix("chave@exemplo.com", None, 100)
    assert "em nome de" not in bolha
    assert "chave pix: chave@exemplo.com" in bolha
    assert "R$100" in bolha


def test_bolha_pix_valor_decimal_da_setting() -> None:
    """Regressão E2E 2026-06-10 (commit 2934443): `settings.pix_deslocamento_valor` é um
    `Decimal` e o JSONB de idempotência o devolve como string `"100.00"`. `_brl` fazia
    `int("100.00")` -> ValueError, descartando o turno inteiro (cliente fica mudo no Pix)."""
    assert "R$100" in _formatar_bolha_pix("chave@exemplo.com", None, Decimal("100.00"))
    assert "R$100" in _formatar_bolha_pix("chave@exemplo.com", None, "100.00")
