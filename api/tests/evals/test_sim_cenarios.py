"""Prova invariantes PUROS do conjunto de cenarios E2E (EVAL-12) -- sem DB/LLM/rede.

`cenarios.py` faz `from .cliente import PersonaCliente` (import relativo), entao -- diferente de
cliente.py/judge.py -- nao da pra carregar por caminho solto: importamos como namespace package
`evals.sim.*` com `api/` no sys.path. Isso tambem prova "cenarios.py importa sem DB" (cliente.py so
toca `barra`/rede dentro de `decidir`, nunca no import).

Invariantes:
- ANTI-LEAKAGE: nenhuma persona carrega termo de gabarito -- `montar_prompt_cliente` nao levanta.
- CONSISTENCIA: todo ato que um roteiro pode disparar foi declarado em `atos_disponiveis`.
- ROTEIROS sao funcoes puras (do indice/estado) com a temporizacao esperada.
"""

import importlib
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

cenarios = importlib.import_module("evals.sim.cenarios")
cliente = importlib.import_module("evals.sim.cliente")

# atendimentos sem ato dual-control: terminam em recusa/escala (puramente adversariais), nao em
# handoff por Pix/portaria. Documenta a intencao -- e o complemento dos que FECHAM via ato.
_PURAMENTE_ADVERSARIAIS = {"desconfiado_ia", "videocall_cartao", "desconto_abaixo_piso"}

_ESTADOS = ["Triagem", "Qualificado", "Aguardando_confirmacao", "Confirmado", "Em_execucao"]


def _ids(cen):
    return cen.nome


@pytest.mark.parametrize("cen", cenarios.CENARIOS, ids=_ids)
def test_persona_nao_vaza_gabarito(cen):
    # a fronteira anti-leakage (montar_prompt_cliente) RECUSA persona com termo de gabarito; se
    # qualquer cenario novo tivesse colado uma expectativa no texto, isto levantaria ValueError.
    msgs = cliente.montar_prompt_cliente(cen.persona, [])
    blob = "\n".join(m["content"] for m in msgs).lower()
    assert cen.persona.o_que_quer.lower() in blob
    for termo in cliente._TERMOS_DE_GABARITO:
        assert termo not in blob


def test_nomes_unicos():
    nomes = [c.nome for c in cenarios.CENARIOS]
    assert len(nomes) == len(set(nomes))


def test_tamanho_do_set_no_intervalo_combinado():
    # decisao de produto: ~14-19 cenarios equilibrados (cobertura da fronteira sem rotulagem brutal).
    # +1 com a F4.2 (`interno_fecha_venda`, ate Fechado); +1 com a F4.3 (`interno_some_perdido`, Perdido);
    # +1 com a F4.4 (`interno_lembrete_fecha`, Fechado pela cobranca proativa).
    assert 14 <= len(cenarios.CENARIOS) <= 19


@pytest.mark.parametrize("cen", cenarios.CENARIOS, ids=_ids)
def test_roteiro_so_dispara_atos_declarados(cen):
    # um roteiro nunca pode pedir um ato que a persona nao declarou em atos_disponiveis (senao
    # _aplicar_ato muta um estado que o cliente nao "tem" como acao). Varre indices x estados.
    if cen.decidir_ato is None:
        assert cen.nome in _PURAMENTE_ADVERSARIAIS or cen.persona.atos_disponiveis
        return
    declarados = set(cen.persona.atos_disponiveis)
    for indice in range(cen.max_turnos + 2):
        for estado in _ESTADOS:
            ato = cen.decidir_ato(indice, {"estado": estado, "ia_pausada": False})
            if ato is not None:
                assert ato in declarados, f"{cen.nome}: roteiro disparou {ato!r} nao declarado"


def test_puramente_adversariais_nao_tem_roteiro():
    # os puramente adversariais nao fecham por ato; terminam em recusa/escala no max_turnos.
    for cen in cenarios.CENARIOS:
        if cen.nome in _PURAMENTE_ADVERSARIAIS:
            assert cen.decidir_ato is None


# --- pureza/temporizacao dos roteiros ----------------------------------------------------------


def test_roteiro_pix_dispara_a_partir_do_indice_ate_confirmado():
    r = cenarios._roteiro_pix("enviar_pix_valido", a_partir=5)
    assert r(4, {"estado": "Qualificado"}) is None
    assert r(5, {"estado": "Qualificado"}) == "enviar_pix_valido"
    assert r(6, {"estado": "Confirmado"}) is None  # ja fechou -> nao repete


def test_roteiro_portaria_aviso_e_foto_no_estado_certo():
    r = cenarios._roteiro_portaria()  # defaults aviso_em=2, portaria_em=4 (comportamento legado)
    assert r(2, {"estado": "Triagem"}) == "enviar_aviso_saida"
    assert r(4, {"estado": "Aguardando_confirmacao"}) == "enviar_foto_portaria"
    # foto so vale em Aguardando_confirmacao (interno) -- fora disso, espera
    assert r(4, {"estado": "Triagem"}) is None
    assert r(3, {"estado": "Aguardando_confirmacao"}) is None  # antes de portaria_em


def test_roteiro_portaria_parametrizavel():
    r = cenarios._roteiro_portaria(aviso_em=6, portaria_em=8)
    assert r(6, {"estado": "Triagem"}) == "enviar_aviso_saida"
    assert r(2, {"estado": "Aguardando_confirmacao"}) is None
    assert r(9, {"estado": "Aguardando_confirmacao"}) == "enviar_foto_portaria"  # primeiro >= 8


def test_roteiro_portaria_sem_aviso():
    # aviso_em=None: probe que nao precisa do "sai de casa" -> so a foto de portaria fecha.
    r = cenarios._roteiro_portaria(aviso_em=None, portaria_em=6)
    for i in range(12):
        assert r(i, {"estado": "Aguardando_confirmacao"}) != "enviar_aviso_saida"
    assert r(5, {"estado": "Aguardando_confirmacao"}) is None
    assert r(6, {"estado": "Aguardando_confirmacao"}) == "enviar_foto_portaria"


def test_roteiro_some_e_volta_silencia_depois_fecha():
    r = cenarios._roteiro_some_e_volta
    assert r(3, {"estado": "Qualificado"}) == "ficar_em_silencio"
    assert r(5, {"estado": "Qualificado"}) is None  # voltou, ainda combinando
    assert r(7, {"estado": "Aguardando_confirmacao"}) == "enviar_foto_portaria"
    assert r(7, {"estado": "Qualificado"}) is None  # foto so em Aguardando_confirmacao
