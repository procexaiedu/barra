"""ADR-0030 — preço do fetiche pago calculado a partir do programa vendido.

Unit puro (sem DB): `calcular_preco_extra_fetiche` é preço-hora efetivo do pacote
(preco_tabela / duracao_horas), somado uma vez por fetiche pago. Multi-hora usa esse
preço-hora, não uma duração-base de 1h.
"""

from decimal import Decimal

from barra.dominio.atendimentos.service import calcular_preco_extra_fetiche


def test_uma_hora_preco_simples():
    assert calcular_preco_extra_fetiche(Decimal("400"), Decimal("1")) == Decimal("400")


def test_multiplas_horas_pernoite_like():
    # Pernoite (12h) a R$3.600 -> preço-hora R$300, não o preço cheio do pacote.
    assert calcular_preco_extra_fetiche(Decimal("3600"), Decimal("12")) == Decimal("300")


def test_preco_nao_multiplo_exato():
    resultado = calcular_preco_extra_fetiche(Decimal("500"), Decimal("3"))
    assert resultado == Decimal("500") / Decimal("3")
    assert round(resultado, 2) == Decimal("166.67")
