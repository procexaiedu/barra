"""As tres Fichas do telefonista, lidas sem LLM e sem banco (spec 0006, ticket 06; ADR-0046).

Os textos aqui sao o template de `docs/dominio/fichas-do-telefonista.md` **e** as formas degradadas
que a operacao vai produzir: campo vazio, secao faltando, "X" fora do parentese, rotulo abreviado.
E o ponto do ticket — no dia de pico, com quatro clientes subindo, o card sai torto, e o que esta
la tem que entrar. Um parser que so le o template perfeito nao le nada.

O que este arquivo prova:

1. Os TRES documentos sao distinguidos pela marca mecanica que o ADR-0046 fixou: o comunicado nao
   tem `( )` e nao tem `Valor total`. Confundi-lo com a ficha completa e o erro caro — a modelo
   receberia uma segunda ficha do mesmo atendimento e ele seria cobrado duas vezes.
2. Card degradado nao derruba a leitura dos campos que estao la.
3. `Valor do transporte` e `Valor antecipado` sao DOIS numeros (ADR-0046 §6): guardar um so apaga a
   diferenca entre "o cliente mandou 100 e o Uber custou 60" e "a casa bancou um Uber de 15".
4. Debito, credito e link sao formas distintas — "cartao" nao existe mais.
5. Texto que nao e ficha continua caindo no leitor de anuncio, com o comportamento de hoje.
6. Quem e a modelo sai do resolver closed-world; nome desconhecido vira pergunta, nunca palpite.
7. A chave de conteudo NAO tem valor dentro: o repost com desconto tem que colidir com a ficha que
   ele veio substituir, e nao criar um segundo atendimento.

Offline de proposito: nao ha banco, nao ha chave e nao ha rede. O que a ficha faz DENTRO da porta
(gravar calada, perguntar pelo nome, deduplicar o repost) exige as tabelas da onda 20260820 e vive
em `tests/integracao/test_grupo_financeiro_ficha.py`, com `needs_db`.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from barra.dominio.grupo_financeiro.anuncio import parece_anuncio_de_venda
from barra.dominio.grupo_financeiro.ficha import (
    FichaDeAgendamento,
    ParticipanteDaFicha,
    casar_comunicado,
    chave_de_conteudo_da_ficha,
    ler_ficha,
    parece_ficha_do_telefonista,
    planejar_ficha,
)
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes

HOJE = date(2026, 8, 20)

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
BIANCA = UUID("22222222-2222-2222-2222-222222222222")
DUDA = UUID("33333333-3333-3333-3333-333333333333")

CADASTRO = CadastroDeNomes.de_linhas(
    modelos=[(YASMIN, "Yasmin"), (BIANCA, "Bianca"), (DUDA, "Duda")],
    apelidos=[(YASMIN, "sofia"), (BIANCA, "bibi"), (DUDA, "sofia ruiva")],
)

# --- os tres documentos, na grafia do template --------------------------------------------------

FICHA_INDIVIDUAL = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Igor
WhatsApp: 21 99999-8888

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: Barra Vips
Origem: (x) Próprio  ( ) Fake
Nome da modelo: Yasmin

🕒 *HORÁRIO*
Data: 22/08
Hora: 19:00
Duração: 1h

📍 *LOCAL*
(x) Local próprio  ( ) Saída
Tipo: ( ) Casa  (X) Hotel  ( ) Motel  ( ) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço: Rua Miguel y Canizares, 200
Número / bloco / complemento: Torre 2 Apt 2706

💰 *VALORES*
Valor total: R$ 700
Valor desta modelo: R$ 700
Valor do transporte: R$ 60
Valor antecipado: R$ 100
Forma do antecipado: (x) Pix  ( ) Link

💳 *PAGAMENTO*
( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link

✏️ *OBSERVAÇÕES*
O cliente pediu para não passar perfume.
"""

FICHA_DE_GRUPO = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Ramon
WhatsApp: 21 98888-7777

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: GSEX
Origem: ( ) Próprio  (x) Fake
Modelo 1: Yasmin
Modelo 2: Bianca
Modelo 3: Duda

🕒 *HORÁRIO*
Data: 23/08/2026
Hora: 22h
Duração: 2h

📍 *LOCAL*
( ) Local próprio  (x) Saída
Tipo: ( ) Casa  ( ) Hotel  ( ) Motel  (x) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço: Av. das Américas, 5000

💰 *VALORES*
Valor total: R$ 2.400,00
Valor de cada modelo: R$ 800
Valor do transporte: R$
Valor antecipado: R$

💳 *PAGAMENTO*
( ) Dinheiro  ( ) Pix  ( ) Débito  (x) Crédito  ( ) Link
"""

COMUNICADO = """👤 *CLIENTE*
Nome: Igor

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Origem: Próprio

🕒 *HORÁRIO*
Duração: 1h

📍 *LOCAL DO JOB*
Tipo: Hotel
Endereço: Rua Miguel y Canizares, 200

💰 *VALOR DO JOB*
Valor: R$ 700
Forma de pagamento: Dinheiro

✏️ *OBSERVAÇÕES*
Não passar perfume.
"""


def test_ficha_individual_le_todos_os_campos_do_card() -> None:
    lida = ler_ficha(FICHA_INDIVIDUAL, hoje=HOJE)

    assert lida is not None
    assert lida.documento == "individual"
    assert lida.cliente_nome == "Igor"
    assert lida.cliente_whatsapp == "21 99999-8888"
    assert lida.nome_anuncio == "Sofia"
    assert lida.site == "Barra Vips"
    assert lida.origem == "proprio"
    assert lida.nomes_das_modelos == ("Yasmin",)
    assert lida.data == date(2026, 8, 22)
    assert lida.hora == time(19, 0)
    assert lida.duracao_minutos == 60
    assert lida.tipo_atendimento == "interno"
    assert lida.tipo_local == "hotel"
    assert lida.endereco == "Rua Miguel y Canizares, 200"
    assert lida.endereco_complemento == "Torre 2 Apt 2706"
    assert lida.valor_total == Decimal("700.00")
    assert lida.valor_da_modelo == Decimal("700.00")
    assert lida.forma_antecipado == "pix"
    assert lida.forma_pagamento == "pix"
    assert lida.observacoes == "O cliente pediu para não passar perfume."


def test_transporte_e_antecipado_sao_dois_numeros_distintos() -> None:
    """ADR-0046 §6: um numero so apagaria a margem (ou o prejuizo) do deslocamento."""
    lida = ler_ficha(FICHA_INDIVIDUAL, hoje=HOJE)

    assert lida is not None
    assert lida.valor_transporte == Decimal("60.00")
    assert lida.valor_antecipado == Decimal("100.00")


def test_um_valor_de_deslocamento_preenchido_e_o_outro_vazio_e_caso_valido() -> None:
    """O Uber curto que a casa bancou sem cobrar do cliente: transporte sim, antecipado nao."""
    lida = ler_ficha(
        FICHA_INDIVIDUAL.replace("Valor antecipado: R$ 100", "Valor antecipado: R$"), hoje=HOJE
    )

    assert lida is not None
    assert lida.valor_transporte == Decimal("60.00")
    assert lida.valor_antecipado is None


def test_ficha_de_grupo_lista_as_modelos_e_o_valor_de_cada_uma() -> None:
    lida = ler_ficha(FICHA_DE_GRUPO, hoje=HOJE)

    assert lida is not None
    assert lida.documento == "grupo"
    assert lida.nomes_das_modelos == ("Yasmin", "Bianca", "Duda")
    assert lida.valor_total == Decimal("2400.00")
    assert lida.valor_da_modelo == Decimal("800.00")

    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=YASMIN)
    assert [p.modelo_id for p in plano.participantes] == [YASMIN, BIANCA, DUDA]
    assert {p.valor for p in plano.participantes} == {Decimal("800.00")}
    assert [p.ordem for p in plano.participantes] == [1, 2, 3]


def test_valor_de_cada_modelo_nao_e_o_total_dividido_por_n() -> None:
    """R$ 2.400 entre tres nao vira R$ 800 por divisao: e o telefonista quem ratea, e ele pode
    ratear desigual. Sem o "de cada modelo", o valor da participante fica vazio — a ficha nao e
    receita e sobrevive sem ele."""
    lida = ler_ficha(FICHA_DE_GRUPO.replace("Valor de cada modelo: R$ 800", ""), hoje=HOJE)

    assert lida is not None
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=YASMIN)
    assert len(plano.participantes) == 3
    assert all(p.valor is None for p in plano.participantes)


def test_comunicado_nao_e_confundido_com_ficha_completa() -> None:
    """Sem `( )` e sem `Valor total` — as duas marcas mecanicas do ADR-0046."""
    lida = ler_ficha(COMUNICADO, hoje=HOJE)

    assert lida is not None
    assert lida.documento == "comunicado"
    assert lida.valor_total is None
    assert lida.valor_da_modelo == Decimal("700.00")
    assert lida.tipo_local == "hotel"
    assert lida.forma_pagamento == "dinheiro"
    assert lida.cliente_whatsapp is None
    assert lida.data is None and lida.hora is None


# --- as grafias que a operacao de Campinas usa de verdade (25/08/2026) --------------------------
#
# Os dois textos abaixo NAO sao o template do `docs/dominio/fichas-do-telefonista.md`: sao o que o
# telefonista posta hoje nos grupos "Campinas Modelo Gabriela / Financeiro" e "... Beatriz". Eles
# entraram porque cada divergencia de rotulo custava um campo inteiro em silencio — e um campo que
# o parser nao le nao aparece em lugar nenhum como erro, so como coluna vazia no painel.

CARD_DE_CAMPINAS = """📋 FICHA DE AGENDAMENTO

👤 CLIENTE
Nome: daniel

📝 CONTRATAÇÃO
Nome no Anúncio: Megan - dupla com Alicia

🕒 HORÁRIO
Duração: 1h

📍 LOCAL
( x ) Local próprio
( ) Saída

💰 VALORES
Valor: R$600,00

💳 PAGAMENTO
Forma: ( )Pix ( )Dinheiro ( )Cartão

✏️ OBSERVAÇÕES
"""

COMUNICADO_DE_CAMPINAS = """👤 CLIENTE

Nome: Marcos

📝 CONTRATAÇÃO

Nome do Perfil: Megan
Anúncio/Origem: ( x ) Próprio ( ) Fake

📍 LOCAL DO JOB

Tipo: Hotel
Endereço: Av. Brasil, 100

🕒 HORÁRIO

Duração: 2h

💰 VALOR DO JOB

Valor total: R$ 1.200,00

💳 PAGAMENTO

Pix

✏️ OBSERVAÇÕES

Cliente não quer que passe perfume.
"""


def test_nome_no_anuncio_e_lido_como_nome_de_anuncio() -> None:
    """ "Nome NO Anúncio" — a preposicao que o card de Campinas usa e o template nao previa.

    Sem o rotulo a linha inteira caia fora: a ficha nascia sem perfil, e com ela ia embora a marca
    de origem colada ao nome, que e o eixo proprio x fake que o dono pediu para medir.
    """
    lida = ler_ficha(CARD_DE_CAMPINAS, hoje=HOJE)

    assert lida is not None
    assert lida.nome_anuncio == "Megan - dupla com Alicia"
    assert lida.valor_da_modelo == Decimal("600.00")
    assert lida.duracao_minutos == 60
    assert lida.tipo_atendimento == "interno"
    # Nada marcado entre "( )Pix ( )Dinheiro ( )Cartão" continua sendo forma NAO dita — e ela e
    # cobrada de manha, junto com as outras pendencias.
    assert lida.forma_pagamento is None


def test_anuncio_barra_origem_e_rotulo_de_origem_e_nao_de_nome() -> None:
    """ "Anúncio/Origem: ( x ) Próprio ( ) Fake" cola os dois nomes num rotulo so.

    O que vem depois do ":" sao as duas opcoes, nunca um nome — ler isso como `nome_anuncio`
    gravaria "( x ) Próprio ( ) Fake" como o perfil pelo qual o cliente comprou.
    """
    lida = ler_ficha(COMUNICADO_DE_CAMPINAS, hoje=HOJE)

    assert lida is not None
    assert lida.origem == "proprio"
    assert lida.nome_anuncio == "Megan"


def test_forma_sozinha_embaixo_do_cabecalho_de_pagamento_e_lida() -> None:
    """O telefonista apaga as opcoes que nao valem e deixa so "Pix" na linha de baixo.

    Forma e a pendencia que a cobranca da manha mais persegue: perde-la aqui e cobrar no grupo uma
    coisa que o card ja dizia.
    """
    lida = ler_ficha(COMUNICADO_DE_CAMPINAS, hoje=HOJE)

    assert lida is not None
    assert lida.forma_pagamento == "pix"
    assert lida.observacoes == "Cliente não quer que passe perfume."


def test_palavra_de_forma_longe_do_cabecalho_nao_vira_forma() -> None:
    """A janela e SO a linha seguinte ao cabecalho — senao uma observacao de uma palavra viraria
    forma de pagamento, e ainda sumiria das observacoes ao ser consumida."""
    texto = COMUNICADO_DE_CAMPINAS.replace("\nPix\n", "\n").replace(
        "Cliente não quer que passe perfume.", "dinheiro"
    )
    lida = ler_ficha(texto, hoje=HOJE)

    assert lida is not None
    assert lida.forma_pagamento is None
    assert lida.observacoes == "dinheiro"


def test_o_comunicado_de_campinas_nao_se_distingue_pela_marca_do_adr0046() -> None:
    """Limite conhecido, fixado aqui para nao ser descoberto em producao.

    O ADR-0046 separa o comunicado da ficha completa por duas marcas mecanicas: ele nao tem `( )`
    e nao tem `Valor total`. O comunicado que Campinas usa tem AS DUAS — o `( )` vem do
    `Anúncio/Origem` e o rotulo do valor dela e literalmente "Valor total". Logo ele e lido como
    ficha completa.

    Hoje isso e inofensivo e ate correto: nao existe Grupo de fichas (a operacao adiou), entao o
    comunicado e o UNICO documento daquele atendimento e tem mesmo que criar a ficha. Vira
    problema no dia em que o Grupo de fichas existir, porque o mesmo job chegara por duas portas
    com conteudos diferentes e as duas criarao ficha. O conserto e do lado do TEMPLATE (tirar o
    `( )` do Anúncio/Origem e escrever "Valor:"), nao de um discriminador que adivinhe.
    """
    lida = ler_ficha(COMUNICADO_DE_CAMPINAS, hoje=HOJE)

    assert lida is not None
    assert lida.documento == "individual"
    # O valor dela chega inteiro do mesmo jeito: com UMA participante, `Valor total` e o valor
    # dela (nao ha rateio a supor).
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=BIANCA)
    assert [p.valor for p in plano.participantes] == [Decimal("1200.00")]


def test_comunicado_sem_nome_de_modelo_cai_na_dona_do_grupo() -> None:
    """Ele vai para o grupo individual dela: o vinculo grupo<->modelo e closed-world, sem palpite.

    E o `Nome do perfil/anuncio` ("Sofia") tambem resolve, porque o resolver e o mesmo indice de
    `modelo_nomes_anuncio` — e o que faz a ficha do Grupo de fichas achar a modelo (ADR-0046 §2).
    """
    lida = ler_ficha(COMUNICADO, hoje=HOJE)

    assert lida is not None
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=BIANCA)
    assert [p.modelo_id for p in plano.participantes] == [YASMIN]
    assert plano.participantes[0].valor == Decimal("700.00")


# --- o comunicado vincula, nunca cria uma segunda ficha -----------------------------------------


def _ficha_aberta(
    *,
    cliente: str | None = "Igor",
    valor: Decimal | None = Decimal("700.00"),
    modelo_id: UUID = YASMIN,
    data_: date | None = date(2026, 8, 22),
) -> FichaDeAgendamento:
    return FichaDeAgendamento(
        id=uuid4(),
        estado="aberta",
        mensagem_id=uuid4(),
        chave_conteudo="x",
        participantes=(ParticipanteDaFicha(modelo_id=modelo_id, valor=valor),),
        cliente_nome=cliente,
        data=data_,
    )


def test_comunicado_casa_com_a_ficha_aberta_e_nao_cria_uma_segunda() -> None:
    lida = ler_ficha(COMUNICADO, hoje=HOJE)
    assert lida is not None
    alvo = _ficha_aberta()

    veredito, casada = casar_comunicado(lida, modelo_id=YASMIN, abertas=[alvo])

    assert veredito == "vincula"
    assert casada is alvo


def test_comunicado_sem_ficha_correspondente_cria_a_ficha() -> None:
    """O arranjo sem Grupo de fichas — e o que acontece quando o telefonista pula a ficha completa."""
    lida = ler_ficha(COMUNICADO, hoje=HOJE)
    assert lida is not None

    veredito, casada = casar_comunicado(
        lida, modelo_id=YASMIN, abertas=[_ficha_aberta(cliente="Ramon", valor=Decimal("900.00"))]
    )

    assert veredito == "cria"
    assert casada is None


def test_comunicado_que_casa_com_duas_fichas_abertas_nao_escolhe() -> None:
    lida = ler_ficha(COMUNICADO, hoje=HOJE)
    assert lida is not None

    veredito, casada = casar_comunicado(
        lida,
        modelo_id=YASMIN,
        abertas=[_ficha_aberta(data_=date(2026, 8, 22)), _ficha_aberta(data_=date(2026, 8, 25))],
    )

    assert veredito == "ambiguo"
    assert casada is None


def test_comunicado_nao_casa_ficha_de_outra_modelo() -> None:
    """O isolamento cross-modelo e o invariante que nao cede: o valor da participante e por
    modelo, e a ficha da Bianca nao responde pelo comunicado da Yasmin."""
    lida = ler_ficha(COMUNICADO, hoje=HOJE)
    assert lida is not None

    veredito, _ = casar_comunicado(
        lida, modelo_id=YASMIN, abertas=[_ficha_aberta(modelo_id=BIANCA)]
    )

    assert veredito == "cria"


# --- card degradado ------------------------------------------------------------------------------

CARD_DEGRADADO = """FICHA DE ATENDIMENTO
Nome: Igor
Nome do perfil/anúncio: Sofia
Data: 22/08/2026
Hora: 19h
Tipo: ( ) Casa  ( ) Hotel X  ( ) Motel
Valor total: 700
Valor desta modelo:
Pagamento: ( ) Dinheiro ( ) Pix ( ) Débito ( ) Crédito ( ) Link
"""


def test_card_degradado_nao_derruba_a_leitura_dos_campos_que_estao_la() -> None:
    """Campo vazio, secao faltando, X fora do parentese, sem emoji e sem negrito."""
    lida = ler_ficha(CARD_DEGRADADO, hoje=HOJE)

    assert lida is not None
    assert lida.documento == "individual"
    assert lida.cliente_nome == "Igor"
    assert lida.data == date(2026, 8, 22)
    assert lida.hora == time(19, 0)
    assert lida.tipo_local == "hotel"
    assert lida.valor_total == Decimal("700.00")
    assert lida.valor_da_modelo is None
    assert lida.forma_pagamento is None


@pytest.mark.parametrize(
    "linha",
    [
        "Tipo: (x) Casa ( ) Hotel",
        "Tipo: ( ) Casa (X) Hotel",
        "Tipo: ( ) Casa ( ) Hotel",
        "Tipo: Hotel",
    ],
    ids=["dentro", "dentro-maiusculo", "nenhuma", "sem-parentese"],
)
def test_grafias_da_marcacao(linha: str) -> None:
    lida = ler_ficha(CARD_DEGRADADO.replace("Tipo: ( ) Casa  ( ) Hotel X  ( ) Motel", linha))

    assert lida is not None
    esperado = {"casa", "hotel"} if "(x) Casa" in linha else {"hotel", None}
    assert lida.tipo_local in esperado


def test_duas_opcoes_marcadas_nao_viram_sorteio() -> None:
    """O telefonista mudou de ideia e nao apagou. Sortear entre debito e credito e mover dinheiro
    entre duas contas diferentes — o campo vazio volta na cobranca da manha."""
    lida = ler_ficha(
        FICHA_INDIVIDUAL.replace(
            "( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link",
            "( ) Dinheiro  (x) Pix  (x) Débito  ( ) Crédito  ( ) Link",
        ),
        hoje=HOJE,
    )

    assert lida is not None
    assert lida.forma_pagamento is None


def test_template_em_branco_nao_tem_conteudo() -> None:
    """O card vazio repostado para alguem copiar. Gravar criaria um atendimento que ninguem
    combinou — e ele seria cobrado na manha seguinte."""
    em_branco = "\n".join(
        linha.split(":")[0] + ":" if ":" in linha else linha
        for linha in FICHA_INDIVIDUAL.splitlines()
    )
    lida = ler_ficha(em_branco, hoje=HOJE)

    assert lida is not None
    assert not lida.tem_conteudo


# --- as cinco formas de pagamento ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("marcada", "esperada"),
    [
        ("Dinheiro", "dinheiro"),
        ("Pix", "pix"),
        ("Débito", "debito"),
        ("Crédito", "credito"),
        ("Link", "link"),
    ],
)
def test_debito_credito_e_link_sao_formas_distintas(marcada: str, esperada: str) -> None:
    """ADR-0046 §4: "cartao" foi desmembrado. So o credito tem taxa de parcelamento e so o link
    nao passa maquininha — juntar os tres perde a conta de qual e qual."""
    opcoes = " ".join(
        f"(x) {nome}" if nome == marcada else f"( ) {nome}"
        for nome in ("Dinheiro", "Pix", "Débito", "Crédito", "Link")
    )
    lida = ler_ficha(
        FICHA_INDIVIDUAL.replace(
            "( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link", opcoes
        ),
        hoje=HOJE,
    )

    assert lida is not None
    assert lida.forma_pagamento == esperada


# --- quem NAO e ficha ---------------------------------------------------------------------------

ANUNCIO_LIVRE = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h"


@pytest.mark.parametrize(
    "texto",
    [
        ANUNCIO_LIVRE,
        "Bom dia amigas",
        "Foi pix ou din ?",
        "Nome: João",
        "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80",
        "",
    ],
    ids=["anuncio-livre", "social", "pergunta", "uma-linha", "cobranca", "vazio"],
)
def test_texto_que_nao_e_card_nao_vira_ficha(texto: str) -> None:
    assert ler_ficha(texto, hoje=HOJE) is None
    assert not parece_ficha_do_telefonista(texto)


def test_o_anuncio_livre_continua_indo_para_o_leitor_de_anuncio() -> None:
    """A precedencia da ficha nao pode custar o caminho de hoje: o telefonista vai esquecer o card,
    e o sistema nao pode ficar mudo quando ele escrever solto."""
    assert ler_ficha(ANUNCIO_LIVRE, hoje=HOJE) is None
    assert parece_anuncio_de_venda(ANUNCIO_LIVRE)


def test_a_ficha_nao_e_lida_como_anuncio_de_venda() -> None:
    """O outro lado da precedencia: o card nao pode virar receita de um atendimento que ainda nao
    aconteceu."""
    assert parece_ficha_do_telefonista(FICHA_INDIVIDUAL)


# --- o resolver closed-world decide quem e a modelo ---------------------------------------------


def test_nome_desconhecido_nao_vira_participante_e_volta_para_a_pergunta() -> None:
    lida = ler_ficha(
        FICHA_INDIVIDUAL.replace("Nome da modelo: Yasmin", "Nome da modelo: fran loira")
    )

    assert lida is not None
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=None)
    assert plano.participantes == ()
    assert plano.nomes_desconhecidos == ("fran loira",)
    assert plano.faltas == ("modelo",)


def test_homonimo_nao_e_sorteado() -> None:
    """Dois cadastros com o mesmo nome sao erro de cadastro: some no painel, nao no grupo."""
    cadastro = CadastroDeNomes.de_linhas(
        modelos=[(YASMIN, "Yasmin"), (BIANCA, "Yasmin")], apelidos=[]
    )
    lida = ler_ficha(FICHA_INDIVIDUAL)
    assert lida is not None

    plano = planejar_ficha(lida, cadastro=cadastro, dona_do_grupo=None)

    assert plano.ambiguo
    assert plano.participantes == ()


def test_festinha_com_uma_conhecida_e_outra_nao_grava_a_conhecida() -> None:
    """Falta parcial nunca trava o resto — a mesma regra do anuncio de duas modelos."""
    lida = ler_ficha(FICHA_DE_GRUPO.replace("Modelo 2: Bianca", "Modelo 2: fran loira"))

    assert lida is not None
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=None)
    assert [p.modelo_id for p in plano.participantes] == [YASMIN, DUDA]
    assert plano.nomes_desconhecidos == ("fran loira",)


def test_a_mesma_modelo_nomeada_duas_vezes_entra_uma_vez() -> None:
    """O card repetiu o nome real numa linha e o do perfil noutra ("Yasmin" e "Sofia")."""
    lida = ler_ficha(FICHA_DE_GRUPO.replace("Modelo 3: Duda", "Modelo 3: Sofia"))

    assert lida is not None
    plano = planejar_ficha(lida, cadastro=CADASTRO, dona_do_grupo=None)
    assert [p.modelo_id for p in plano.participantes] == [YASMIN, BIANCA]


# --- a chave de conteudo -------------------------------------------------------------------------


def test_a_chave_nao_muda_quando_o_repost_muda_o_valor() -> None:
    """O repost EXISTE para mudar o valor ("o cliente negociou desconto"). Com o valor na chave,
    cada negociacao criaria uma ficha nova e a antiga ficaria viva cobrando um numero morto."""
    original = ler_ficha(FICHA_INDIVIDUAL, hoje=HOJE)
    com_desconto = ler_ficha(
        FICHA_INDIVIDUAL.replace("Valor desta modelo: R$ 700", "Valor desta modelo: R$ 600"),
        hoje=HOJE,
    )
    assert original is not None and com_desconto is not None
    assert original.valor_da_modelo != com_desconto.valor_da_modelo

    assert chave_de_conteudo_da_ficha(
        data=original.data, hora=original.hora, cliente=original.cliente_nome, modelo_ids=[YASMIN]
    ) == chave_de_conteudo_da_ficha(
        data=com_desconto.data,
        hora=com_desconto.hora,
        cliente=com_desconto.cliente_nome,
        modelo_ids=[YASMIN],
    )


def test_a_ordem_das_modelos_nao_muda_a_chave() -> None:
    """A mesma festinha postada em dois grupos tem que produzir a mesma chave — a ordem em que o
    telefonista digitou os nomes muda entre um post e outro."""
    uma = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 23), hora=None, cliente="Ramon", modelo_ids=[YASMIN, BIANCA, DUDA]
    )
    outra = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 23), hora=None, cliente="Ramon", modelo_ids=[DUDA, YASMIN, BIANCA]
    )

    assert uma == outra


def test_dias_diferentes_sao_fichas_diferentes() -> None:
    de_sabado = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 22), hora=time(19, 0), cliente="Igor", modelo_ids=[YASMIN]
    )
    de_domingo = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 23), hora=time(19, 0), cliente="Igor", modelo_ids=[YASMIN]
    )

    assert de_sabado != de_domingo


def test_a_grafia_do_cliente_nao_decide_se_a_ficha_duplica() -> None:
    """ "Cliente Antônio" e "cliente antonio" sao o mesmo homem — a mesma normalizacao da venda."""
    com_acento = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 22), hora=None, cliente="Antônio", modelo_ids=[YASMIN]
    )
    sem_acento = chave_de_conteudo_da_ficha(
        data=date(2026, 8, 22), hora=None, cliente="  antonio ", modelo_ids=[YASMIN]
    )

    assert com_acento == sem_acento


# --- a data sem ano ------------------------------------------------------------------------------


def test_data_sem_ano_usa_o_dia_da_mensagem() -> None:
    lida = ler_ficha(FICHA_INDIVIDUAL, hoje=date(2026, 8, 20))

    assert lida is not None
    assert lida.data == date(2026, 8, 22)


def test_data_sem_ano_na_virada_do_ano_vai_para_o_ano_que_vem() -> None:
    """A ficha nasce ANTES do servico: "02/01" postada em 28/12 e a semana que vem."""
    lida = ler_ficha(
        FICHA_INDIVIDUAL.replace("Data: 22/08", "Data: 02/01"), hoje=date(2026, 12, 28)
    )

    assert lida is not None
    assert lida.data == date(2027, 1, 2)


def test_data_sem_ano_e_sem_o_dia_da_mensagem_nao_e_chutada() -> None:
    lida = ler_ficha(FICHA_INDIVIDUAL)

    assert lida is not None
    assert lida.data is None
