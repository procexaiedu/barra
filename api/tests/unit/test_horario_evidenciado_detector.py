"""Detector determinístico do horário EVIDENCIADO (spec extracao-proveniencia-horario).

Unit puro (sem DB, sem LLM): a tabela de falas do corpus contra o booleano esperado.
Dois níveis:
  - `contem_hora_explicita` (agente/_disciplina.py) — a regex crua sobre UMA fala;
  - `_horario_evidenciado_no_turno` (nos/prepare_context.py) — os três gatilhos sobre a janela:
    hora explícita na fala do cliente, confirmação curta logo após bolha da IA com hora, e o
    aceite da sondagem de imediatismo ("Seria agora ?" → "sim").
"""

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente._disciplina import contem_hora_explicita
from barra.agente.nos.prepare_context import _horario_evidenciado_no_turno


def _ia(texto: str) -> AIMessage:
    return AIMessage(content=texto)


def _cli(texto: str) -> HumanMessage:
    return HumanMessage(content=texto)


# --- contem_hora_explicita: positivos (falas reais do corpus) ---


def test_hora_com_minuto_e_hora_cheia_com_marcador():
    for fala in (
        "Umas 16 horas",  # #24
        "Tipo 18h, 18h15",  # #34
        "Consigo às 17:30",  # bolha da IA do #34
        "Posso confirmar às 18h",  # bolha da IA do #34
        "daqui 1h",
        "daqui a 1h",
        "pode ser 2h então",  # promoção tardia a partir do #25
        "meio dia",
        "meia noite",
        "por volta das 22h",
        "as 20hs",
        "depois das 23 horas",
    ):
        assert contem_hora_explicita(fala) is True, fala


# --- contem_hora_explicita: negativos que enganam ---


def test_negativos_do_corpus():
    for fala in (
        "Não conheço",  # respondendo "Campinas?" — não é hora (#41)
        "Campinas?",
        "600",
        "1000 fecha?",
        "quanto é 1h?",  # duração de programa, não horário
        "600 1h no meu local",  # cotação da IA: o "1h" é a duração vendida
        "faz oral sem camisinha?",
        "vc topa menage?",
        "manda foto",
        "",
    ):
        assert contem_hora_explicita(fala) is False, fala


# --- _horario_evidenciado_no_turno: os três gatilhos ---


def test_gatilho_hora_explicita_na_fala_do_cliente():
    # #24: "Umas 16 horas" — o cliente cravou a hora.
    msgs = [_ia("que horas você quer amor?"), _cli("Umas 16 horas")]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_gatilho_confirmacao_curta_apos_bolha_da_ia_com_hora():
    # #34: a IA propõe "Posso confirmar às 18h" e ele responde "Perfeito".
    msgs = [_cli("Tipo 18h, 18h15"), _ia("Posso confirmar às 18h 🥰"), _cli("Perfeito")]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_gatilho_sondagem_de_imediatismo_aceita():
    # #35: o número veio do fallback (horario_minimo), mas a intenção é dele — "Seria agora ?"/"sim".
    msgs = [_ia("Seria agora ?"), _cli("sim")]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_sondagem_do_dia_aceita_nao_evidencia_a_hora():
    # "Seria hoje ?" + "sim" crava o DIA, não a HORA: aceitar isso carimbaria evidência sobre o
    # horário que o fallback sintetizou — o #25 voltando por outra porta. (O par segue valendo p/
    # a captura do dia e p/ o piso de intenção, que leem `sondagem_aceita`.)
    msgs = [_ia("Seria hoje ?"), _cli("sim")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_confirmacao_curta_sem_hora_na_bolha_da_ia_nao_evidencia():
    msgs = [_ia("quer que eu te mande uma foto? 😊"), _cli("pode")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_caso_25_cliente_ignora_a_sondagem():
    # #25 (23/07): a IA sondou, ele mudou de assunto. O horário é gravado pelo fallback, mas NÃO
    # é evidenciado — é exatamente o palpite que a IA passou a tratar como "pedido dele".
    msgs = [_ia("Seria agora ?"), _cli("vc faz oral sem camisinha?")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_hora_dita_pela_ia_sozinha_nao_evidencia():
    # A IA falar hora não é evidência: quem sustenta o horário é o cliente.
    msgs = [_cli("oi"), _ia("Consigo às 17:30 amor")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_burst_de_varias_bolhas_do_cliente():
    # O cliente manda em bolhas separadas; a hora está numa delas.
    msgs = [_ia("que horas?"), _cli("olha"), _cli("umas 16 horas")]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_hora_antiga_do_cliente_fora_do_burst_nao_reevidencia():
    # A evidência é EVENTO do turno (como o piso de intenção): a hora dita 4 turnos atrás não
    # revalida o valor que o sistema mudou depois. O que preserva a marca é a persistência.
    msgs = [_cli("umas 16 horas"), _ia("fechou 🥰"), _cli("e você faz massagem?")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_janela_vazia_ou_ultima_fala_da_ia():
    assert _horario_evidenciado_no_turno([]) is False
    assert _horario_evidenciado_no_turno([_cli("umas 16 horas"), _ia("fechou")]) is False
