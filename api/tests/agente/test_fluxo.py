"""Teste puro de barra.agente.fluxo — sem DB, sem credito (suite padrao)."""

from __future__ import annotations

from collections import Counter

from barra.agente.fluxo import js_divergencia, matriz_transicao, rotular_turno


def test_rotulador_precedencia() -> None:
    assert rotular_turno("400 a hora amor, beijo e oral") == "cotacao"
    assert rotular_turno("R$ 700 as 2h") == "cotacao"
    assert rotular_turno("", tem_midia=True) == "midia"
    assert rotular_turno("[foto] acabei de gravar pra vc") == "midia"
    assert rotular_turno("consigo te fazer um descontinho amor") == "desconto"
    assert rotular_turno("me manda o pix amor que reservo seu horario") == "logistica"
    assert rotular_turno("seria hoje amor? 🥰") == "sondagem"
    assert rotular_turno("oi amor, tudo bem?") == "saudacao"
    assert rotular_turno("kkk vc e um gato") == "outro"


def test_preco_nao_confunde_com_hora() -> None:
    # "22h" e hora, nao preco -> nao deve virar cotacao.
    assert rotular_turno("pode ser as 22h amor?") != "cotacao"


def test_jsd_identico_e_zero() -> None:
    c = matriz_transicao([["saudacao", "sondagem", "cotacao", "logistica"]])
    assert js_divergencia(c, c) == 0.0


def test_jsd_disjunto_e_um() -> None:
    p = Counter({("saudacao", "sondagem"): 1})
    q = Counter({("cotacao", "logistica"): 1})
    assert abs(js_divergencia(p, q) - 1.0) < 1e-9


def test_jsd_simetrica() -> None:
    p = matriz_transicao([["saudacao", "cotacao", "logistica"]])
    q = matriz_transicao([["saudacao", "sondagem", "cotacao"]])
    assert abs(js_divergencia(p, q) - js_divergencia(q, p)) < 1e-12
