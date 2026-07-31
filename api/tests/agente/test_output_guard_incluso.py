"""Detector de "incluso fantasma" no output-guard (corrida do conduta_gate, 30/07).

A modelo do cenário tem o bloco `<fetiches>` vazio — renderiza `(sem fetiches cadastrados)` — e a
IA respondeu "Beijo na boca e oral sem camisinha já vem junto 🥰", copiando palavra por palavra a
fala do `<exemplo>` de apresentação. Três cláusulas de `regras.md.j2` proibiam exatamente isso
(`<apresentacao>`, `<fora_do_cardapio>` e o preâmbulo de `<exemplos>`) e todas perderam para o
exemplo concreto; o `violacoes_duras` do gate marcou 0 — nenhuma rede pegava.

O detector é ESTREITO de propósito: os testes de fala legítima valem tanto quanto os de captura,
porque o fallback dropa a bolha (depois de uma regen) e falso-positivo aqui derruba fala boa.
"""

from barra.agente.nos.output_guard import bolhas_incluso_fantasma, tokens_de_incluso

# Modelo do cenário do gate: nenhum fetiche vinculado -> linha "Inclusos" inexistente.
_SEM_LINHA: set[str] = set()
# Modelo com a linha: "Inclusos (você faz sem custo extra): Beijo na boca, Oral sem camisinha."
_COM_LINHA = tokens_de_incluso("Beijo na boca", "Oral sem camisinha")


# --- a falha medida ------------------------------------------------------------------------


def test_a_bolha_da_corrida_de_hoje_e_reprovada() -> None:
    # Turno 2 de `externo:eb02:159064281587876@lid`, transcritos.jsonl da corrida 20260730-145037.
    bolha = "Beijo na boca e oral sem camisinha já vem junto 🥰"
    assert bolhas_incluso_fantasma(bolha, _SEM_LINHA) == [bolha]


def test_a_fala_do_exemplo_copiada_e_reprovada() -> None:
    # A fala ilustrativa do <exemplo> de apresentação, copiada por quem não tem a linha.
    bolha = "Beijo no pescoço e carinho sem pressa tá incluso amor"
    assert bolhas_incluso_fantasma(bolha, _SEM_LINHA) == [bolha]


def test_so_a_bolha_ofensora_volta() -> None:
    # O fallback dropa por bolha: a apresentação de estilo do mesmo turno tem de sobreviver.
    texto = "Carinhosa e atenciosa amor\n\nBeijo na boca e oral sem camisinha já vem junto 🥰"
    assert bolhas_incluso_fantasma(texto, _SEM_LINHA) == [
        "Beijo na boca e oral sem camisinha já vem junto 🥰"
    ]


# --- a modelo que TEM a linha continua falando os itens dela --------------------------------


def test_itens_da_linha_dela_passam() -> None:
    for fala in (
        "Beijo na boca e oral sem camisinha tá incluso amor",
        "Mas oral sem tá incluso rs",
        "Tem sim amor, o oral sem já vem junto rs",
        "Beijo na boca já vem junto 🥰",
    ):
        assert bolhas_incluso_fantasma(fala, _COM_LINHA) == [], fala


def test_item_fora_da_linha_dela_e_reprovado() -> None:
    # Ela tem beijo e oral inclusos; menage e inversão não estão na linha — não viram cortesia.
    assert bolhas_incluso_fantasma("Menage tá incluso amor", _COM_LINHA) != []
    assert bolhas_incluso_fantasma("Inversão já vem junto amor", _COM_LINHA) != []


def test_limite_conhecido_o_item_que_compartilha_palavra_com_a_linha_escapa() -> None:
    # UM token da linha dela absolve a bolha (generoso de propósito: "oral sem" abrevia "oral sem
    # camisinha", e exigir o nome inteiro derrubaria a fala curta que é a voz dela). O preço é
    # este falso-negativo: "beijo grego" carona no "beijo" de "beijo na boca". Fica pro judge.
    assert bolhas_incluso_fantasma("Beijo grego tá incluso amor", _COM_LINHA) == []
    # Sem a linha no bloco não há carona: é reprovado.
    assert bolhas_incluso_fantasma("Beijo grego tá incluso amor", _SEM_LINHA) != []


def test_sem_a_linha_o_mesmo_item_e_reprovado() -> None:
    # O contraste que dá teeth ao <apresentacao>: a MESMA fala, sem a linha no bloco, é fail.
    assert bolhas_incluso_fantasma("Mas oral sem tá incluso rs", _SEM_LINHA) != []


# --- falso-positivo: falas legítimas que dizem "incluso" ------------------------------------


def test_incluso_do_PROGRAMA_nao_e_do_fetiches() -> None:
    # O que o pacote traz (penetração no Normal, anal no Completo) nunca saiu da linha "Inclusos".
    # "Tudo isso tá incluso no completo" é fala REAL do corpus de prod (Tatiane).
    for fala in (
        "Tudo isso tá incluso no completo",
        "O completo tem anal incluso amor",
        "Anal já vem junto no completo",
        "Tá incluso no valor amor",
        "O uber ida e volta tá incluso no valor",
    ):
        assert bolhas_incluso_fantasma(fala, _SEM_LINHA) == [], fala


def test_o_verbo_incluir_do_programa_nao_e_claim() -> None:
    # <girias_do_cliente>: "o Normal já inclui a penetração (vaginal)". Fala prescrita.
    assert bolhas_incluso_fantasma("O normal já inclui a penetração amor", _SEM_LINHA) == []


def test_claim_negado_e_recusa_correta() -> None:
    for fala in (
        "Beijo na boca não tá incluso amor",
        "Não amor, oral sem camisinha não vem junto",
        "Não tem nada incluso além do programa",
    ):
        assert bolhas_incluso_fantasma(fala, _SEM_LINHA) == [], fala


def test_bolha_curta_sem_item_nomeado_passa() -> None:
    # Resposta curta a uma pergunta do turno anterior: sem item nomeado não há "fora da linha",
    # e barrar aqui mataria a bolha curta que é a voz dela.
    for fala in (
        "Já vem junto sim amor",
        "Vem junto sim",
        "Isso amor, tá incluso 🥰",
    ):
        assert bolhas_incluso_fantasma(fala, _SEM_LINHA) == [], fala


def test_fala_sem_claim_nenhum_passa() -> None:
    for fala in (
        "Sou bem tranquila",
        "Estilo namoradinha",
        "Carinhosa e atenciosa amor",
        "Não faço isso amor",
        "Beijo na boca eu faço sim amor",
        "400 1h no meu local",
    ):
        assert bolhas_incluso_fantasma(fala, _SEM_LINHA) == [], fala


# --- camisinha: nunca sai como "incluso" (<fora_do_cardapio>) -------------------------------


def test_a_afirmacao_direta_da_camisinha_passa() -> None:
    # A fala prescrita: "Só faço com camisinha amor" afirma como ela trabalha, não promete incluso.
    for fala in (
        "Só faço com camisinha amor",
        "Sexo seguro com camisinha rs",
    ):
        for linha in (_SEM_LINHA, _COM_LINHA):
            assert bolhas_incluso_fantasma(fala, linha) == [], fala


def test_camisinha_declarada_incluso_e_reprovada_mesmo_com_oral_sem_na_linha() -> None:
    # "incluso" sugere uma versão sem, que se compra. A palavra "camisinha" fica fora do
    # vocabulário mesmo vindo de "Oral sem camisinha", senão a linha absolveria o claim.
    assert bolhas_incluso_fantasma("Camisinha tá incluso amor", _COM_LINHA) != []
    assert bolhas_incluso_fantasma("Camisinha tá incluso amor", _SEM_LINHA) != []


# --- casos colhidos das 471 bolhas da IA nos transcritos de eval (evals/saidas, gitignored) ---
# Rodar o detector contra elas mediu o falso-positivo: 7/471 flagradas com o bloco vazio, e as 7
# são a MESMA fala copiada do exemplo (as variantes abaixo); com a linha "Inclusos" no bloco,
# 0/471. Nenhuma fala legítima cai. Estas asserções congelam o resultado medido.


def test_variantes_da_copia_do_exemplo_medidas_nos_transcritos() -> None:
    for fala in (
        "Beijo na boca e oral sem camisinha tá incluso",
        "Beijo na boca e oral sem camisinha tá incluso amor 🥰",
        "Beijo na boca e oral sem camisinha tá incluso 🥰",
        "Beijo na boca e oral sem tá incluso",
        "Beijo na boca e oral sem tá incluso amor 🥰",
    ):
        assert bolhas_incluso_fantasma(fala, _SEM_LINHA) == [fala], fala
        assert bolhas_incluso_fantasma(fala, _COM_LINHA) == [], fala


# --- vocabulário ----------------------------------------------------------------------------


def test_ligacao_nao_entra_no_vocabulario() -> None:
    # "sem" de "oral sem camisinha" absolveria qualquer bolha com um "sem" ("carinho sem pressa").
    assert "sem" not in _COM_LINHA
    assert "camisinha" not in _COM_LINHA
    assert {"beijo", "boca", "oral"} <= _COM_LINHA


def test_modelo_sem_fetiche_cadastrado_da_vocabulario_vazio() -> None:
    assert tokens_de_incluso() == set()
