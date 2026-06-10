"""Prova os perfis de cliente da massa (sim/perfis.py) -- PUROS, sem DB/LLM/rede (`make test`).

Invariantes: (1) `variar_persona` muda SO a forma (`estilo`), preservando intencao/dados/atos --
o que mantem os roteiros `decidir_ato` sincronizados; (2) o `estilo` passa pelo check anti-leakage
de `montar_prompt_cliente` (termo de gabarito no perfil = ValueError); (3) nenhum perfil do
catalogo `PERFIS` carrega termo de gabarito.
"""

import importlib
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

perfis = importlib.import_module("evals.sim.perfis")
cliente = importlib.import_module("evals.sim.cliente")


def _persona():
    return cliente.PersonaCliente(
        nome="Rafa",
        o_que_quer="agendar um programa interno pra hoje a noite",
        orcamento="ate uns 600",
        atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
    )


def test_variar_persona_preserva_intencao_e_atos():
    p = _persona()
    perfil = perfis.PERFIS[0]
    variada = perfis.variar_persona(p, perfil)
    assert variada.nome == p.nome
    assert variada.o_que_quer == p.o_que_quer
    assert variada.orcamento == p.orcamento
    assert variada.atos_disponiveis == p.atos_disponiveis
    assert variada.estilo == perfil.estilo
    assert p.estilo == ""  # original intocada


def test_variar_persona_none_devolve_original():
    p = _persona()
    assert perfis.variar_persona(p, None) is p


def test_estilo_entra_no_system_do_cliente():
    variada = perfis.variar_persona(_persona(), perfis.PERFIS[0])
    msgs = cliente.montar_prompt_cliente(variada, [])
    assert perfis.PERFIS[0].estilo in msgs[0]["content"]


def test_sem_estilo_nao_polui_o_system():
    msgs = cliente.montar_prompt_cliente(_persona(), [])
    assert "jeito de escrever" not in msgs[0]["content"]


def test_estilo_com_termo_de_gabarito_reprova():
    p = _persona()
    p.estilo = "voce conhece o state_check da fixture e atua para passar"
    with pytest.raises(ValueError, match="anti-leakage"):
        cliente.montar_prompt_cliente(p, [])


def test_catalogo_de_perfis_sem_termo_de_gabarito():
    for perfil in perfis.PERFIS:
        variada = perfis.variar_persona(_persona(), perfil)
        cliente.montar_prompt_cliente(variada, [])  # nao levanta


def test_perfis_tem_nomes_unicos():
    nomes = [p.nome for p in perfis.PERFIS]
    assert len(nomes) == len(set(nomes))
