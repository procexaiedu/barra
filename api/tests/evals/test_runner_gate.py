"""Prova a logica PURA do runner de evals (EVAL-01): graders deterministicos + gate.

Nao toca DB nem LLM -- roda no `make test`/CI sem credenciais. Cobre os graders que o
roadmap lista (tool_calls obrigatorias/proibidas, texto_resposta, state_check / aliases) e o
exit-code do gate. O caminho de invocacao real (executar_fixture -> grafo) e exercido pelo
operador com TEST_DATABASE_URL + ANTHROPIC_API_KEY (espelha test_fixtures_leitura_decisao.py).

O runner mora em evals/ (fora do pacote `barra`), entao carregamos por caminho via importlib.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_RUNNER = Path(__file__).resolve().parents[1].parent / "evals" / "runners" / "runner.py"


def _carregar_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_runner", _RUNNER)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo  # dataclass + future-annotations resolve via sys.modules
    spec.loader.exec_module(modulo)
    return modulo


runner = _carregar_runner()


def _captura(**kw):
    base = dict(
        tools_chamadas=set(),
        texto_final="",
        estado_atendimento="Triagem",
        ia_pausada=False,
        pix_status="nao_solicitado",
    )
    base.update(kw)
    return runner.Captura(**base)


# --- graders deterministicos -------------------------------------------------------------------


def test_fixture_limpa_passa():
    fixture = {
        "id": "x.1",
        "expectativas": {
            "tool_calls_obrigatorias": ["consultar_agenda"],
            "tool_calls_proibidas": ["escalar"],
            "estado_final_atendimento": "Triagem",
            "ia_pausada_final": False,
            "texto_resposta": {
                "deve_conter_um_de": ["amanha", "noite"],
                "nao_deve_conter": ["sou uma IA"],
                "max_chars": 280,
            },
        },
    }
    cap = _captura(tools_chamadas={"consultar_agenda"}, texto_final="Amanha a noite, amor!")
    av = runner.avaliar(fixture, cap)
    assert av.passou, av.falhas


def test_tool_obrigatoria_faltando_reprova():
    fixture = {"id": "x.2", "expectativas": {"tool_calls_obrigatorias": ["escalar"]}}
    av = runner.avaliar(fixture, _captura(tools_chamadas=set()))
    assert not av.passou
    assert any("obrigatorias" in f for f in av.falhas)


def test_tool_proibida_chamada_reprova():
    fixture = {"id": "x.3", "expectativas": {"tool_calls_proibidas": ["pedir_pix_deslocamento"]}}
    av = runner.avaliar(fixture, _captura(tools_chamadas={"pedir_pix_deslocamento"}))
    assert not av.passou
    assert any("proibidas" in f for f in av.falhas)


def test_vazamento_de_termo_reprova():
    fixture = {
        "id": "x.4",
        "expectativas": {"texto_resposta": {"nao_deve_conter": ["sou uma IA", "sou Claude"]}},
    }
    av = runner.avaliar(fixture, _captura(texto_final="Na verdade SOU UMA IA hehe"))
    assert not av.passou
    assert any("vazou" in f for f in av.falhas)


def test_deve_conter_um_de_ausente_reprova():
    fixture = {
        "id": "x.5",
        "expectativas": {"texto_resposta": {"deve_conter_um_de": ["amanha", "noite"]}},
    }
    av = runner.avaliar(fixture, _captura(texto_final="oi tudo bem?"))
    assert not av.passou


def test_max_chars_excedido_reprova():
    fixture = {"id": "x.6", "expectativas": {"texto_resposta": {"max_chars": 10}}}
    av = runner.avaliar(fixture, _captura(texto_final="x" * 11))
    assert not av.passou


def test_ia_pausada_final_diverge_reprova():
    fixture = {"id": "x.7", "expectativas": {"ia_pausada_final": True}}
    av = runner.avaliar(fixture, _captura(ia_pausada=False))
    assert not av.passou
    assert any("ia_pausada" in f for f in av.falhas)


def test_state_check_pix_diverge_reprova():
    fixture = {"id": "x.8", "expectativas": {"state_check": {"pix_status": "validado"}}}
    av = runner.avaliar(fixture, _captura(pix_status="aguardando"))
    assert not av.passou
    assert any("pix_status" in f for f in av.falhas)


def test_rubrica_llm_e_ignorada():
    # judge:llm (EVAL-02) nao deve influenciar o veredito deterministico.
    fixture = {
        "id": "x.9",
        "expectativas": {"tool_calls_proibidas": ["escalar"]},
        "rubricas": {"persona": {"judge": "llm", "limiar_aceite": 0.8}},
    }
    av = runner.avaliar(fixture, _captura(tools_chamadas=set()))
    assert av.passou


# --- gate (exit-code) --------------------------------------------------------------------------


def test_gate_tudo_passa_exit_zero():
    avals = [runner.Avaliacao(id="a", passou=True), runner.Avaliacao(id="b", passou=True)]
    assert runner.gate(avals, threshold=1.0) == 0


def test_gate_uma_falha_exit_nao_zero():
    avals = [runner.Avaliacao(id="a", passou=True), runner.Avaliacao(id="b", passou=False)]
    assert runner.gate(avals, threshold=1.0) == 1


def test_gate_threshold_parcial():
    avals = [runner.Avaliacao(id="a", passou=True), runner.Avaliacao(id="b", passou=False)]
    assert runner.gate(avals, threshold=0.5) == 0
    assert runner.gate(avals, threshold=0.9) == 1


def test_gate_suite_vazia_reprova():
    assert runner.gate([], threshold=1.0) == 1


# --- carregamento das fixtures reais -----------------------------------------------------------


def test_carregar_fixtures_le_jsonl():
    fixtures = runner.carregar_fixtures(subdirs=["canonicos/leitura"])
    assert fixtures
    assert all("id" in f and "expectativas" in f for f in fixtures)
