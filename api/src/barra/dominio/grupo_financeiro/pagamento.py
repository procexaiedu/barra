"""Absorver a forma de pagamento dita no grupo (spec 0005, ticket 03).

O grupo real anuncia a venda e cobra o pagamento DEPOIS, em mensagens de uma palavra:

    [12/08 13:22:35] Atendimento no nosso local / Cliente Lucas / Bianca seu nome / 600 1h
    [12/08 13:22:47] O Lucas de ontem
    [12/08 13:22:52] Foi pix também amiga ?
    [12/08 13:23:54] Sim

Duas perguntas tem que ser respondidas para essa sequencia virar dado: **o que foi dito** e
**sobre qual venda**. Este modulo responde as duas, e nas duas a regra e a mesma do resto do
modulo: na duvida, nao adivinha — a venda fica pendente e a rotina da manha cobra (ticket 10).

## O que foi dito — `ler_fala_de_pagamento`

Casamento por ALLOWLIST, nao por "contem a palavra pix". O grupo esta cheio de mensagens com
"pix" que NAO sao resposta de pagamento e que, absorvidas, escreveriam dinheiro errado na venda
de alguem: "Pix erick", "Pode enviar nesse pix", "Minha Chave Pix para transferência: +5571…",
"Yasmin confere por favor / 600 pix / 600 pix" (fechamento, ticket 09). Por isso a fala so conta
quando TODAS as palavras da mensagem estao na allowlist (a forma + recheio de conversa) e a
mensagem e curta: um nome proprio, um verbo no imperativo ou um numero sobrando ja a
desqualificam.

"?" (ou "ou") faz a mesma frase virar PERGUNTA em vez de resposta — e a pergunta importa: e dela
que o "Sim" seguinte herda a forma.

## Sobre qual venda — `escolher_pagamento`

Escada de sinais, do mais forte ao mais fraco, parando no primeiro que decide:

0. **Quantificador coletivo** — "todos foram pix" nao escolhe uma venda: escolhe TODAS as abertas.
   Vem antes de tudo porque e uma afirmacao sobre escopo, e escopo dito vence alvo inferido.
1. **Quote** — a mensagem responde o anuncio (ou o recibo dele). Nao ha o que interpretar.
2. **Cliente citado no contexto recente** — "O Lucas de ontem" antes do "Foi pix?". E este passo
   que cumpre "atualiza a venda certa, nao a ultima": sem ele, a resposta cairia na venda mais
   recente so por ser a mais recente, e a venda citada (dias mais velha) ficaria pendente para
   sempre. Varre do mais recente para o mais antigo; a mencao mais proxima da resposta ganha.
3. **Unica venda aberta** — nao ha o que confundir.

Sem nenhum dos tres: `ambigua`. Marcar "dinheiro" na venda de outro cliente e o erro que nunca
mais e descoberto — a venda errada some do fechamento e a certa nunca mais e cobrada. Mas o
silencio tambem cobra um preco (`montar_pergunta_de_desempate`): quem disse a forma acha que
resolveu, e a mesma cobranca volta identica amanha. Entre adivinhar e calar existe a terceira
conduta, que e a que este modulo toma quando ha candidata: perguntar de qual.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.bolso import Bolso, VendaComBolso
from barra.dominio.grupo_financeiro.ficha import FichaDeAgendamento
from barra.dominio.grupo_financeiro.modelos import (
    FormaPagamento,
    MensagemRegistrada,
    VendaRegistrada,
)
from barra.dominio.grupo_financeiro.pendencia import EM_ESPECIE_COM_A_MODELO, em_especie
from barra.dominio.grupo_financeiro.recibo import (
    CONVITE_DE_CORRECAO,
    formatar_duracao,
    formatar_reais,
)

TipoDeFala = Literal["pergunta", "resposta", "confirmacao"]

MotivoDaEscolha = Literal["escolhida", "todas", "sem_venda_aberta", "sem_forma", "ambigua"]

# Mensagem de pagamento e telegrafica ("Pix", "Dinheiro", "Foi pix também amiga ?"). O teto
# derruba de graca tudo que e frase de verdade — chave Pix ditada, instrucao de transferencia,
# conferencia de fechamento — antes mesmo da allowlist.
MAX_PALAVRAS = 6

_PALAVRA = re.compile(r"[a-z0-9]+")

_PIX = frozenset({"pix"})
_DINHEIRO = frozenset({"dinheiro", "din", "dindin", "especie", "cash"})

# As TRES formas de cartao (ADR-0046 §4, ticket 11). Cada uma tem vocabulario proprio porque cada
# uma concilia no seu extrato: dizer "debito" quando foi credito manda o operador procurar o
# dinheiro na adquirente errada, e ele so descobre no fim do mes.
_DEBITO = frozenset({"debito"})
_CREDITO = frozenset({"credito", "parcelado"})
_LINK = frozenset({"link"})

# "Cartao" e "maquininha" NAO sao forma, e nao viram uma: sao a FAMILIA. Depois do desmembramento
# elas nao tem para onde ser gravadas — nao existe mais o valor "cartao" na coluna — e escolher uma
# das tres por frequencia mandaria o operador procurar o dinheiro na adquirente errada, coisa que
# ele so descobre no fim do mes.
#
# Elas entram como RECHEIO, entao "recebi no cartao de credito" e lido (quem decide e "credito") e
# "recebi em cartao" continua sendo descartado inteiro, como antes deste ticket: a familia sozinha
# nao e resposta. O silencio ali e conhecido e esta pinado em teste — fecha-lo e devolver uma
# pergunta de uma palavra ("debito, credito ou link?"), e perguntar e conduta da porta, nao deste
# leitor.
_CARTAO_GENERICO = frozenset({"cartao", "cartoes", "maquininha", "maquineta"})

_CONFIRMACAO = frozenset({"sim", "isso", "exato", "positivo", "confirmado", "confirma"})

# Recheio de conversa que pode acompanhar a forma sem mudar o que ela diz. Fechada de proposito:
# palavra fora daqui (um nome proprio, um verbo) e sinal de que a mensagem NAO e uma resposta de
# pagamento — e o que separa "Pix" de "Pix erick".
#
# Os DEMONSTRATIVOS ("esse foi pix", "essa foi dinheiro") entram porque sao o jeito mais comum de
# apontar a venda recem-anunciada sem repetir o nome do cliente, e sem eles a fala inteira era
# descartada em silencio — a modelo respondia e nada acontecia. Eles nao decidem QUAL venda (isso
# e `escolher_pagamento`, que na duvida pergunta): so deixam a fala existir. "nesse"/"desse" sao
# palavras diferentes e seguem fora, que e o que mantem "Pode enviar nesse pix" descartado.
_RECHEIO = frozenset(
    {
        "a",
        "ai",
        "amiga",
        "amigo",
        "aquela",
        "aquele",
        "da",
        "de",
        "do",
        "e",
        "eh",
        "ela",
        "ele",
        "em",
        "entao",
        "era",
        "eram",
        "eles",
        "elas",
        "esse",
        "essa",
        "esses",
        "essas",
        "este",
        "esta",
        "estes",
        "estas",
        "foi",
        "foram",
        "os",
        "as",
        "forma",
        "gente",
        "na",
        "ne",
        "no",
        "obg",
        "obrigada",
        "ok",
        "ou",
        "pagamento",
        "pago",
        "pagou",
        "sim",
        "isso",
        "tambem",
        "tbm",
        "certo",
        "o",
        "por",
        "pela",
        "pelo",
        "favor",
    }
)

# O QUANTIFICADOR COLETIVO. A cobranca da manha e consolidada — ela lista N vendas de uma vez —,
# entao a resposta humana a ela tambem e coletiva ("todos foram pix"), e nao quatro mensagens. Sem
# estas palavras a fila nao andava de dois jeitos: "todos foram pix" era descartado em silencio e
# "tudo pix" era lido como resposta SINGULAR, o que fazia o agente reperguntar "foi pix em qual?"
# logo depois de o gestor ter respondido "em todas" — devolvendo como pergunta a mesma lista que
# ele acabara de mandar.
#
# "tudo"/"td" saíram do recheio para ca: como recheio, elas nao mudavam nada e a frase inteira
# valia por uma venda so. Aqui elas dizem o que sempre disseram.
_COLETIVOS = frozenset({"todos", "todas", "tudo", "td"})

# O coletivo que conta: "ambos", "os dois", "as duas" dizem TODAS **se forem duas**. Com quatro
# pendencias abertas, "os dois foram pix" nao e o universal — e uma frase sobre duas delas, e o
# agente nao sabe quais. Sem esta separacao, o numeral seria lido como "todas" e escreveria em
# quatro vendas por causa de uma palavra que diz dois. Quando a conta nao bate, cai na pergunta de
# desempate, que e exatamente a conduta certa: perguntar quais.
_COLETIVOS_DE_PAR = frozenset({"ambos", "ambas", "dois", "duas"})

# O VERBO DO AVISO (ticket 07). Depois do ADR-0044 a fala que fecha o fato mudou de dono e de
# forma: nao e mais a gestora respondendo "Pix" a uma pergunta, e a MODELO avisando por conta
# propria — "recebi, foi dinheiro", "recebi em pix", e as tres variantes que o Rossi ditou na
# reuniao de 20/08 ("recebi", "recebi em dinheiro", "recebi em cartão", "recebi em pix").
#
# Sem estas palavras a frase inteira do ticket era descartada em silencio: "recebi" nao estava na
# allowlist, e uma palavra fora dela desqualifica a mensagem toda. A modelo avisava, o agente
# calava, e a ficha do Igor seguia aberta sendo cobrada na manha seguinte.
#
# Entram como RECHEIO e nao como confirmacao: "recebi" sozinho continua nao decidindo nada — ele
# nao responde "foi pix ou dinheiro?", e o gesto de promover sem forma dita e a outra porta
# (o ✅ do telefonista, ticket 20).
_RECEBIMENTO = frozenset({"recebi", "recebido", "recebida", "recebeu", "ja"})

_FORMAS_DITAS: tuple[tuple[frozenset[str], FormaPagamento], ...] = (
    (_PIX, "pix"),
    (_DINHEIRO, "dinheiro"),
    (_DEBITO, "debito"),
    (_CREDITO, "credito"),
    (_LINK, "link"),
)
"""As cinco formas e as palavras que as dizem, na ordem em que a fala e varrida.

Uma tabela e nao cinco `if`: a leitura precisa saber QUANTAS formas distintas a mensagem cita
(uma = resposta, duas ou mais = pergunta/oferta, "foi pix ou no debito?"), e isso e uma contagem,
nao uma cadeia de condicoes. Forma nova = mais uma linha aqui."""

_PERMITIDAS = (
    _RECHEIO
    | _PIX
    | _DINHEIRO
    | _DEBITO
    | _CREDITO
    | _LINK
    | _CARTAO_GENERICO
    | _CONFIRMACAO
    | _COLETIVOS
    | _COLETIVOS_DE_PAR
    | _RECEBIMENTO
)


@dataclass(frozen=True)
class FalaDePagamento:
    """O que uma mensagem curta diz sobre forma de pagamento.

    `forma` nula numa pergunta = ela ofereceu mais de uma ("Foi pix ou din ?"), entao um "Sim"
    depois dela nao decide nada. Numa `resposta` a forma nunca e nula (a fala nao existiria sem
    ela) — inclusive quando a mensagem diz "cartao": a familia sozinha nao produz fala nenhuma.
    """

    tipo: TipoDeFala
    forma: FormaPagamento | None = None
    coletiva: bool = False
    """A fala diz "todas" — uma afirmacao sobre ESCOPO, nao sobre uma venda ("todos foram pix")."""
    alvos_esperados: int | None = None
    """Quantas vendas o coletivo diz cobrir. `None` = o universal ("todos"), que vale para quantas
    houver. `2` = o numeral ("os dois", "ambas"), que so vale se houver exatamente duas abertas."""


@dataclass(frozen=True)
class EscolhaDePagamento:
    """A quem pendurar a forma dita — ou por que nao deu para saber."""

    motivo: MotivoDaEscolha
    venda_id: UUID | None = None
    forma: FormaPagamento | None = None
    vendas: tuple[UUID, ...] = ()
    """So o motivo `todas` preenche: os alvos do quantificador coletivo. Fica separado de
    `venda_id` de proposito — quem trata uma venda so nao deve compilar contra o caso coletivo por
    acidente, e o recibo dos dois e diferente."""


def ler_fala_de_pagamento(
    texto: str, *, nomes_de_cliente: Sequence[str] = ()
) -> FalaDePagamento | None:
    """A mensagem fala de forma de pagamento? `None` para todo o resto do grupo.

    `nomes_de_cliente` sao os clientes das vendas ABERTAS do grupo, e eles entram na allowlist
    como recheio. E o que torna a cobranca da manha respondivel: ela nomeia N vendas ("Cliente
    Gabriel · R$ 700,00 · ontem — foi pix ou dinheiro?"), e a resposta humana a uma lista nomeia
    de qual delas se fala ("o do Gabriel foi pix"). Sem isso, "gabriel" e palavra fora da
    allowlist, a fala inteira e descartada, e a partir de DUAS pendencias nenhuma resposta
    possivel fecha a cobranca — ela volta identica amanha, que e o loop que a rotina existe para
    fechar.

    So os clientes de venda ABERTA entram, e so eles: a allowlist continua fechada para nome
    proprio em geral ("Pix erick", quando Erick nao e cliente de nada aberto, segue descartado).
    """
    normalizado = normalizar(texto)
    if not normalizado:
        return None
    palavras = _PALAVRA.findall(normalizado)
    if not palavras:
        return None
    nomes = [_PALAVRA.findall(normalizar(nome)) for nome in nomes_de_cliente]
    permitidas = _PERMITIDAS | {palavra for nome in nomes for palavra in nome}
    # O teto acompanha o nome do cliente: "o do Gabriel foi pix" cabe em 6, mas "o do Antonio
    # Carlos foi pix" nao. A folga e o tamanho do MAIOR nome aberto — sem ela, nomear a venda
    # derrubaria a propria fala que a nomeia.
    teto = MAX_PALAVRAS + max((len(nome) for nome in nomes), default=0)
    if len(palavras) > teto:
        return None

    ditas = tuple(
        forma_dita
        for vocabulario, forma_dita in _FORMAS_DITAS
        if any(p in vocabulario for p in palavras)
    )

    if not ditas:
        # "Sim" / "Isso" sozinho. Vale como confirmacao SO se a pergunta imediatamente anterior
        # trouxer a forma — quem checa isso e `escolher_pagamento`, porque aqui nao ha contexto.
        # Nome de cliente NAO entra aqui: "o do Gabriel" sozinho nao confirma nada.
        confirma = any(p in _CONFIRMACAO for p in palavras)
        if confirma and all(p in _PERMITIDAS for p in palavras) and "?" not in normalizado:
            return FalaDePagamento("confirmacao")
        return None

    if any(p not in permitidas for p in palavras):
        return None

    # UMA forma dita = a fala decide. Duas ou mais ("foi pix ou no debito?", "metade no credito e
    # metade em dinheiro") nao decidem nada: a primeira e uma oferta e a segunda e um pagamento
    # dividido, que este modulo nao sabe gravar — a venda tem UMA coluna de forma.
    forma: FormaPagamento | None = ditas[0] if len(ditas) == 1 else None
    if forma is None or "?" in normalizado or "ou" in palavras:
        # PERGUNTA nao carrega o coletivo: "todos foram pix?" e a gestora cobrando, nao afirmando.
        # Quem responde "Sim" a ela responde sobre a venda do turno, e alargar isso para todas as
        # abertas seria transformar uma confirmacao de uma palavra na escrita mais larga do modulo.
        return FalaDePagamento("pergunta", forma)
    universal = any(p in _COLETIVOS for p in palavras)
    par = any(p in _COLETIVOS_DE_PAR for p in palavras)
    return FalaDePagamento(
        "resposta",
        forma,
        coletiva=universal or par,
        alvos_esperados=None if universal else (2 if par else None),
    )


def escolher_pagamento(
    *,
    fala: FalaDePagamento,
    texto: str = "",
    contexto: Sequence[MensagemRegistrada],
    abertas: Sequence[VendaRegistrada],
    venda_citada: UUID | None = None,
) -> EscolhaDePagamento:
    """Liga a fala a UMA venda aberta. `contexto` vem do mais recente para o mais antigo.

    `texto` e a mensagem que esta falando AGORA (o contexto e estritamente o que veio antes dela).
    Ele entra logo depois do quote, como segundo sinal mais forte: quem responde uma cobranca que
    nomeia varias vendas nomeia de qual fala ("o do Gabriel foi pix"), e o nome dito na propria
    resposta vale mais do que qualquer nome achado no historico. Sem este passo a cobranca
    consolidada da manha e inrespondivel a partir de duas pendencias — a mensagem mais recente do
    contexto e a propria cobranca, que nomeia todas elas, e o resultado e sempre `ambigua`.
    """
    forma = fala.forma
    if fala.tipo == "confirmacao":
        forma = _forma_da_pergunta_anterior(contexto)
    if forma is None:
        return EscolhaDePagamento("sem_forma")
    if not abertas:
        return EscolhaDePagamento("sem_venda_aberta", forma=forma)

    if fala.coletiva and len(abertas) > 1:
        # ESCOPO DITO vence alvo inferido, e por isso o coletivo vem antes do quote e do nome: a
        # escada abaixo existe para descobrir de qual venda a fala trata, e aqui isso ja esta
        # respondido — de todas. Manter a escada rodando faria a mensagem cair no quote (a venda do
        # anuncio citado) e escrever em UMA, contradizendo a palavra que o gestor escolheu.
        #
        # Com uma venda so, coletivo e singular sao a mesma coisa: cai na escada normal, que rende
        # o recibo nomeado (cliente + valor + dia), mais util que "1 venda".
        if fala.alvos_esperados is not None and fala.alvos_esperados != len(abertas):
            # "os dois foram pix" com quatro abertas: a frase fala de duas e nao diz quais.
            return EscolhaDePagamento("ambigua", forma=forma)
        return EscolhaDePagamento("todas", forma=forma, vendas=tuple(venda.id for venda in abertas))

    if venda_citada is not None and any(v.id == venda_citada for v in abertas):
        return EscolhaDePagamento("escolhida", venda_id=venda_citada, forma=forma)

    nomeadas = [v for v in abertas if _cita_cliente(texto, v.cliente_nome)]
    if len(nomeadas) == 1:
        return EscolhaDePagamento("escolhida", venda_id=nomeadas[0].id, forma=forma)
    if len(nomeadas) > 1:
        # A propria resposta nomeia duas vendas abertas. Ir procurar no historico seria trocar um
        # empate DITO por um palpite achado.
        return EscolhaDePagamento("ambigua", forma=forma)

    for mensagem in contexto:
        citadas = [v for v in abertas if _cita_cliente(mensagem.texto, v.cliente_nome)]
        if len(citadas) == 1:
            return EscolhaDePagamento("escolhida", venda_id=citadas[0].id, forma=forma)
        if len(citadas) > 1:
            # A mensagem mais proxima nomeia duas vendas abertas ("Gabriel e Lucas foram pix?").
            # Ir procurar mais para tras seria trocar um empate por um palpite.
            return EscolhaDePagamento("ambigua", forma=forma)

    if len(abertas) == 1:
        return EscolhaDePagamento("escolhida", venda_id=abertas[0].id, forma=forma)
    return EscolhaDePagamento("ambigua", forma=forma)


PREFIXO_DO_DESEMPATE = "❓ Foi "
"""Assinatura da pergunta de desempate. E por ela que a porta reconhece, no proprio log do grupo,
que ja perguntou — e nao repergunta a cada "pix" solto (a metralhadora que o dominio proibe)."""

MAX_CANDIDATAS_NOMEADAS = 3
"""Quantas vendas a pergunta nomeia. A resposta e um NOME, e o nome de qualquer venda aberta
serve — inclusive de uma que nao coube na lista (a allowlist de `ler_fala_de_pagamento` carrega
todas). Nomear as tres mais recentes e so o atalho para o caso comum; listar sete seria
transformar uma pergunta de uma palavra num formulario."""


def montar_pergunta_de_desempate(
    *, forma: FormaPagamento, candidatas: Sequence[VendaRegistrada]
) -> str | None:
    """A pergunta que salva uma forma ja dita e sem dono. `None` = nao ha o que perguntar.

    Nao e cobrar forma de pagamento (isso e Pendencia, e a cobranca dela e consolidada de manha,
    ticket 10): a forma JA foi dita nesta mensagem. O que falta e o alvo — e perguntar o alvo e a
    unica conduta que aproveita o que a modelo acabou de falar sem escrever na venda errada.

    Objetiva como toda pergunta deste modulo: se responde com um nome. As mais RECENTES primeiro
    porque a resposta de pagamento fala quase sempre da venda de agora; as antigas seguem na
    cobranca da manha, que e o lugar delas.
    """
    if not candidatas:
        return None
    recentes = list(candidatas[-MAX_CANDIDATAS_NOMEADAS:])
    recentes.reverse()
    itens = " · ".join(_candidata(venda) for venda in recentes)
    resto = len(candidatas) - len(recentes)
    cauda = f" (e mais {resto})" if resto > 0 else ""
    return f"{PREFIXO_DO_DESEMPATE}{forma} em qual? {itens}{cauda} — me diz o nome do cliente."


# --- sobre qual FICHA (ticket 07) ---------------------------------------------------------------
#
# A partir do ADR-0044 a mesma fala tem dois alvos possiveis: a Venda registrada que ja existe e
# espera a forma, e a **Ficha de agendamento** que ainda nao virou venda. "recebi, foi dinheiro"
# num grupo com a ficha do Igor aberta nao e resposta de pendencia — e o fato nascendo.
#
# A escada e a MESMA de `escolher_pagamento`, e de proposito: quote > nome dito na fala > nome no
# contexto recente > unica aberta > ambigua. Um segundo criterio para o mesmo gesto faria o
# agente responder coisas diferentes para "foi pix" conforme o alvo, que e o tipo de divergencia
# que ninguem descobre olhando o grupo.
#
# O que muda e o ESCOPO: a lista de fichas e a **da modelo** (ADR-0046 §2), venha o card do grupo
# dela ou do Grupo de fichas — enquanto a lista de vendas abertas e a do grupo.

SinalDaFicha = Literal["quote", "nome", "unica"]
"""Por que esta ficha foi escolhida. `quote` e `nome` sao sinais DITOS pelo humano; `unica` e o
fallback de "nao ha o que confundir" — e e por isso que a porta trata os dois grupos de forma
diferente quando ha, ao mesmo tempo, uma venda aberta disputando a mesma fala."""

MotivoDaEscolhaDaFicha = Literal["escolhida", "sem_ficha_aberta", "ambigua"]


@dataclass(frozen=True)
class EscolhaDaFicha:
    """Qual Ficha de agendamento esta fala fecha — ou por que nao deu para saber."""

    motivo: MotivoDaEscolhaDaFicha
    ficha: FichaDeAgendamento | None = None
    sinal: SinalDaFicha | None = None


def escolher_ficha(
    *,
    texto: str = "",
    contexto: Sequence[MensagemRegistrada] = (),
    abertas: Sequence[FichaDeAgendamento],
    ficha_citada: UUID | None = None,
) -> EscolhaDaFicha:
    """Liga a fala de pagamento a UMA ficha aberta da modelo. `contexto` vem do mais recente.

    Tres fichas abertas e nada que aponte devolve `ambigua`, nunca a mais recente: promover a
    ficha errada cria uma venda com o cliente e o valor de OUTRO atendimento, e a certa continua
    aberta sendo cobrada. Quem desempata e uma pergunta (`montar_pergunta_de_desempate_de_fichas`),
    que custa uma mensagem — o palpite custa uma venda que ninguem mais confere.
    """
    if not abertas:
        return EscolhaDaFicha("sem_ficha_aberta")

    if ficha_citada is not None:
        citada = next((f for f in abertas if f.id == ficha_citada), None)
        if citada is not None:
            return EscolhaDaFicha("escolhida", ficha=citada, sinal="quote")

    nomeadas = [f for f in abertas if _cita_cliente(texto, f.cliente_nome)]
    if len(nomeadas) == 1:
        return EscolhaDaFicha("escolhida", ficha=nomeadas[0], sinal="nome")
    if len(nomeadas) > 1:
        return EscolhaDaFicha("ambigua")

    for mensagem in contexto:
        citadas = [f for f in abertas if _cita_cliente(mensagem.texto, f.cliente_nome)]
        if len(citadas) == 1:
            return EscolhaDaFicha("escolhida", ficha=citadas[0], sinal="nome")
        if len(citadas) > 1:
            return EscolhaDaFicha("ambigua")

    if len(abertas) == 1:
        return EscolhaDaFicha("escolhida", ficha=abertas[0], sinal="unica")
    return EscolhaDaFicha("ambigua")


def montar_pergunta_de_desempate_de_fichas(
    *, forma: FormaPagamento, candidatas: Sequence[FichaDeAgendamento], modelo_id: UUID
) -> str | None:
    """ "❓ Foi dinheiro em qual? Igor (R$ 700,00) · … — me diz o nome do cliente."

    Irma de `montar_pergunta_de_desempate` e com o MESMO prefixo, porque a tranca contra
    reperguntar (a porta reconhece a propria pergunta no log do grupo) tem que valer para os dois
    alvos: quem responde "recebi" sem nomear com tres fichas abertas repete "recebi" sem nomear, e
    duas perguntas por gesto e a metralhadora que o dominio proibe.

    O valor mostrado e o **da participante** (`valor_de`), nunca o `valor_total`: numa festinha,
    dizer 2.000 para uma das tres entrega a conta das outras.
    """
    if not candidatas:
        return None
    # As mais RECENTES primeiro, como na pergunta das vendas: quem acabou de receber esta falando
    # do atendimento de agora. A ficha SEM data (a que nasceu de um comunicado) vai para o fim —
    # e a menos identificada de todas, e nomea-la primeiro gastaria a lista com a pior opcao.
    ordenadas = sorted(candidatas, key=lambda f: f.data or date.min, reverse=True)
    recentes = ordenadas[:MAX_CANDIDATAS_NOMEADAS]
    itens = " · ".join(_candidata_da_ficha(ficha, modelo_id) for ficha in recentes)
    resto = len(candidatas) - len(recentes)
    cauda = f" (e mais {resto})" if resto > 0 else ""
    return f"{PREFIXO_DO_DESEMPATE}{forma} em qual? {itens}{cauda} — me diz o nome do cliente."


def montar_recibo_da_promocao(
    *,
    nome_da_modelo: str | None,
    valor: Decimal,
    data: date,
    forma: FormaPagamento | None = None,
    cliente: str | None = None,
    duracao_minutos: int | None = None,
    local: str | None = None,
) -> str:
    """ "✅ Registrei: Sofia R$ 700,00 · dinheiro (em espécie com a modelo) · 22/08 · Cliente Igor ·
    1h · no nosso local — corrige aí se algo estiver errado".

    O recibo da venda que NASCEU da ficha. Um so, e nao o recibo da venda mais o do pagamento: o
    que aconteceu no mundo foi um fato so, e duas mensagens seguidas sobre ele viram ruido num
    grupo habitado.

    Ele repete o que o telefonista digitou de proposito — cliente, duracao, local — porque e a
    primeira vez que a modelo ve **o sistema** afirmando aqueles campos, e e por este recibo que
    ela corrige por quote (o de->para do ticket 05 sai identico ao da venda de texto livre).

    Sem forma dita (o ✅ solto do ticket 20), a linha da forma simplesmente nao aparece: recibo
    nao e formulario, e campo vazio anunciado seria uma pergunta disfarcada.
    """
    partes = [f"{nome_da_modelo or 'modelo'} {formatar_reais(valor)}"]
    if forma is not None:
        partes.append(f"{forma} ({EM_ESPECIE_COM_A_MODELO})" if em_especie(forma) else forma)
    partes.append(f"{data:%d/%m}")
    if cliente:
        partes.append(f"Cliente {cliente}")
    if duracao_minutos:
        partes.append(formatar_duracao(duracao_minutos))
    if local:
        partes.append(local)
    return f"✅ Registrei: {' · '.join(partes)} — {CONVITE_DE_CORRECAO}"


# --- em que BOLSO caiu: a fala explicita (ADR-0047 §2, ticket 21) --------------------------------
#
# A terceira linha da tabela de evidencia. As duas de cima sao imagem (comprovante); as duas de
# baixo sao regra (`forma = dinheiro`) e ignorancia (`nao_dito`). Esta e a unica que e FALA, e por
# isso mora aqui, ao lado do outro leitor de fala curta do modulo: "foi pix" e "ficou com voce"
# sao a mesma mensagem de uma linha, ditas no mesmo minuto, sobre a mesma venda — duas gramaticas
# separadas divergiriam no primeiro dia em que uma ganhasse uma palavra e a outra nao.
#
# O que muda e a TECNICA de casamento, e a diferenca e do dominio, nao de gosto. A forma se diz com
# uma PALAVRA ("pix", "dinheiro"), entao a allowlist de palavras funciona. O bolso se diz com uma
# FRASE cuja unica diferenca entre os dois sentidos e uma palavra no meio:
#
#     "caiu na minha conta"  ->  dela
#     "caiu na conta da casa" -> empresa
#
# Um saco de palavras leria as duas como iguais (as duas tem "caiu", "na", "conta"). Por isso aqui
# o casamento e por FRASE inteira, em ordem — e a tabela e fechada, como toda allowlist do modulo:
# frase que nao esta nela nao decide nada, e a venda segue `nao_dito`, que e estado legitimo.

MAX_PALAVRAS_DO_BOLSO = 12
"""Teto de palavras para a frase valer como fala de bolso.

Mais folgado que `MAX_PALAVRAS` (a forma se diz em uma palavra; o bolso, em quatro) e ainda assim
um teto: "ficou com voce" no meio de um paragrafo e conversa, e mexer no sinal do saldo de alguem
por causa de tres palavras perdidas num texto longo e o palpite que o modulo se proibe."""

_BOLSO_DITO: tuple[tuple[str, Bolso], ...] = (
    # DELA — o dinheiro parou na mao/conta da modelo.
    ("caiu na minha conta", "dela"),
    ("caiu no meu pix", "dela"),
    ("caiu na minha chave", "dela"),
    ("caiu pra mim", "dela"),
    ("caiu comigo", "dela"),
    ("recebi na minha conta", "dela"),
    ("recebi no meu pix", "dela"),
    ("veio pra mim", "dela"),
    ("foi pra minha conta", "dela"),
    ("foi pro meu pix", "dela"),
    ("ficou comigo", "dela"),
    ("ficou com voce", "dela"),
    ("ficou contigo", "dela"),
    ("fica comigo", "dela"),
    ("fica com voce", "dela"),
    ("ta comigo", "dela"),
    ("esta comigo", "dela"),
    # EMPRESA — o dinheiro entrou direto na conta da casa.
    ("caiu na conta da casa", "empresa"),
    ("caiu na conta da empresa", "empresa"),
    ("caiu no pix da casa", "empresa"),
    ("caiu no pix da empresa", "empresa"),
    ("caiu pra voces", "empresa"),
    ("caiu pra gente", "empresa"),
    ("foi pra conta da casa", "empresa"),
    ("foi pro pix da casa", "empresa"),
    ("foi pra empresa", "empresa"),
    ("pagou direto pra voces", "empresa"),
    ("pagou direto pra casa", "empresa"),
    ("pagou no pix da casa", "empresa"),
    ("voces receberam", "empresa"),
    ("nao passou por mim", "empresa"),
)
"""As frases que dizem onde o dinheiro caiu, e o bolso de cada uma. Fechada de proposito.

As mais LONGAS sao testadas primeiro (`ler_fala_de_bolso` ordena), e isso nao e detalhe: "caiu na
conta da casa" contem "caiu na conta"; sem a ordem por tamanho, um prefixo mais curto poderia
roubar a frase mais especifica e inverter o sinal do saldo.

Duas ausencias deliberadas. **"foi pra casa"** nao esta aqui: no grupo real ela quase sempre fala
do cliente que foi embora, e uma frase ambigua numa tabela de evidencia contamina justamente a
decisao mais cara do modulo. **"no meu pix"** solto tambem nao: "pode enviar no meu pix" e a
modelo DITANDO a chave dela (ticket 12), nao dizendo onde o dinheiro caiu."""

_NEGACOES = ("nao ", "n ", "nem ")
"""O que, imediatamente antes da frase, a desqualifica.

"nao caiu na minha conta" CONTEM "caiu na minha conta" — sem esta guarda, a negacao seria lida
como a afirmacao contraria do que foi dito, que e o pior erro possivel neste campo. E ela DESCARTA
em vez de inverter: "nao caiu na minha conta" nao prova que caiu na da casa (pode ter caido na da
parceira), e inferir o oposto de uma negacao e adivinhar. A venda segue `nao_dito` e entra na
cobranca da manha, que e o canal que ja existe."""

MotivoDaEscolhaDoBolso = Literal["escolhida", "sem_venda", "ambigua"]


@dataclass(frozen=True)
class FalaDeBolso:
    """O que uma mensagem curta diz sobre EM QUE BOLSO o dinheiro daquela venda caiu."""

    bolso: Bolso
    frase: str
    """A frase da tabela que decidiu — auditoria da leitura, e o que um teste pina."""


@dataclass(frozen=True)
class EscolhaDoBolso:
    """A que venda pendurar o bolso dito — ou por que nao deu para saber."""

    motivo: MotivoDaEscolhaDoBolso
    venda: VendaComBolso | None = None


def ler_fala_de_bolso(texto: str) -> FalaDeBolso | None:
    """A mensagem diz onde o dinheiro caiu? `None` para todo o resto do grupo.

    Casamento por FRASE INTEIRA numa tabela fechada, da mais longa para a mais curta, sobre o texto
    ja normalizado e sem pontuacao. Duas guardas antes disso:

    * **"?" descarta.** "Ficou com voce?" e a gestora perguntando, e absorver a pergunta como
      resposta escreveria na venda o que ninguem afirmou — o mesmo criterio de
      `ler_fala_de_pagamento`.
    * **negacao descarta**, nunca inverte (`_NEGACOES`).

    Nao ha ladder de confirmacao ("Sim") aqui de proposito, e a diferenca com a forma de pagamento
    e do grupo real: a forma chega como PERGUNTA da gestora e resposta da modelo ("Foi pix ou din
    ?" -> "Sim"), enquanto o bolso chega afirmado de uma vez ("Ficou com voce", 12/08 19:09). O
    grupo responde "Sim" o dia inteiro para coisa nenhuma; fazer um "Sim" fixar bolso seria mexer
    no sinal do saldo por uma palavra que quase sempre e sobre outra coisa.
    """
    normalizado = normalizar(texto)
    if not normalizado or "?" in normalizado:
        return None
    palavras = _PALAVRA.findall(normalizado)
    if not palavras or len(palavras) > MAX_PALAVRAS_DO_BOLSO:
        return None
    limpo = " ".join(palavras)
    for frase, bolso in sorted(_BOLSO_DITO, key=lambda par: len(par[0]), reverse=True):
        posicao = limpo.find(frase)
        if posicao < 0:
            continue
        antes = limpo[:posicao]
        if any(antes.endswith(negacao) for negacao in _NEGACOES):
            return None
        return FalaDeBolso(bolso, frase)
    return None


def escolher_venda_do_bolso(
    *,
    texto: str = "",
    contexto: Sequence[MensagemRegistrada] = (),
    candidatas: Sequence[VendaComBolso],
    venda_citada: UUID | None = None,
) -> EscolhaDoBolso:
    """Liga a fala de bolso a UMA venda. `contexto` vem do mais recente para o mais antigo.

    A MESMA escada de `escolher_pagamento` e `escolher_ficha`, e de proposito: quote > nome dito na
    propria fala > nome no contexto recente > unica candidata > ambigua. Um segundo criterio para o
    mesmo gesto faria o agente responder coisas diferentes a "ficou com voce" conforme o alvo.

    `candidatas` e a janela de vendas que o chamador considera confrontaveis (as recentes da
    modelo), e nao a vida inteira dela: com trinta vendas na lista, "unica" nunca dispara e toda
    fala vira `ambigua` — a escada precisa de um universo do tamanho da conversa.

    Vendas com bolso JA afirmado continuam na lista: a fala que as contradiz nao e ignorada, ela
    vira pergunta (`bolso.confrontar_bolso`). Tirar as afirmadas daqui faria a contradicao cair
    calada na venda vizinha, que e o erro que ninguem descobre.
    """
    if not candidatas:
        return EscolhaDoBolso("sem_venda")

    if venda_citada is not None:
        citada = next((v for v in candidatas if v.id == venda_citada), None)
        if citada is not None:
            return EscolhaDoBolso("escolhida", citada)

    nomeadas = [v for v in candidatas if _cita_cliente(texto, v.cliente_nome)]
    if len(nomeadas) == 1:
        return EscolhaDoBolso("escolhida", nomeadas[0])
    if len(nomeadas) > 1:
        return EscolhaDoBolso("ambigua")

    for mensagem in contexto:
        citadas = [v for v in candidatas if _cita_cliente(mensagem.texto, v.cliente_nome)]
        if len(citadas) == 1:
            return EscolhaDoBolso("escolhida", citadas[0])
        if len(citadas) > 1:
            return EscolhaDoBolso("ambigua")

    if len(candidatas) == 1:
        return EscolhaDoBolso("escolhida", candidatas[0])
    return EscolhaDoBolso("ambigua")


# --- interno ------------------------------------------------------------------------------------


def _candidata(venda: VendaRegistrada) -> str:
    """Uma venda aberta como opcao de resposta: o nome primeiro, que e o que se responde."""
    quem = venda.cliente_nome or f"{venda.data:%d/%m}"
    return f"{quem} ({formatar_reais(venda.valor)})"


def _forma_da_pergunta_anterior(contexto: Sequence[MensagemRegistrada]) -> FormaPagamento | None:
    """ "Sim" so confirma a pergunta IMEDIATAMENTE anterior.

    O grupo responde "Sim" o dia inteiro para coisa nenhuma a ver com dinheiro ("Ficou com você"
    -> "Sim", 12/08 19:09). Aceitar a ultima pergunta de pagamento que existir no historico faria
    esse "Sim" reabrir uma conversa de seis horas antes, ja respondida. Exigir adjacencia e o que
    mantem a confirmacao ancorada no turno em que ela foi dita.
    """
    if not contexto:
        return None
    anterior = ler_fala_de_pagamento(contexto[0].texto)
    if anterior is None or anterior.tipo != "pergunta":
        return None
    return anterior.forma


def _cita_cliente(texto: str, cliente: str | None) -> bool:
    """O texto nomeia este cliente? Casamento EXATO de palavra inteira, na forma normalizada.

    Palavra inteira (e nao substring) porque cliente e texto livre e nome curto: "Igor" nao pode
    casar dentro de "Rodrigor", e "ramon" nao pode casar dentro de "ramona".
    """
    if not cliente:
        return False
    alvo = normalizar(cliente)
    if not alvo:
        return False
    padrao = rf"(?<![a-z0-9]){re.escape(alvo)}(?![a-z0-9])"
    return re.search(padrao, normalizar(texto)) is not None


def _candidata_da_ficha(ficha: FichaDeAgendamento, modelo_id: UUID) -> str:
    """Uma ficha aberta como opcao de resposta: o nome do cliente primeiro, que e o que se responde.

    Sem cliente no card, o dia do combinado — que e o outro jeito de a modelo dizer qual ("o de
    ontem"). Sem os dois, o valor dela, que e o ultimo discriminador que sobra.
    """
    valor = ficha.valor_de(modelo_id)
    if ficha.cliente_nome:
        quem = ficha.cliente_nome
    elif ficha.data:
        quem = f"{ficha.data:%d/%m}"
    else:
        quem = "sem cliente"
    return f"{quem} ({formatar_reais(valor)})" if valor is not None else quem
