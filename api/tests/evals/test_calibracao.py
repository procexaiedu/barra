"""Prova a estatistica PURA de calibracao do judge (EVAL-10 / ADR 0015).

Nao toca DB/LLM/rede -- roda no `make test`/CI sem credenciais. `calibracao.py` mora em evals/
(fora do pacote `barra`), entao carregamos por caminho via importlib (igual test_runner_gate.py).
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CALIBRACAO = Path(__file__).resolve().parents[1].parent / "evals" / "calibracao" / "calibracao.py"


def _carregar_calibracao() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_calibracao", _CALIBRACAO)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


calibracao = _carregar_calibracao()


# --- matriz de confusao ------------------------------------------------------------------------


def test_matriz_confusao_conta_celulas():
    humano = [True, True, False, False]
    judge = [True, False, True, False]
    m = calibracao.matriz_confusao(humano, judge)
    assert m == {"tp": 1, "fn": 1, "fp": 1, "tn": 1}


def test_matriz_confusao_exige_mesmo_tamanho():
    with pytest.raises(ValueError):
        calibracao.matriz_confusao([True], [True, False])


def test_matriz_confusao_rejeita_vazio():
    with pytest.raises(ValueError):
        calibracao.matriz_confusao([], [])


# --- TPR / TNR ---------------------------------------------------------------------------------


def test_tpr_tnr_judge_perfeito():
    humano = [True, True, False, False]
    assert calibracao.tpr(humano, list(humano)) == 1.0
    assert calibracao.tnr(humano, list(humano)) == 1.0


def test_tpr_pega_falsos_negativos():
    humano = [True, True, True, True]
    judge = [True, True, False, False]  # 2 fn
    assert calibracao.tpr(humano, judge) == 0.5


def test_tnr_pega_falsos_positivos():
    humano = [False, False, False, False]
    judge = [True, False, False, False]  # 1 fp em 4 negativos reais
    assert calibracao.tnr(humano, judge) == 0.75


# --- kappa de Cohen ----------------------------------------------------------------------------


def test_kappa_judge_perfeito_e_um():
    humano = [True, False, True, False, True, False]
    assert calibracao.kappa_cohen(humano, list(humano)) == pytest.approx(1.0)


def test_kappa_aleatorio_proximo_de_zero():
    # padrao alternado vs. blocos -> acordo ~ chance -> kappa ~ 0.
    humano = [True, False, True, False, True, False, True, False]
    judge = [True, True, False, False, True, True, False, False]
    assert calibracao.kappa_cohen(humano, judge) == pytest.approx(0.0, abs=0.05)


def test_kappa_ambos_degeneram_mesma_classe_e_um():
    # Pe=1 (ambos sempre True): por convencao acordo perfeito.
    assert calibracao.kappa_cohen([True, True, True], [True, True, True]) == 1.0


# --- Gwet AC2: robusto ao paradoxo do kappa em prevalencia assimetrica --------------------------


def test_gwet_alto_onde_kappa_despenca_prevalencia_assimetrica():
    # persona/tom: quase tudo passa (18/20 True). So 2 desacordos -> Po=0.9 alto. Mas as marginais
    # ficam quase saturadas em True, entao o Pe do kappa infla e o kappa despenca (paradoxo);
    # o Gwet AC2 (Pe = 2q(1-q)) permanece alto.
    humano = [True] * 18 + [False, True]
    judge = [True] * 18 + [True, False]  # difere em 2 itens -> Po = 0.9
    kappa = calibracao.kappa_cohen(humano, judge)
    gwet = calibracao.gwet_ac2(humano, judge)
    assert gwet > 0.8  # robusto a prevalencia
    assert gwet > kappa  # e estritamente acima do kappa paradoxal
    assert kappa < 0.5


def test_gwet_perfeito_e_um():
    humano = [True, False, True, False, True]
    assert calibracao.gwet_ac2(humano, list(humano)) == pytest.approx(1.0)


# --- Youden's J --------------------------------------------------------------------------------


def test_youden_j_formula():
    assert calibracao.youden_j(1.0, 1.0) == pytest.approx(1.0)
    assert calibracao.youden_j(0.9, 0.85) == pytest.approx(0.75)
    assert calibracao.youden_j(0.5, 0.5) == pytest.approx(0.0)


# --- acordo humano-humano (teto da meta) -------------------------------------------------------


def test_acordo_humano_humano_e_kappa_entre_os_dois():
    fernando = [True, True, False, False, True]
    socia = [True, True, False, False, True]
    assert calibracao.acordo_humano_humano(fernando, socia) == pytest.approx(1.0)


# --- promove_a_blocker: portao liga/desliga nos limiares ----------------------------------------


def test_promove_a_blocker_passa_nos_limiares():
    assert calibracao.promove_a_blocker(0.9, 0.85, 0.6) is True
    assert calibracao.promove_a_blocker(1.0, 1.0, 1.0) is True


def test_promove_a_blocker_reprova_abaixo_de_qualquer_limiar():
    assert calibracao.promove_a_blocker(0.89, 0.85, 0.6) is False  # tpr abaixo
    assert calibracao.promove_a_blocker(0.9, 0.84, 0.6) is False  # tnr abaixo
    assert calibracao.promove_a_blocker(0.9, 0.85, 0.59) is False  # kappa abaixo


def test_promove_a_blocker_limiares_customizaveis():
    # operador pode afrouxar quando kappa_humano (teto) for baixo (refino 08b §3.1).
    assert calibracao.promove_a_blocker(0.7, 0.7, 0.5, min_tpr=0.7, min_tnr=0.7, min_kappa=0.5)
