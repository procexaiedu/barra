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


# --- por-pessoa (casal/menage): dobra o pacote, não o preço-hora (ADR-0035) ------------------


def test_por_pessoa_dobra_o_pacote_uma_hora():
    # 2 pessoas -> extra = pacote INTEIRO. Em 1h o pacote == preço-hora, então coincide com o ato.
    assert calcular_preco_extra_fetiche(
        Decimal("400"), Decimal("1"), cobra_por_pessoa=True
    ) == Decimal("400")


def test_por_pessoa_dobra_pacote_multi_hora():
    # 3h a R$300 (preço-hora R$100): o ato somaria +100; por-pessoa dobra -> +300 (o pacote todo).
    assert calcular_preco_extra_fetiche(
        Decimal("300"), Decimal("3"), cobra_por_pessoa=True
    ) == Decimal("300")


def test_por_pessoa_e_ato_divergem_de_duas_horas_em_diante():
    ato = calcular_preco_extra_fetiche(Decimal("800"), Decimal("2"))
    por_pessoa = calcular_preco_extra_fetiche(Decimal("800"), Decimal("2"), cobra_por_pessoa=True)
    assert ato == Decimal("400")  # preço-hora
    assert por_pessoa == Decimal("800")  # pacote inteiro (dobra)


def test_ato_default_inalterado():
    # Retrocompat: sem o kwarg, o regime é o de sempre (preço-hora).
    assert calcular_preco_extra_fetiche(Decimal("3600"), Decimal("12")) == Decimal("300")
