"""Prova o invariante PURO anti-leakage do cliente simulado (EVAL-12 / RealUserSim).

Nao toca DB/LLM/rede -- roda no `make test`/CI sem credenciais. `cliente.py` mora em evals/ (fora
do pacote `barra`), entao carregamos por caminho via importlib (igual test_runner_gate.py). O
`decidir` (chamada real ao Sonnet) e needs_anthropic_api e nao e exercido aqui.

Invariante: o cliente simulado NUNCA pode ver o gabarito/expectativas da fixture -- so intencao +
dados + o que observa. `montar_prompt_cliente` e a fronteira que garante isso.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CLIENTE = Path(__file__).resolve().parents[1].parent / "evals" / "sim" / "cliente.py"


def _carregar_cliente() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_sim_cliente", _CLIENTE)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


cliente = _carregar_cliente()


def _persona():
    return cliente.PersonaCliente(
        nome="Rafa",
        o_que_quer="agendar um programa interno pra hoje a noite",
        orcamento="ate uns 600",
        atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
    )


# --- o gabarito secreto NUNCA aparece no prompt ------------------------------------------------


def test_prompt_nunca_contem_gabarito_secreto():
    # gabarito que a fixture teria, mas que o cliente JAMAIS pode ver.
    gabarito_secreto = "CANARY-GABARITO-9Z8Y7X"
    persona = _persona()
    historico = ["amor, hoje a noite eu consigo sim", "que horas voce pensa em vir?"]
    msgs = cliente.montar_prompt_cliente(persona, historico)
    blob = "\n".join(m["content"] for m in msgs)
    assert gabarito_secreto not in blob
    # o que ele OBSERVA (bolhas da IA) e a intencao entram; nada mais.
    assert "que horas voce pensa em vir?" in blob
    assert persona.o_que_quer in blob


def test_prompt_recusa_persona_com_termo_de_gabarito():
    # se um termo de gabarito escapou para a persona, montar_prompt_cliente RECUSA (defesa em prof.).
    persona = cliente.PersonaCliente(
        nome="Rafa",
        o_que_quer="quero o tool_calls_obrigatorias do gate",  # vazou
        orcamento="600",
    )
    with pytest.raises(ValueError, match="anti-leakage"):
        cliente.montar_prompt_cliente(persona, [])


@pytest.mark.parametrize(
    "termo",
    [
        "expectativas",
        "nao_deve_conter",
        "isolamento_canary",
        "state_check",
        "nodes_proibidos",
        "limiar_aceite",
    ],
)
def test_prompt_recusa_cada_termo_de_gabarito(termo):
    persona = cliente.PersonaCliente(nome="X", o_que_quer=f"falar de {termo}", orcamento="100")
    with pytest.raises(ValueError):
        cliente.montar_prompt_cliente(persona, [])


# --- a PersonaCliente nao expoe campo de gabarito ----------------------------------------------


def test_persona_cliente_nao_tem_campo_de_gabarito():
    campos = set(cliente.PersonaCliente.__dataclass_fields__)
    # `estilo` (perfis.py) e variacao de FORMA, nao gabarito -- e passa pelo mesmo check
    # anti-leakage do montar_prompt_cliente (ver test_perfis_anti_leakage.py).
    assert campos == {"nome", "o_que_quer", "orcamento", "atos_disponiveis", "estilo"}
    # nenhum nome de campo sugere gabarito/expectativa.
    assert not any("gabarito" in c or "expectativa" in c or "esperado" in c for c in campos)


# --- estrutura minima do prompt ----------------------------------------------------------------


def test_prompt_tem_system_e_user_e_nao_diz_que_testa():
    msgs = cliente.montar_prompt_cliente(_persona(), [])
    assert [m["role"] for m in msgs] == ["system", "user"]
    # o cliente nao sabe que esta num teste nem se o outro lado e IA (RealUserSim).
    system = msgs[0]["content"].lower()
    assert "nao esta testando" in system
    assert "primeira mensagem" in msgs[1]["content"].lower()  # sem historico -> inicia a conversa
