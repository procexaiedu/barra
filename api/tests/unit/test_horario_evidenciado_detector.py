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
from barra.agente.nos._janela_do_turno import _horario_evidenciado_no_turno


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


def test_falas_reais_que_o_marcador_fechado_perdia() -> None:
    """Diagnóstico 11/08 (P0-2): das 9 falas com hora dos traces, 5 não casavam a lista fechada de
    marcadores — e o belief então AFIRMAVA "palpite seu, ele não confirmou" sobre uma hora que o
    cliente cravou três vezes, mandando re-ofertar em plena fase de fechamento (agenda_local
    t3-t5, traces 648d7f6f / a9f0378a / 95a9935e)."""
    for fala in (
        "pode ser no seu local então, hoje 21h. me passa o endereço",
        "pras 22h de hoje",
        "21h então rola",
        "fechou, 21h to ai",
        "hoje 21h com a inversao entao",
    ):
        assert contem_hora_explicita(fala) is True, fala


def test_marcador_de_dia_cobre_amanha_e_dia_da_semana() -> None:
    for fala in ("amanhã 14h", "sexta 22h", "dia 12 19h", "hj 20h"):
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


def test_duracao_em_contexto_de_preco_nao_vira_horario() -> None:
    """O empate hora-vs-duração é o que mantinha o marcador fechado (#25). As famílias LARGAS
    (dia, "pra/pras", verbo de fechamento) são vetadas por contexto de preço na mesma bolha —
    senão a cotação da IA ("600 1h no meu local, fechamos ?") passaria a evidenciar horário."""
    for fala in (
        "quanto pra 1h?",
        "quanto é pra 2 horas?",
        "600 1h no meu local, fechamos ?",
        "o valor de 1h é 400, fechado ?",
        "hoje o de 1h sai 400",
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
    # a captura do dia, `_confirmou_dia_hoje`.)
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


def test_hora_da_agenda_dele_na_remarcacao() -> None:
    """3a geração (12/08, roteiro `remarcou`): remarcando, o cliente fala pela agenda DELE — sem
    marcador, sem dia, sem verbo de fechamento. A hora nova não era evidenciada e a conversa morria
    numa escalada em 5 de 5 conversas."""
    for fala in (
        "amor, deu ruim aqui, consigo so 22h. pode?",
        "só consigo 21h",
        "chego 19h",
        "me libero 20h",
        "22h pode?",
        "18h serve?",
    ):
        assert contem_hora_explicita(fala) is True, fala


def test_hora_da_agenda_dele_nao_confunde_duracao_com_relogio() -> None:
    """O que torna a família acima segura: só 13-23 conta, e nenhum pacote da tabela usa essas
    durações (o mais longo é o pernoite de 12h)."""
    for fala in (
        "consigo 2h",
        "me vê 12h de pernoite",
        "quanto custa 12h?",
        "vou de 2 horas então",
    ):
        assert contem_hora_explicita(fala) is False, fala


def test_offset_relativo_em_minutos_e_hora_explicita() -> None:
    """loop-massa r1 (eixo decidido_rapido): "daki uns 40 minutos" cravou o encontro e o detector
    dizia não-evidenciado — offset em horas contava ("daqui 1h") e em minutos não, sem uma linha
    de recorte que justificasse. "daqui" torna a leitura de duração impossível por construção."""
    for fala in (
        "daqui 30 min",
        "daqui uns 40 minutos",
        "daqui a 20 minutos",
        "chego daqui umas 15 min",
        "daqui meia hora",
    ):
        assert contem_hora_explicita(fala) is True, fala


def test_minutos_sem_offset_seguem_sendo_duracao() -> None:
    # Sem o "daqui", minutos continuam duração de programa ("250 30minutos" é cotação).
    for fala in ("quanto é 30 min?", "faz 40 minutos?", "250 30 minutos"):
        assert contem_hora_explicita(fala) is False, fala


def test_offset_por_extenso_em_horas() -> None:
    """loop-massa r3: o fix C2 da r1 grafou "meia hora" por extenso e parou aí — "daqui uma hora"
    ficou de fora sem recorte que justificasse. O "daqui" mata a leitura de duração."""
    for fala in ("daqui uma hora", "daqui duas horas", "daqui a uma hora", "daqui tres horas"):
        assert contem_hora_explicita(fala) is True, fala


def test_hora_por_extenso_sem_offset_nao_e_horario() -> None:
    for fala in ("quanto e uma hora?", "uma hora 400"):
        assert contem_hora_explicita(fala) is False, fala


def test_imperativo_fecha_com_hora_inequivoca() -> None:
    """loop-massa r3 (`remarcacao` t4): "Fecha 20h" é o eco literal do empurrão que o prompt manda
    a IA usar ("Consigo às 20h, fecha ?"), e `fechou 20h` (uma inflexão de distância) já contava."""
    for fala in ("Fecha 20h", "fecha 20h entao", "fecha as 21h"):
        assert contem_hora_explicita(fala) is True, fala


def test_fecha_nao_herda_a_colisao_com_duracao_das_irmas() -> None:
    """O ramo do "fecha" é restrito a 13-23 DE PROPÓSITO: as outras inflexões já leem duração como
    relógio fora de contexto de preço (`fechamos 2h` acende em HEAD) e este não entra nesse buraco.
    "fecha a porta" nunca colidiu — a família exige uma HORA a até 20 caracteres."""
    for fala in ("fecha a porta", "fecha 2h", "fecha 1h", "quanto fecha 1h?", "fecha 400 1h"):
        assert contem_hora_explicita(fala) is False, fala


def test_espelho_hora_antes_do_dia() -> None:
    """loop-massa r3 (externo_a t5/t6): "21h hj" é a ordem mais natural do WhatsApp, e a bolha da
    IA do mesmo turno usava a MESMA ordem — o "Blz" do t6 caiu no vazio pelos dois lados."""
    for fala in ("21h hj", "21h hoje", "21h hj entao", "20h amanha", "22h de hoje"):
        assert contem_hora_explicita(fala) is True, fala


def test_espelho_hora_dia_nao_pode_ser_largo() -> None:
    """A assimetria com `_RE_HORA_COM_DIA` é medida, não estética: com o dia ANTES, "hoje 2h" lê
    como relógio; com o dia DEPOIS, "2h hoje" lê como DURAÇÃO. Por isso só 13-23 no espelho."""
    for fala in ("2h hoje", "1h hoje", "3h sexta", "faz 2h hoje?"):
        assert contem_hora_explicita(fala) is False, fala


def test_hora_nua_terminal_com_periodo_ou_moldura() -> None:
    """Extensão PARCIAL do achado do "umas 8": o sufixo-h é desenho e fica, mas hora nua em posição
    TERMINAL com período do dia colado (ou moldura temporal na bolha) é inequívoca."""
    for fala in ("as 8 da noite", "Tinha q ser mais tarde, umas 8", "hoje umas 8"):
        assert contem_hora_explicita(fala) is True, fala


def test_hora_nua_sem_moldura_e_numero_seguido_de_substantivo_ficam_fora() -> None:
    """O sufixo obrigatório é LOAD-BEARING: sem estas duas condições entram "umas 3 fotos" e
    "me manda umas 10 fotos". "umas 8" solto, sem moldura nenhuma, segue de fora — aqui o desenho
    do módulo e o do achado concordam."""
    for fala in (
        "umas 8",
        "me manda umas 20",
        "umas 8 fotos",
        "umas 3 fotos",
        "tenho umas 9 amigas",
        "me manda umas 10 fotos",
    ):
        assert contem_hora_explicita(fala) is False, fala


def test_faixa_aberta_da_ia_nao_evidencia_a_hora() -> None:
    """loop-massa r3 (`remarcacao` t3): "Isso, hoje mesmo" depois de "Estou livre hoje a partir das
    19:30" carimbava evidência sobre 19:30 — a reserva nasceu ali com a conversa correndo em 20h.
    "a partir das" é PISO, não ponto: nem como oferta ela cravaria a hora. É a MESMA fronteira que
    o gatilho 3 já documenta (o par que crava o DIA e não a HORA)."""
    for bolha_ia in (
        "Estou livre hoje a partir das 19:30",
        "estou livre depois das 22h",
        "Atendo das 14h as 23h amor",
    ):
        msgs = [_ia(bolha_ia), _cli("Isso, hoje mesmo")]
        assert _horario_evidenciado_no_turno(msgs) is False, bolha_ia


def test_oferta_com_hora_segue_evidenciando_apos_afirmacao_curta() -> None:
    """O que desqualifica é o PISO/INTERVALO, não o verbo: "Estou livre às 20h" é oferta legítima,
    e o positivo pinado do #34 continua de pé."""
    for bolha_ia in (
        "Posso confirmar às 18h 🥰",
        "Consigo às 20h, fecha ?",
        "Consigo às 17:30 amor",
        "Estou livre às 20h, fecha ?",
    ):
        msgs = [_ia(bolha_ia), _cli("Perfeito")]
        assert _horario_evidenciado_no_turno(msgs) is True, bolha_ia
