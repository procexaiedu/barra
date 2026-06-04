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
    # sem historico fornecido -> nenhum bloco de contexto vaza para o prompt
    assert "CONTEXTO" not in user


def test_montar_mensagens_inclui_contexto_em_qualquer_rubrica():
    # O contexto (historico) entra para QUALQUER rubrica -- tom_pt_br/instruction_following
    # precisam ver o que o cliente pediu / em que idioma, nao so persona (EVAL-10).
    historico = ["cliente: hey love, are you available tonight?"]
    for rubrica in ("tom_pt_br", "persona", "instruction_following"):
        msgs = judge.montar_mensagens(rubrica, "hi love, 900 for 1h", historico=historico)
        user = msgs[1]["content"]
        assert "CONTEXTO DA CONVERSA" in user
        assert "are you available tonight" in user
        # contexto rotulado como nao-avaliavel e ANTES da resposta sob analise
        assert user.index("CONTEXTO DA CONVERSA") < user.index("RESPOSTA A AVALIAR")


def test_schema_holistico_cobre_exatamente_rubricas_llm():
    # O JudgeHolistico (1 chamada p/ as 4 dimensoes) tem que ter UM campo por rubrica LLM, nem
    # mais nem menos -- senao a calibracao holistica julgaria um conjunto diferente do humano.
    assert set(judge.JudgeHolistico.model_fields) == set(judge.RUBRICAS_LLM)


def test_montar_mensagens_holistico_lista_rubricas_e_contexto():
    historico = ["cliente: hey love, are you available tonight?"]
    msgs = judge.montar_mensagens_holistico("hi love, 900 for 1h", historico=historico)
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    # as 4 rubricas LLM aparecem nomeadas na unica chamada
    for rubrica in judge.RUBRICAS_LLM:
        assert rubrica in user
    # contexto rotulado como nao-avaliavel e ANTES da resposta sob analise (igual ao modo single)
    assert "CONTEXTO DA CONVERSA" in user
    assert user.index("CONTEXTO DA CONVERSA") < user.index("RESPOSTA A AVALIAR")
    # anti-leakage: nenhum termo de gabarito vaza
    assert "expectativas" not in user
    assert "state_check" not in user


def test_holistico_passou_exige_todas_as_rubricas():
    ok = judge.JudgeVeredito(passou=True, score=0.9, justificativa="ok")
    falha = judge.JudgeVeredito(passou=False, score=0.1, justificativa="vazou identidade")
    todas_ok = judge.JudgeHolistico(
        non_disclosure_passivo=ok, persona=ok, instruction_following=ok, tom_pt_br=ok
    )
    assert judge.holistico_passou(todas_ok) is True
    # uma so dimensao reprovada -> a fala inteira "nao passou" (espelha o ✕ holistico do humano)
    uma_falha = judge.JudgeHolistico(
        non_disclosure_passivo=falha, persona=ok, instruction_following=ok, tom_pt_br=ok
    )
    assert judge.holistico_passou(uma_falha) is False


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
