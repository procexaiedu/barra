"""Detector determinístico de RECUO do cliente (spec extracao-aceite-hibrido).

Unit puro (sem DB, sem LLM): a tabela de falas do corpus contra as três saídas do detector —
recuo autônomo, negativa correferenciada e "não é recuo". Dois níveis:
  - `classificar_recuo` (agente/_disciplina.py) — o detector cru sobre burst + bolhas da IA;
  - `_recuo_no_turno` (nos/prepare_context.py) — o mesmo detector sobre a janela do turno.

O caso que sustenta a lista negativa é o #34 ("Perfeito, vou te avisando então"): o ÚNICO aceite
verdadeiro do corpus auditado, que um detector ingênuo de adiamento rebaixaria.
"""

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente._disciplina import classificar_recuo
from barra.agente.nos._janela_do_turno import _recuo_no_turno


def _ia(texto: str) -> AIMessage:
    return AIMessage(content=texto)


def _cli(texto: str) -> HumanMessage:
    return HumanMessage(content=texto)


# --- recuo autônomo: não precisa de correferência ---


def test_recuo_autonomo_do_corpus_e_do_vocabulario_do_prompt():
    for fala in (
        "Quero muito ir mas... tenho que esperar começo do mês",  # #20
        "Hoje não consigo, te mando msg mais pra frente",  # #27
        "vou ver e te falo",  # <conducao_da_venda> "Recuo pós-objeção"
        "estou analisando",
        "te chamo antes",
        "vou pensar melhor",
        "deixa eu ver certinho",
        "mês que vem eu marco",
        "quando eu tiver uma grana eu chamo",
        "hoje não vai dar",
        "agora não consigo",
        "semana que vem",
        "outro dia a gente marca",
    ):
        assert classificar_recuo([fala], []) == "autonomo", fala


def test_recuo_autonomo_dispensa_bolha_da_ia():
    # Sem nenhuma bolha antecedente o recuo autônomo continua valendo — é o que o distingue da
    # negativa, que só vale colada num pedido de fechamento.
    assert classificar_recuo(["hoje não consigo"], []) == "autonomo"


# --- negativa correferenciada: só colada num pedido de fechamento ---


def test_19_nao_apos_pedido_de_confirmacao():
    # #19: a IA pediu "Podemos confirmar 18h ?" e ele respondeu "Não".
    assert classificar_recuo(["Não"], ["Podemos confirmar 18h ?"]) == "correferenciado"


def test_negativas_curtas_apos_variantes_do_empurrao_de_fechamento():
    for bolha in (
        "Posso confirmar às 18h ?",
        "Vamos confirmar 14h amor ?",
        "Consigo às 22h, fecha ?",
        "Confirmado ?",
        "Fechamos 15h então ?",
        "Podemos deixar marcado amanhã 15h ?",
    ):
        assert classificar_recuo(["não"], [bolha]) == "correferenciado", bolha
    for fala in ("nao", "agora não", "acho que não", "hoje não", "melhor não", "não posso"):
        assert classificar_recuo([fala], ["Confirmado ?"]) == "correferenciado", fala


def test_24_negativa_ambigua_sem_pedido_de_fechamento_nao_e_recuo():
    # #24: "Não conheço" respondendo a "Campinas?" — negativa sem correferência de fechamento.
    assert classificar_recuo(["Não conheço"], ["Campinas ?"]) is None
    # Nem mesmo colada num pedido de fechamento: "não conheço" não é a negativa curta do conjunto.
    assert classificar_recuo(["Não conheço"], ["Podemos confirmar 18h ?"]) is None


def test_negativa_sem_bolha_de_fechamento_nao_e_recuo():
    assert classificar_recuo(["não"], ["Você prefere hotel ou apartamento ?"]) is None
    assert classificar_recuo(["não"], []) is None


# --- lista negativa: nunca é recuo ---


def test_34_vou_te_avisando_preserva_o_aceite():
    # #34, o único aceite verdadeiro do corpus: quem diz isso já quer, só não manda no relógio.
    assert (
        classificar_recuo(["Perfeito, vou te avisando então"], ["Posso confirmar às 18h ?"]) is None
    )
    for fala in ("te aviso quando sair", "vou te avisando", "me confirma de manhã"):
        assert classificar_recuo([fala], ["Confirmado ?"]) is None, fala


def test_aceite_comum_nao_e_recuo():
    for fala in ("pode ser", "fechou", "vamos marcar", "Tipo 18h, 18h15", "sim"):
        assert classificar_recuo([fala], ["Podemos confirmar 18h ?"]) is None, fala


def test_veto_derruba_o_condicional_mas_nao_o_recuo_explicito():
    # O veto age sobre a família condicional, que é onde o vocabulário colide de fato...
    assert classificar_recuo(["te aviso quando eu puder"], []) is None
    assert classificar_recuo(["quando eu puder eu chamo"], []) == "autonomo"
    # ...e não sobre o recuo explícito, que vence mesmo dentro da MESMA bolha (no WhatsApp as duas
    # coisas cabem numa bolha só).
    assert classificar_recuo(["hoje não consigo, te aviso quando der"], []) == "autonomo"
    assert classificar_recuo(["hoje não consigo", "te aviso"], []) == "autonomo"


def test_aviso_com_outro_verbo_tambem_preserva_o_aceite():
    # "te chamo quando sair" é o #34 com outro verbo: quem já fechou avisando que não manda no
    # relógio. Só as formas do prompt ("te chamo antes") contam como recuo.
    for fala in ("Fechou, te chamo quando sair de casa", "pode ser, te ligo já já"):
        assert classificar_recuo([fala], []) is None, fala
    assert classificar_recuo(["te chamo antes"], []) == "autonomo"


def test_pedido_do_cliente_nao_e_recuo():
    # "me manda quando puder" é ele pedindo mídia, não adiando o encontro — o condicional exige o
    # sujeito "eu" justamente por isso.
    for fala in ("me manda quando puder", "me chama quando estiver livre"):
        assert classificar_recuo([fala], ["Confirmado ?"]) is None, fala


def test_demais_falas_do_corpus_auditado_nao_recuam():
    # Os outros cinco atendimentos da auditoria: aceite falso marcado sem recuo nenhum na fala. O
    # detector não pode inventar recuo neles — quem os corrige é a descrição do campo (issue 08).
    for fala in (
        "quanto PG",  # #41
        "obrigado",  # #41
        "Le de novo com calma gata",  # #21
        "É o mesmo vl",  # #9
        "O normal o que seria",  # #9
        "Rua gata seria do seu local dlc?",  # #8
        "Tem fotos",  # #24
        "E liberal?",  # #24
        "Aonde atende",  # #24
        "Hummm",  # #19
        "Pretendo...mais para o final do dia",  # #19
        "ainda não conheço, mas topo",  # a ambiguidade do #24 com "ainda"
    ):
        assert classificar_recuo([fala], ["Podemos confirmar 18h ?"]) is None, fala


def test_ainda_nao_isolado_e_negativa_correferenciada():
    # O prompt cita "Ainda não" como resposta À proposta — logo, correferenciada, não autônoma.
    assert classificar_recuo(["ainda não"], ["Podemos confirmar 18h ?"]) == "correferenciado"
    assert classificar_recuo(["ainda não"], ["Você prefere hotel ?"]) is None


# --- _recuo_no_turno: o detector sobre a janela ---


def test_janela_negativa_correferenciada_no_burst_atual():
    janela = [_cli("Hummm"), _ia("Podemos confirmar 18h ?"), _cli("Não")]
    assert _recuo_no_turno(janela) is True


def test_janela_ignora_recuo_antigo_fora_do_burst_atual():
    # Recuo de dez turnos atrás não rebaixa de novo o aceite que veio DEPOIS dele.
    janela = [
        _cli("hoje não consigo"),
        _ia("Tranquilo amor, me avisa 🥰"),
        _cli("consegui, fechou"),
    ]
    assert _recuo_no_turno(janela) is False


def test_janela_sem_fala_do_cliente_no_fim_nao_recua():
    assert _recuo_no_turno([_cli("Não"), _ia("Sem problema amor 🥰")]) is False


def test_janela_34_preserva():
    janela = [_ia("Posso confirmar às 18h ?"), _cli("Perfeito, vou te avisando então")]
    assert _recuo_no_turno(janela) is False
