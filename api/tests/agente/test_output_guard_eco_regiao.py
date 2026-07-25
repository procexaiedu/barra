"""Detector de eco de região no output-guard (#41, 24/07).

Cliente chuta um bairro, a IA confirma como se fosse o dela. `regras.md.j2` proíbe literalmente
(incluindo o "centro" genérico como exemplo), e mesmo assim: cliente "atendimento centro" → IA
"Isso amor, aqui no centro", com o cadastro dizendo Cambuí.

O detector é ESTREITO de propósito — os testes de fala legítima valem tanto quanto os de captura:
falso-positivo aqui derruba bolha boa (o gatilho regenera 1x e, persistindo, dropa a bolha).
"""

from barra.agente.nos.output_guard import bolhas_eco_regiao, tokens_de_lugar

# Cadastro real da Tatiane no #41.
_PERMITIDOS = tokens_de_lugar(
    "Cambuí, Campinas", None, "R. Santos Dumont, 291 - Cambuí, Campinas - SP, 13024-020"
)


def test_eco_do_centro_generico_e_pego() -> None:
    # A bolha exata do #41 (08:10:45).
    assert bolhas_eco_regiao("Isso amor, aqui no centro", _PERMITIDOS) == [
        "Isso amor, aqui no centro"
    ]


def test_eco_do_bairro_que_ele_chutou() -> None:
    assert bolhas_eco_regiao("Isso mesmo, fico na Vila Industrial", _PERMITIDOS) != []


def test_confirmar_a_regiao_certa_passa() -> None:
    # A bolha das 10:15:25 do MESMO atendimento: Cambuí É o cadastro, e é fala correta.
    assert bolhas_eco_regiao("Isso amor, no Cambuí", _PERMITIDOS) == []


def test_endereco_do_cadastro_passa() -> None:
    # "Santos Dumont" é maiúscula e não é bairro, mas está no endereço cadastrado.
    assert bolhas_eco_regiao("To no hotel na rua Santos Dumont", _PERMITIDOS) == []
    assert bolhas_eco_regiao("Hotel na Santos Dumont, bem discreto", _PERMITIDOS) == []


def test_substantivo_comum_nao_e_lugar() -> None:
    # Nada disto é bairro — e todas são falas dela no corpus.
    for fala in (
        "Isso amor, aqui no hotel",
        "Estou no meu local",
        "Fico no apartamento sim",
        "Isso, é no Pix mesmo",
        "Isso amor, te chamo no WhatsApp",
    ):
        assert bolhas_eco_regiao(fala, _PERMITIDOS) == [], fala


def test_sem_abridor_nao_casa() -> None:
    # Sem a forma de confirmar/situar, um nome próprio solto não é a IA se colocando num lugar.
    assert bolhas_eco_regiao("Vou te mandar no Pix agora", _PERMITIDOS) == []
    assert bolhas_eco_regiao("Chego de Uber tranquilo", _PERMITIDOS) == []


def test_so_a_bolha_ofensora_volta() -> None:
    # O fallback dropa por bolha: a fala boa do mesmo turno tem de sobreviver.
    texto = "Oi amor tudo bem ?\n\nIsso amor, aqui no centro\n\nQue horas você viria ?"
    assert bolhas_eco_regiao(texto, _PERMITIDOS) == ["Isso amor, aqui no centro"]


def test_sem_cadastro_o_detector_fica_desligado() -> None:
    # Sem campo de lugar não há "fora do cadastro" — inventar veredito derrubaria fala legítima.
    assert bolhas_eco_regiao("Isso amor, aqui no centro", set()) == []


def test_cadastro_no_centro_libera_a_palavra() -> None:
    # A modelo que ATENDE no centro diz "centro" sem ser barrada.
    permitidos = tokens_de_lugar("Centro, Campinas", None, None)
    assert bolhas_eco_regiao("Isso amor, aqui no centro", permitidos) == []


def test_tokens_curtos_e_numeros_do_endereco_nao_viram_vocabulario() -> None:
    # "SP", "291" e o CEP casariam com quase tudo e furariam o detector.
    tokens = tokens_de_lugar(None, None, "R. Santos Dumont, 291 - Cambuí, Campinas - SP, 13024-020")
    assert "291" not in tokens
    assert "sp" not in tokens
    assert {"santos", "dumont", "cambui", "campinas"} <= tokens


# --- casos colhidos das 525 falas reais da IA em prod (Tatiane + Lucia) --------------------
# Rodar o detector contra o corpus foi o que achou o bug do `re.IGNORECASE` (que anulava o teste
# de maiúscula e transformava "nas fotos"/"no completo" em ofensa). Estas asserções travam o
# resultado medido: 8/525 flagradas, todas o "centro" genérico; nenhuma fala legítima cai.


def test_corpus_falas_legitimas_nao_casam() -> None:
    for fala in (
        "Amor, entendo seu cuidado, mas sou eu mesma nas fotos",
        "Fica 800 no normal 1h ou 1600 no completo 1h",
        "Pra vocês três fica 1600 1h no completo amor",
        "Se quiser marcar o encontro presencial, fico feliz em te receber",
        "Sou sua no período combinado amor rs",
        "Tudo isso tá incluso no completo",
        "Tô na faixa dos 400 pro normal, 800 pro completo",
        "Atendo no Cambuí, centro de Campinas",
        "Estou no Cambuí, região central de Campinas amor",
        "Fico por aqui se quiser algo depois",
    ):
        assert bolhas_eco_regiao(fala, _PERMITIDOS) == [], fala


def test_corpus_apelido_do_bairro_do_cadastro_passa() -> None:
    # Fala real: "Cambuizinho" é o Cambuí do cadastro, não um bairro inventado.
    assert bolhas_eco_regiao("Tô no Cambuizinho", _PERMITIDOS) == []


def test_corpus_centro_generico_casa_mesmo_com_o_bairro_certo_junto() -> None:
    # regras.md.j2 proíbe o "centro" genérico mesmo acompanhado da região certa — a região que sai
    # da boca dela é a do cadastro, palavra por palavra.
    for fala in (
        "Estou no centro amor, no Cambuí",
        "To no hotel no centro de campinas, no cambuí",
        "To no centro",
    ):
        assert bolhas_eco_regiao(fala, _PERMITIDOS) != [], fala


def test_corpus_hotel_fora_do_cadastro_casa() -> None:
    # "hotel sunny" / "vitória express" não são o ponto de encontro cadastrado: alucinação de local.
    assert bolhas_eco_regiao("Estou no centro amor, no hotel sunny", _PERMITIDOS) != []
    assert bolhas_eco_regiao("To no centro, perto do vitória express", _PERMITIDOS) != []
