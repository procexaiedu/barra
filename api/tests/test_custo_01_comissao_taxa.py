"""Aceite CUSTO-01: fórmulas de valor do serviço, repasse e comissão (ADRs 0012 / 0013).

Funções puras testáveis offline. Invariantes do ADR:
- taxa só desconta o serviço (nunca o bruto na base de repasse/comissão);
- só com taxa o serviço difere do bruto;
- repasse e comissão são INDEPENDENTES (nenhum desconta o outro), mesma base;
- IA conduz (sem nível) → comissão 0.
A regra "só Fechado conta" é garantida pelo filtro de estado nas queries SQL (needs_db),
não pela função pura — aqui cobrimos a aritmética.
"""

import pytest

from barra.dominio.financeiro.calculos import (
    comissao_vendedor,
    repasse_modelo,
    valor_servico,
)


def test_valor_servico_sem_taxa_igual_ao_bruto() -> None:
    # Pix/dinheiro (ou cartão isento): serviço == bruto.
    assert valor_servico(1000.0, None) == pytest.approx(1000.0)
    assert valor_servico(1000.0, 0.0) == pytest.approx(1000.0)


def test_valor_servico_desconta_a_taxa() -> None:
    # Cartão 10%: cliente pagou 1100 bruto p/ um serviço de 1000 (1100 / 1.10).
    assert valor_servico(1100.0, 10.0) == pytest.approx(1000.0)


def test_repasse_incide_sobre_servico_nao_sobre_bruto() -> None:
    # Bruto 1100 (taxa 10% → serviço 1000), repasse 40%: 400, não 440.
    assert repasse_modelo(1100.0, 10.0, 40.0) == pytest.approx(400.0)
    # Sem taxa, mesma % sobre o bruto.
    assert repasse_modelo(1000.0, None, 40.0) == pytest.approx(400.0)


def test_repasse_sem_snapshot_e_zero() -> None:
    # percentual_repasse None (fecha com repasse pendente, ADR 0011).
    assert repasse_modelo(1000.0, None, None) == pytest.approx(0.0)


def test_comissao_incide_sobre_servico() -> None:
    # Bruto 1100 (taxa 10% → serviço 1000), comissão nível 5%: 50, não 55.
    assert comissao_vendedor(1100.0, 10.0, 5.0) == pytest.approx(50.0)


def test_comissao_ia_sem_nivel_e_zero() -> None:
    # IA conduz → sem vendedor → sem nível → comissão 0 (ADR 0012).
    assert comissao_vendedor(1000.0, None, None) == pytest.approx(0.0)


def test_repasse_e_comissao_independentes() -> None:
    # Mesma base (serviço), nenhum desconta o outro. Serviço 1000, repasse 40%, comissão 5%.
    servico = valor_servico(1100.0, 10.0)  # 1000
    rep = repasse_modelo(1100.0, 10.0, 40.0)  # 400
    com = comissao_vendedor(1100.0, 10.0, 5.0)  # 50
    # comissão NÃO é calculada sobre (serviço - repasse); é direto sobre o serviço.
    assert com == pytest.approx(servico * 5.0 / 100.0)
    assert rep == pytest.approx(servico * 40.0 / 100.0)
    # a soma dos dois custos pode passar de nenhum limite cruzado — são paralelos.
    assert rep + com == pytest.approx(450.0)


def test_pix_deslocamento_nunca_entra() -> None:
    # O Pix de deslocamento não está em valor_final; a função só recebe o bruto do serviço,
    # então por construção a base nunca inclui o Pix. Sanity: bruto sem taxa = serviço.
    assert valor_servico(800.0, None) == pytest.approx(800.0)
