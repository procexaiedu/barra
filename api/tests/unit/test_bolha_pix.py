"""Bug F (teste E2E ao vivo 2026-06-05): o sistema anexa chave/titular/valor do Pix de
deslocamento após o texto da IA — a solicitação determinística de Pix (registrar_extracao)
mantém a chave fora do LLM.
"""

from decimal import Decimal

import pytest

from barra.workers.coordenador import _eh_pre_anuncio_pix, _formatar_bolha_pix


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


@pytest.mark.parametrize(
    "bolha",
    [
        "mandando por aqui 🥰",
        "mandando por aqui",
        "segue 🥰",
        "ta aqui amor",
        "já te mando",
        "aqui vai",
    ],
)
def test_pre_anuncio_pix_descartado(bolha: str) -> None:
    """E2E 2026-06-14: a IA adicionava uma bolha-ponte de pré-anúncio ("mandando por aqui 🥰")
    antes da chave, redundante com a bolha que o coordenador anexa. A guarda a descarta."""
    assert _eh_pre_anuncio_pix(bolha)


@pytest.mark.parametrize(
    "bolha",
    [
        "pra eu já chamar o uber e sair na hora certa, me manda o pixzinho do deslocamento de R$100",
        "me manda o pixzinho do deslocamento",
        "ótimo amor 😊",
        "então tá combinado, meio-dia eu vou aí",
        "",
    ],
)
def test_pre_anuncio_pix_preserva_enquadramento(bolha: str) -> None:
    """O enquadramento do pedido (e qualquer bolha de conteúdo) NÃO é ponte: deve sobreviver."""
    assert not _eh_pre_anuncio_pix(bolha)
