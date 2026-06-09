"""Prova invariantes PUROS do cliente FIXO e do conjunto de conversas roteirizadas (EVAL-12).

Sem DB/LLM/rede: `cenarios_fixos.py` so importa `cenarios`/`cliente` (que so tocam `barra`/rede
dentro de `ClienteSimulado.decidir`, nunca no import) e `cliente_fixo.py` nao chama LLM em lugar
nenhum. Como `test_sim_cenarios`, carregamos como namespace package `evals.sim.*` com `api/` no
sys.path (os modulos usam imports relativos, nao da pra carregar por caminho solto).

Invariantes:
- `ClienteRoteirizado` devolve as falas NA ORDEM e, esgotado, a `mensagem_padrao` ("?"). Sem LLM.
- ANTI-LEAKAGE: nenhuma fala fixa carrega termo de gabarito (nunca embute o veredito esperado).
- CONSISTENCIA: todo ato que um roteiro pode disparar foi declarado em `atos_disponiveis`.
- TAMANHO/UNICIDADE do conjunto; toda conversa tem ao menos uma fala de cliente.
"""

import importlib
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

cenarios_fixos = importlib.import_module("evals.sim.cenarios_fixos")
cliente = importlib.import_module("evals.sim.cliente")
cliente_fixo = importlib.import_module("evals.sim.cliente_fixo")

# iteração + held-out: os invariantes (anti-leakage, falas, atos) valem para TODOS os fixos.
_TODOS = cenarios_fixos.todos_fixos()

# conversas sem roteiro de ato: adversariais que terminam em recusa/escala (videocall, abaixo do
# piso), nao em handoff por Pix/portaria. Complemento dos que FECHAM via ato.
_SEM_ATO = {"fixo_004_videocall_cartao", "fixo_var_desconto_abaixo_piso"}

_ESTADOS = ["Triagem", "Qualificado", "Aguardando_confirmacao", "Confirmado", "Em_execucao"]


def _ids(cen):
    return cen.nome


async def test_cliente_roteirizado_entrega_na_ordem_e_esgota():
    roteiro = cliente_fixo.ClienteRoteirizado(["oi", "quanto e?", "fechou"])
    assert (await roteiro.decidir([])).mensagem == "oi"
    assert (await roteiro.decidir(["resposta da ia"])).mensagem == "quanto e?"
    assert (await roteiro.decidir([])).mensagem == "fechou"
    # esgotado -> mensagem_padrao "?" (cliente impaciente real), nunca um ato.
    esgotado = await roteiro.decidir([])
    assert esgotado.mensagem == "?"
    assert esgotado.ato is None


async def test_cliente_roteirizado_ignora_historico():
    # o roteiro e fixo: a proxima fala nao depende do que a IA disse (a IA e quem varia).
    a = cliente_fixo.ClienteRoteirizado(["primeira", "segunda"])
    b = cliente_fixo.ClienteRoteirizado(["primeira", "segunda"])
    assert (await a.decidir([])).mensagem == (await b.decidir(["qualquer coisa"])).mensagem


def test_nomes_unicos():
    nomes = [c.nome for c in _TODOS]
    assert len(nomes) == len(set(nomes))


def test_tamanho_dos_conjuntos():
    # iteração: conjunto enxuto p/ rotulagem barata (4 reais 001..004 + variacoes + jornadas F4.x).
    assert 6 <= len(cenarios_fixos.CENARIOS_FIXOS) <= 11
    # held-out: medição de generalização -- pequeno e disjunto.
    assert 2 <= len(cenarios_fixos.CENARIOS_FIXOS_HELDOUT) <= 6


def test_heldout_disjunto_da_iteracao():
    # o held-out NUNCA pode entrar na iteração (senão deixa de medir generalização -- vira overfit).
    iteracao = {c.nome for c in cenarios_fixos.CENARIOS_FIXOS}
    held = {c.nome for c in cenarios_fixos.CENARIOS_FIXOS_HELDOUT}
    assert iteracao.isdisjoint(held)


@pytest.mark.parametrize("cen", _TODOS, ids=_ids)
def test_conversa_tem_falas_de_cliente(cen):
    assert cen.mensagens_cliente, f"{cen.nome}: sem falas de cliente"
    assert all(m.strip() for m in cen.mensagens_cliente), f"{cen.nome}: fala vazia"


@pytest.mark.parametrize("cen", _TODOS, ids=_ids)
def test_falas_nao_vazam_gabarito(cen):
    # falas sao do CLIENTE realista; nunca embutem o veredito/gabarito esperado (RealUserSim).
    blob = "\n".join(cen.mensagens_cliente).lower()
    for termo in cliente._TERMOS_DE_GABARITO:
        assert termo not in blob, f"{cen.nome}: fala carrega termo de gabarito {termo!r}"


@pytest.mark.parametrize("cen", _TODOS, ids=_ids)
def test_roteiro_so_dispara_atos_declarados(cen):
    # um roteiro nunca pode pedir um ato que o cenario nao declarou em atos_disponiveis (senao
    # _aplicar_ato muta um estado que o cliente nao "tem" como acao). Varre indices x estados.
    if cen.decidir_ato is None:
        assert cen.nome in _SEM_ATO or cen.atos_disponiveis
        return
    declarados = set(cen.atos_disponiveis)
    for indice in range(cen.max_turnos + 2):
        for estado in _ESTADOS:
            ato = cen.decidir_ato(indice, {"estado": estado, "ia_pausada": False})
            if ato is not None:
                assert ato in declarados, f"{cen.nome}: roteiro disparou {ato!r} nao declarado"


def test_conversas_sem_ato_nao_tem_roteiro():
    # as adversariais (recusa/escala) nao fecham por ato; terminam no max_turnos.
    for cen in _TODOS:
        if cen.nome in _SEM_ATO:
            assert cen.decidir_ato is None
