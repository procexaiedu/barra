"""Detectores de preco/servico fantasma + pedidos do cliente (rodada 3 do eval, fase 1-E).

Familia da sonda/regiao/incluso: PUROS, estreitos de proposito — o fallback dropa a bolha
(depois de uma regen), entao os testes de fala legitima valem tanto quanto os de captura.
A falha medida no shadow v2: "Faço sim amor" para anal fora do cadastro (recusa_limite 40%),
preco citado sem validacao (preco 65%) e localizacao pedida sem entrega (logistica 57%).
"""

from decimal import Decimal

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente._disciplina import (
    contem_pedido_de_endereco,
    contem_pedido_de_infos,
    periodo_da_saudacao,
)
from barra.agente.nos.output_guard import (
    _FEEDBACK_GATILHO,
    _feedback_preco_fantasma,
    _valores_legitimos,
    bolhas_preco_fantasma,
    bolhas_servico_fantasma,
    extrair_precos_citados,
    resposta_so_pedagio,
    saudacao_em_conflito,
    vocabulario_de_servicos,
)
from barra.settings import get_settings

# --- extracao de preco citado (contexto monetario exigido) ----------------------------------


def test_cotacao_canonica_e_extraida() -> None:
    assert extrair_precos_citados("600 1h no meu local") == {600}
    assert extrair_precos_citados("R$ 500 amor") == {500}
    assert extrair_precos_citados("500 reais o encontro") == {500}
    assert extrair_precos_citados("consigo 450 se for hoje") == {450}
    assert extrair_precos_citados("fica 1.000 a pernoite... por 800 fecho") == {1000, 800}


def test_horario_duracao_e_endereco_nao_sao_preco() -> None:
    # Horario ("18h", "17:30"), duracao ("1h") e numero de rua nunca entram no scan.
    assert extrair_precos_citados("Consigo às 18h amor") == set()
    assert extrair_precos_citados("Pode ser 17:30 ?") == set()
    assert extrair_precos_citados("O encontro é de 1h") == set()
    assert extrair_precos_citados("Av. Aquidabã 130, Hotel Sirius") == set()
    # Taxa pequena de uber fica fora (piso de 100): o guard mira preco de PROGRAMA.
    assert extrair_precos_citados("O uber fica uns 50 reais") == set()


# --- preco fantasma -------------------------------------------------------------------------

_VALIDOS = {400, 500, 600, 800, 1000}


def test_preco_da_tabela_passa_e_inventado_cai() -> None:
    assert bolhas_preco_fantasma("O encontro é 500 1h amor", _VALIDOS) == []
    assert bolhas_preco_fantasma("O encontro é 550 1h amor", _VALIDOS) == [
        "O encontro é 550 1h amor"
    ]


def test_so_a_bolha_ofensora_cai() -> None:
    texto = "Oi amor 🥰\n\nFica 700 1h no meu local"
    assert bolhas_preco_fantasma(texto, _VALIDOS) == ["Fica 700 1h no meu local"]


def test_sem_tabela_o_detector_desliga() -> None:
    # Modelo sem programa cadastrado: sem tabela nao ha "fora da tabela" (mesma regra do eco).
    assert bolhas_preco_fantasma("Fica 999 1h amor", set()) == []


def test_valores_legitimos_cobre_extra_dobro_degraus_e_eco_do_cliente() -> None:
    validos = _valores_legitimos(
        [(Decimal("400"), Decimal("1"), None)],
        None,
        [HumanMessage(content="e por 250 nao rola ?"), AIMessage(content="nao amor")],
    )
    assert 400 in validos  # tabela
    assert 800 in validos  # dobro (casal/menage, ADR-0035)
    assert 250 in validos  # eco do numero do CLIENTE (recusar o numero dele e fala legitima)
    assert any(v < 400 for v in validos)  # degrau/piso da escada de desconto (ADR-0031)


# Tabela canonica da Catarina (decisao de 11/08/2026), no formato que o guard recebe:
# (preco, horas, preco_minimo). A 1h a 400/300 e a base do extra de fetiche (ADR-0038).
_CATARINA = [
    (Decimal("250"), Decimal("0.5"), Decimal("250")),
    (Decimal("400"), Decimal("1"), Decimal("300")),
    (Decimal("800"), Decimal("2"), Decimal("600")),
    (Decimal("1000"), Decimal("3"), Decimal("900")),
    (Decimal("2000"), Decimal("12"), None),
]


def test_totais_de_fetiche_sao_legitimos_nos_tres_patamares() -> None:
    # O extra ACOMPANHA o patamar do pacote (ADR-0038): a 1h vale 400 cheia, 350 no degrau e 300
    # no piso. Legitimar so o cheio barraria a fala que o proprio <desconto> manda dar — "600
    # amor, com a inversao" no piso da 1h.
    validos = _valores_legitimos(_CATARINA, None, [])
    assert {800, 1200} <= validos  # cheio: 400 + 400 e 400 + 2x400
    assert {700, 1050} <= validos  # degrau: 350 + 350 e 350 + 2x350
    assert {600, 900} <= validos  # piso: 300 + 300 e 300 + 2x300


def test_totais_de_fetiche_nas_outras_duracoes() -> None:
    # O extra e FIXO em relacao a duracao: os numeros da tabela ditada pelo dono do produto.
    validos = _valores_legitimos(_CATARINA, None, [])
    assert 1200 in validos  # 2h cheia (800) + 400
    assert 1400 in validos  # 3h cheia (1000) + 400
    assert 2400 in validos  # pernoite (2000) + 400
    assert 900 in validos  # 2h no piso (600) + 300
    # 3h no piso: o piso ABSOLUTO da linha e 900 (fator 0,9) — o extra continua sendo 300, nao
    # 360. O 1.200 ja esta no conjunto; o 1.260 do fator NAO entra.
    assert 1260 not in validos


def test_pacote_curto_nao_legitima_total_de_fetiche() -> None:
    # Espelho do render: o <fetiches> nao imprime linha de fetiche para os 30min, e o guard nao
    # legitima o total dela — nem o extra (250 + 400), nem o dobro do "Por pessoa" (250 x 2),
    # nem o 750 que a formula antiga produzia.
    validos = _valores_legitimos(_CATARINA, None, [])
    assert 250 in validos  # o preco da linha continua citavel
    assert 650 not in validos
    assert 500 not in validos
    assert 750 not in validos


def test_valor_acordado_entra_no_conjunto() -> None:
    validos = _valores_legitimos([(Decimal("400"), Decimal("1"), None)], Decimal("350"), [])
    assert 350 in validos


# --- servico fantasma (closed-world do cardapio) --------------------------------------------

_SEM_CARDAPIO: set[str] = set()
_COM_COMPLETO = vocabulario_de_servicos([], ["Completo", "Normal"])
_COM_ORAL_SEM = vocabulario_de_servicos(["Beijo na boca", "Oral sem camisinha"], ["Normal"])


def test_faco_sim_para_anal_fora_do_cadastro_cai() -> None:
    # A derrota medida: "E completo, vaginal e anal?" -> "Faço sim amor" com modelo sem anal.
    assert bolhas_servico_fantasma("Faço sim amor, anal também", _SEM_CARDAPIO) != []
    assert bolhas_servico_fantasma("Anal pode sim amor rs", _SEM_CARDAPIO) != []


def test_programa_completo_absolve_anal_e_grego() -> None:
    # <girias_do_cliente>: o anal mora no Completo — quem tem o programa faz.
    assert bolhas_servico_fantasma("Faço anal sim amor, é no completo", _COM_COMPLETO) == []


def test_oral_sem_camisinha_absolve_natural() -> None:
    assert bolhas_servico_fantasma("Natural faço sim amor", _COM_ORAL_SEM) == []
    assert bolhas_servico_fantasma("Natural faço sim amor", _SEM_CARDAPIO) != []


def test_recusa_e_eco_negacao_nao_disparam() -> None:
    # Licao do ven_004: regex cego a negacao pune a resposta certa.
    for fala in (
        "Não faço anal amor",
        "Anal não faço rs",
        "Faço anal não amor",
        "Anal não amor, mas beijo na boca e oral sem rs",
    ):
        assert bolhas_servico_fantasma(fala, _SEM_CARDAPIO) == [], fala


def test_afirmacao_longe_do_token_nao_dispara() -> None:
    # "pode" de outra frase da bolha nao vira promessa do servico.
    fala = "Pode chegar às 20h amor, te espero. Sobre o resto a gente conversa: anal é tabu aqui"
    assert bolhas_servico_fantasma(fala, _SEM_CARDAPIO) == []


def test_fala_sem_token_de_risco_passa() -> None:
    # "Pode sim" para beijo/carinho e conduta aberta, nao cardapio — nunca dispara.
    assert bolhas_servico_fantasma("Pode sim amor, adoro beijar rs", _SEM_CARDAPIO) == []


# --- pedidos do cliente (alimentam gatilho de endereco e ponteiro de pitch) -----------------


def test_pedido_de_endereco_casa_as_formas_reais() -> None:
    for fala in (
        "Manda a localização",
        "me passa o endereço por favor",
        "Onde fica?",
        "onde você atende amor",
        "Qual o endereço?",
    ):
        assert contem_pedido_de_endereco(fala), fala


def test_fala_de_local_sem_pedido_nao_casa() -> None:
    for fala in (
        "no meu local amor",
        "prefiro no seu local",
        "chego em 10 min",
        "onde você mora?",  # residencia != ponto de encontro (PII)
    ):
        assert not contem_pedido_de_endereco(fala), fala


def test_pedido_de_infos_casa_as_formas_reais() -> None:
    for fala in (
        "como funciona?",
        "Me passa as infos por favor",
        "quero saber mais",
        "me da mais detalhes",
    ):
        assert contem_pedido_de_infos(fala), fala


def test_pergunta_de_preco_nao_e_pedido_de_infos() -> None:
    # "quanto custa" e <cotacao>, tem trilho proprio — o ponteiro de pitch nao arma.
    for fala in ("quanto custa?", "qual o valor amor", "quanto é 1h?"):
        assert not contem_pedido_de_infos(fala), fala


# --- rodada 4: preco ja citado pela propria IA/vendedora entra no conjunto ------------------


def test_preco_citado_no_historico_proprio_e_legitimo() -> None:
    # Historico (seedado ou real) com promo fora da tabela de hoje: repetir o numero ja dado
    # e consistencia, nao invencao — e a escada sobre ele tambem vale.
    validos = _valores_legitimos(
        [(Decimal("400"), Decimal("1"), None)],
        None,
        [AIMessage(content="Faço 350 1h pra você amor", id="hist-1")],
    )
    assert 350 in validos
    assert any(v < 350 for v in validos)  # degrau/piso computados sobre o citado


def test_preco_do_proprio_turno_nao_se_legitima_sozinho() -> None:
    # O turno em julgamento NAO entra no conjunto — senao o preco errado se aprovaria.
    validos = _valores_legitimos(
        [(Decimal("400"), Decimal("1"), None)],
        None,
        [AIMessage(content="Fica 999 1h amor", id="turno-atual")],
        ids_do_turno={"turno-atual"},
    )
    assert 999 not in validos


# --- rodada 4: pedagio (empurrao vazio como resposta universal) -----------------------------


def test_so_empurrao_vazio_e_pedagio() -> None:
    assert resposta_so_pedagio("Seria hoje ?")
    assert resposta_so_pedagio("Poxa amor\n\nSeria que horas ?")
    assert resposta_so_pedagio("Haha\n\nVamos marcar amor ?")


def test_empurrao_com_conteudo_nao_e_pedagio() -> None:
    # A jogada certa — responde E avanca — nunca dispara.
    assert not resposta_so_pedagio("O encontro é 500 1h amor\n\nSeria hoje ?")
    assert not resposta_so_pedagio("Fico na Aquidabã amor\n\nSeria que horas ?")


def test_proposta_com_horario_concreto_e_substancia() -> None:
    # Anti-FP central: pergunta pendente de HORA respondida com proposta concreta tem digito
    # (carrega dado) e nao pode ser tratada como empurrao vazio.
    assert not resposta_so_pedagio("Consigo às 22h, fecha ?")


def test_recusa_curta_e_substancia() -> None:
    assert not resposta_so_pedagio("Não faço amor\n\nSeria hoje ?")


def test_fala_sem_empurrao_nao_e_pedagio() -> None:
    # Filler sozinho (sem empurrao nenhum) nao dispara — o alvo e o empurrao-so.
    assert not resposta_so_pedagio("Poxa amor")
    assert not resposta_so_pedagio("")


# --- rodada 4: saudacao espelhada ------------------------------------------------------------


def test_saudacao_conflitante_dispara() -> None:
    assert saudacao_em_conflito("Boa noite amor 🥰", "boa tarde")
    assert saudacao_em_conflito("Oii\n\nBom dia amor", "boa noite")


def test_saudacao_espelhada_ou_ausente_nao_dispara() -> None:
    assert not saudacao_em_conflito("Boa tarde amor 🥰", "boa tarde")
    # Resposta sem saudacao de periodo: nada a conflitar.
    assert not saudacao_em_conflito("Oii amor, tudo bem sim", "boa tarde")
    # Cliente nao saudou: "boa noite" legitimo a noite nao e julgado.
    assert not saudacao_em_conflito("Boa noite amor", None)


def test_periodo_da_saudacao_normaliza() -> None:
    assert periodo_da_saudacao("Boa Tarde!!") == "boa tarde"
    assert periodo_da_saudacao("bom diaa") is None  # forma exata, sem stemming
    assert periodo_da_saudacao("oi amor") is None


# --- rodada 4: vocabulario coloquial de pedido de endereco ----------------------------------


# --- pix de deslocamento (fala prescrita do <tipos_de_encontro>) ----------------------------


def test_pix_deslocamento_entra_no_conjunto() -> None:
    # Incidente 11/08: "O uber ida e volta fica 100" — a fala PRESCRITA pelo BP_GERAL (pix_valor
    # vem de settings.pix_deslocamento_valor) — era derrubada como preco fantasma e o turno saia
    # MUDO. O unico numero legitimo de fora da tabela que vem de settings entra no conjunto.
    validos = _valores_legitimos([(Decimal("400"), Decimal("1"), None)], None, [])
    assert int(get_settings().pix_deslocamento_valor) in validos


def test_pix_nao_arma_o_detector_de_modelo_sem_tabela() -> None:
    # Sem tabela nem negociacao o conjunto segue VAZIO (= detector desligado, mesma regra do
    # eco): o pix incondicional armaria o closed-world para modelo sem programa cadastrado.
    assert _valores_legitimos([], None, []) == set()


# --- mensagem de regen do preco fantasma: escada nomeada (familia do incidente #36) ---------


def test_feedback_preco_nomeia_a_escada_com_um_preco() -> None:
    # Tabela com UM preco (400): degrau 350 (12,5%) e piso 300 (25%) saem NOMEADOS na mensagem,
    # em cima da razao estatica — proibir sem dar o valor de substituicao fazia o modelo recuar
    # para a recusa seca sem contraproposta. A RODADA nao e nomeada: desde 11/08/2026 a escada
    # depende do dia do encontro (hoje = piso direto) e o dia nao chega ate aqui.
    msg = _feedback_preco_fantasma([(Decimal("400"), Decimal("1"), None)], None)
    assert msg.startswith(_FEEDBACK_GATILHO["preco"])
    assert "os seus numeros possiveis sao 350 e 300" in msg
    assert "com encontro hoje o valor e 300" in msg
    assert "ecoar ou recusar o numero que ELE disse" in msg


def test_feedback_preco_filtra_pela_duracao_fechada() -> None:
    # Tabela multi-duracao mas duracao em pauta fechada (1h): a escada sai sobre o preco DELA.
    tabela = [(Decimal("400"), Decimal("1"), None), (Decimal("700"), Decimal("2"), None)]
    msg = _feedback_preco_fantasma(tabela, 1)
    assert "os seus numeros possiveis sao 350 e 300" in msg


def test_feedback_preco_ambiguo_fica_na_mensagem_estatica() -> None:
    # Mesmo criterio fail-closed do teto_de_contraproposta: dois precos na duracao em pauta
    # ("Padrao 1h 400" e "Casal 1h 700"), ou tabela multi-duracao sem duracao fechada, e a
    # escada sairia sobre o pacote errado — mensagem estatica de hoje, sem numero.
    duas_na_mesma = [(Decimal("400"), Decimal("1"), None), (Decimal("700"), Decimal("1"), None)]
    assert _feedback_preco_fantasma(duas_na_mesma, 1) == _FEEDBACK_GATILHO["preco"]
    multi_sem_duracao = [(Decimal("400"), Decimal("1"), None), (Decimal("700"), Decimal("2"), None)]
    assert _feedback_preco_fantasma(multi_sem_duracao, None) == _FEEDBACK_GATILHO["preco"]


# --- piso ABSOLUTO da linha (`preco_minimo`, 11/08/2026) ------------------------------------


def test_piso_da_linha_clampa_o_conjunto_legitimo() -> None:
    # Os 30min da Catarina: 250 cadastrado COMO o minimo dela. Sem o clamp o guard legitimaria
    # 219 (degrau) e 188 (piso) — e a bolha que ofertasse 188 passaria batida.
    validos = _valores_legitimos([(Decimal("250"), Decimal("0.5"), Decimal("250"))], None, [])
    assert 250 in validos
    assert 219 not in validos  # degrau de 12,5%
    assert 188 not in validos  # teto de 25%


def test_piso_da_linha_clampa_tambem_a_escada_sobre_o_preco_CITADO() -> None:
    # A escada volta pela porta dos fundos se o clamp so valer para a tabela: bastava a IA ter
    # cotado os 250 num turno anterior para o 188 reentrar pelo ramo do historico.
    validos = _valores_legitimos(
        [(Decimal("250"), Decimal("0.5"), Decimal("250"))],
        None,
        [AIMessage(content="250 30min amor", id="hist-1")],
    )
    assert 188 not in validos
    assert 219 not in validos


def test_piso_parcial_deixa_o_degrau_de_pe() -> None:
    # Minimo entre degrau e teto (400 com piso 320): 350 continua legitimo, 300 nao.
    validos = _valores_legitimos([(Decimal("400"), Decimal("1"), Decimal("320"))], None, [])
    assert 350 in validos
    assert 320 in validos
    assert 300 not in validos


def test_feedback_da_linha_sem_desconto_nao_nomeia_numero() -> None:
    # Nomear "os seus numeros sao 250 e 250" em cima de uma tabela de 250 ensinaria a IA a
    # apresentar o proprio preco como concessao — cai na mensagem estatica.
    tabela = [(Decimal("250"), Decimal("0.5"), Decimal("250"))]
    assert _feedback_preco_fantasma(tabela, Decimal("0.5")) == _FEEDBACK_GATILHO["preco"]


def test_pedido_de_endereco_formas_coloquiais() -> None:
    for fala in (
        "Próximo onde?",
        "que rua fica?",
        "não conheço esse hotel rs",
    ):
        assert contem_pedido_de_endereco(fala), fala


def test_objecao_de_distancia_nao_arma_o_guard() -> None:
    # "fica longe"/"é casa ou apartamento" ficam SO no foco (_foco_do_turno): a resposta boa
    # pode nao ter token de endereco ("posso ir até você") e o regen pressionaria a fala errada.
    for fala in ("fica longe pra mim", "o seu é apartamento?"):
        assert not contem_pedido_de_endereco(fala), fala
