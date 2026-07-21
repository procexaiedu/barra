"""Sorteio canned DETERMINISTICO por seed (turno_id): no replay do job ARQ a MESMA frase sai,
senao o texto despachado ao cliente divergiria do auditado/re-enviado. Teste puro (sem rede/DB).
"""

from barra.agente._canned import (
    CANCELAMENTO_PILOTO_CANNED,
    NEGACOES_CANNED,
    TRANSCRICAO_FALHOU_CANNED,
    escolher_cancelamento_piloto,
    escolher_canned_transcricao_falhou,
    escolher_negacao,
)


def test_negacao_deterministica_por_seed():
    s = "turno-abc-123"
    assert escolher_negacao(seed=s) == escolher_negacao(seed=s)


def test_negacao_varia_entre_seeds_e_fica_no_pool():
    vistos = {escolher_negacao(seed=f"turno-{i}") for i in range(50)}
    assert len(vistos) > 1  # nao colapsa numa unica frase (mantem o anti-tell)
    assert vistos <= set(NEGACOES_CANNED)


def test_negacao_sem_seed_ainda_sorteia_do_pool():
    assert escolher_negacao() in NEGACOES_CANNED


def test_transcricao_falhou_deterministica_por_seed():
    s = "turno-xyz"
    assert escolher_canned_transcricao_falhou(seed=s) == escolher_canned_transcricao_falhou(seed=s)
    assert escolher_canned_transcricao_falhou(seed=s) in TRANSCRICAO_FALHOU_CANNED


def test_cancelamento_piloto_pool_tem_mais_de_uma_frase():
    # ADR-0033: evita regressao pro caso "desculpa unica" (padrao identico repetido).
    assert len(CANCELAMENTO_PILOTO_CANNED) >= 3


def test_cancelamento_piloto_sorteia_do_pool():
    vistos = {escolher_cancelamento_piloto() for _ in range(50)}
    assert len(vistos) > 1
    assert vistos <= set(CANCELAMENTO_PILOTO_CANNED)
