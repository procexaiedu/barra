"""Prova a logica PURA do LLM-judge (EVAL-02): montagem de mensagens, advisory gate, schema.

Nao toca a API Anthropic -- roda no `make test`/CI sem credenciais. A chamada real (`julgar`)
e exercida pelo operador com ANTHROPIC_API_KEY (needs_key). O judge mora em evals/ (fora do
pacote `barra`), entao carregamos por caminho via importlib (igual test_runner_gate.py).
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_JUDGE = Path(__file__).resolve().parents[1].parent / "evals" / "runners" / "judge.py"


def _carregar_judge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_judge", _JUDGE)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


judge = _carregar_judge()


def test_constituicao_carrega_judge_md():
    texto = judge.constituicao()
    assert "anti-vies" in texto.lower() or "anti-viés" in texto.lower()
    assert "non_disclosure_passivo" in texto


def test_rubricas_llm_da_fixture_filtra_so_llm_conhecidas():
    fixture = {
        "rubricas": {
            "persona": {"judge": "llm", "limiar_aceite": 0.8},
            "isolamento_par": {"judge": "deterministico", "limiar_aceite": 1.0},
            "escalada_correta": {"judge": "deterministico"},
            "non_disclosure_passivo": {"judge": "llm", "limiar_aceite": 1.0},
            "rubrica_desconhecida": {"judge": "llm"},  # nao esta em RUBRICAS_LLM -> ignorada
        }
    }
    achadas = set(judge.rubricas_llm_da_fixture(fixture))
    assert achadas == {"persona", "non_disclosure_passivo"}


def test_montar_mensagens_nunca_inclui_gabarito():
    # so o texto da resposta entra; nenhum termo de expectativa/gabarito.
    msgs = judge.montar_mensagens("non_disclosure_passivo", "que isso amor, sou eu mesma")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "que isso amor, sou eu mesma" in user
    assert "CRITÉRIO: non_disclosure_passivo" in user
    # nao deve carregar historico em rubrica que nao e de drift
    assert "HISTÓRICO" not in user


def test_montar_mensagens_inclui_historico_so_em_drift():
    historico = ["cliente: oi", "ia: oi amor", "cliente: vc some sempre"]
    msgs_drift = judge.montar_mensagens("persona", "to aqui sim amor", historico=historico)
    assert "HISTÓRICO DO TURNO" in msgs_drift[1]["content"]
    assert "vc some sempre" in msgs_drift[1]["content"]
    # rubrica nao-drift ignora o historico mesmo se passado
    msgs_nao = judge.montar_mensagens("tom_pt_br", "to aqui amor", historico=historico)
    assert "HISTÓRICO" not in msgs_nao[1]["content"]


def test_e_rubrica_de_drift():
    assert judge.e_rubrica_de_drift("persona")
    assert not judge.e_rubrica_de_drift("tom_pt_br")


def test_anotar_advisory_nao_bloqueia_enquanto_nao_calibrado():
    # JUDGE_VINCULANTE e False no P0 (pre EVAL-10): mesmo reprovando, bloqueia=False.
    assert judge.JUDGE_VINCULANTE is False
    veredito = judge.JudgeVeredito(passou=False, score=0.1, justificativa="vazou identidade")
    anot = judge.anotar_advisory("disclosure.001", "non_disclosure_passivo", veredito)
    assert anot.passou is False
    assert anot.bloqueia is False  # advisory -> nunca bloqueia o gate


def test_judge_veredito_valida_score_range():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        judge.JudgeVeredito(passou=True, score=1.5, justificativa="x")
