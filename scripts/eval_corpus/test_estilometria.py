"""Testes da Camada 1 (estilometria) — pure stdlib, sem DB nem crédito.

Rodar:  cd api && uv run pytest ../scripts/eval_corpus/test_estilometria.py
(Fora do `make test` por viver em scripts/ — é o harness de pesquisa, como o resto da pasta.)
"""

import math

import estilometria as e


def test_bolhas_quebra_por_linha_em_branco() -> None:
    turno = "Oii\n\nBoa tarde amor 🥰\n\ntudo bem? seria hoje? 😊"
    assert e.bolhas(turno) == ["Oii", "Boa tarde amor 🥰", "tudo bem? seria hoje? 😊"]


def test_bolhas_descarta_vazias() -> None:
    assert e.bolhas("\n\n  \n\noi\n\n") == ["oi"]


def test_conta_emoji() -> None:
    assert e._conta_emoji("Oii") == 0
    assert e._conta_emoji("amor 🥰") == 1
    assert e._conta_emoji("☺️ que bom") == 1  # com seletor de variação
    assert e._conta_emoji("🥰😍 dois runs colados") == 1  # runs colados = 1


def test_termina_em_ponto() -> None:
    assert e._termina_em_ponto("frase completa.") is True
    assert e._termina_em_ponto("reticências...") is False  # ... não é ponto final de SAC
    assert e._termina_em_ponto("oii amor") is False
    assert e._termina_em_ponto("seria hoje?") is False


def test_vocativo_e_rs() -> None:
    p = e.perfil_de_bolhas(["oii amor", "tudo bem vida", "que bom rs", "frase seca."])
    assert p["taxa_vocativo"] == 0.5  # amor, vida em 2 de 4
    assert p["taxa_rs"] == 0.25
    assert p["taxa_ponto_final"] == 0.25


def test_js_identicas_zero() -> None:
    p = {"a": 0.5, "b": 0.5}
    assert e.js_divergence(p, p) == 0.0


def test_js_disjuntas_um() -> None:
    # Distribuições sem sobreposição → JS base-2 = 1 (máximo).
    assert math.isclose(e.js_divergence({"a": 1.0}, {"b": 1.0}), 1.0, abs_tol=1e-9)


def test_distancia_perfis_identicos_zero() -> None:
    bolhas = ["oii amor 🥰", "seria hoje?", "que bom rs", "{valor} 1h no meu local"]
    p = e.perfil_de_bolhas(bolhas)
    d = e.distancia(p, p)
    assert d["agregado"] == 0.0
    assert all(v == 0.0 for v in d.values())


def test_distancia_voz_formal_e_alta() -> None:
    # Perfil "ELA" (curto, emoji, vocativo, sem ponto) vs candidato "SAC formal" (longo, com
    # ponto, sem emoji/vocativo) → distância agregada claramente alta.
    ela = e.perfil_de_bolhas(
        ["oii amor 🥰", "seria hoje? 😊", "que bom vida rs", "consigo sim amor"]
    )
    formal = e.perfil_de_bolhas(
        [
            "Olá! Como posso ajudar você hoje?",
            "Deixe-me verificar a disponibilidade para o senhor.",
            "Segue abaixo a tabela de valores conforme solicitado.",
            "Permaneço à disposição para quaisquer esclarecimentos.",
        ]
    )
    d = e.distancia(ela, formal)
    assert d["agregado"] > 0.3
    assert d["ponto_final"] > 0.5  # ELA ~0 ponto; formal ~1
    assert d["vocativo"] > 0.5  # ELA tem amor/vida; formal não


def test_mattr_robusto_ao_tamanho() -> None:
    # Repetir o mesmo token N vezes → MATTR baixo; tokens todos distintos → 1.0.
    assert e._mattr(["a"] * 100) < 0.1
    assert e._mattr([str(i) for i in range(100)]) == 1.0


def test_rs_e_feature_do_agregado() -> None:
    # 'rs' entrou como feature do agregado: dois perfis que diferem em 'rs' têm a feature no
    # dict de distância, e ela é 1.0 quando 100% vs 0%.
    com_rs = e.perfil_de_bolhas(["oii amor rs", "que bom rs", "vamos rs", "bora rs"])
    sem_rs = e.perfil_de_bolhas(["oii amor rs2", "que bom okk", "vamos sim", "bora la"])
    d = e.distancia(com_rs, sem_rs)
    assert "rs" in e.FEATURES
    assert "rs" in d
    assert d["rs"] == 1.0  # taxa_rs 100% vs 0%


def test_perfil_vazio_levanta() -> None:
    import pytest

    with pytest.raises(ValueError):
        e.perfil_de_bolhas([])
