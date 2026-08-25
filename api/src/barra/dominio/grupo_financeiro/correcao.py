"""Correcao por quote no recibo (spec 0005, ticket 05).

O recibo do ticket 02 termina em "corrige aí se algo estiver errado" — e ISTO le a correcao. O
grupo responde o recibo (ou o proprio anuncio) com o campo novo e mais nada:

    [08/08 01:12] ✅ Registrei: Yasmin R$ 700,00 · 08/08 · Cliente Gabriel · 1h — corrige aí …
    [08/08 01:13] foi 650                     -> valor
    [08/08 01:13] o cliente era Ramon         -> cliente
    [08/08 01:14] foi dia 07                  -> data
    [08/08 01:15] era 1h30                    -> duracao
    [08/08 01:16] na verdade foi 800          -> valor   (o "na verdade" e decapitado)
    [08/08 01:17] era o Caio Silva            -> cliente (o artigo e o gatilho)

Tres decisoes moldam a leitura, e as tres saem do mesmo lugar: **a correcao escreve por cima de
um dado que ja esta na conta de alguem**.

1. **So dentro do quote.** As mesmas palavras soltas no grupo nao corrigem nada — "650" sozinho e
   resposta de pergunta minima (ticket 03) e "foi pix" e absorcao de forma de pagamento. O quote
   e o unico sinal que diz DE QUAL venda se esta falando sem adivinhar; quem le o contexto para
   escolher a venda ja tem o direito de errar uma vez (a forma de pagamento), e errar duas vezes
   seria escrever o valor de um atendimento em cima de outro.
2. **Ou a mensagem inteira e correcao, ou nada e.** Cada linha tem que render um campo; uma linha
   que nao rende derruba a leitura toda. E isso que impede um anuncio novo postado em cima do
   recibo (que tem linha "Cliente …", legivel aqui) de virar correcao do anuncio velho.
3. **Um campo aparece uma vez.** Duas linhas dizendo dois valores nao viram "o ultimo ganha" —
   viram silencio. Escolher entre duas afirmacoes contraditorias e exatamente o palpite que o
   modulo inteiro se proibe.

A gramatica ABRIU em 14/08 por um motivo medido: a gestora escrevia "na verdade foi 800" e "era o
Caio Silva" citando o anuncio, e o agente ficava mudo — a correcao nao acontecia e ninguem sabia,
que e o pior desfecho possivel para uma porta que existe para consertar. Duas aberturas, as duas
presas ao mesmo criterio (a linha ainda tem que render um campo):

* **Prefixo de retificacao decapitado** ("na verdade", "corrigindo", "opa") — ele nao dita campo,
  entao vira ruido a remover, nao um campo a inventar.
* **Cliente sem a palavra "cliente"**, com o ARTIGO como gatilho ("era o Caio") e teto de
  palavras. E o ultimo recurso da linha: pagamento, data, duracao e valor sao tentados antes,
  senao "era o pix" viraria um cliente chamado pix.

Fora de escopo de proposito: **local** ("no nosso local" e indistinguivel de conversa e nao move
dinheiro nenhum) e **modelo** (trocar a mulher de uma venda e mudar de quem e o dinheiro; isso
sai pela porta de anular-e-repostar, que deixa as duas linhas visiveis no rastro).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, time
from decimal import Decimal
from typing import Any, Literal

from barra.dominio.grupo_financeiro.anuncio import ler_valor_avulso, normalizar
from barra.dominio.grupo_financeiro.ficha import (
    AlteracaoDaFicha,
    EstadoDaFicha,
    FichaDeAgendamento,
    MudancaNaFicha,
    alterar_ficha,
    mudancas_na_ficha,
    nome_do_atendimento,
    valor_alteravel,
)
from barra.dominio.grupo_financeiro.gesto import EventoDaFicha
from barra.dominio.grupo_financeiro.modelos import FormaPagamento, VendaRegistrada
from barra.dominio.grupo_financeiro.pagamento import ler_fala_de_pagamento
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA
from barra.dominio.grupo_financeiro.recibo import (
    CONVITE_DE_CORRECAO,
    formatar_duracao,
    formatar_reais,
)

CampoCorrigivel = Literal["valor", "data", "cliente", "duracao", "forma_pagamento"]

CAMPOS_DA_LINHA: tuple[CampoCorrigivel, ...] = ("valor", "forma_pagamento")
"""Campos que pertencem a UMA Venda registrada, e nao ao anuncio.

Os outros (data, cliente, duracao) sao do FATO: corrigi-los num recibo de duas modelos vale para
as duas, porque foi um atendimento so. Estes dois nao — cada mulher tem o valor dela e pode ter
recebido de um jeito diferente. Corrigir "o valor" num recibo de duas so e seguro quando as duas
estao no mesmo valor hoje (o caso do "cada uma"); quem decide isso e a porta."""

SEM_VALOR = "—"
"""Como um campo vazio aparece no eco e no rastro. Melhor que "None" para quem le no grupo e no
painel."""

AVISO_DE_CORRECAO_DUPLICADA = (
    "♻️ Não apliquei: essa correção deixaria a venda igual a outra que já está registrada."
)
"""A correcao existe, foi entendida, e mesmo assim nada mudou. Ficar calado aqui e o pior dos
mundos — a gestora corrigiu e vai embora achando que corrigiu."""

AVISO_DE_CORRECAO_AMBIGUA = (
    "❓ Esse registro tem duas modelos em valores diferentes — não sei de qual é a correção. "
    "Ajusta no painel, aí não tem risco de eu trocar."
)
"""Correcao de campo POR LINHA num recibo de duas modelos que nao estao no mesmo valor. Adivinhar
qual delas move o dinheiro de uma para a outra; perguntar "de quem?" abriria um vai-e-vem que a
porta ainda nao sabe terminar. Manda para onde o dado e visivel e o erro e reversivel."""

ROTULO: dict[CampoCorrigivel, str] = {
    "valor": "valor",
    "data": "data",
    "cliente": "cliente",
    "duracao": "duração",
    "forma_pagamento": "forma de pagamento",
}

# Teto de linhas de uma correcao. O grupo corrige um campo, as vezes dois ("foi 650" + "o cliente
# era Ramon"); tres ja e generoso. Um anuncio inteiro tem mais linhas que isto e morre aqui antes
# de qualquer leitura.
MAX_LINHAS = 3

_VERBO = r"(?:foi|era|eh|e|é)"

_CLIENTE = re.compile(
    rf"^(?:o\s+)?cliente\b[\s:,\-]*(?:{_VERBO}\s+)?(?:[oa]\s+)?(?P<nome>\S.*?)\s*$",
    re.IGNORECASE,
)

# Como quem corrige ABRE a frase. Nao dita campo nenhum — e so o pedido de desculpa que vem colado
# no dado ("na verdade foi 800", "corrigindo: 650", "opa, era o Ramon"). Sem isto a linha inteira
# morria: "na verdade" nao rende campo, e uma linha que nao rende campo derruba a leitura toda.
# Lista fechada, como toda allowlist deste modulo — palavra generica aqui viraria licenca para
# decapitar qualquer coisa ate sobrar um numero.
_RETIFICACAO = re.compile(
    r"^(?:na\s+verdade|na\s+vdd|corrigindo|corre[cç][aã]o|desculpa?e?|perd[aã]o|"
    r"opa|ops|eita|ali[aá]s|pera[ií]?|peraí|ah|obs)\b[\s:,\-–—!]*",
    re.IGNORECASE,
)
_RETIFICACAO_NO_FIM = re.compile(
    r"[\s,;\-–—]*(?:na\s+verdade|na\s+vdd|ali[aá]s|desculpa?e?|perd[aã]o)[\s.!]*$",
    re.IGNORECASE,
)

# "era o Caio Silva", "é a Duda", "o nome dele é Ramon". O gatilho e o ARTIGO depois do verbo (ou
# a palavra "nome"): e ele que separa nome proprio de "era 1h30" e "foi 650", que nao levam artigo.
# Ainda assim isto e o ULTIMO recurso da linha — tudo que tem leitura propria (pagamento, data,
# duracao, valor) e tentado antes, senao "era o pix" viraria um cliente chamado "pix".
_CLIENTE_IMPLICITO = re.compile(
    rf"^(?:o\s+nome\s+(?:dele\s+|dela\s+|do\s+cliente\s+)?)?{_VERBO}\s+"
    rf"(?:[oa]\s+)(?P<nome>[^\W\d_][^\n]*?)\s*$",
    re.IGNORECASE,
)
_CLIENTE_IMPLICITO_NOMEADO = re.compile(
    rf"^o\s+nome\s+(?:dele\s+|dela\s+|do\s+cliente\s+)?{_VERBO}\s+"
    rf"(?:[oa]\s+)?(?P<nome>[^\W\d_][^\n]*?)\s*$",
    re.IGNORECASE,
)

MAX_PALAVRAS_DO_NOME = 3
"""Teto do nome lido SEM a palavra "cliente". Nome de cliente e curto ("Caio Silva"); frase
comprida que comeca com "era o" e conversa ("era o combinado desde ontem"), e conversa que vira
nome reescreve o registro de alguem."""

# "foi dia 07", "dia 7/8", "dia 07/08/2026".
_DIA = re.compile(
    rf"^(?:{_VERBO}\s+)?(?:o\s+)?dia\s+(?P<d>\d{{1,2}})"
    r"(?:[/-](?P<m>\d{1,2}))?(?:[/-](?P<a>\d{2,4}))?$"
)
# "07/08", "7/8/2026" — a grafia curta que o grupo usa quando o anuncio atrasou um dia.
_DATA = re.compile(
    rf"^(?:{_VERBO}\s+)?(?P<d>\d{{1,2}})[/-](?P<m>\d{{1,2}})(?:[/-](?P<a>\d{{2,4}}))?$"
)
_RELATIVO = {"hoje": 0, "ontem": 1, "anteontem": 2}
_DIA_RELATIVO = re.compile(rf"^(?:{_VERBO}\s+)?(?P<quando>hoje|ontem|anteontem)$")

# "era 1h30", "foi 2h", "30min". Lida ANTES do valor de proposito: o parser de valor tira um
# numero de "30min" (30 minutos vira R$ 3,00 quando o "0min" some como duracao zero).
_DURACAO = re.compile(
    rf"^(?:{_VERBO}\s+)?(?:de\s+)?"
    r"(?:(?P<horas>\d{1,2})\s*h(?:oras?)?\s*(?:(?P<h_min>\d{1,2})\s*(?:min\w*)?)?"
    r"|(?P<minutos>\d{1,3})\s*min\w*)$"
)


@dataclass(frozen=True)
class Correcao:
    """O que a mensagem de correcao diz — antes de encostar em venda nenhuma.

    Campo nulo = a mensagem nao falou dele, e o que ela nao falou nao muda. Nao ha como APAGAR um
    campo por aqui de proposito: "sem cliente" nao e uma frase que o grupo diz, e um apagamento
    silencioso e o tipo de escrita que ninguem confere.
    """

    valor: Decimal | None = None
    data: date | None = None
    cliente: str | None = None
    duracao_minutos: int | None = None
    forma: FormaPagamento | None = None

    def campos(self) -> tuple[CampoCorrigivel, ...]:
        """Os campos que esta mensagem quer trocar (na ordem canonica do rotulo)."""
        ditos: list[CampoCorrigivel] = []
        if self.valor is not None:
            ditos.append("valor")
        if self.data is not None:
            ditos.append("data")
        if self.cliente is not None:
            ditos.append("cliente")
        if self.duracao_minutos is not None:
            ditos.append("duracao")
        if self.forma is not None:
            ditos.append("forma_pagamento")
        return tuple(ditos)


@dataclass(frozen=True)
class Mudanca:
    """Um campo que de fato mudou, ja em texto legivel — o eco no grupo e o rastro no banco.

    Texto (e nao valor tipado) porque os dois consumidores sao humanos lendo: a gestora de relance
    no grupo e quem for auditar a linha no painel. Um so lugar formata, entao a fala e o rastro
    nunca divergem.
    """

    campo: CampoCorrigivel
    de: str
    para: str


def ler_correcao(texto: str, *, referencia: date) -> Correcao | None:
    """A mensagem (respondendo um recibo) e uma correcao? `None` para tudo o mais.

    `referencia` e o dia BRT de quem esta corrigindo: e dele que "ontem" e "dia 07" tiram mes e
    ano. Correcao de data e sempre para tras na pratica (o anuncio de madrugada que o grupo conta
    como do dia anterior), mas nao ha trava para o futuro aqui — travar a data seria travar o
    registro, e o dominio proibe.
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if not linhas or len(linhas) > MAX_LINHAS:
        return None

    dito: dict[str, Any] = {}
    for linha in linhas:
        lido = _ler_linha(linha, referencia=referencia)
        if lido is None:
            return None
        if any(chave in dito for chave in lido):
            # Duas linhas mexendo no mesmo campo: nao ha "a ultima vale".
            return None
        dito.update(lido)
    return Correcao(**dito)


def aplicar_correcao(venda: VendaRegistrada, correcao: Correcao) -> VendaRegistrada:
    """A venda como ela fica depois da correcao. Puro: nao escreve, so devolve o estado novo."""
    return replace(
        venda,
        valor=correcao.valor if correcao.valor is not None else venda.valor,
        data=correcao.data or venda.data,
        cliente_nome=correcao.cliente or venda.cliente_nome,
        duracao_minutos=correcao.duracao_minutos or venda.duracao_minutos,
        forma_pagamento=correcao.forma or venda.forma_pagamento,
    )


def mudancas_entre(antes: VendaRegistrada, depois: VendaRegistrada) -> tuple[Mudanca, ...]:
    """O que REALMENTE mudou entre os dois estados — vazio quando a correcao repetiu o que ja era.

    Comparar os dois estados (em vez de confiar no que a mensagem disse) e o que mantem o eco e o
    rastro honestos: "foi 650" numa venda que ja esta em 650 nao gerou evento nenhum, e dizer
    "corrigi" ali seria mentir para quem confere de relance.
    """
    encontradas: list[Mudanca] = []
    if antes.valor != depois.valor:
        encontradas.append(
            Mudanca("valor", formatar_reais(antes.valor), formatar_reais(depois.valor))
        )
    if antes.data != depois.data:
        encontradas.append(Mudanca("data", f"{antes.data:%d/%m}", f"{depois.data:%d/%m}"))
    if antes.cliente_nome != depois.cliente_nome:
        encontradas.append(
            Mudanca("cliente", antes.cliente_nome or SEM_VALOR, depois.cliente_nome or SEM_VALOR)
        )
    if antes.duracao_minutos != depois.duracao_minutos:
        encontradas.append(
            Mudanca("duracao", _duracao(antes.duracao_minutos), _duracao(depois.duracao_minutos))
        )
    if antes.forma_pagamento != depois.forma_pagamento:
        encontradas.append(
            Mudanca(
                "forma_pagamento",
                antes.forma_pagamento or SEM_VALOR,
                depois.forma_pagamento or SEM_VALOR,
            )
        )
    return tuple(encontradas)


def montar_eco_de_correcao(mudancas: tuple[Mudanca, ...], *, linhas: int = 1) -> str:
    """ "✏️ Corrigi: valor R$ 700,00 → R$ 650,00 — corrige aí se algo estiver errado".

    O eco repete o de→para porque a correcao e o unico momento em que um dado JA CONFERIDO some.
    Sem o "de", quem le nao consegue distinguir "o agente corrigiu o que eu pedi" de "o agente
    entendeu outra coisa" — e a correcao mal entendida e pior que o erro original.

    `linhas` > 1 = o anuncio tinha duas modelos e a correcao valeu para as duas (a porta so chega
    aqui quando isso e seguro). Dizer quantas linhas mudaram evita a leitura de que so a primeira
    do recibo foi corrigida.
    """
    corpo = " · ".join(f"{ROTULO[m.campo]} {m.de} → {m.para}" for m in mudancas)
    cabeca = "✏️ Corrigi" if linhas < 2 else f"✏️ Corrigi ({linhas} linhas)"
    return f"{cabeca}: {corpo} — {CONVITE_DE_CORRECAO}"


# --- quote na Ficha de agendamento (ticket 09) ---------------------------------------------------
#
# O telefonista responde o card e escreve "mudou pra 800", "nao veio", "confirmado". E o MESMO
# gesto que corrige o recibo — o quote e o unico sinal que diz de qual atendimento se fala sem
# adivinhar — mas o alvo e o COMBINADO, e nao dinheiro ja recebido, e por isso ele diz duas coisas
# que o recibo nunca diz: que o atendimento **furou** e que ele esta **confirmado**.
#
# `confirmado` importa mais do que parece. Depois do ADR-0046 §5 o ✅ do telefonista passou a
# PROMOVER a venda, e com isso nenhum gesto produz mais o estado `confirmada` da ficha: esta e a
# unica porta que o produz. Se ela nao existir, o estado nasce orfao e a maquina do ADR-0044 §1
# vira `aberta -> realizada | cancelada` sem ninguem ter decidido isso.
#
# A leitura mora AQUI, e nao em `ficha.py`, por uma razao de dependencia e uma de dominio: este
# modulo ja e o leitor de quote do modulo (e ja importa `pagamento`, que importa `ficha`), e as
# duas gramaticas tem que envelhecer juntas — "foi 650" corrige uma venda e altera uma ficha com a
# mesma frase, e duas leituras diferentes para a mesma frase seriam duas condutas divergentes.

MAX_PALAVRAS_DO_GESTO = 6
"""Teto de palavras para "nao veio" / "confirmado" valerem como gesto sobre a ficha.

Vocabulario fechado num texto CURTO: "confirmado" numa frase de vinte palavras e conversa
("depois que o cliente tiver confirmado a gente ve"), e mover o estado de um combinado por causa
de uma palavra no meio de um paragrafo e o palpite que o modulo se proibe."""

MAX_DURACAO_PLAUSIVEL = 720
"""12 h — o pernoite, a maior duracao que a casa vende.

Existe por causa de uma ambiguidade que so a ficha tem: ela guarda HORA e DURACAO, e "22h" e as
duas coisas. No recibo de venda nao ha hora, entao "era 2h" so pode ser duracao; aqui, "mudou pra
22h" quase sempre e o horario novo. Acima deste teto a leitura nao escolhe — vira pergunta."""

# O que o gesto de cancelamento diz na grafia do grupo. Allowlist fechada: e o mesmo efeito do ❌
# (ticket 08), e um verbo generico aqui apagaria um combinado por causa de conversa.
_NAO_VEIO = re.compile(
    r"\b(?:nao\s+(?:veio|vem\s+mais|vai\s+mais|vai\s+dar|rolou|rola|foi|aconteceu|deu\s+certo)"
    r"|furou|furo|cancel(?:a|ou|ado|ada|amos)|desmarc(?:ou|ado|ada|amos))\b"
)

_CONFIRMADO = re.compile(r"\bconfirmad[oa]\b|\bconfirm(?:ou|ei|amos)\b")

# "nao confirmou", "ainda nao confirmado": a mesma palavra com o sinal trocado. Sem esta tranca o
# gesto que diz o CONTRARIO moveria a ficha para `confirmada`.
_NEGACAO = re.compile(r"\b(?:nao|nem|ainda\s+nao)\b")

# Como quem ALTERA abre a frase, quando a frase nao diz o campo. Nao vira alteracao: vira a
# pergunta que devolve o campo ("valor 800"). Silencio aqui seria pior — o telefonista escreveu,
# viu o agente calado e vai embora achando que mudou.
_MUDANCA = re.compile(
    r"^(?:mud(?:ou|ei|o)|troc(?:ou|ei)|alter(?:ou|ei)|remarc(?:ou|amos|ei)|adi(?:ou|amos|ei)"
    r"|passou)\b"
)

# O prefixo que ABRE a alteracao e nao dita campo nenhum ("mudou pra 800", "ficou em 650"). Como o
# "na verdade" da correcao do recibo, ele e ruido a remover — a linha continua tendo que render um
# campo depois disto, que e o que impede "mudou pra sexta" de virar valor.
#
# O substantivo do campo entra na decapitacao SO para os campos que nao tem leitura propria de
# grafia ("mudou o valor pra 800" -> "800"). `hora` e `horario` ficam de fora de proposito: eles
# sao a UNICA marca que separa "22h" horario de "22h" duracao, e apaga-los aqui devolveria a
# ambiguidade que `_HORA_DITA` existe para resolver.
_MUDOU_PARA = re.compile(
    r"^(?:mud(?:ou|ei|o)|troc(?:ou|ei)|alter(?:ou|ei)|passou|ficou|vai\s+ser)\s+"
    r"(?:[oa]\s+(?:valor|preco|duracao|cliente)\s+)?"
    r"(?:pra|para|em|de)\s+",
    re.IGNORECASE,
)

# "horario 22h", "mudou o horario pra 22:30", "as 22h" — o horario DITO como horario.
_HORA_DITA = re.compile(
    r"^(?:(?:mud(?:ou|ei|o)|troc(?:ou|ei)|passou|ficou|vai\s+ser)\s+)?"
    r"(?:[oa]\s+)?(?:horario|hora)\s+(?:pra|para|e|eh|de|:)?\s*"
    r"(?P<h>\d{1,2})(?:[:h](?P<m>\d{2}))?\s*h?$"
)
_AS_HORAS = re.compile(
    r"^(?:(?:mud(?:ou|ei|o)|troc(?:ou|ei)|passou|ficou|vai\s+ser)\s+)?(?:pra|para)?\s*"
    r"as\s+(?P<h>\d{1,2})(?:[:h](?P<m>\d{2}))?\s*h?$"
)

GestoNoQuoteDaFicha = Literal["altera", "cancela", "confirma", "ambiguo"]
"""O que a resposta ao card QUER dizer. `ambiguo` e um veredito de primeira classe, e nao um erro
de leitura: ele existe para o gesto mal escrito virar UMA pergunta em vez de virar silencio."""


@dataclass(frozen=True)
class QuoteNaFicha:
    """A resposta ao card, ja lida — antes de encostar em ficha nenhuma.

    `alteracao` e o que muda no COMBINADO; `correcao` e a mesma frase na forma que a Venda
    registrada entende. Vem os dois porque o alvo depende de um fato que a leitura nao conhece: se
    a ficha ja virou venda, "mudou pra 800" e correcao de venda, e nao alteracao de combinado
    (senao o dinheiro registrado continuaria valendo o numero velho).
    """

    gesto: GestoNoQuoteDaFicha
    alteracao: AlteracaoDaFicha | None = None
    correcao: Correcao | None = None


def ler_quote_na_ficha(texto: str, *, referencia: date) -> QuoteNaFicha | None:
    """A mensagem (respondendo um card) e um gesto sobre a ficha? `None` para tudo o mais.

    `None` e o caso comum e e silencio de proposito: o grupo responde o card com "ok", "vou lá",
    "obrigada" o tempo todo, e nada disso muda combinado nenhum.

    A ordem das tentativas e a unica coisa nao obvia: cancelamento e confirmacao vem antes de
    qualquer leitura de campo porque sao vocabulario fechado e nao tem numero dentro; a hora vem
    antes da correcao porque "22h" e duracao para o leitor do recibo; e a duracao implausivel
    (acima do pernoite) vira pergunta em vez de virar um atendimento de 22 horas.
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if not linhas or len(linhas) > MAX_LINHAS:
        return None
    inteiro = normalizar(" ".join(linhas))

    if _e_gesto_curto(inteiro) and _NAO_VEIO.search(inteiro):
        return QuoteNaFicha("cancela")
    if _e_gesto_curto(inteiro) and _CONFIRMADO.search(inteiro) and not _NEGACAO.search(inteiro):
        return QuoteNaFicha("confirma")

    hora = _hora_dita(inteiro)
    if hora is not None:
        return QuoteNaFicha("altera", alteracao=AlteracaoDaFicha(hora=hora))

    correcao = ler_correcao(texto, referencia=referencia)
    if correcao is not None:
        if (
            correcao.campos() == ("duracao",)
            and correcao.duracao_minutos is not None
            and correcao.duracao_minutos > MAX_DURACAO_PLAUSIVEL
        ):
            return QuoteNaFicha("ambiguo")
        return QuoteNaFicha(
            "altera",
            alteracao=AlteracaoDaFicha(
                valor=correcao.valor,
                data=correcao.data,
                duracao_minutos=correcao.duracao_minutos,
                cliente=correcao.cliente,
                forma_pagamento=correcao.forma,
            ),
            correcao=correcao,
        )

    if _MUDANCA.match(inteiro):
        return QuoteNaFicha("ambiguo")
    return None


EfeitoDoQuote = Literal[
    "alterar_ficha",
    "corrigir_venda",
    "cancelar",
    "confirmar",
    "perguntar",
    "ignorar",
]
"""O que quem chama tem que FAZER. Um efeito = uma acao, sem sobreposicao — o mesmo contrato de
`gesto.decidir_gesto`, para as duas superficies do mesmo combinado (o emoji e o texto) nao
divergirem em conduta."""

MotivoDoQuote = Literal[
    "ficha_alterada",
    "ficha_sem_alteracao",
    "valor_de_varias",
    "alteracao_vira_correcao",
    "cancelamento_do_telefonista",
    "cancelamento_com_venda",
    "ficha_confirmada",
    "confirmacao_sobre_cancelada",
    "quote_ambiguo",
    "quote_sobre_ficha_cancelada",
    "quote_sem_efeito",
]


@dataclass(frozen=True)
class DecisaoDoQuote:
    """O que fazer com a ficha. `estado_resultante is None` = nao mexe no estado."""

    efeito: EfeitoDoQuote
    motivo: MotivoDoQuote
    alteracao: AlteracaoDaFicha | None = None
    correcao: Correcao | None = None
    mudancas: tuple[MudancaNaFicha, ...] = ()
    estado_resultante: EstadoDaFicha | None = None
    eventos: tuple[EventoDaFicha, ...] = ()
    """O rastro APPEND-ONLY a gravar — UMA linha por campo alterado, que e o que o CHECK
    `ficha_de_agendamento_eventos_alteracao_tem_campo` exige."""
    pergunta: str | None = None
    """UMA pergunta, so onde o silencio erraria com dinheiro ou com o combinado. Nos outros casos
    e `None`: o gesto sobre a ficha e calado, como a gravacao dela."""


def decidir_quote_na_ficha(
    quote: QuoteNaFicha, *, ficha: FichaDeAgendamento, venda_viva: bool = False
) -> DecisaoDoQuote:
    """A decisao inteira do quote sobre a ficha, em uma funcao pura.

    `venda_viva` e o fato que vira o alvo do avesso (ADR-0044 §2): depois que a ficha virou Venda
    registrada, o combinado ja nao e o que vale — o dinheiro e. Alterar a ficha ali deixaria a
    venda com o numero velho e o painel com dois numeros diferentes para o mesmo atendimento, cada
    um verdadeiro na sua tabela.
    """
    if quote.gesto == "ambiguo":
        return DecisaoDoQuote(
            "perguntar", "quote_ambiguo", pergunta=_pergunta_do_quote_ambiguo(ficha)
        )
    if quote.gesto == "cancela":
        return _decidir_cancelamento_por_texto(ficha, venda_viva=venda_viva)
    if quote.gesto == "confirma":
        return _decidir_confirmacao(ficha, venda_viva=venda_viva)
    return _decidir_alteracao(quote, ficha=ficha, venda_viva=venda_viva)


AVISO_DE_ALTERACAO_AMBIGUA = (
    "❓ Essa ficha tem mais de uma modelo em valores diferentes — não sei de qual é a alteração. "
    "Ajusta no painel, aí não tem risco de eu trocar."
)
"""Alteracao de VALOR numa festinha de rateio desigual. Adivinhar move dinheiro de uma mulher para
a outra; perguntar "de quem?" abriria um vai-e-vem que a porta ainda nao sabe terminar. Mesma
saida do recibo de duas modelos (`AVISO_DE_CORRECAO_AMBIGUA`)."""


def eventos_da_alteracao(mudancas: Sequence[MudancaNaFicha]) -> tuple[EventoDaFicha, ...]:
    """UMA linha de auditoria por campo — o formato que a tabela exige e que o painel le.

    Publico porque o REPOST grava o mesmo rastro sem passar por decisao nenhuma: o card
    substituido e o quote "mudou pra 800" sao o mesmo fato contado de dois jeitos, e uma auditoria
    que os distinguisse pelo formato mentiria sobre o que aconteceu.
    """
    return tuple(
        EventoDaFicha("alteracao", campo=m.campo, valor_anterior=m.de, valor_novo=m.para)
        for m in mudancas
    )


# --- interno ------------------------------------------------------------------------------------


def _ler_linha(linha: str, *, referencia: date) -> dict[str, Any] | None:
    """Uma linha -> os campos que ela dita. `None` quando a linha nao e correcao de nada.

    A ordem das tentativas e a unica coisa nao obvia aqui: `cliente` primeiro porque o nome dele
    pode ser qualquer coisa (inclusive um numero), e `duracao` antes de `valor` porque "30min"
    rende um valor de R$ 3,00 no parser de dinheiro. O cliente SEM a palavra-chave ("era o Caio")
    fecha a fila pelo motivo inverso: ele aceitaria demais se viesse antes.
    """
    linha = _sem_retificacao(linha)
    if not linha:
        return None

    cliente = _CLIENTE.match(linha)
    if cliente is not None:
        return {"cliente": cliente.group("nome")}

    fala = ler_fala_de_pagamento(linha)
    if fala is not None and fala.tipo == "resposta" and fala.forma is not None:
        return {"forma": fala.forma}

    n = normalizar(linha)

    quando = _data_da_linha(n, referencia=referencia)
    if quando is not None:
        return {"data": quando}

    duracao = _DURACAO.match(n)
    if duracao is not None:
        minutos = _minutos_da_duracao(duracao)
        return {"duracao_minutos": minutos} if minutos else None

    achado = ler_valor_avulso(linha)
    if achado is not None:
        valor, minutos_do_valor = achado
        if minutos_do_valor is None:
            return {"valor": valor}
        return {"valor": valor, "duracao_minutos": minutos_do_valor}

    nome = _cliente_sem_a_palavra(linha)
    return None if nome is None else {"cliente": nome}


def _sem_retificacao(linha: str) -> str:
    """Tira o "na verdade"/"corrigindo" que abre (ou fecha) a frase, e devolve o resto.

    Decapitar em vez de tratar como campo mantem a regra 2 intacta: a linha continua tendo que
    render um campo depois disto. O que muda e que "na verdade foi 800" passou a ser a mesma coisa
    que "foi 800" — que e o que ela e para quem leu no grupo.

    O verbo de MUDANCA ("mudou pra 800", "ficou em 650") entrou pela mesma porta no ticket 09: a
    ficha do telefonista muda depois de combinada, e a frase com que ele a muda e essa. Ele
    tambem nao dita campo — quem dita e o que sobra —, entao decapita-lo nao afrouxa nada: "mudou
    pra sexta" continua morrendo por nao render campo nenhum.
    """
    sem_abertura = _MUDOU_PARA.sub("", _RETIFICACAO.sub("", linha.strip()))
    return _RETIFICACAO_NO_FIM.sub("", sem_abertura).strip()


def _cliente_sem_a_palavra(linha: str) -> str | None:
    """ "era o Caio Silva" / "o nome dele é Ramon" -> o nome. `None` quando nao e nome nenhum.

    Ultimo recurso da linha, e de proposito: aqui nao ha palavra-chave garantindo do que se fala —
    so o artigo (ou "nome") e o teto de palavras. Tudo que tem leitura propria ja passou, entao o
    que chega aqui e texto que nao era forma de pagamento, nem data, nem duracao, nem dinheiro.
    """
    achado = _CLIENTE_IMPLICITO_NOMEADO.match(linha) or _CLIENTE_IMPLICITO.match(linha)
    if achado is None:
        return None
    nome = achado.group("nome").strip(" .!,;")
    if not nome or len(nome.split()) > MAX_PALAVRAS_DO_NOME:
        return None
    # Maiuscula inicial: sem a palavra "cliente" nao ha nada dizendo que se fala de gente, e
    # "era o combinado" tem exatamente a forma de "era o Caio". Quem escreve o nome em minusculas
    # continua tendo a porta de sempre ("o cliente era ramon"), que nao depende de palpite.
    return nome if nome[0].isupper() else None


def _data_da_linha(normalizada: str, *, referencia: date) -> date | None:
    relativo = _DIA_RELATIVO.match(normalizada)
    if relativo is not None:
        return date.fromordinal(referencia.toordinal() - _RELATIVO[relativo.group("quando")])
    m = _DIA.match(normalizada) or _DATA.match(normalizada)
    if m is None:
        return None
    ano = m.group("a")
    try:
        return date(
            _ano(ano, referencia) if ano else referencia.year,
            int(m.group("m")) if m.group("m") else referencia.month,
            int(m.group("d")),
        )
    except ValueError:
        # "dia 32", "45/13": o grupo digitou errado. Nao e correcao de nada.
        return None


def _ano(dito: str, referencia: date) -> int:
    numero = int(dito)
    return numero if numero > 99 else (referencia.year // 100) * 100 + numero


def _minutos_da_duracao(m: re.Match[str]) -> int:
    if m.group("horas"):
        return int(m.group("horas")) * 60 + int(m.group("h_min") or 0)
    return int(m.group("minutos") or 0)


def _duracao(minutos: int | None) -> str:
    return formatar_duracao(minutos) if minutos else SEM_VALOR


def _decidir_alteracao(
    quote: QuoteNaFicha, *, ficha: FichaDeAgendamento, venda_viva: bool
) -> DecisaoDoQuote:
    alteracao = quote.alteracao
    if alteracao is None or alteracao.vazia:  # pragma: no cover - leitura sem campo nao chega aqui
        return DecisaoDoQuote("ignorar", "quote_sem_efeito")

    if venda_viva:
        # O fato ja e dinheiro. A mesma frase vira correcao da VENDA — a porta que ja existe, com
        # o mesmo de->para e o mesmo evento de auditoria —, e nunca uma venda nova: o atendimento
        # e um so, e foi so o numero dele que mudou.
        if quote.correcao is None:
            # Sobra o que so a ficha tem (o horario). Depois do pagamento ele nao move dinheiro
            # nenhum e nao vale reabrir um combinado fechado por causa dele.
            return DecisaoDoQuote("ignorar", "quote_sem_efeito")
        return DecisaoDoQuote("corrigir_venda", "alteracao_vira_correcao", correcao=quote.correcao)

    if ficha.estado == "cancelada":
        # Alterar um combinado que morreu. Calar faria o telefonista ir embora achando que mudou;
        # ressuscitar em silencio desfaria um "nao veio" deliberado.
        return DecisaoDoQuote(
            "perguntar",
            "quote_sobre_ficha_cancelada",
            pergunta=_pergunta_da_alteracao_sobre_cancelada(ficha),
        )

    if alteracao.mexe_no_valor and not valor_alteravel(ficha):
        return DecisaoDoQuote("perguntar", "valor_de_varias", pergunta=AVISO_DE_ALTERACAO_AMBIGUA)

    completa = _com_o_total(alteracao, ficha=ficha)
    mudancas = mudancas_na_ficha(ficha, alterar_ficha(ficha, completa))
    if not mudancas:
        # "mudou pra 800" numa ficha que ja esta em 800 (o repost do mesmo card, o telefonista
        # repetindo). Calado de proposito: nao houve evento, e dizer "alterei" seria mentir.
        return DecisaoDoQuote("ignorar", "ficha_sem_alteracao")
    return DecisaoDoQuote(
        "alterar_ficha",
        "ficha_alterada",
        alteracao=completa,
        mudancas=mudancas,
        eventos=eventos_da_alteracao(mudancas),
    )


def _decidir_cancelamento_por_texto(
    ficha: FichaDeAgendamento, *, venda_viva: bool
) -> DecisaoDoQuote:
    """ "nao veio" — o mesmo efeito do ❌ (ticket 08), dito em texto.

    As duas superficies compartilham a regra porque compartilham a consequencia: cancelar para a
    cobranca da manha, e cancelar em cima de dinheiro registrado apagaria receita em silencio.
    """
    if ficha.estado == "cancelada":
        return DecisaoDoQuote("ignorar", "quote_sem_efeito")
    if venda_viva:
        return DecisaoDoQuote(
            "perguntar",
            "cancelamento_com_venda",
            pergunta=_pergunta_do_cancelamento_com_venda(ficha),
        )
    return DecisaoDoQuote(
        "cancelar",
        "cancelamento_do_telefonista",
        estado_resultante="cancelada",
        eventos=(
            EventoDaFicha("cancelamento", valor_anterior=ficha.estado, valor_novo="cancelada"),
        ),
    )


def _decidir_confirmacao(ficha: FichaDeAgendamento, *, venda_viva: bool) -> DecisaoDoQuote:
    """ "confirmado" — a UNICA porta que ainda produz o estado `confirmada` (ADR-0046 §5).

    Ela **nao cria venda**, e essa e a diferenca que o ADR-0046 desenhou: o ✅ do telefonista vem
    DEPOIS do pagamento e promove; a palavra "confirmado" vem antes do atendimento e so diz que o
    combinado esta de pe. Confundir os dois registraria receita de um atendimento que ainda nao
    aconteceu.
    """
    if venda_viva or ficha.estado == "realizada":
        # Confirmar o que ja virou dinheiro nao diz nada de novo.
        return DecisaoDoQuote("ignorar", "quote_sem_efeito")
    if ficha.estado == "cancelada":
        return DecisaoDoQuote(
            "perguntar",
            "confirmacao_sobre_cancelada",
            pergunta=_pergunta_da_confirmacao_sobre_cancelada(ficha),
        )
    if ficha.estado == "confirmada":
        return DecisaoDoQuote("ignorar", "quote_sem_efeito")
    return DecisaoDoQuote(
        "confirmar",
        "ficha_confirmada",
        estado_resultante="confirmada",
        eventos=(
            EventoDaFicha("confirmacao", valor_anterior=ficha.estado, valor_novo="confirmada"),
        ),
    )


def _com_o_total(alteracao: AlteracaoDaFicha, *, ficha: FichaDeAgendamento) -> AlteracaoDaFicha:
    """ "mudou pra 800" numa ficha de UMA modelo troca os dois numeros, nao um.

    `valor_total` e `Valor desta modelo` sao o mesmo dinheiro quando ela esta sozinha, e deixar um
    deles para tras faria o painel mostrar R$ 700 de atendimento com R$ 800 para a modelo. Na
    festinha nao ha o que deduzir: quem diz o total e o card, e a alteracao por texto mexe so no
    valor de cada uma.
    """
    if alteracao.valor is None or len(ficha.participantes) > 1:
        return alteracao
    return replace(alteracao, valor_total=alteracao.valor)


def _e_gesto_curto(normalizada: str) -> bool:
    return 0 < len(normalizada.split()) <= MAX_PALAVRAS_DO_GESTO


def _hora_dita(normalizada: str) -> time | None:
    achado = _HORA_DITA.match(normalizada) or _AS_HORAS.match(normalizada)
    if achado is None:
        return None
    hora = int(achado.group("h"))
    minuto = int(achado.group("m") or 0)
    if hora > 23 or minuto > 59:
        return None
    return time(hour=hora, minute=minuto)


def _pergunta_do_quote_ambiguo(ficha: FichaDeAgendamento) -> str:
    return (
        f"{PREFIXO_DA_PERGUNTA}o que mudou em {nome_do_atendimento(ficha)}? "
        'Diz o campo e o valor novo ("valor 800", "horário 22h").'
    )


def _pergunta_do_cancelamento_com_venda(ficha: FichaDeAgendamento) -> str:
    return f"❓ {nome_do_atendimento(ficha)} já está registrado como recebido. Anulo a venda?"


def _pergunta_da_confirmacao_sobre_cancelada(ficha: FichaDeAgendamento) -> str:
    return f"❓ {nome_do_atendimento(ficha)} está como cancelado. Confirmo assim mesmo?"


def _pergunta_da_alteracao_sobre_cancelada(ficha: FichaDeAgendamento) -> str:
    return f"❓ {nome_do_atendimento(ficha)} está como cancelado. Reabro com a alteração?"
