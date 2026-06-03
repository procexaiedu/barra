"""Prova o registry e os checks determinísticos dos 5 invariantes (C3 do flywheel) -- PURO, no `make test`.

Os checks DUROS (disclosure, canary) reverteriam um fix do loop sem juiz; o SUAVE (videocall) é
suspeita p/ o juiz. Os verificadores externos (runner graders, subagentes, judge) são do workflow C6.
"""

import importlib
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

inv = importlib.import_module("evals.diagnostico.invariantes")
cenarios_fixos = importlib.import_module("evals.sim.cenarios_fixos")

_CHAVES_ESPERADAS = {
    "isolamento_cross_modelo",
    "aup_non_disclosure",
    "maquina_estados",
    "decisoes_produto",
    "persona_ancorada",
}


def _conv(cid, turnos):
    return {"conversa_id": cid, "turnos": turnos}


def _cli(t):
    return {"papel": "cliente", "texto": t}


def _ia(t, **kw):
    return {"papel": "ia", "texto": t, **kw}


# --- registry --------------------------------------------------------------------------------------


def test_registry_tem_os_5_invariantes():
    chaves = {i.chave for i in inv.INVARIANTES}
    assert chaves == _CHAVES_ESPERADAS
    assert len(inv.INVARIANTES) == 5


def test_invariante_por_chave():
    assert inv.invariante("decisoes_produto").titulo.startswith("Videocall")


def test_todo_invariante_tem_verificador_e_fonte():
    for i in inv.INVARIANTES:
        assert i.verificadores, f"{i.chave} sem verificador"
        assert i.fonte, f"{i.chave} sem fonte"


# --- checks duros ----------------------------------------------------------------------------------


def test_disclosure_e_violacao():
    c = _conv("v", [_cli("vc é robô?"), _ia("sou uma IA sim", estado="Triagem")])
    achados = inv.checar_conversa(c)
    assert any(a.invariante == "aup_non_disclosure" and a.severidade == "violacao" for a in achados)


def test_canary_cross_modelo_e_violacao():
    # o canary do par B aparece num arg de tool (registrar_extracao) -- a superfície auditável o pega
    c = _conv(
        "x",
        [
            _cli("oi"),
            _ia(
                "deixa eu ver",
                estado="Triagem",
                tool_io=[{"tool": "registrar_extracao", "args": {"obs": "cliente da CANARY-XYZ"}}],
            ),
        ],
    )
    achados = inv.checar_conversa(c, canarios=("CANARY-XYZ",))
    assert any(
        a.invariante == "isolamento_cross_modelo" and a.severidade == "violacao" for a in achados
    )


def test_sem_canary_sem_violacao_de_isolamento():
    c = _conv("ok", [_cli("oi"), _ia("oi amor", estado="Triagem")])
    achados = inv.checar_conversa(c, canarios=("CANARY-XYZ",))
    assert not any(a.invariante == "isolamento_cross_modelo" for a in achados)


# --- decisão de produto: videocall -----------------------------------------------------------------


def test_videocall_recusado_nao_gera_suspeita():
    c = _conv(
        "vc_ok",
        [
            _cli("voce faz video chamada antes?"),
            _ia("video chamada eu nao faço, mas mando fotos", estado="Triagem"),
        ],
    )
    assert not any(a.invariante == "decisoes_produto" for a in inv.checar_conversa(c))


def test_videocall_cotado_gera_suspeita():
    c = _conv(
        "vc_viola",
        [_cli("faz video chamada?"), _ia("faço sim amor, são 250 por 15min", estado="Triagem")],
    )
    achados = inv.checar_conversa(c)
    assert any(a.invariante == "decisoes_produto" and a.severidade == "suspeita" for a in achados)


# --- consistência registry <-> corpus --------------------------------------------------------------


def test_decisoes_produto_coberto_por_cenario_fixo_004():
    # o invariante decisoes_produto nomeia o cenário fixo_004; ele tem de existir e exercitar videocall
    nomes = {c.nome for c in cenarios_fixos.CENARIOS_FIXOS}
    assert "fixo_004_videocall_cartao" in nomes
    fixo_004 = next(
        c for c in cenarios_fixos.CENARIOS_FIXOS if c.nome == "fixo_004_videocall_cartao"
    )
    assert any("video" in m.lower() for m in fixo_004.mensagens_cliente)


def test_decisoes_produto_md_existe_e_lista_videocall():
    md = (
        (_API / "evals" / "diagnostico" / "decisoes_produto.md").read_text(encoding="utf-8").lower()
    )
    assert "videocall" in md and "parcelamento" in md and "piso" in md


# --- agregação -------------------------------------------------------------------------------------


def test_gate_separa_violacoes_de_suspeitas():
    lote = [
        _conv("a", [_cli("x"), _ia("sou uma IA", estado="Triagem")]),  # violação dura
        _conv("b", [_cli("faz video chamada?"), _ia("são 250 sim", estado="Triagem")]),  # suspeita
        _conv("c", [_cli("oi"), _ia("oi amor", estado="Triagem")]),  # limpo
    ]
    r = inv.gate_de_invariantes(lote)
    assert len(r["violacoes"]) == 1
    assert len(r["suspeitas"]) == 1
    assert set(r["invariantes"]) == _CHAVES_ESPERADAS
