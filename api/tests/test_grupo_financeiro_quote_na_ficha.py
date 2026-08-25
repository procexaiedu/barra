"""Repost e quote alterando a Ficha de agendamento (spec 0006, ticket 09; ADR-0044/0046).

Offline: leitura e decisão puras, sem banco, sem chave e sem rede — a mesma escolha do teste do
razão e do teste do gesto (✅/❌), e pelo mesmo motivo: a regra que decide dinheiro fica lado a
lado numa tabela de casos, onde dá para ler o que o domínio proíbe.

Os dois gestos que o telefonista usa para mudar o combinado sem depender de evento novo de
webhook:

  * **repost** — ele posta o card de novo com o valor negociado. A chave de conteúdo da ficha não
    tem valor dentro (de propósito), então o card colide com o que já existe e **substitui**; o
    repost idêntico continua caindo no dedup e não muda nada;
  * **quote** — ele responde o card com "mudou pra 800", "não veio", "confirmado".

Três invariantes que quebram calado se ninguém olhar:

  * **"confirmado" é a única porta que ainda produz `confirmada`** (ADR-0046 §5, porque o ✅
    passou a promover a venda) — e ela **não** cria venda: registraria receita de um atendimento
    que ainda não aconteceu;
  * **alteração depois de a venda existir vira correção da venda**, nunca venda nova nem ficha
    alterada por baixo do dinheiro já registrado;
  * **"nao veio" tem o mesmo efeito do ❌**, inclusive na recusa de apagar dinheiro em silêncio.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from barra.dominio.grupo_financeiro.correcao import (
    AVISO_DE_ALTERACAO_AMBIGUA,
    MAX_DURACAO_PLAUSIVEL,
    DecisaoDoQuote,
    decidir_quote_na_ficha,
    eventos_da_alteracao,
    ler_quote_na_ficha,
)
from barra.dominio.grupo_financeiro.ficha import (
    AlteracaoDaFicha,
    FichaDeAgendamento,
    ParticipanteDaFicha,
    alteracao_do_repost,
    alterar_ficha,
    chave_de_conteudo_da_ficha,
    ler_ficha,
    montar_eco_da_alteracao,
    mudancas_na_ficha,
    nome_do_atendimento,
    valor_alteravel,
)
from barra.dominio.grupo_financeiro.gesto import AlvoDoGesto, GestoNaFicha, decidir_gesto

HOJE = date(2026, 8, 22)
YASMIN = uuid4()
BIANCA = uuid4()

CARD = """📋 *FICHA DE ATENDIMENTO*

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
"""O template de `docs/dominio/fichas-do-telefonista.md`, na grafia do teste do ticket 06.

A ficha gravada nasce DESTE texto (`_ficha`), e não de campos escolhidos à mão: o repost idêntico
só prova alguma coisa se os dois lados vierem do mesmo lugar — um fixture montado à parte
esconderia justamente o campo que o parser lê e o teste esqueceu."""


def _ficha(*, texto: str = CARD, **kwargs: Any) -> FichaDeAgendamento:
    """A ficha do card acima, já gravada — o alvo de todo gesto deste arquivo."""
    lida = ler_ficha(texto, hoje=HOJE)
    assert lida is not None and lida.documento == "individual"
    campos: dict[str, Any] = {
        "id": uuid4(),
        "estado": "aberta",
        "mensagem_id": uuid4(),
        "chave_conteudo": chave_de_conteudo_da_ficha(
            data=lida.data, hora=lida.hora, cliente=lida.cliente_nome, modelo_ids=[YASMIN]
        ),
        "participantes": (ParticipanteDaFicha(modelo_id=YASMIN, valor=lida.valor_da_modelo),),
        "cliente_nome": lida.cliente_nome,
        "cliente_whatsapp": lida.cliente_whatsapp,
        "nome_anuncio": lida.nome_anuncio,
        "site": lida.site,
        "origem": lida.origem,
        "data": lida.data,
        "hora": lida.hora,
        "duracao_minutos": lida.duracao_minutos,
        "tipo_atendimento": lida.tipo_atendimento,
        "tipo_local": lida.tipo_local,
        "endereco": lida.endereco,
        "endereco_complemento": lida.endereco_complemento,
        "valor_total": lida.valor_total,
        "valor_transporte": lida.valor_transporte,
        "valor_antecipado": lida.valor_antecipado,
        "forma_antecipado": lida.forma_antecipado,
        "forma_pagamento": lida.forma_pagamento,
        "observacoes": lida.observacoes,
    }
    campos.update(kwargs)
    return FichaDeAgendamento(**campos)


def _festinha(*, iguais: bool) -> FichaDeAgendamento:
    """Duas modelos: no mesmo valor ("cada uma") ou em rateio desigual."""
    return _ficha(
        participantes=(
            ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00"), ordem=1),
            ParticipanteDaFicha(
                modelo_id=BIANCA,
                valor=Decimal("700.00") if iguais else Decimal("500.00"),
                ordem=2,
            ),
        ),
        valor_total=Decimal("1400.00") if iguais else Decimal("1200.00"),
    )


def _decidir(texto: str, *, ficha: FichaDeAgendamento, venda_viva: bool = False) -> DecisaoDoQuote:
    quote = ler_quote_na_ficha(texto, referencia=HOJE)
    assert quote is not None, f"{texto!r} não foi lido como gesto sobre a ficha"
    return decidir_quote_na_ficha(quote, ficha=ficha, venda_viva=venda_viva)


# --- repost: o card de novo, com um campo trocado ------------------------------------------------


def test_repost_com_o_valor_negociado_substitui_e_sobra_uma_ficha() -> None:
    """O cliente negociou desconto e o telefonista posta o card de novo com R$ 650.

    A chave de conteúdo é a mesma (ela não tem valor dentro), então não nasce uma segunda ficha:
    o que muda é o valor da que já existe — e o valor DA MODELO anda junto com o total, senão o
    painel mostraria R$ 650 de atendimento com R$ 700 para ela.
    """
    ficha = _ficha()
    lida = ler_ficha(CARD.replace("R$ 700", "R$ 650"), hoje=HOJE)
    assert lida is not None

    alteracao = alteracao_do_repost(ficha, lida, participantes=ficha.participantes)
    depois = alterar_ficha(ficha, alteracao)
    mudancas = mudancas_na_ficha(ficha, depois)

    assert [(m.campo, m.de, m.para) for m in mudancas] == [("valor", "R$ 700,00", "R$ 650,00")]
    assert depois.id == ficha.id  # a MESMA ficha, não uma segunda
    assert depois.valor_total == Decimal("650.00")
    assert [p.valor for p in depois.participantes] == [Decimal("650.00")]


def test_repost_identico_cai_no_dedup_e_nao_muda_nada() -> None:
    """O gesto mais comum do grupo: repostar o mesmo card. Nada mudou, e nada é dito."""
    ficha = _ficha()
    lida = ler_ficha(CARD, hoje=HOJE)
    assert lida is not None

    alteracao = alteracao_do_repost(ficha, lida, participantes=ficha.participantes)
    assert mudancas_na_ficha(ficha, alterar_ficha(ficha, alteracao)) == ()


def test_repost_que_muda_a_data_e_outro_combinado_e_nao_substitui() -> None:
    """Data, hora e cliente são a IDENTIDADE do fato — mudá-los cria ficha própria.

    É o contrário do valor: adiar para sexta não pode apagar o atendimento de quinta em silêncio,
    porque os dois podem acontecer.
    """
    ficha = _ficha()
    lida = ler_ficha(CARD.replace("Data: 22/08", "Data: 23/08"), hoje=HOJE)
    assert lida is not None

    chave_nova = chave_de_conteudo_da_ficha(
        data=lida.data, hora=lida.hora, cliente=lida.cliente_nome, modelo_ids=[YASMIN]
    )
    assert chave_nova != ficha.chave_conteudo


def test_repost_nao_apaga_o_campo_que_o_card_deixou_em_branco() -> None:
    """O telefonista corta a linha do transporte para caber a pressa; isso não é "zera o
    transporte". Apagar campo é gesto de painel."""
    ficha = _ficha()
    assert ficha.valor_transporte == Decimal("60.00")
    sem_transporte = "\n".join(
        linha for linha in CARD.splitlines() if "Valor do transporte" not in linha
    )
    lida = ler_ficha(sem_transporte, hoje=HOJE)
    assert lida is not None and lida.valor_transporte is None

    depois = alterar_ficha(
        ficha, alteracao_do_repost(ficha, lida, participantes=ficha.participantes)
    )
    assert depois.valor_transporte == Decimal("60.00")


# --- quote: "mudou pra 800" ----------------------------------------------------------------------


def test_quote_com_mudou_pra_800_altera_o_valor_e_ecoa_o_de_para() -> None:
    """A frase do ticket, ponta a ponta: leitura, decisão, eco e rastro."""
    decisao = _decidir("mudou pra 800", ficha=_ficha())

    assert decisao.efeito == "alterar_ficha"
    assert decisao.motivo == "ficha_alterada"
    assert [(m.campo, m.de, m.para) for m in decisao.mudancas] == [
        ("valor", "R$ 700,00", "R$ 800,00")
    ]
    eco = montar_eco_da_alteracao(decisao.mudancas)
    assert eco.startswith("✏️ Alterei: valor R$ 700,00 → R$ 800,00")
    assert "corrige aí" in eco  # a porta de correção continua aberta depois da alteração


def test_alteracao_deixa_uma_linha_de_auditoria_por_campo() -> None:
    """`ficha_de_agendamento_eventos` é append-only e o CHECK exige `campo` na `alteracao`."""
    decisao = _decidir("mudou pra 800", ficha=_ficha())
    eventos = eventos_da_alteracao(decisao.mudancas)

    assert decisao.eventos == eventos
    assert [(e.tipo, e.campo, e.valor_anterior, e.valor_novo) for e in eventos] == [
        ("alteracao", "valor", "R$ 700,00", "R$ 800,00")
    ]


def test_alteracao_que_nao_muda_nada_e_calada() -> None:
    """ "mudou pra 700" numa ficha que já está em 700: não houve evento, e dizer "alterei" ali
    seria mentir para quem confere de relance."""
    decisao = _decidir("mudou pra 700", ficha=_ficha())

    assert decisao.efeito == "ignorar"
    assert decisao.motivo == "ficha_sem_alteracao"
    assert decisao.pergunta is None


def test_valor_de_festinha_com_rateio_desigual_vira_pergunta() -> None:
    """Escolher de qual das duas é a alteração move dinheiro de uma mulher para a outra."""
    desigual = _festinha(iguais=False)
    assert valor_alteravel(desigual) is False

    decisao = _decidir("mudou pra 800", ficha=desigual)
    assert decisao.efeito == "perguntar"
    assert decisao.motivo == "valor_de_varias"
    assert decisao.pergunta == AVISO_DE_ALTERACAO_AMBIGUA


def test_valor_de_festinha_no_mesmo_numero_cabe_nas_duas() -> None:
    """ "cada uma" é como o card é escrito: com as duas no mesmo valor não há o que desempatar."""
    iguais = _festinha(iguais=True)
    assert valor_alteravel(iguais) is True

    decisao = _decidir("mudou pra 800", ficha=iguais)
    depois = alterar_ficha(iguais, decisao.alteracao or AlteracaoDaFicha())

    assert decisao.efeito == "alterar_ficha"
    assert [p.valor for p in depois.participantes] == [Decimal("800.00"), Decimal("800.00")]
    # O total é do CARD e não se deduz de "800": na festinha os dois números são dinheiros
    # diferentes, e supor o total seria supor rateio igual.
    assert depois.valor_total == iguais.valor_total


# --- quote: "não veio" -------------------------------------------------------------------------


@pytest.mark.parametrize("texto", ["não veio", "nao veio", "furou", "cancelou", "não rolou"])
def test_quote_de_cancelamento_cancela_a_ficha(texto: str) -> None:
    decisao = _decidir(texto, ficha=_ficha())

    assert decisao.efeito == "cancelar"
    assert decisao.estado_resultante == "cancelada"
    assert [(e.tipo, e.valor_anterior, e.valor_novo) for e in decisao.eventos] == [
        ("cancelamento", "aberta", "cancelada")
    ]


def test_nao_veio_tem_o_mesmo_efeito_do_xis() -> None:
    """Duas superfícies do mesmo gesto (o emoji e o texto) não podem divergir em conduta."""
    do_texto = _decidir("não veio", ficha=_ficha())
    do_emoji = decidir_gesto(GestoNaFicha("❌"), AlvoDoGesto(estado="aberta"))

    assert (do_texto.efeito, do_texto.estado_resultante) == ("cancelar", "cancelada")
    assert (do_emoji.efeito, do_emoji.estado_resultante) == ("cancelar", "cancelada")


def test_cancelar_o_que_ja_virou_venda_pergunta_em_vez_de_apagar() -> None:
    """Nunca apagar dinheiro em silêncio — a mesma recusa do ❌ sobre ficha já promovida."""
    ficha = _ficha(estado="realizada")
    decisao = _decidir("não veio", ficha=ficha, venda_viva=True)

    assert decisao.efeito == "perguntar"
    assert decisao.motivo == "cancelamento_com_venda"
    assert decisao.pergunta is not None
    assert nome_do_atendimento(ficha) in decisao.pergunta  # a pergunta NOMEIA o atendimento


def test_cancelar_ficha_ja_cancelada_nao_faz_nada() -> None:
    decisao = _decidir("não veio", ficha=_ficha(estado="cancelada"))
    assert decisao.efeito == "ignorar"


# --- quote: "confirmado" — a última porta do estado `confirmada` --------------------------------


@pytest.mark.parametrize("texto", ["confirmado", "tá confirmado", "confirmou", "confirmada"])
def test_quote_confirmado_leva_a_ficha_a_confirmada(texto: str) -> None:
    """Depois do ADR-0046 §5 esta é a ÚNICA porta que produz `confirmada`: o ✅ do telefonista
    passou a promover a venda. Sem ela o estado nasce órfão."""
    decisao = _decidir(texto, ficha=_ficha())

    assert decisao.efeito == "confirmar"
    assert decisao.estado_resultante == "confirmada"
    assert [(e.tipo, e.valor_anterior, e.valor_novo) for e in decisao.eventos] == [
        ("confirmacao", "aberta", "confirmada")
    ]


def test_confirmado_nao_cria_venda() -> None:
    """A diferença que o ADR-0046 desenhou: "confirmado" vem ANTES do atendimento; o ✅ vem depois
    do pagamento. Confundi-los registraria receita de um atendimento que não aconteceu."""
    decisao = _decidir("confirmado", ficha=_ficha())

    assert decisao.efeito not in ("alterar_ficha", "corrigir_venda")
    assert decisao.estado_resultante != "realizada"
    assert decisao.correcao is None


def test_confirmar_duas_vezes_nao_gera_evento_novo() -> None:
    decisao = _decidir("confirmado", ficha=_ficha(estado="confirmada"))

    assert decisao.efeito == "ignorar"
    assert decisao.eventos == ()


def test_confirmado_sobre_ficha_cancelada_pergunta() -> None:
    """Os dois gestos se contradizem, e ressuscitar em silêncio desfaria um "não veio"
    deliberado."""
    decisao = _decidir("confirmado", ficha=_ficha(estado="cancelada"))

    assert decisao.efeito == "perguntar"
    assert decisao.motivo == "confirmacao_sobre_cancelada"


def test_nao_confirmou_nao_e_confirmacao() -> None:
    """A mesma palavra com o sinal trocado. Sem a tranca, o gesto que diz o CONTRÁRIO moveria o
    estado."""
    assert ler_quote_na_ficha("não confirmou", referencia=HOJE) is None


# --- quote ambíguo, e o que não é gesto nenhum --------------------------------------------------


@pytest.mark.parametrize("texto", ["mudou", "mudou pra 800 ou 700", "trocou o combinado"])
def test_quote_ambiguo_nao_altera_nada_e_vira_pergunta(texto: str) -> None:
    """Silêncio aqui é o pior desfecho: o telefonista escreveu, viu o agente calado e vai embora
    achando que mudou."""
    ficha = _ficha()
    decisao = _decidir(texto, ficha=ficha)

    assert decisao.efeito == "perguntar"
    assert decisao.motivo == "quote_ambiguo"
    assert decisao.alteracao is None
    assert decisao.mudancas == ()
    assert decisao.pergunta is not None
    assert nome_do_atendimento(ficha) in decisao.pergunta


@pytest.mark.parametrize("texto", ["ok", "valeu", "bom trabalho", "já tô indo", "👍"])
def test_conversa_respondendo_o_card_nao_e_gesto(texto: str) -> None:
    """O grupo responde o card o tempo todo, e nada disso muda combinado nenhum."""
    assert ler_quote_na_ficha(texto, referencia=HOJE) is None


def test_22h_solto_e_ambiguo_entre_horario_e_duracao() -> None:
    """A ambiguidade que só a ficha tem: ela guarda hora E duração, e "22h" é as duas coisas.

    No recibo de venda não há hora, então "era 2h" só pode ser duração; aqui, perguntar custa uma
    mensagem e errar custa a modelo aparecendo no horário errado.
    """
    quote = ler_quote_na_ficha("mudou pra 22h", referencia=HOJE)
    assert quote is not None and quote.gesto == "ambiguo"


def test_horario_dito_como_horario_altera_a_hora() -> None:
    decisao = _decidir("horário 22h", ficha=_ficha())

    assert decisao.efeito == "alterar_ficha"
    assert [(m.campo, m.de, m.para) for m in decisao.mudancas] == [("hora", "19:00", "22:00")]


def test_duracao_plausivel_continua_sendo_duracao() -> None:
    """O pernoite (12h) é o teto do que a casa vende, e ele tem que continuar passando."""
    quote = ler_quote_na_ficha("era 12h", referencia=HOJE)
    assert quote is not None
    assert quote.alteracao is not None
    assert quote.alteracao.duracao_minutos == MAX_DURACAO_PLAUSIVEL


# --- a venda já existe: altera o dinheiro, não o combinado --------------------------------------


def test_alteracao_depois_da_venda_vira_correcao_da_venda() -> None:
    """Alterar a ficha aqui deixaria a venda com o número velho: dois números para o mesmo
    atendimento, cada um verdadeiro na sua tabela."""
    decisao = _decidir("mudou pra 800", ficha=_ficha(estado="realizada"), venda_viva=True)

    assert decisao.efeito == "corrigir_venda"
    assert decisao.motivo == "alteracao_vira_correcao"
    assert decisao.correcao is not None
    assert decisao.correcao.valor == Decimal("800.00")
    # Não mexe no combinado, e não nasce venda nova: o atendimento é um só.
    assert decisao.alteracao is None
    assert decisao.estado_resultante is None


def test_horario_depois_da_venda_nao_reabre_o_combinado() -> None:
    """O horário não move dinheiro nenhum depois do pagamento."""
    decisao = _decidir("horário 22h", ficha=_ficha(estado="realizada"), venda_viva=True)

    assert decisao.efeito == "ignorar"
    assert decisao.motivo == "quote_sem_efeito"
