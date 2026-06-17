"""Belief-state derivado da FSM da extração (state-update prompting).

`derivar_belief_state` e `_proxima_transicao` compartilham a MESMA tabela de pré-condições
(`_PRECONDICOES_TRANSICAO`) — estes testes provam (a) o que cada estado expõe como faltante /
próximo passo e (b) a consistência fonte-única: o belief só fica "sem faltantes" exatamente
quando a FSM dispararia a transição. Puro, sem DB.
"""

from datetime import date, time

import pytest

from barra.agente.persona import render_contexto_dinamico
from barra.dominio.atendimentos.service import (
    _PRECONDICOES_TRANSICAO,
    _proxima_transicao,
    derivar_belief_state,
)

_HORA = time(15, 0)


def test_novo_sem_intencao_falta_entender() -> None:
    b = derivar_belief_state(
        estado="Novo", intencao=None, tipo_atendimento=None, horario_desejado=None
    )
    assert b.proxima_transicao is None
    assert b.slots_faltantes == ["o que ele procura"]
    assert b.proximo_passo == "entender o que ele procura e puxar pro encontro"


def test_novo_com_intencao_promove_triagem() -> None:
    b = derivar_belief_state(
        estado="Novo", intencao="curiosidade", tipo_atendimento=None, horario_desejado=None
    )
    assert b.proxima_transicao == "Triagem"
    assert b.slots_faltantes == []


def test_triagem_curiosidade_falta_querer_marcar() -> None:
    # Horário deixou de ser slot de Triagem (virou o limiar de Aguardando_confirmacao): Triagem
    # cobra intenção real + o tipo ("dado mínimo"), nunca a hora.
    b = derivar_belief_state(
        estado="Triagem", intencao="curiosidade", tipo_atendimento=None, horario_desejado=None
    )
    assert b.proxima_transicao is None
    assert "ele querer mesmo marcar" in b.slots_faltantes
    assert "que horas ele quer" not in b.slots_faltantes


def test_qualificado_so_falta_horario() -> None:
    # tipo preenchido (externo), horário ainda não: só o horário entra em faltantes (não o tipo).
    b = derivar_belief_state(
        estado="Qualificado",
        intencao="agendamento",
        tipo_atendimento="externo",
        horario_desejado=None,
    )
    assert b.proxima_transicao is None
    assert b.slots_faltantes == ["que horas ele quer"]


def test_qualificado_completo_nada_falta_e_promove() -> None:
    b = derivar_belief_state(
        estado="Qualificado",
        intencao="agendamento",
        tipo_atendimento="interno",
        horario_desejado=_HORA,
    )
    assert b.proxima_transicao == "Aguardando_confirmacao"
    assert b.slots_faltantes == []


def test_externo_uber_promove_sem_cliente_busca() -> None:
    # cliente_busca não é condição: externo com horário promove igual aos demais (espelha o
    # comportamento histórico de _decidir_transicao).
    b = derivar_belief_state(
        estado="Qualificado",
        intencao="agendamento",
        tipo_atendimento="externo",
        horario_desejado=_HORA,
    )
    assert b.proxima_transicao == "Aguardando_confirmacao"


def test_estado_none_belief_neutro() -> None:
    b = derivar_belief_state(
        estado=None, intencao=None, tipo_atendimento=None, horario_desejado=None
    )
    assert b.proxima_transicao is None
    assert b.slots_faltantes == []
    assert b.proximo_passo == "conduzir o atendimento"


# --- consistência fonte-única (o teste-chave contra divergência) ---------------------------------

_ESTADOS = ["Novo", "Triagem", "Qualificado", "Aguardando_confirmacao", "Confirmado", None]
_INTENCOES = [None, "curiosidade", "cotacao", "agendamento"]
_TIPOS = [None, "interno", "externo", "remoto"]
_HORARIOS = [None, _HORA]


@pytest.mark.parametrize("estado", _ESTADOS)
@pytest.mark.parametrize("intencao", _INTENCOES)
@pytest.mark.parametrize("tipo", _TIPOS)
@pytest.mark.parametrize("horario", _HORARIOS)
def test_belief_consistente_com_fsm(
    estado: str | None, intencao: str | None, tipo: str | None, horario: time | None
) -> None:
    kwargs = dict(estado=estado, intencao=intencao, tipo_atendimento=tipo, horario_desejado=horario)
    b = derivar_belief_state(**kwargs)  # type: ignore[arg-type]
    fsm = _proxima_transicao(**kwargs)  # type: ignore[arg-type]
    # 1. o belief reporta exatamente a transição da FSM (mesma fonte).
    assert b.proxima_transicao == fsm
    # 2. bicondicional só para estados COM transição automática definida: sem faltantes <=> FSM
    #    dispara. Estados fora da tabela não têm "faltantes" no sentido da FSM (lista vazia).
    if estado in _PRECONDICOES_TRANSICAO:
        assert (b.slots_faltantes == []) == (fsm is not None)
    else:
        assert b.slots_faltantes == []


# --- render do template (markup ativo) ----------------------------------------------------------


def _render(estado: str, **over: object) -> str:
    b = derivar_belief_state(
        estado=estado,
        intencao=over.pop("intencao", "agendamento"),  # type: ignore[arg-type]
        tipo_atendimento=over.get("tipo_atendimento"),  # type: ignore[arg-type]
        horario_desejado=over.get("horario_desejado"),  # type: ignore[arg-type]
    )
    return render_contexto_dinamico(
        numero_curto=7,
        estado=estado,
        slots_faltantes=b.slots_faltantes,
        proximo_passo=b.proximo_passo,
        pix_status="não aplicável",
        **over,
    )


def test_render_slot_vazio_aparece_explicito() -> None:
    # Em Qualificado com o tipo combinado e a hora ainda não: a hora é o slot faltante explícito
    # (horário virou limiar de Aguardando_confirmacao, não mais de Triagem).
    out = _render("Qualificado", tipo_atendimento="interno", horario_desejado=None)
    assert "<situacao_do_atendimento" in out
    assert "<ja_combinado>" in out
    assert "<interno" not in out  # sanity: tipo vai dentro de <tipo>, não como tag própria
    assert "<tipo>interno</tipo>" in out
    # o que falta NÃO é omitido — aparece como <item> dentro de <ainda_falta>.
    assert "<ainda_falta>" in out
    assert "que horas ele quer" in out
    assert "<proximo_passo>" in out
    assert "releia a última mensagem do cliente" in out


def test_render_etapa_completa_diz_nada_falta() -> None:
    out = _render("Qualificado", tipo_atendimento="interno", horario_desejado=_HORA)
    assert "tudo desta etapa já está combinado" in out


def test_render_dia_capturado_sai_de_ainda_falta_sem_as_none() -> None:
    # cliente confirmou o dia mas ainda não a hora: o dia entra em <ja_combinado>, só a hora fica
    # em <ainda_falta>, e nada renderiza "às None" (regressão do split dia/hora).
    out = _render(
        "Qualificado",
        tipo_atendimento="interno",
        data_desejada=date(2026, 6, 15),
        horario_desejado=None,
    )
    assert "<dia>2026-06-15</dia>" in out
    assert "<hora>" not in out
    assert "às None" not in out
    assert "que horas ele quer" in out  # a hora ainda falta
