"""Prova o agregador GO/NO-GO da rodada (diagnostico/veredito.py) -- PURO, sem DB/LLM/rede.

Matriz de criterios: gate ausente/nao-verde, violacao de invariante, taxa E2E abaixo do alvo,
falha dura, custo p95 estourado e cache-hit abaixo do piso (so quando o piso e setado) -- cada um
derruba o GO sozinho. `render_markdown` carrega os comandos `extrair` da fila do juiz.
"""

import importlib
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

ver = importlib.import_module("evals.diagnostico.veredito")


def _massa_ok(**sobrescreve):
    base = {
        "n": 10,
        "e2e_completo": 9,
        "taxa_e2e_completo": 0.9,
        "por_terminal": {"fechado": 5, "handoff_pix": 4, "recusa_ou_aberto": 1},
        "falhas_duras": [],
        "precisa_julgamento": ["interno_fecha_venda#k1"],
        "vereditos": [],
        "invariantes_violacoes": [],
        "invariantes_suspeitas": [],
    }
    base.update(sobrescreve)
    return base


def _saude_ok(**sobrescreve):
    base = {
        "n_turnos_com_custo": 40,
        "custo_total_turnos_ia_brl": 8.0,
        "custo_total_jornadas_brl": 12.0,
        "custo_p95_turno_brl": 0.18,
        "cache_hit_medio_turnos_2mais": 0.7,
    }
    base.update(sobrescreve)
    return base


_GATE_VERDE = {
    "tipo": "cutover",
    "carimbo": "x",
    "k": 5,
    "verde": True,
    "n_regressao": 24,
    "n_pass": 24,
}


def test_tudo_verde_da_go():
    v = ver.montar_veredito(_massa_ok(), _saude_ok(), _GATE_VERDE, ver.CriteriosGo())
    assert v["go"] is True
    assert v["motivos"] == []


def test_gate_ausente_e_no_go():
    v = ver.montar_veredito(_massa_ok(), _saude_ok(), None, ver.CriteriosGo())
    assert v["go"] is False
    assert any("cutover.json" in m for m in v["motivos"])


def test_gate_nao_verde_e_no_go():
    gate = dict(_GATE_VERDE, verde=False, n_pass=22)
    v = ver.montar_veredito(_massa_ok(), _saude_ok(), gate, ver.CriteriosGo())
    assert v["go"] is False
    assert any("NÃO-verde" in m for m in v["motivos"])


def test_violacao_de_invariante_e_no_go():
    massa = _massa_ok(
        invariantes_violacoes=[{"invariante": "aup_non_disclosure", "conversa_id": "x"}]
    )
    v = ver.montar_veredito(massa, _saude_ok(), _GATE_VERDE, ver.CriteriosGo())
    assert v["go"] is False
    assert any("invariante" in m for m in v["motivos"])


def test_taxa_e2e_abaixo_do_alvo_e_no_go():
    v = ver.montar_veredito(
        _massa_ok(taxa_e2e_completo=0.7), _saude_ok(), _GATE_VERDE, ver.CriteriosGo()
    )
    assert v["go"] is False
    assert any("taxa E2E" in m for m in v["motivos"])


def test_falha_dura_e_no_go():
    v = ver.montar_veredito(
        _massa_ok(falhas_duras=["x#k0"]), _saude_ok(), _GATE_VERDE, ver.CriteriosGo()
    )
    assert v["go"] is False


def test_custo_p95_estourado_e_no_go():
    v = ver.montar_veredito(
        _massa_ok(), _saude_ok(custo_p95_turno_brl=0.40), _GATE_VERDE, ver.CriteriosGo()
    )
    assert v["go"] is False
    assert any("p95" in m for m in v["motivos"])


def test_cache_hit_advisory_por_default_e_duro_quando_setado():
    saude = _saude_ok(cache_hit_medio_turnos_2mais=0.2)
    assert ver.montar_veredito(_massa_ok(), saude, _GATE_VERDE, ver.CriteriosGo())["go"] is True
    criterios = ver.CriteriosGo(cache_hit_minimo=0.5)
    v = ver.montar_veredito(_massa_ok(), saude, _GATE_VERDE, criterios)
    assert v["go"] is False


def test_saude_tolerante_a_campos_ausentes():
    conversas = [
        {
            "custo_brl": 1.5,
            "turnos": [
                {"papel": "cliente", "texto": "oi"},
                {"papel": "ia", "texto": "a", "custo_brl": 0.1, "cache_hit_rate": None},
                {"papel": "ia", "texto": "b", "custo_brl": None, "cache_hit_rate": 0.9},
                {"papel": "ato", "ato": "enviar_pix_valido", "estado": "Confirmado"},
            ],
        },
        {"turnos": []},  # conversa antiga sem extras: nao quebra
    ]
    s = ver.saude_custo_cache(conversas)
    assert s["n_turnos_com_custo"] == 1
    assert s["custo_total_jornadas_brl"] == pytest.approx(1.5)
    assert s["cache_hit_medio_turnos_2mais"] == pytest.approx(0.9)


def test_saude_vazia_nao_quebra_nem_da_falso_estouro():
    s = ver.saude_custo_cache([])
    assert s["custo_p95_turno_brl"] is None
    v = ver.montar_veredito(_massa_ok(), s, _GATE_VERDE, ver.CriteriosGo())
    assert not any("p95" in m for m in v["motivos"])  # sem medida -> criterio nao aplica


def test_render_markdown_tem_veredito_e_fila_do_juiz(tmp_path):
    v = ver.montar_veredito(_massa_ok(), _saude_ok(), None, ver.CriteriosGo())
    md = ver.render_markdown(v, tmp_path / "20260610T120000")
    assert "NO-GO" in md
    assert "evals.diagnostico.extrair" in md
    assert "interno_fecha_venda#k1" in md
