"""Aceite CUSTO-06: o alvo de custo por turno tem FONTE UNICA em settings.custo_alvo_brl.

Antes o numero 0.03 estava duplicado em comentarios/help de core/metrics.py, agente/nos/llm.py
e _custo.py. Esta suite trava o contrato: (1) o campo existe com o default documentado (0.03) e
(2) os help/docstrings nao reintroduzem o numero literal — apontam para o settings pelo nome.

NAO confundir com `max_custo_brl` das fixtures de eval (budget por-fixture mais estrito, knob
diferente e inerte no runner). CUSTO-06 unifica so o ALVO DE TURNO.
"""

from pathlib import Path

from barra.core.metrics import AGENTE_CUSTO_TURNO_BRL
from barra.settings import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "barra"


def test_custo_alvo_brl_default_documentado() -> None:
    # 0.03 e a meta recalibrada p/ DeepSeek V4 Flash (com cache); fonte unica no settings (03 §4.2).
    assert Settings().custo_alvo_brl == 0.03


def test_custo_alvo_brl_positivo() -> None:
    # gt=0.0 no Field: alvo nao-positivo nao faz sentido (divisao/comparacao de custo).
    assert Settings().custo_alvo_brl > 0.0


def test_help_do_histogram_aponta_pro_settings_sem_numero() -> None:
    # O help do Histogram nao repete o numero; referencia o settings pelo nome (fonte unica).
    doc = AGENTE_CUSTO_TURNO_BRL._documentation
    assert "settings.custo_alvo_brl" in doc
    assert "0.03" not in doc


def test_nenhum_modulo_de_custo_hardcoda_o_numero() -> None:
    # Guard contra regressao: o literal 0.03 nao pode voltar aos modulos que so observam/calculam
    # o custo. O unico lugar com o numero e o default do Field em settings.py.
    for rel in ("core/metrics.py", "agente/nos/llm.py", "agente/_custo.py"):
        texto = (SRC / rel).read_text(encoding="utf-8")
        assert "0.03" not in texto, f"{rel} reintroduziu o alvo de custo hardcoded"
