"""Prova a logica PURA da rodada em massa (sim/massa.py) -- sem DB/LLM/rede (`make test`).

Cobre: composicao deterministica do plano (k_robo x cenarios + fixos + held-out, ids unicos),
o budget guard (GuardaOrcamento), a soma de custo por jornada (IA + cliente-LLM) e a serializacao
ADITIVA (`_serializar` com conversa_id/extras preserva o comportamento default do Loop A).
"""

import importlib
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

massa = importlib.import_module("evals.sim.massa")
loop = importlib.import_module("evals.sim.loop")
gerar = importlib.import_module("evals.sim.gerar_conversas")
cenarios_mod = importlib.import_module("evals.sim.cenarios")
fixos_mod = importlib.import_module("evals.sim.cenarios_fixos")

_N_ROBO = len(cenarios_mod.CENARIOS)
_N_FIXOS = len(fixos_mod.CENARIOS_FIXOS)
_N_HELDOUT = len(fixos_mod.CENARIOS_FIXOS_HELDOUT)


# --- montar_plano ---------------------------------------------------------------------------------


def test_plano_default_composicao_completa():
    plano = massa.montar_plano()
    assert len(plano) == _N_ROBO * 2 + _N_FIXOS + _N_HELDOUT
    ids = [it.conversa_id for it in plano]
    assert len(ids) == len(set(ids)), "ids de amostra devem ser unicos"
    assert all("#k" in cid for cid in ids)


def test_plano_k0_sem_perfil_k1_com_perfil():
    plano = [it for it in massa.montar_plano(k_robo=2) if it.tipo == "robo"]
    k0 = [it for it in plano if it.conversa_id.endswith("#k0")]
    k1 = [it for it in plano if it.conversa_id.endswith("#k1")]
    assert all(it.perfil is None for it in k0), "k0 = persona original"
    assert all(it.perfil is not None for it in k1), "k1+ = perfil rotacionado"


def test_plano_deterministico_por_semente():
    a = massa.montar_plano(semente=3)
    b = massa.montar_plano(semente=3)
    assert [(it.conversa_id, it.perfil) for it in a] == [(it.conversa_id, it.perfil) for it in b]
    c = massa.montar_plano(semente=4)
    assert [it.perfil for it in a] != [it.perfil for it in c], "semente redistribui perfis"


def test_plano_filtro_por_cenario_e_exclusoes():
    plano = massa.montar_plano(
        k_robo=1,
        incluir_fixos=False,
        incluir_heldout=False,
        nomes=[cenarios_mod.CENARIOS[0].nome],
    )
    assert len(plano) == 1
    assert plano[0].tipo == "robo"
    with pytest.raises(ValueError, match="nenhum cenario"):
        massa.montar_plano(nomes=["nao_existe"])


# --- GuardaOrcamento e custo ----------------------------------------------------------------------


def test_guarda_orcamento_acumula_e_estoura():
    g = massa.GuardaOrcamento(teto_brl=1.0)
    g.registrar(0.4)
    assert not g.estourou
    g.registrar(None)  # jornada sem usage medivel: no-op
    assert g.acumulado_brl == pytest.approx(0.4)
    g.registrar(0.6)
    assert g.estourou


def _passo(custo=None, **kw):
    return loop.PassoJornada(
        indice=0,
        acao_mensagem="oi",
        acao_ato=None,
        bolha_ia="oi amor",
        estado_atendimento="Triagem",
        ia_pausada=False,
        custo_brl=custo,
        **kw,
    )


def test_custo_da_jornada_soma_ia_e_cliente():
    traj = loop.Trajetoria(passos=[_passo(0.10), _passo(None), _passo(0.05)])

    class _Cliente:
        custo_brl_acumulado = 0.07

    assert massa.custo_da_jornada(traj, _Cliente()) == pytest.approx(0.22)
    # cliente roteirizado (sem acumulador) -> so a IA conta
    assert massa.custo_da_jornada(traj, object()) == pytest.approx(0.15)


# --- _serializar aditivo (default do Loop A intocado) -----------------------------------------------


class _CenarioFake:
    nome = "cenario_x"


def test_serializar_default_preserva_comportamento():
    traj = loop.Trajetoria(passos=[_passo(0.10, cache_hit_rate=0.8)])
    conversa = gerar._serializar(_CenarioFake(), traj)
    assert conversa["conversa_id"] == "cenario_x"
    assert conversa["cenario"] == "cenario_x"
    assert set(conversa) == {"conversa_id", "cenario", "turnos"}
    turno_ia = next(t for t in conversa["turnos"] if t["papel"] == "ia")
    assert turno_ia["custo_brl"] == pytest.approx(0.10)
    assert turno_ia["cache_hit_rate"] == pytest.approx(0.8)


def test_serializar_com_conversa_id_e_extras():
    traj = loop.Trajetoria(passos=[_passo()])
    conversa = gerar._serializar(
        _CenarioFake(),
        traj,
        conversa_id="cenario_x#k1",
        extras={"tipo": "robo", "perfil": "regateiro"},
    )
    assert conversa["conversa_id"] == "cenario_x#k1"
    assert conversa["cenario"] == "cenario_x"
    assert conversa["tipo"] == "robo"
    assert conversa["perfil"] == "regateiro"
