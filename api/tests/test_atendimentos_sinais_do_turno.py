"""Derivacao deterministica dos sinais de qualificacao redundantes com campo estruturado.

Diagnostico E2E #5 (2026-06-09): o LLM as vezes preenche `horario_desejado` mas esquece de marcar
`informa_horario` (extracao dropa o False) — defasagem que auto-corrige no turno seguinte.
`_sinais_qualificacao_do_turno` fecha o gap espelhando o campo no boolean. Funcao pura (sem DB),
espelha o padrao de test_atendimentos_transicao_painel.

`valor_acordado` NAO deriva `aceita_valor` (atendimento #41, 24/07): ele e gravado JA NA COTACAO,
entao derivar aceite dele marcava "valor combinado" sobre um cliente que so tinha dito "obrigado".
E `limpar` REBAIXA o sinal — sem isso o merge `||` deixava `aceita_valor` como latch de mao unica.
"""

from barra.dominio.atendimentos.service import _sinais_qualificacao_do_turno


def test_valor_acordado_nao_deriva_aceita_valor() -> None:
    # #41 (24/07): `valor_acordado` e gravado na COTACAO — nao prova aceite (ver docstring).
    sinais = _sinais_qualificacao_do_turno({"valor_acordado": "800"}, set())
    assert sinais == {}


def test_horario_desejado_deriva_informa_horario() -> None:
    sinais = _sinais_qualificacao_do_turno({"horario_desejado": "22:00:00"}, set())
    assert sinais == {"informa_horario": True}


def test_t7_campos_preenchidos_sem_boolean_deriva_so_o_horario() -> None:
    # Reproduz o T7: campos cheios, LLM nao marcou os booleans -> so o horario e derivado.
    sinais = _sinais_qualificacao_do_turno(
        {"valor_acordado": "800", "horario_desejado": "10:15:00"}, set()
    )
    assert sinais == {"informa_horario": True}


def test_preserva_sinais_que_o_llm_passou() -> None:
    sinais = _sinais_qualificacao_do_turno(
        {"valor_acordado": "800", "sinais_qualificacao": {"responde_objetivamente": True}}, set()
    )
    assert sinais == {"responde_objetivamente": True}


def test_aceite_explicito_do_llm_passa_intacto() -> None:
    # A UNICA fonte de `aceita_valor` agora e o sinal explicito do extrator.
    sinais = _sinais_qualificacao_do_turno(
        {"valor_acordado": "800", "sinais_qualificacao": {"aceita_valor": True}}, set()
    )
    assert sinais == {"aceita_valor": True}


def test_limpar_horario_rebaixa_informa_horario() -> None:
    # Cliente recuou (campo no `limpar`): o sinal vai a False, nao some — o merge `||` sobrescreve,
    # entao emitir False e o que desfaz um True gravado num turno anterior.
    sinais = _sinais_qualificacao_do_turno({"horario_desejado": "22:00:00"}, {"horario_desejado"})
    assert sinais == {"informa_horario": False}


def test_limpar_valor_rebaixa_aceita_valor() -> None:
    # Recuo pos-objecao (`<conducao_da_venda>`): limpar `valor_acordado` tem que reabrir a escada
    # do desconto — sem o False o belief seguia anunciando "valor ja combinado" pra sempre (#41).
    sinais = _sinais_qualificacao_do_turno({}, {"valor_acordado"})
    assert sinais == {"aceita_valor": False}


def test_limpar_vence_o_aceite_que_o_llm_passou_no_mesmo_turno() -> None:
    # `limpar` tem precedencia sobre o payload (mesmo principio do UPSERT): o recuo explicito do
    # cliente manda, mesmo que o extrator ainda marque o aceite no mesmo turno.
    sinais = _sinais_qualificacao_do_turno(
        {"sinais_qualificacao": {"aceita_valor": True}}, {"valor_acordado"}
    )
    assert sinais == {"aceita_valor": False}


def test_sem_campo_nem_sinal_fica_vazio() -> None:
    assert _sinais_qualificacao_do_turno({"proxima_acao_esperada": "x"}, set()) == {}


def test_nao_muta_o_dict_de_sinais_do_payload() -> None:
    payload = {"valor_acordado": "800", "sinais_qualificacao": {"envia_pix": True}}
    _sinais_qualificacao_do_turno(payload, set())
    assert payload["sinais_qualificacao"] == {"envia_pix": True}  # intacto
