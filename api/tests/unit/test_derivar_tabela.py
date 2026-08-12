"""Derivação da tabela de preços a partir do preço de 1 hora (Fernando, 11/08/2026).

A tabela inteira de uma modelo sai de duas entradas (preço de 1h e mínimo de 1h) e é
MATERIALIZADA como linhas absolutas em `modelo_programas` — a IA lê a tabela pronta, nunca
multiplica. Este arquivo trava (a) os valores canônicos que o Fernando ditou, (b) o arredondamento
para cima ao múltiplo de 100, que é o que faz os números serem faláveis, e (c) a invariante
`preco_minimo <= preco`, que é CHECK no banco (`modelo_programas_preco_minimo_ate_preco`) e por
isso não pode depender de o cadastro ser "bem-comportado". Sem DB, sem crédito.
"""

from decimal import Decimal

import pytest

from barra.dominio.modelos.service import (
    LinhaDerivada,
    derivar_linha_da_tabela,
    teto_de_cem,
)

# A Catarina: 400 a hora, 300 de mínimo na hora.
_PRECO_1H = Decimal("400")
_MINIMO_1H = Decimal("300")


def _linha(horas: str) -> LinhaDerivada:
    return derivar_linha_da_tabela(Decimal(horas), preco_1h=_PRECO_1H, minimo_1h=_MINIMO_1H)


# --- os valores canônicos -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("horas", "preco", "minimo"),
    [
        ("1", "400", "300"),
        ("2", "800", "600"),
        ("3", "1000", "900"),
        ("4", "1300", "1200"),
        ("6", "2000", "2000"),
    ],
)
def test_tabela_canonica_da_catarina(horas: str, preco: str, minimo: str) -> None:
    """A tabela ditada pelo Fernando. Qualquer mexida no fator ou no arredondamento aparece aqui
    antes de aparecer no WhatsApp de um cliente."""
    linha = _linha(horas)
    assert linha.preco == Decimal(preco)
    assert linha.preco_minimo == Decimal(minimo)


def test_o_fator_so_entra_a_partir_de_3h() -> None:
    """Até 2h a linha é proporcional pura (400, 800); em 3h o fator de 0,8 entra e 1200 vira 960,
    que o teto devolve como 1000."""
    assert _linha("2").preco == Decimal("800")
    assert _linha("3").preco == Decimal("1000")


def test_o_desconto_efetivo_em_3h_e_menor_que_o_parametro() -> None:
    """O fator é 0,8 (20%), mas o teto em 100 devolve parte do desconto: 960 → 1000 deixa o
    desconto real em 16,7%. É intencional (número redondo de fala) — se um dia alguém "corrigir"
    para 960, é este teste que explica por que não."""
    proporcional = _PRECO_1H * Decimal("3")
    assert _linha("3").preco == Decimal("1000")
    assert proporcional - _linha("3").preco == Decimal("200")  # 16,7% e não 20%


def test_do_pernoite_em_diante_a_linha_nao_desconta() -> None:
    """`preco_minimo == preco` na semântica do ADR-0037: linha não descontável. O pernoite já é o
    desconto de volume; descontar de novo venderia a noite pelo preço de uma tarde."""
    for horas in ("6", "8", "12"):
        linha = _linha(horas)
        assert linha.preco_minimo == linha.preco


def test_abaixo_do_pernoite_o_minimo_e_proprio() -> None:
    """Abaixo de 6h o piso tem vida própria (300/h, sem o fator) e fica ABAIXO do preço — é o que
    dá à escada do ADR-0031 espaço para descontar."""
    for horas in ("1", "2", "3", "4"):
        linha = _linha(horas)
        assert linha.preco_minimo < linha.preco


# --- o teto em 100 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("960", "1000"),
        ("1920", "2000"),
        ("1280", "1300"),
        ("400", "400"),  # já múltiplo: não sobe um degrau à toa
        ("100", "100"),
        ("1", "100"),
        ("100.01", "200"),
        ("0", "0"),
    ],
)
def test_teto_de_cem_arredonda_sempre_para_cima(bruto: str, esperado: str) -> None:
    assert teto_de_cem(Decimal(bruto)) == Decimal(esperado)


def test_teto_de_cem_nunca_devolve_desconto_de_graca() -> None:
    """Arredondar "para o mais próximo" faria 1240 virar 1200 — R$40 de desconto que ninguém
    aprovou, em cima do preço de TABELA, antes de a escada descontar o que ela desconta."""
    assert teto_de_cem(Decimal("1240")) == Decimal("1300")


# --- a invariante do CHECK do banco ---------------------------------------------------------


@pytest.mark.parametrize("preco_1h", ["150", "250", "400", "500", "700", "1200"])
@pytest.mark.parametrize("minimo_1h", ["100", "150", "250", "300", "400", "700", "1200"])
@pytest.mark.parametrize("horas", ["1", "1.5", "2", "3", "4", "6", "8", "12", "24"])
def test_minimo_nunca_passa_do_preco(preco_1h: str, minimo_1h: str, horas: str) -> None:
    """CHECK `modelo_programas_preco_minimo_ate_preco`: a linha derivada tem que ser INSERÍVEL
    para qualquer cadastro plausível, inclusive mínimo folgado. Sem o clamp, minimo_1h acima de
    80% do preço de 1h estoura o CHECK na faixa de 3h a 5h, onde só o preço leva o fator."""
    if Decimal(minimo_1h) > Decimal(preco_1h):
        pytest.skip("mínimo acima do preço de 1h já é cadastro inválido na entrada")
    linha = derivar_linha_da_tabela(
        Decimal(horas), preco_1h=Decimal(preco_1h), minimo_1h=Decimal(minimo_1h)
    )
    assert linha.preco_minimo <= linha.preco
    assert linha.preco > 0


def test_minimo_folgado_e_clampado_no_preco_da_faixa_do_fator() -> None:
    """O caso concreto que o clamp existe para segurar: 400/350 em 3h daria preço 1000 e piso
    1100 — piso ACIMA da tabela, que o banco recusa e que faria a escada cotar mais caro no
    desconto."""
    linha = derivar_linha_da_tabela(Decimal("3"), preco_1h=Decimal("400"), minimo_1h=Decimal("350"))
    assert linha.preco == Decimal("1000")
    assert linha.preco_minimo == Decimal("1000")


# --- a derivação é parametrizada (não é a tabela da Catarina hardcoded) ----------------------


def test_outro_preco_de_hora_produz_outra_tabela_coerente() -> None:
    """Modelo de 500/h com mínimo de 400/h: mesma forma, outros números. Se algum canônico da
    Catarina tivesse vazado como constante, este teste quebraria."""

    def linha(horas: str) -> LinhaDerivada:
        return derivar_linha_da_tabela(
            Decimal(horas), preco_1h=Decimal("500"), minimo_1h=Decimal("400")
        )

    assert linha("1") == LinhaDerivada(preco=Decimal("500"), preco_minimo=Decimal("400"))
    assert linha("2") == LinhaDerivada(preco=Decimal("1000"), preco_minimo=Decimal("800"))
    # 500 x 3 x 0,8 = 1200 (já redondo); piso 400 x 3 = 1200 → clampado no preço.
    assert linha("3") == LinhaDerivada(preco=Decimal("1200"), preco_minimo=Decimal("1200"))
    # 500 x 6 x 0,8 = 2400: pernoite, piso == preço.
    assert linha("6") == LinhaDerivada(preco=Decimal("2400"), preco_minimo=Decimal("2400"))


def test_duracao_fracionaria_e_recusada_em_vez_de_derivada() -> None:
    """Fail-closed (Fernando, 11/08/2026): os 30min da Catarina são 250/250 em prod, piso
    COMERCIAL cravado à mão. A fórmula devolveria 200/150 e rebaixaria o piso dela em 40% —
    meia hora não custa metade de uma hora porque o custo fixo do encontro (deslocamento,
    preparo, quarto) não se divide. Rodar o derivador sobre a tabela inteira dela tem que
    estourar, não sobrescrever o cadastro em silêncio."""
    with pytest.raises(ValueError, match="À MÃO"):
        _linha("0.5")


def test_uma_hora_cheia_continua_derivando() -> None:
    """A fronteira é fechada em 1h: o corte das fracionárias não pode ter levado junto a linha
    que é a própria ENTRADA da derivação."""
    assert _linha("1") == LinhaDerivada(preco=Decimal("400"), preco_minimo=Decimal("300"))


def test_duracao_nao_positiva_e_recusada() -> None:
    """Sem o guard, 0h derivaria uma linha de R$0 — pacote de graça cadastrado em silêncio. Cai
    no mesmo piso de 1h das fracionárias."""
    for horas in ("0", "-1"):
        with pytest.raises(ValueError, match="não é derivável"):
            derivar_linha_da_tabela(Decimal(horas), preco_1h=_PRECO_1H, minimo_1h=_MINIMO_1H)
