"""O razao da modelo: saldo com sinal, sem banco (ADR-0045, ADR-0046 §6, ADR-0047, ticket 02).

Funcao pura, entao teste puro: nada aqui toca DB, repo ou porta. Os quatro cenarios de sinal do
export real de 12/08/2026 ficam lado a lado de proposito — e a comparacao entre eles que prova a
regra, nao cada um sozinho.
"""

from decimal import Decimal
from uuid import uuid4

from barra.dominio.grupo_financeiro.razao import (
    Bolso,
    CobrancaNoRazao,
    DeslocamentoNoRazao,
    TransferenciaNoRazao,
    ValeNoRazao,
    VendaNoRazao,
    apurar,
    bolso_efetivo,
)

MEIO = Decimal("50")  # percentual_repasse_snapshot: 50%, default de cadastro (ADR-0045 §3)


def _vendas_do_export(bolso: Bolso = "dela") -> list[VendaNoRazao]:
    """As duas vendas reais de 12/08: "600 pix" + "600 pix", 50% de repasse."""
    return [
        VendaNoRazao(
            valor=Decimal("600.00"),
            bolso=bolso,
            percentual_repasse_snapshot=MEIO,
        )
        for _ in range(2)
    ]


# --- os quatro cenarios de sinal (ADR-0045 §1) ----------------------------------------------


def test_transferiu_tudo_a_casa_deve_600() -> None:
    """Caso real do export: 600 + 600 no bolso dela, comprovante de R$ 1.200,00 -> +600."""
    razao = apurar([*_vendas_do_export(), TransferenciaNoRazao(valor=Decimal("1200.00"))])

    assert razao.saldo == Decimal("600.00")
    assert razao.debitos == Decimal("1200.00")
    assert razao.creditos == Decimal("1800.00")
    assert razao.a_casa_deve == Decimal("600.00")
    assert razao.ela_deve == Decimal("0.00")


def test_nao_transferiu_ela_deve_600() -> None:
    """Mesmas vendas, sem comprovante: ela esta com o bruto na mao -> -600."""
    razao = apurar(_vendas_do_export())

    assert razao.saldo == Decimal("-600.00")
    assert razao.ela_deve == Decimal("600.00")
    assert razao.a_casa_deve == Decimal("0.00")


def test_tudo_dinheiro_ela_deve_600() -> None:
    """Especie entra no razao como qualquer venda de bolso dela (ADR-0045 §2) -> -600.

    O espelho do cenario anterior: e o MESMO numero, e e disso que se trata — deixar o cash fora
    faria a casa "dever" o liquido inteiro a quem ja esta com o bruto.
    """
    razao = apurar(_vendas_do_export(bolso="dela"))

    assert razao.saldo == Decimal("-600.00")


def test_pix_da_empresa_a_casa_deve_600() -> None:
    """Dinheiro na conta da casa: nao ha debito, so a comissao -> +600, sem transferencia."""
    razao = apurar(_vendas_do_export(bolso="empresa"))

    assert razao.saldo == Decimal("600.00")
    assert razao.debitos == Decimal("0.00")
    assert razao.creditos == Decimal("600.00")


# --- bolso: fato da venda, com "nao dito" lido como "dela" (ADR-0047) -----------------------


def test_nao_dito_conta_como_dela() -> None:
    """`nao_dito` e estado legitimo e o default do razao e `dela` (ADR-0047 §§3-4)."""
    assert bolso_efetivo("nao_dito") == "dela"
    assert bolso_efetivo("dela") == "dela"
    assert bolso_efetivo("empresa") == "empresa"

    assert apurar(_vendas_do_export(bolso="nao_dito")).saldo == apurar(_vendas_do_export()).saldo


def test_bolso_e_por_venda_nao_por_modelo() -> None:
    """Duas vendas da mesma modelo, bolsos diferentes: o razao le cada venda (ADR-0047 §1)."""
    razao = apurar(
        [
            VendaNoRazao(valor=Decimal("600.00"), bolso="dela", percentual_repasse_snapshot=MEIO),
            VendaNoRazao(
                valor=Decimal("600.00"), bolso="empresa", percentual_repasse_snapshot=MEIO
            ),
        ]
    )

    # debita so a primeira (600), credita as duas comissoes (300 + 300) -> zero.
    assert razao.debitos == Decimal("600.00")
    assert razao.creditos == Decimal("600.00")
    assert razao.saldo == Decimal("0.00")


# --- comissao (ADR-0045 §3) ------------------------------------------------------------------


def test_comissao_sai_de_toda_venda_inclusive_da_empresa() -> None:
    linhas = apurar(
        [VendaNoRazao(valor=Decimal("600.00"), bolso="empresa", percentual_repasse_snapshot=MEIO)]
    ).linhas

    assert [linha.tipo for linha in linhas] == ["comissao"]
    assert linhas[0].credito == Decimal("300.00")


def test_taxa_de_cartao_nunca_e_descontada() -> None:
    """Bruto = valor do card (ADR-0045 §3): a comissao de 50% de 1.000 e 500, nao 4-e-tanto."""
    razao = apurar(
        [VendaNoRazao(valor=Decimal("1000.00"), bolso="empresa", percentual_repasse_snapshot=MEIO)]
    )

    assert razao.creditos == Decimal("500.00")


def test_snapshot_do_percentual_governa_a_venda() -> None:
    """Mudar o cadastro nao mexe em venda ja registrada: cada venda carrega o seu percentual."""
    razao = apurar(
        [
            VendaNoRazao(
                valor=Decimal("600.00"), bolso="empresa", percentual_repasse_snapshot=MEIO
            ),
            VendaNoRazao(
                valor=Decimal("600.00"),
                bolso="empresa",
                percentual_repasse_snapshot=Decimal("40"),
            ),
        ]
    )

    assert razao.creditos == Decimal("540.00")  # 300 + 240


def test_venda_sem_snapshot_nao_credita_comissao() -> None:
    """Sem percentual nao ha 50% chutado no codigo — o saldo erra para o lado conservador."""
    razao = apurar([VendaNoRazao(valor=Decimal("600.00"), bolso="dela")])

    assert razao.saldo == Decimal("-600.00")
    assert [linha.tipo for linha in razao.linhas] == ["venda"]


def test_comissao_arredonda_em_centavos() -> None:
    razao = apurar(
        [VendaNoRazao(valor=Decimal("333.33"), bolso="empresa", percentual_repasse_snapshot=MEIO)]
    )

    assert razao.creditos == Decimal("166.67")  # 166.665 -> HALF_UP


# --- cobranca da agencia e vale (ADR-0045 §1, §8) --------------------------------------------


def test_cobranca_debita_e_nao_abate_venda() -> None:
    """A Cobranca e eixo a parte (ticket 08): entra como debito e nao toca as vendas."""
    razao = apurar(
        [
            VendaNoRazao(
                valor=Decimal("600.00"), bolso="empresa", percentual_repasse_snapshot=MEIO
            ),
            CobrancaNoRazao(valor=Decimal("385.80")),
        ]
    )

    assert razao.debitos == Decimal("385.80")
    assert razao.saldo == Decimal("-85.80")


def test_vale_debita_e_a_transferencia_credita() -> None:
    razao = apurar(
        [
            ValeNoRazao(valor=Decimal("500.00")),
            TransferenciaNoRazao(valor=Decimal("200.00")),
        ]
    )

    assert razao.saldo == Decimal("-300.00")


# --- deslocamento: uma conta, nao uma tabela (ADR-0046 §6, ticket 12) -------------------------


def test_deslocamento_recebido_por_ela_e_uber_pago_pela_casa() -> None:
    """Recebeu 100, a casa pagou o Uber -> debito 100 (ela esta com dinheiro da casa)."""
    razao = apurar(
        [
            DeslocamentoNoRazao(
                valor_antecipado=Decimal("100.00"),
                recebido_por_ela=True,
                valor_transporte=Decimal("100.00"),
                pago_por_ela=False,
            )
        ]
    )

    assert razao.saldo == Decimal("-100.00")
    assert razao.linhas[0].debito == Decimal("100.00")


def test_deslocamento_recebido_e_pago_pela_casa_nao_toca_o_razao() -> None:
    razao = apurar(
        [
            DeslocamentoNoRazao(
                valor_antecipado=Decimal("100.00"),
                recebido_por_ela=False,
                valor_transporte=Decimal("100.00"),
                pago_por_ela=False,
            )
        ]
    )

    assert razao.saldo == Decimal("0.00")
    assert razao.linhas == ()


def test_deslocamento_recebeu_100_e_pagou_60_debita_40() -> None:
    """A sobra e que fica com ela — debito de 40, nao de 100."""
    razao = apurar(
        [
            DeslocamentoNoRazao(
                valor_antecipado=Decimal("100.00"),
                recebido_por_ela=True,
                valor_transporte=Decimal("60.00"),
                pago_por_ela=True,
            )
        ]
    )

    assert razao.saldo == Decimal("-40.00")


def test_deslocamento_sem_antecipado_com_uber_dela_e_credito() -> None:
    """O caso que a tabela de um valor so nao sabia representar: credito de 15 (ADR-0046 §6)."""
    razao = apurar(
        [
            DeslocamentoNoRazao(
                valor_antecipado=Decimal("0.00"),
                recebido_por_ela=False,
                valor_transporte=Decimal("15.00"),
                pago_por_ela=True,
            )
        ]
    )

    assert razao.saldo == Decimal("15.00")
    assert razao.linhas[0].credito == Decimal("15.00")
    assert razao.a_casa_deve == Decimal("15.00")


def test_deslocamento_nunca_entra_na_base_de_comissao() -> None:
    """Reembolso de custo, nao servico: nenhuma linha de comissao nasce do deslocamento."""
    razao = apurar(
        [
            DeslocamentoNoRazao(
                valor_antecipado=Decimal("100.00"),
                recebido_por_ela=True,
                valor_transporte=Decimal("100.00"),
                pago_por_ela=False,
            )
        ]
    )

    assert [linha.tipo for linha in razao.linhas] == ["deslocamento"]


# --- as linhas explicam o saldo --------------------------------------------------------------


def test_linhas_carregam_a_origem_e_somam_o_saldo() -> None:
    """O extrato precisa apontar de volta para a venda; e a soma dos efeitos e o saldo."""
    venda_id = uuid4()
    razao = apurar(
        [
            VendaNoRazao(
                valor=Decimal("600.00"),
                bolso="dela",
                percentual_repasse_snapshot=MEIO,
                origem_id=venda_id,
                descricao="Cliente Antonio 1h",
            ),
            TransferenciaNoRazao(valor=Decimal("600.00")),
        ]
    )

    assert [linha.tipo for linha in razao.linhas] == ["venda", "comissao", "transferencia"]
    assert all(linha.origem_id == venda_id for linha in razao.linhas[:2])
    assert razao.linhas[0].descricao == "Cliente Antonio 1h"
    assert sum((linha.efeito for linha in razao.linhas), Decimal("0.00")) == razao.saldo
    assert razao.saldo == Decimal("300.00")


def test_razao_vazio_e_saldo_zero() -> None:
    razao = apurar([])

    assert razao.saldo == Decimal("0.00")
    assert razao.linhas == ()
