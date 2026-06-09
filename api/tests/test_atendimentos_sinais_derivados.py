"""Derivacao deterministica dos sinais de qualificacao redundantes com campo estruturado.

Diagnostico E2E #5 (2026-06-09): o LLM as vezes preenche `valor_acordado`/`horario_desejado`
mas esquece de marcar `aceita_valor`/`informa_horario` (extracao dropa o False) — defasagem que
auto-corrige no turno seguinte. `_sinais_qualificacao_derivados` fecha o gap espelhando o campo
no boolean. Funcao pura (sem DB), espelha o padrao de test_atendimentos_transicao_painel.
"""

from barra.dominio.atendimentos.service import _sinais_qualificacao_derivados


def test_valor_acordado_deriva_aceita_valor() -> None:
    sinais = _sinais_qualificacao_derivados({"valor_acordado": "800"}, set())
    assert sinais == {"aceita_valor": True}


def test_horario_desejado_deriva_informa_horario() -> None:
    sinais = _sinais_qualificacao_derivados({"horario_desejado": "22:00:00"}, set())
    assert sinais == {"informa_horario": True}


def test_t7_campos_preenchidos_sem_boolean_deriva_ambos() -> None:
    # Reproduz o T7: campos cheios, LLM nao marcou os booleans -> derivados devem suprir.
    sinais = _sinais_qualificacao_derivados(
        {"valor_acordado": "800", "horario_desejado": "10:15:00"}, set()
    )
    assert sinais == {"aceita_valor": True, "informa_horario": True}


def test_preserva_sinais_que_o_llm_passou() -> None:
    sinais = _sinais_qualificacao_derivados(
        {"valor_acordado": "800", "sinais_qualificacao": {"responde_objetivamente": True}}, set()
    )
    assert sinais == {"responde_objetivamente": True, "aceita_valor": True}


def test_limpar_campo_nao_deriva_sinal() -> None:
    # Cliente recuou (campo no `limpar`): nao reafirma o sinal como True.
    sinais = _sinais_qualificacao_derivados({"horario_desejado": "22:00:00"}, {"horario_desejado"})
    assert sinais == {}


def test_sem_campo_nem_sinal_fica_vazio() -> None:
    assert _sinais_qualificacao_derivados({"proxima_acao_esperada": "x"}, set()) == {}


def test_nao_muta_o_dict_de_sinais_do_payload() -> None:
    payload = {"valor_acordado": "800", "sinais_qualificacao": {"envia_pix": True}}
    _sinais_qualificacao_derivados(payload, set())
    assert payload["sinais_qualificacao"] == {"envia_pix": True}  # intacto
