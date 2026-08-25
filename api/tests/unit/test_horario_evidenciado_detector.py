"""Detector determinístico do horário EVIDENCIADO (spec extracao-proveniencia-horario).

Unit puro (sem DB, sem LLM): a tabela de falas do corpus contra o booleano esperado.
Dois níveis:
  - `contem_hora_explicita` (agente/_disciplina.py) — a regex crua sobre UMA fala;
  - `_horario_evidenciado_no_turno` (nos/prepare_context.py) — os três gatilhos sobre a janela:
    hora explícita na fala do cliente, confirmação curta logo após bolha da IA com hora, e o
    aceite da sondagem de imediatismo ("Seria agora ?" → "sim").
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente._disciplina import contem_hora_explicita
from barra.agente.nos._janela_do_turno import (
    _aceite_por_continuidade,
    _burst_do_cliente,
    _horario_evidenciado_no_turno,
    aceite_provavel_sem_confirmacao,
)


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


def test_gatilho_vou_sim_apos_proposta_de_hora() -> None:
    """Campanha 13/08 (eb02:30472893644814 t9): "seria 10h então ?" → "Vou sim" não contava — a
    cabeça "vou" não é forte e é token de DESFAZ. Como cabeça de dois tokens, o aceite mais direto
    do corpus passa a evidenciar."""
    msgs = [
        _ia("Então seria 10h hoje ?"),
        _cli("Entendi"),
        _cli("Obrigado pela compreensão"),
        _cli("Vou sim"),
    ]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_vou_sim_com_cauda_de_adiamento_nao_conta() -> None:
    msgs = [_ia("Então seria 10h hoje ?"), _cli("vou sim mas depois te confirmo")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_gatilho_fala_de_vinda_com_hora_proposta_na_janela() -> None:
    """Campanha 13/08 (eb02:30472893644814 t10-t13): "Confirmado sim" / "To no caminho" são
    compromissos com o encontro COMBINADO — a hora proposta pela IA pode estar turnos atrás
    (adjacência do gatilho 2 tornava a evidência inalcançável depois do 1º "Confirmado" sem
    hora). A varredura é da janela inteira, só bolhas da IA que PROPÕEM hora."""
    msgs = [
        _ia("Consigo às 10h, fecha ?"),
        _cli("Entendi"),
        _ia("Confirmado"),
        _ia("Te espero amor"),
        _cli("Confirmado sim"),
    ]
    assert _horario_evidenciado_no_turno(msgs) is True
    msgs2 = [
        _ia("Consigo às 10h, fecha ?"),
        _cli("show"),
        _ia("Te espero amor"),
        _cli("To no caminho"),
    ]
    assert _horario_evidenciado_no_turno(msgs2) is True


def test_fala_de_vinda_sem_hora_proposta_na_janela_nao_evidencia() -> None:
    """O freio do #25 se mantém: sem NENHUMA bolha da IA propondo hora na janela, "to no caminho"
    não evidencia (a hora em pauta seria só o palpite do sistema). Faixa de disponibilidade
    ("a partir das") segue não contando como proposta."""
    msgs = [_ia("Te espero amor"), _cli("To no caminho")]
    assert _horario_evidenciado_no_turno(msgs) is False
    msgs2 = [
        _ia("Estou livre hoje a partir das 11:30 amor"),
        _cli("blz"),
        _ia("Te espero"),
        _cli("Confirmado"),
    ]
    assert _horario_evidenciado_no_turno(msgs2) is False


def test_fala_de_vinda_com_outro_dia_nao_evidencia() -> None:
    msgs = [_ia("Consigo às 10h, fecha ?"), _cli("confirmado, mas amanhã")]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_aceite_de_fechamento_fecha_apos_empurrao_com_hora() -> None:
    """Campanha 13/08 (ciclo1 eb04:187007389155571 t6): "Consigo às 18h, fecha ?" → "Fecha" e o
    estado ficava em Qualificado — o léxico tinha "fechado"/"fechou" mas não o presente
    ("fecha"/"fecho"), o eco literal do empurrão que o prompt manda a IA usar."""
    msgs = [
        _cli("A ceita cartão"),
        _ia("Aceito"),
        _ia("Consigo às 18h, fecha ?"),
        _cli("Fecha"),
    ]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_aceite_de_fechamento_confirmo_sim_com_proposta_turnos_atras() -> None:
    """Retenção (eb04:211711990710521 t7): "Confirmo sim" respondia a "Me confirma 10h que eu te
    passo o número certinho" — que NÃO é proposta pela régua de `contem_hora_explicita` — e a
    proposta real ("Consigo hoje às 10h, fecha ?") estava turnos atrás. A adjacência do gatilho 2
    nunca alcançaria; só a varredura de janela do gatilho 4 sustenta o aceite."""
    msgs = [
        _ia("Uma hora comigo"),
        _ia("Consigo hoje às 10h, fecha ?"),
        _cli("Fecho. Me manda localização pra ver quanto tempo até aí"),
        _ia("To na rua Latino Coelho, Chácara da Barra"),
        _cli("Ta dando quanto tempo daqui?"),
        _ia("To na Chácara da Barra"),
        _ia("Me confirma 10h que eu te passo o número certinho"),
        _cli("Confirmo sim"),
    ]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_aceite_interrogativo_ou_com_numero_e_contraproposta() -> None:
    """ "fecha por 500 ?" é CONTRAPROPOSTA e "combinado ?" é sondagem DELE: pergunta e número nunca
    evidenciam, mesmo com proposta de hora da IA na janela (mesmos vetos da família curta —
    `_RE_DIGITO` e o "?")."""
    for fala in ("fecha por 500?", "Fecha por 500 ?", "combinado?", "fecha por 500", "fecho 350"):
        msgs = [_ia("Consigo às 18h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala


def test_aceite_negado_adiado_ou_sem_proposta_na_janela_nao_evidencia() -> None:
    """Negação/adiamento desfazem o aceite ("não fecho", "vou pensar se fecha"), outro dia adia
    ("fecha amanhã então") — e sem NENHUMA bolha da IA propondo hora na janela o "Fecha" aceitaria
    só o palpite do sistema (freio do #25, o mesmo do gatilho 4)."""
    for fala in ("não fecho", "vou pensar se fecha", "fecha amanhã então", "vou ver se fecha"):
        msgs = [_ia("Consigo às 18h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala
    msgs = [_ia("Te espero amor"), _cli("Fecha")]
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


def test_topo_e_ta_fechado_do_caso_eb02_ciclo2() -> None:
    """Campanha 13/08 ciclo 2 (eb02:19134800761083 t7 e t10): "Topo" respondendo a "Te espero às
    14h então" e "Tá fechado então" com a proposta turnos atrás não contavam — a IA re-pedia a
    confirmação já dada ("Me confirma o 14h que eu te passo o número"). "Topo" entra pelo conjunto
    exato (gatilho 2) e pela cabeça posicional do gatilho 4; "Tá fechado então" pela cabeça de dois
    tokens e pelo token "fechado" do gatilho 4."""
    # t7: aceite da contraproposta, bolha da IA contígua propõe a hora.
    msgs_t7 = [
        _cli("Ahh\nFoi 400 por 1h né\nFaz por 350?"),
        _ia("Consigo 350 sim amor"),
        _ia("Te espero às 14h então"),
        _cli("Topo"),
    ]
    assert _horario_evidenciado_no_turno(msgs_t7) is True
    # t10: fechamento com a proposta de hora turnos atrás (só o gatilho 4 alcança).
    msgs_t10 = [
        _ia("Te espero às 14h então"),
        _cli("Topo"),
        _ia("Combinado então, às 14h"),
        _cli("Me passa o endereço certinho aí"),
        _ia("To na rua Latino Coelho, Chácara da Barra amor"),
        _cli("Tá fechado então"),
        _cli("Me passa o número do hotel q eu te chamo qdo chegar"),
    ]
    assert _horario_evidenciado_no_turno(msgs_t10) is True


def test_variantes_de_topo_e_girias_de_aceite() -> None:
    """As formas inequívocas que entraram com o caso eb02: verbo "topar" em bolha curta ou cabeça
    de mensagem, "tamo/tamos fechado", e as gírias "dale"/"demorou" em bolha curta."""
    for fala in (
        "topo",
        "Eu topo",
        "Topo sim",
        "Topo, me passa o endereço",
        "tamo fechado",
        "Tamos fechado então",
        "Dale",
        "Demorou",
    ):
        msgs = [_ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is True, fala


def test_topo_substantivo_e_caudas_que_desfazem_nao_evidenciam() -> None:
    """O recall fica menor de propósito: "topo" substantivo ("no topo da lista", "topo de linha"),
    contraproposta com número ("topo se for 300"), interrogativo ("tá fechado ?", "topo ?"),
    reclamação com cauda ("demorou pra responder hein") e adiamento ("tá fechado mas vou ver")
    seguem sem evidenciar — os vetos existentes não afrouxam."""
    for fala in (
        "no topo da lista",
        "me espera no topo do prédio",
        "Topo de linha essa massagem",
        "topo se for 300",
        "tá fechado?",
        "Tá fechado ?",
        "topo ?",
        "demorou pra responder hein",
        "dale que eu vou pensar",
        "tá fechado mas amanhã",
    ):
        msgs = [_ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala
    # Sem NENHUMA proposta de hora da IA na janela, nem o aceite novo evidencia (freio do #25).
    assert _horario_evidenciado_no_turno([_ia("Te espero amor"), _cli("Topo")]) is False


# --- Fix 1 do diagnóstico da degradação tardia (14/08): 1b (infinitivo) + gatilho 5 ------------


def test_1b_fechar_no_infinitivo_e_aceite() -> None:
    """M5 do diagnóstico (c3-lote/eb02:139384791793838 t9): "Fechamos 11h então ?" → "Pode fechar"
    e o atendimento seguia em `Qualificado` — `re.search(_RE_ACEITE_DE_FECHAMENTO, "pode fechar")`
    era None (o léxico tinha "fechado"/"fechamos"/"fecho", nunca o INFINITIVO). Um turno perdido
    trava a FSM: o belief renderizou "não confirmada — ofereça esta hora e espere o sim" até o fim
    da conversa e a IA cobrou confirmação já dada em três turnos seguidos.

    Medido no corpus da campanha: sozinho, este caractere move a 1ª evidência do t12 para o t9 na
    conversa-farol — os dois "Me confirma que eu te passo o endereço" somem."""
    for fala in ("Pode fechar", "pode fechar então", "podemos fechar amor", "Fechar então"):
        msgs = [_ia("Assim que você confirmar eu já chamo o uber"), _ia("Fechamos 11h então ?")]
        assert _horario_evidenciado_no_turno([*msgs, _cli(fala)]) is True, fala
    # "vamos fechar" fica de FORA e a perda é nomeada: "vamos" é token de `_RE_CAUDA_QUE_DESFAZ`
    # ("beleza vamos ver") — o infinitivo não afrouxa nenhum dos vetos que já existiam.
    assert (
        _horario_evidenciado_no_turno([_ia("Fechamos 11h então ?"), _cli("vamos fechar")]) is False
    )
    # Os vetos da família seguem valendo sobre o infinitivo: pergunta, número, outro dia, negação.
    for fala in ("posso fechar ?", "fechar por 500", "fechar amanhã então", "não vou fechar"):
        msgs = [_ia("Fechamos 11h então ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala


def _janela_da_cobranca(fala_do_cliente: str, meio: str = "Qual o hotel ?") -> list[BaseMessage]:
    """Forma do t11 de M5: ela propõe+cobra a hora, ele fala, ela cobra DE NOVO (agora sem repetir
    a hora) e ele responde. A afirmação dele fica correferida a uma bolha SEM hora — cega para o
    gatilho 2, que exige a hora na bolha contígua."""
    return [
        _ia("400 1h no meu local"),
        _ia("Consigo às 11h, fecha ?"),
        _cli(meio),
        _ia("Me passa o endereço do hotel amor"),
        _ia("Me confirma que eu te passo o endereço certinho"),
        _cli(fala_do_cliente),
    ]


def test_gatilho5_afirmacao_correferida_a_cobranca_sem_hora() -> None:
    """Gatilho 5 — a hora que ELA cobrou continua na mesa: o "Beleza" dado à cobrança seguinte
    (que já não repete a hora) é aceite DAQUELA hora. Sem isto, a única porta é turno-local e
    adjacente, e um turno perdido tranca a evidência para sempre."""
    for fala in ("Beleza", "Ok", "Perfeito", "Isso", "Tá bom amor"):
        assert _horario_evidenciado_no_turno(_janela_da_cobranca(fala)) is True, fala


def test_gatilho5_exige_ancora_que_propoe_e_cobra_a_hora() -> None:
    """A âncora é bolha dela que PROPÕE a hora *e* COBRA o fechamento. Disponibilidade ("a partir
    das 10h", mesma fronteira do `_RE_FAIXA_ABERTA` do gatilho 2) e promessa sem cobrança ("te
    espero às 14h então") não ancoram — senão o gatilho carimbaria evidência sobre um horário que
    ninguém pôs em pergunta (o #25 por outra porta)."""
    for ancora in ("Hoje to livre a partir das 10h, te espero", "Te espero às 14h então"):
        msgs = [
            _ia(ancora),
            _cli("Qual o hotel ?"),
            _ia("Me confirma que eu te passo o endereço certinho"),
            _cli("Beleza"),
        ]
        assert _horario_evidenciado_no_turno(msgs) is False, ancora


def test_gatilho5_vetos_de_reabertura() -> None:
    """Qualquer turno dele que REABRA a negociação entre a cobrança e a afirmação desliga o
    gatilho: recuo, outra hora, outro dia, preço de volta à mesa, contraproposta, pedido de infos e
    a hora RE-PERGUNTADA (quem pergunta "que horas te espero ?" não combinou hora nenhuma — caso
    real c3-lote/eb04:242335677997143 t4)."""
    for meio in (
        "vou pensar",
        "pode ser 14h então",
        "amanhã fica melhor",
        "quanto fica 2h",
        "faz por 300",
        "me passa as infos",
        "que horas te espero ?",
    ):
        assert _horario_evidenciado_no_turno(_janela_da_cobranca("Beleza", meio)) is False, meio


def test_gatilho5_exige_dois_turnos_dele_sem_custo_de_recall() -> None:
    """A continuidade pedida é ≥2 turnos dele desde a âncora (mitigação do diagnóstico contra o
    falso positivo). Não custa recall: com UM turno só, a âncora ainda é bolha contígua e o
    gatilho 2 resolve — aqui o detector diz True mesmo com o gatilho 5 dizendo False."""
    msgs = [
        _ia("Consigo às 11h, fecha ?"),
        _ia("Me confirma que eu te passo o endereço certinho"),
        _cli("Beleza"),
    ]
    assert _aceite_por_continuidade(msgs, _burst_do_cliente(msgs)) is False
    assert _horario_evidenciado_no_turno(msgs) is True


def test_gatilho5_nao_evidencia_cliente_que_ainda_qualifica() -> None:
    """O que a medição do corpus DESCARTOU: "ele continuou falando ≥2 turnos sem objeção, logo
    aceitou". Falas reais dos turnos que a versão sem adesão passaria a evidenciar —
    c3-fotos/duvida_das_fotos (fotos/altura) e c3-lote/eb01:73852784775215 (DDD/portaria) — são
    cliente AINDA QUALIFICANDO sob a hora, não aceite. Falso positivo aqui reserva o slot da agenda
    (`Qualificado -> Aguardando_confirmacao`) e vira pedido de Pix a quem não combinou nada."""
    fotos = [
        _ia("Consigo às 17h hoje, fecha ?"),
        _cli("essas fotos são suas mesmo ?"),
        _ia("Sou eu mesma amor, bem gata como nas fotos rs"),
        _cli("vc tem quantos de altura ?"),
    ]
    assert _horario_evidenciado_no_turno(fotos) is False
    # E a afirmação curta só conta CORREFERIDA: o "Sim" real de eb01:73852784775215 t12 responde a
    # "sou de fora, cheguei recente aqui na Barra" — nada tem com as 21h propostas 5 turnos antes.
    rio = [
        _ia("Gravei um vídeo pra você 🥰 Consigo às 21h, fecha?"),
        _cli("Tu é. Do Rio"),
        _ia("Não amor, to aqui na Barra em Campinas rs"),
        _cli("Tem portaria ai?"),
        _ia("Sou de fora amor, cheguei recente aqui na Barra rs"),
        _cli("Sim"),
    ]
    assert _horario_evidenciado_no_turno(rio) is False


def test_gatilho5_para_na_marca_de_pausa() -> None:
    """Mesma fronteira dos detectores irmãos: a hora cobrada seis dias atrás não é a hora deste
    atendimento — a janela de 40 bolhas cruza atendimentos (incidente 29/07)."""
    from datetime import UTC, datetime, timedelta

    from barra.agente.nos.prepare_context import _texto_marca_pausa

    antes = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
    pausa = HumanMessage(content=_texto_marca_pausa(antes, antes + timedelta(days=6)), id="pausa-1")
    msgs = [
        _ia("Consigo às 11h, fecha ?"),
        _cli("Qual o hotel ?"),
        pausa,
        _ia("Me confirma que eu te passo o endereço certinho"),
        _cli("Beleza"),
    ]
    assert _horario_evidenciado_no_turno(msgs) is False


def test_adesao_por_eco_do_verbo_da_cobranca() -> None:
    """2ª passada do Fix 1 — o único padrão que a triagem do corpus classificou como aceite em 3 de
    3 leituras: ele responde ecoando o verbo de possibilidade que ELA usou na cobrança
    (c4-lote/eb04:19134800761083 t7 e eb03:197499826503682 t5, ambos com a IA confirmando no turno
    seguinte). Não é léxico novo — o conjunto é o `_VERBO_DE_POSSIBILIDADE` de `_disciplina`, e o
    "sim" é o de sempre; o que muda é o ALCANCE, dentro do gate de correferência do gatilho 5."""
    for fala in ("Consigo sim", "Posso sim", "Pode sim", "Consigo sim amor"):
        msgs = [_ia("400 1h no meu local"), _ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is True, fala
    # Sem a cobrança dela como antecedente, o eco não vale — é o mesmo freio que segura o "Sim".
    assert _horario_evidenciado_no_turno([_ia("Te mando sim 🥰"), _cli("Consigo sim")]) is False


def test_eco_do_verbo_nao_afrouxa_os_vetos_da_familia_curta() -> None:
    """Pergunta, número, outro dia, adiamento e cauda livre continuam derrubando: "consigo sim, mas
    só amanhã" não é aceite de hoje, e a cauda restrita a vocativo é a mesma da família de dois
    tokens ("vou sim")."""
    for fala in (
        "consigo sim ?",
        "consigo sim por 300",
        "consigo sim mas amanhã",
        "consigo sim, mas depois eu confirmo",
        "posso sim se der certo mais tarde",
    ):
        msgs = [_ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala


def test_adiamento_da_confirmacao_nao_e_aceite() -> None:
    """ "Eu confirmo DEPOIS" é o contrário de "eu confirmo" — e era lido como aceite pelo token
    `confirmo` do gatilho 4. Cinco turnos do corpus, todos com o cliente dizendo o oposto do que o
    detector entendia (`ciclo1-rerun/eb02:21123135741957` t13/t17 carimbavam a evidência SEIS
    turnos antes do aceite real, "Ok amor, fecho com você então")."""
    for fala in (
        "Tô vendo aqui e te confirmo",
        "Te chamo e te confirmo",
        "Te confirmo assim que finalizar aqui",
        "Só um minutinho, já te confirmo certinho.",
        "vou confirmar amor",
        "deixa eu ver aqui",
    ):
        msgs = [_ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala
    # "Confirmo sim" (sem o "te") segue sendo aceite — o veto é do ADIAMENTO, não do verbo.
    msgs = [_ia("Consigo hoje às 10h, fecha ?"), _ia("Me confirma 10h"), _cli("Confirmo sim")]
    assert _horario_evidenciado_no_turno(msgs) is True


def test_adiamento_tambem_veta_a_continuidade() -> None:
    """O hedge no meio da continuidade desliga o gatilho 5 inteiro: quem disse "vou confirmar" no
    turno passado não aceitou nada por seguir conversando."""
    for meio in ("vou confirmar amor", "tô vendo aqui", "deixa eu ver aqui", "te aviso depois"):
        assert _horario_evidenciado_no_turno(_janela_da_cobranca("Beleza", meio)) is False, meio


def test_falas_que_a_triagem_do_corpus_reprovou_seguem_fora() -> None:
    """Conjunto de CONTROLE da triagem (falas curtas correferidas a uma âncora, classificadas uma a
    uma lendo a conversa): acknowledgment e elogio não são aceite, e o cliente que os diz segue
    qualificando ou hedgeando no turno seguinte."""
    for fala in (
        "Legal",  # "Legal / Duas finalizações?" — só fecha três turnos depois
        "Entendi",  # "Entendi / Deixa eu ver aqui"
        "Certo",  # "Certo / Qual o valor do seu atendimento?"
        "Ótimo",  # segue perguntando preço e se as fotos são reais
        "Não tenho duvidas",  # conversa termina em perdido_objecao
        "uau",
        "Maravilhosa",
        "Poxa amor",
        "Tô em Campinas sim",
    ):
        msgs = [_ia("400 1h no meu local"), _ia("Consigo às 14h, fecha ?"), _cli(fala)]
        assert _horario_evidenciado_no_turno(msgs) is False, fala
        assert _horario_evidenciado_no_turno(_janela_da_cobranca(fala)) is False, fala


# --- sinal FRACO (redação do belief, nunca estado) ---------------------------------------------


def test_sinal_fraco_contem_a_evidencia() -> None:
    """`aceite_provavel_sem_confirmacao` inclui por construção todo turno evidenciado — aceite
    confirmado é caso particular de aceite provável, e quem consome pergunta "posso parar de cobrar
    a confirmação ?". Medido no corpus: 96 evidenciados, 96 contidos, ZERO violações."""
    for msgs in (
        [_ia("Fechamos 11h então ?"), _cli("Pode fechar")],
        [_ia("que horas você quer amor?"), _cli("Umas 16 horas")],
        [_ia("Consigo às 14h, fecha ?"), _cli("Consigo sim")],
        _janela_da_cobranca("Beleza"),
    ):
        assert _horario_evidenciado_no_turno(msgs) is True
        assert aceite_provavel_sem_confirmacao(msgs) is True


def test_sinal_fraco_acende_no_cliente_que_ainda_qualifica() -> None:
    """É a diferença de propósito entre os dois: aqui True é ESPERADO nos mesmos turnos que seriam
    falso positivo para o estado. A hora está de pé, ele não objetou, e o belief não deveria estar
    mandando "ofereça esta hora e espere o sim" pela sexta vez — mas ninguém reserva agenda com
    isto. Falas literais do corpus (c3-fotos/duvida_das_fotos, c3-lote/eb01:73852784775215)."""
    fotos = [
        _ia("Consigo às 17h hoje, fecha ?"),
        _cli("essas fotos são suas mesmo ?"),
        _ia("Sou eu mesma amor, bem gata como nas fotos rs"),
        _cli("vc tem quantos de altura ?"),
    ]
    assert _horario_evidenciado_no_turno(fotos) is False
    assert aceite_provavel_sem_confirmacao(fotos) is True


def test_sinal_fraco_apaga_no_recuo_no_hedge_e_na_reabertura() -> None:
    """Os vetos são os MESMOS do gatilho 5 (o núcleo é compartilhado, `_leitura_da_continuidade`):
    quem recuou, adiou, mudou a hora ou o dia, voltou ao preço ou pediu a apresentação não está sob
    a hora que ela cobrou — e aí a cobrança da confirmação volta a ser a conduta certa."""
    for meio in (
        "vou pensar",
        "vou confirmar amor",
        "tô vendo aqui",
        "deixa eu ver aqui",
        "pode ser 14h então",
        "amanhã fica melhor",
        "quanto fica 2h",
        "faz por 300",
        "me passa as infos",
        "que horas te espero ?",
    ):
        janela = _janela_da_cobranca("Tem estacionamento", meio)
        assert aceite_provavel_sem_confirmacao(janela) is False, meio


def test_sinal_fraco_exige_ancora_e_continuidade() -> None:
    """Sem âncora (disponibilidade, promessa, nenhuma hora) não há sinal — o belief segue cobrando.
    E um único turno dele desde a âncora não é continuidade: aí a cobrança acabou de sair."""
    for ancora in (
        "Hoje to livre a partir das 10h, te espero",
        "Te espero às 14h então",
        "Oii amor",
    ):
        msgs = [
            _ia(ancora),
            _cli("Qual o hotel ?"),
            _ia("Me passa o endereço"),
            _cli("Tem estacionamento"),
        ]
        assert aceite_provavel_sem_confirmacao(msgs) is False, ancora
    um_turno = [_ia("Consigo às 11h, fecha ?"), _cli("Tem estacionamento")]
    assert aceite_provavel_sem_confirmacao(um_turno) is False
