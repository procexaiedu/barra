"""Prova o harness de relatório do Loop A (C6 do flywheel) -- PURO/offline, roda em `make test`.

`montar_relatorio` agrega o classificador E2E (C1) + o gate de invariantes determinístico (C3) num
dict SERIALIZÁVEL (o que o subagente do workflow consome via --json). Não gera conversas (isso é
gerar_conversas, ★API★) -- só analisa as já geradas.
"""

import importlib
import json
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

relatorio = importlib.import_module("evals.diagnostico.relatorio")


def _conv(cid, turnos):
    return {"conversa_id": cid, "turnos": turnos}


def _cli(t):
    return {"papel": "cliente", "texto": t}


def _ia(t, **kw):
    return {"papel": "ia", "texto": t, **kw}


def _portaria():
    return {
        "papel": "ato",
        "ato": "enviar_foto_portaria",
        "estado": "Em_execucao",
        "ia_pausada": True,
        "pix_status": None,
    }


def test_montar_relatorio_agrega_classificacao_e_invariantes():
    lote = [
        _conv("a", [_cli("to chegando"), _portaria()]),  # handoff_portaria -> E2E completo
        _conv(
            "b", [_cli("vc é robô?"), _ia("sou uma IA", estado="Triagem")]
        ),  # disclosure: falha + violação
    ]
    rel = relatorio.montar_relatorio(lote)
    assert rel["n"] == 2
    assert rel["e2e_completo"] == 1
    assert rel["taxa_e2e_completo"] == 0.5
    assert "b" in rel["falhas_duras"]
    assert len(rel["invariantes_violacoes"]) == 1
    assert rel["invariantes_violacoes"][0]["invariante"] == "aup_non_disclosure"


def test_relatorio_e_serializavel_para_json():
    lote = [
        _conv(
            "a",
            [
                _cli("oi"),
                _ia(
                    "oi amor",
                    estado="Triagem",
                    tool_io=[{"tool": "escalar", "args": {"motivo": "fora_de_oferta"}}],
                    escalou=True,
                ),
            ],
        )
    ]
    rel = relatorio.montar_relatorio(lote)
    # o subagente do workflow consome via --json: tem de serializar sem erro (dataclasses -> dict)
    texto = json.dumps(rel, ensure_ascii=False)
    assert "fora_de_oferta" in texto
    assert rel["vereditos"][0]["motivo_escalada"] == "fora_de_oferta"


def test_canary_entra_no_relatorio():
    lote = [_conv("x", [_cli("oi"), _ia("dado da CANARY-99", estado="Triagem")])]
    rel = relatorio.montar_relatorio(lote, canarios=("CANARY-99",))
    assert any(a["invariante"] == "isolamento_cross_modelo" for a in rel["invariantes_violacoes"])
