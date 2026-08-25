"""O Fechamento: a conferencia vendido x comprovado por modelo (spec 0005, ticket 09).

E a conta que a Parcerias faz de cabeca no grupo ("confere: 600 pix, 600 pix / ficou com voce"),
agora deterministica. Quatro decisoes moram aqui:

* **Nao existe tabela de fechamento.** O extrato e DERIVADO das Vendas registradas e dos
  Comprovantes de transferencia, na hora em que alguem pede. Materializa-lo seria criar periodos
  estanques por outro nome — e periodo que "fecha" e exatamente o que o dominio proibe: o
  comprovante que chega tres dias depois entra no saldo corrente contínuo sem nada precisar ser
  reaberto. Sem estado proprio tambem nao ha o que reconciliar quando uma venda e corrigida
  (ticket 05) ou anulada; o proximo pedido ja le o mundo novo.
* **As tres colunas SOMAM o vendido, e a quarta e a diferenca.** `vendido = comprovado +
  em_especie + a_comprovar + sem_forma` e uma identidade, nao um relatorio: e ela que garante
  que nenhum dinheiro anunciado no grupo sumiu entre as colunas. `a_comprovar` e a **diferenca**
  que o gestor quer saber, e `sem_forma` e o dinheiro que ainda nao escolheu coluna (a Pendencia
  mais comum do grupo — o anuncio sempre precede o pagamento).
* **Divergencia e pergunta, nunca erro.** Comprovante que nao fechou venda nenhuma, sobra de um
  comprovante maior que a fila e Pix que nenhuma venda em pix explica nao interrompem o extrato:
  viram uma linha de pergunta no fim dele, com o valor a vista. Travar aqui transformaria o sinal
  em paralisia — e o dinheiro divergente e, justamente, dinheiro que ja saiu. Cada dinheiro rende
  UMA pergunta: duas linhas sobre os mesmos R$ 400,00 nao dobram o sinal, so ensinam a pular o fim
  da mensagem.
* **A Cobranca da agencia e um EIXO A PARTE, nao uma quinta coluna.** Ela nao entra na identidade
  acima nem e abatida do vendido: e debito da modelo para com a agencia (ticket 08), e o Pix que
  a quita nao e fechamento de venda nenhuma. Aparece no extrato como linha de debito e some de la
  quando o comprovante chega.

O **comprovado** conta o valor das VENDAS que tem comprovante, e nao a soma dos comprovantes.
Sao coisas diferentes quando o comprovante nao casa com nada ou sobra troco, e e a diferenca entre
as duas que vira a divergencia — somar comprovante como "comprovado" faria a coluna dizer que uma
venda foi paga por um Pix que nao era dela.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.cobranca import CobrancaDaAgencia
from barra.dominio.grupo_financeiro.comprovante import ComprovanteDoGrupo
from barra.dominio.grupo_financeiro.modelos import VendaRegistrada
from barra.dominio.grupo_financeiro.pendencia import (
    EM_ESPECIE_COM_A_MODELO,
    Pendencia,
    em_especie,
    espera_comprovante,
    pendencias_da_venda,
)
from barra.dominio.grupo_financeiro.razao import Razao
from barra.dominio.grupo_financeiro.recibo import formatar_reais

ZERO = Decimal("0.00")


# --- o pedido: "fechamento", "confere aí" -------------------------------------------------------

_TOKEN = re.compile(r"[0-9a-z]+")

_GATILHOS = frozenset(
    {
        "fechamento",
        "fechamentos",
        "fecha",
        "fechar",
        "extrato",
        "confere",
        "conferir",
        "conferencia",
    }
)
"""As palavras que, sozinhas, ja sao o pedido. Fora delas nao ha fechamento — o gestor que quiser
o extrato escreve uma destas, e um agente que adivinha pedido responde a conversa alheia."""

_ACOMPANHANTES = frozenset(
    {
        "a",
        "ai",
        "agora",
        "amiga",
        "amor",
        "bb",
        "bora",
        "como",
        "conta",
        "da",
        "de",
        "do",
        "e",
        "esta",
        "faz",
        "favor",
        "financeiro",
        "hoje",
        "manda",
        "me",
        "meu",
        "mim",
        "nosso",
        "o",
        "pf",
        "pfv",
        "por",
        "pra",
        "que",
        "quanto",
        "saldo",
        "so",
        "ta",
        "tudo",
        "vamos",
        "ver",
    }
)
"""O que pode acompanhar o gatilho sem mudar o pedido ("faz o fechamento aí pra mim", "como tá o
extrato?"). Allowlist FECHADA, como a da forma de pagamento: palavra que este modulo nao conhece
significa que a frase e sobre outra coisa, e o silencio erra menos que o extrato no meio de uma
conversa. Quem quer o fechamento sempre pode dizer so "fechamento"."""

MAX_PALAVRAS_DO_PEDIDO = 6
"""Pedido e telegrafico. Paragrafo com a palavra "fechamento" dentro e conversa sobre fechamento,
nao pedido de fechamento."""


def e_pedido_de_fechamento(texto: str) -> bool:
    """O grupo esta pedindo o extrato agora?

    Numero na mensagem DESQUALIFICA o pedido, e essa e a regra que separa este comando da conta
    que a gestora faz na mao: "confere: 600 pix, 600 pix" e ela conferindo (e pode ser correcao,
    valor de anuncio, resposta de pergunta minima), nao um pedido ao agente. O extrato so sai
    quando ninguem esta falando de um valor especifico.
    """
    normalizado = normalizar(texto)
    palavras = _TOKEN.findall(normalizado)
    if not palavras or len(palavras) > MAX_PALAVRAS_DO_PEDIDO:
        return False
    if any(p.isdigit() or any(c.isdigit() for c in p) for p in palavras):
        return False
    if not any(p in _GATILHOS for p in palavras):
        return False
    return all(p in _GATILHOS or p in _ACOMPANHANTES for p in palavras)


# --- o extrato ----------------------------------------------------------------------------------

TipoDeDivergencia = Literal[
    "comprovante_sem_par",
    "credito_da_modelo",
    "pix_sem_venda_em_pix",
    "venda_comprovada_a_menor",
]
"""O que nao bate. Nenhum deles impede o extrato de sair: os quatro viram pergunta no grupo e ficam
visiveis no painel (ticket 11) pela mesma leitura que os produziu aqui.

Os dois ultimos nascem DEPOIS da conciliacao, e por isso foram os ultimos a aparecer (14/08): a
venda ja estava fechada quando alguem mexeu nela. `venda_comprovada_a_menor` e a venda que subiu de
valor depois do Pix (corrigir 600 para 800 depois do Pix de 600 deixava o extrato dizendo "tudo
conciliado" com R$ 200,00 que nunca entraram). `pix_sem_venda_em_pix` e o contrario — o Pix que
perdeu o par, porque a venda que ele fechou virou dinheiro, encolheu ou foi anulada.

`pix_sem_venda_em_pix` se chamava `comprovado_acima_do_vendido` e comparava o transferido com o
**vendido total**. Era o eixo errado duas vezes: deixava passar o Pix cuja venda virou especie (o
vendido nao muda, e o mesmo dinheiro ficava contado na casa E na mao da modelo) e perguntava duas
vezes pela sobra de um comprovante maior, que ja tem a linha de `credito_da_modelo`."""


@dataclass(frozen=True)
class Divergencia:
    """Dinheiro que nao encontrou par. Sempre com o VALOR a vista — divergencia sem numero nao
    deixa ninguem fazer nada."""

    tipo: TipoDeDivergencia
    valor: Decimal
    data: date | None = None
    comprovante_id: UUID | None = None


@dataclass(frozen=True)
class Extrato:
    """O retrato do aberto de UMA modelo, no instante em que foi pedido.

    `vendido = comprovado + em_especie + a_comprovar + sem_forma` — a identidade que prova que
    toda venda anunciada esta em exatamente uma coluna.
    """

    modelo_id: UUID
    vendido: Decimal = ZERO
    comprovado: Decimal = ZERO
    """Vendas em pix que ja tem Comprovante de transferencia — dinheiro provado."""
    em_especie: Decimal = ZERO
    """Vendas em dinheiro: contam no vendido e ficam FORA da expectativa de comprovante."""
    a_comprovar: Decimal = ZERO
    """A **diferenca**: vendas em pix ainda sem comprovante."""
    sem_forma: Decimal = ZERO
    """Vendas cuja forma de pagamento ninguem disse ainda — nao sao nem comprovaveis nem especie."""
    vendas: int = 0
    pendencias: tuple[Pendencia, ...] = field(default_factory=tuple)
    divergencias: tuple[Divergencia, ...] = field(default_factory=tuple)
    cobrancas: tuple[CobrancaDaAgencia, ...] = field(default_factory=tuple)
    """As Cobrancas da agencia ABERTAS da modelo (ticket 08) — a coluna de **debito**.

    Elas ficam fora da identidade das quatro colunas de proposito: cobranca nao e venda, e um
    debito DELA para com a agencia. Somar (ou subtrair) esse dinheiro do vendido faria o extrato
    misturar dois eixos que nunca se cruzam — e a conta que o gestor confere de cabeca e sobre
    receita, nao sobre o que a modelo paga pelo anuncio.

    E a **Pendencia de cobranca nao paga** do dominio, sem objeto derivado: a `Pendencia` existe
    porque falta de forma/comprovante nao tem linha propria em lugar nenhum (ela e coluna nula da
    venda). A cobranca aberta JA e uma linha, com id, valor e descricao — derivar dela um segundo
    objeto so criaria o risco de os dois discordarem.
    """
    razao: Razao | None = None
    """O saldo com SINAL da modelo (ADR-0045 §1, ticket 02) — o numero que o gestor realmente quer.

    Campo NOVO ao lado das colunas antigas, e nao no lugar delas: as tres colunas e as
    divergencias continuam valendo como recorte (ADR-0045 §2 — "em especie" sobrevive como
    recorte visual, o que nao tem comprovante a cobrar), e o saldo e o numero final.

    `None` significa **nao apurado**, e nunca zero. Quem monta o extrato sem os lancamentos do
    razao (o caminho antigo, que nao le `bolso` nem `percentual_repasse_snapshot`) recebe `None`
    e o extrato simplesmente nao fala de saldo. Um `Razao()` vazio como default diria "saldo
    R$ 0,00" — a casa e a modelo quites — para toda modelo cujo razao ninguem leu, que e a
    mentira mais cara que este modulo poderia contar.
    """

    @property
    def saldo(self) -> Decimal | None:
        """`creditos - debitos` do razao. Positivo = a casa deve a ela; negativo = ela deve.

        `None` quando o razao nao foi apurado — a ausencia do numero, nunca um zero inventado.
        """
        return None if self.razao is None else self.razao.saldo

    @property
    def debito(self) -> Decimal:
        """Quanto a modelo ainda deve a agencia. Derivado das cobrancas, nunca guardado a parte."""
        return _soma(c.valor for c in self.cobrancas)

    @property
    def conciliado(self) -> bool:
        """Nada aberto e nada divergente: o extrato nao precisa ser mostrado.

        Cobranca aberta conta como "aberto": a modelo deve dinheiro e ninguem viu o comprovante —
        responder "tudo conciliado" ali seria o agente dando quitacao que ele nao tem.

        **Saldo diferente de zero tambem conta como aberto** (ADR-0045). Sem isso, a temporada
        inteira feita em dinheiro — nenhuma pendencia, nenhuma divergencia, nenhuma cobranca —
        seria respondida com "tudo conciliado" enquanto a modelo esta com R$ 600,00 da casa na
        mao. Extrato com `razao is None` (nao apurado) mantem o comportamento antigo: quem nao
        leu o razao nao afirma nada sobre ele.
        """
        aberto = self.pendencias or self.divergencias or self.cobrancas
        return not aberto and (self.razao is None or self.razao.saldo == ZERO)


def montar_extrato(
    *,
    modelo_id: UUID,
    vendas: Sequence[VendaRegistrada],
    comprovantes: Sequence[ComprovanteDoGrupo],
    cobrancas: Sequence[CobrancaDaAgencia] = (),
    razao: Razao | None = None,
) -> Extrato:
    """As tres colunas, a diferenca, o debito e o que nao bate — puro, sobre o lido do banco.

    `vendas` sao as VIVAS da modelo (o repo nunca devolve anulada) e `comprovantes` os dela, de
    todo o sempre: **saldo corrente continuo**, sem recorte de periodo. Um comprovante de dias
    atras aparece aqui do mesmo jeito que o de hoje, e uma venda de semanas atras continua na
    coluna "falta comprovar" ate alguem comprova-la.

    `cobrancas` sao as Cobrancas da agencia ABERTAS (ticket 08) — a coluna de debito. Default
    vazio porque ela e um eixo a parte: nenhuma conta das quatro colunas muda por causa dela, e
    quem so quer conferir vendido x comprovado nao precisa passar a lista.

    `razao` chega PRONTO (ADR-0045, ticket 02), e nao e apurado aqui: o razao le colunas que a
    `VendaRegistrada` nao carrega (`bolso`, `percentual_repasse_snapshot`, quem recebeu) e soma
    lancamentos que nem sao venda (vale, deslocamento). Apura-lo daqui obrigaria esta funcao a
    receber uma SEGUNDA lista de vendas, com os mesmos fatos em outro formato — e duas listas de
    venda no mesmo extrato e a receita para as colunas e o saldo discordarem. Quem le do banco
    apura (`temporada.apurar_o_razao`) e passa. Default `None` = **nao apurado**, nunca zero.
    """
    comprovado = _soma(v.valor for v in vendas if _comprovada(v))
    a_comprovar = _soma(
        v.valor for v in vendas if espera_comprovante(v.forma_pagamento) and not _comprovada(v)
    )
    especie = _soma(v.valor for v in vendas if em_especie(v.forma_pagamento))
    sem_forma = _soma(v.valor for v in vendas if v.forma_pagamento is None)

    return Extrato(
        modelo_id=modelo_id,
        vendido=_soma(v.valor for v in vendas),
        comprovado=comprovado,
        em_especie=especie,
        a_comprovar=a_comprovar,
        sem_forma=sem_forma,
        vendas=len(vendas),
        pendencias=tuple(p for venda in vendas for p in pendencias_da_venda(venda)),
        divergencias=_divergencias(vendas=vendas, comprovantes=comprovantes),
        cobrancas=tuple(c for c in cobrancas if c.aberta),
        razao=razao,
    )


def _comprovada(venda: VendaRegistrada) -> bool:
    return espera_comprovante(venda.forma_pagamento) and venda.comprovante_id is not None


def _divergencias(
    *, vendas: Sequence[VendaRegistrada], comprovantes: Sequence[ComprovanteDoGrupo]
) -> tuple[Divergencia, ...]:
    """O que o extrato NAO consegue explicar — uma linha por dinheiro sem par.

    O comprovante `ilegivel` fica de fora: dele nao se sabe nem o valor, entao ele nao e uma
    divergencia de conta, e um pedido de reenvio ja feito (ticket 07). Divergir exige numero.
    """
    achadas: list[Divergencia] = []
    transferido = ZERO
    sobras = ZERO
    for comprovante in comprovantes:
        if comprovante.valor is None or comprovante.valor <= 0:
            continue
        if comprovante.classificacao == "cobranca":
            # Pagou uma Cobranca da agencia (ticket 08): esse dinheiro nao e fechamento de venda
            # nenhuma e nao entra em `transferido`. Some-lo empurraria o "transferido" acima do
            # vendido e faria o extrato perguntar sobre o unico Pix cujo destino ele JA sabe — o
            # mesmo comprovante que, ate o ticket 08, aparecia como `comprovante_sem_par`.
            continue
        if comprovante.classificacao == "nao_classificado":
            # Ja tem a linha dele ("nao fechou venda nenhuma") — e por isso NAO entra em
            # `transferido`. Somar aqui faria o mesmo dinheiro divergir duas vezes: uma como
            # comprovante sem par e outra empurrando o total transferido acima do vendido. Duas
            # perguntas para um comprovante so, e a segunda sem resposta possivel.
            achadas.append(
                Divergencia(
                    "comprovante_sem_par",
                    comprovante.valor,
                    data=comprovante.data_transferencia,
                    comprovante_id=comprovante.id,
                )
            )
            continue
        transferido += comprovante.valor
        if comprovante.sobra > 0:
            sobras += comprovante.sobra
            achadas.append(
                Divergencia(
                    "credito_da_modelo",
                    comprovante.sobra,
                    data=comprovante.data_transferencia,
                    comprovante_id=comprovante.id,
                )
            )

    comprovado = _soma(v.valor for v in vendas if _comprovada(v))
    if comprovado > transferido:
        # Ha venda marcada como PAGA por um Pix menor do que ela. So acontece depois da
        # conciliacao — o abate nunca fecha uma venda com menos do que o comprovante cobre —, e o
        # caminho e a correcao de valor para cima (ticket 05) numa venda que ja tinha comprovante.
        # Sem esta linha o extrato fica bonito exatamente ali: `comprovado` sobe junto com o
        # `vendido`, a identidade das quatro colunas continua fechando, e a diferenca some.
        achadas.append(Divergencia("venda_comprovada_a_menor", comprovado - transferido))

    # O EIXO PIX, e nao o vendido total: o que este dinheiro pode explicar sao as vendas em pix —
    # as que ja tem comprovante e as que ainda esperam um. Venda em dinheiro e venda sem forma
    # dita estao no vendido e ficam FORA daqui de proposito: nenhuma delas justifica um Pix.
    #
    # `lastro` desconta as sobras porque elas ja tem a linha de `credito_da_modelo` acima. Sem esse
    # desconto, o caso mais comum do grupo — a modelo manda um Pix redondo maior que a venda —
    # rendia DUAS perguntas sobre os mesmos R$ 200,00, e a segunda sem resposta possivel.
    lastro = transferido - sobras
    explicavel = comprovado + _soma(
        v.valor for v in vendas if espera_comprovante(v.forma_pagamento) and not _comprovada(v)
    )
    if lastro > explicavel:
        # Chegou Pix que nenhuma venda em pix explica. O abate nunca fecha uma venda que nao esta
        # aberta, entao isto so acontece quando a venda MUDOU depois de conciliada: virou dinheiro,
        # encolheu de valor ou foi anulada. Sem esta linha o extrato fecha bonito no pior caso — a
        # venda paga por Pix vira "em especie com a modelo" e o mesmo dinheiro fica contado nos dois
        # lugares, sem nada em aberto para ninguem procurar.
        #
        # Vendas ainda sem forma dita nao entram em `explicavel`, mas tambem nao ficam mudas: elas
        # ja aparecem na coluna "Sem forma dita" e na pendencia de forma. (O pagamento de Cobranca
        # da agencia REGISTRADA nao chega ate aqui: sai do laco acima, no `classificacao ==
        # "cobranca"`.)
        achadas.append(Divergencia("pix_sem_venda_em_pix", lastro - explicavel))
    return tuple(achadas)


def _soma(valores: Iterable[Decimal]) -> Decimal:
    return sum(valores, ZERO)


# --- o que o agente diz no grupo ----------------------------------------------------------------

TUDO_CONCILIADO = "✅ Tudo conciliado — não tem nada em aberto por aqui."
"""A resposta quando nao ha movimento aberto. Curta de proposito: extrato com quatro linhas
zeradas seria o agente ocupando o grupo para dizer que nao tem nada a dizer."""

TITULO = "📊 Fechamento"


def montar_fala_do_fechamento(extrato: Extrato) -> str:
    """O extrato como o grupo o le — tres colunas, a diferenca, o que falta e o que nao bate.

    Uma mensagem so, na ordem em que o gestor faz a conta: quanto entrou, quanto ja esta provado,
    quanto ficou em especie, quanto falta comprovar. As pendencias vem depois do numero porque
    elas explicam o numero; as divergencias vem por ultimo, como pergunta, porque sao a unica
    parte que espera resposta de gente.
    """
    if extrato.conciliado:
        return TUDO_CONCILIADO

    plural = "s" if extrato.vendas != 1 else ""
    linhas = [
        TITULO,
        f"Vendido: {formatar_reais(extrato.vendido)} ({extrato.vendas} venda{plural})",
        f"Comprovado (pix): {formatar_reais(extrato.comprovado)}",
        f"{EM_ESPECIE_COM_A_MODELO.capitalize()}: {formatar_reais(extrato.em_especie)}",
        f"Falta comprovar: {formatar_reais(extrato.a_comprovar)}",
    ]
    if extrato.sem_forma > ZERO:
        # A QUARTA parcela da identidade, dentro do bloco de numeros. Ela ficou de fora ate 14/08 e
        # o resultado era um extrato que nao fecha na leitura: "Vendido: R$ 2.200,00" com
        # 1.500 + 0 + 0 embaixo, e os R$ 700,00 restantes so mencionados la adiante, na linha de
        # pendencia. O gestor confere ESTE bloco de cabeca — se ele nao soma, o agente perdeu a
        # unica coisa que tinha para oferecer.
        #
        # So aparece quando ha dinheiro nela: linha "R$ 0,00" em todo extrato ensina a pular o
        # bloco (mesma razao da linha de debito).
        linhas.append(f"Sem forma dita: {formatar_reais(extrato.sem_forma)}")
    debito = _linha_do_debito(extrato)
    if debito is not None:
        linhas.append(debito)
    saldo = _linha_do_saldo(extrato)
    if saldo is not None:
        linhas.append(saldo)
    aberto = _linha_de_pendencias(extrato)
    if aberto is not None:
        linhas.append(aberto)
    linhas += [_pergunta_da_divergencia(d) for d in extrato.divergencias]
    return "\n".join(linhas)


def _linha_do_debito(extrato: Extrato) -> str | None:
    """ "Cobrança da agência: R$ 385,80 (3RJ Suporte/Anúncio: 3 DIAS — não paga)"

    So aparece quando ha cobranca aberta: uma linha "R$ 0,00" em todo extrato ensinaria o grupo a
    pular o bloco de numeros. Uma cobranca vai NOMEADA (e a descricao que diz de que e a divida);
    varias viram contagem, pela mesma razao do teto de vendas nomeadas da rotina da manha.

    Fica depois das quatro colunas, e fora da soma delas, porque e outro eixo: aqui e o que a
    modelo DEVE, nao o que ela vendeu.
    """
    if not extrato.cobrancas:
        return None
    if len(extrato.cobrancas) == 1:
        (cobranca,) = extrato.cobrancas
        return f"Cobrança da agência: {formatar_reais(cobranca.valor)} ({cobranca.descricao} — não paga)"
    quantas = len(extrato.cobrancas)
    return f"Cobrança da agência: {formatar_reais(extrato.debito)} ({quantas} não pagas)"


def _linha_do_saldo(extrato: Extrato) -> str | None:
    """ "💰 A casa te deve R$ 600,00" — o numero que o gestor realmente quer (ADR-0045 §1).

    Fecha o bloco de numeros, DEPOIS das colunas e do debito, porque e o resultado delas: as
    quatro colunas dizem quanto entrou e por onde, o saldo diz quem termina devendo a quem. Ele
    nao substitui nenhuma coluna — "em especie" continua sendo o recorte do que nao tem
    comprovante a cobrar (ADR-0045 §2).

    Sai calado quando o razao nao foi apurado (`None`): extrato montado pelo caminho antigo nao
    afirma nada sobre saldo. Zero tem linha propria — "nao devo nada" e informacao, e o silencio
    ali seria lido como "o agente nao sabe".
    """
    saldo = extrato.saldo
    if saldo is None:
        return None
    if saldo > ZERO:
        return f"💰 A casa te deve {formatar_reais(saldo)}"
    if saldo < ZERO:
        return f"💰 Você deve {formatar_reais(-saldo)} pra casa"
    return "💰 Saldo zerado — a casa e você estão quites."


def _linha_de_pendencias(extrato: Extrato) -> str | None:
    """ "⏳ Falta a forma de pagamento de 2 vendas · 1 venda em pix sem comprovante."

    Consolidada numa linha, nunca uma por venda: cobranca de pendencia e consolidada por regra do
    dominio, e o extrato e o mesmo texto que a rotina da manha (ticket 10) vai postar.
    """
    partes: list[str] = []
    formas = sum(1 for p in extrato.pendencias if p.tipo == "forma_pagamento")
    comprovantes = sum(1 for p in extrato.pendencias if p.tipo == "comprovante")
    if formas:
        # Sem repetir o VALOR: ele agora e uma coluna do bloco de numeros ("Sem forma dita"). O
        # mesmo R$ 700,00 duas vezes na mesma mensagem faz o leitor procurar a diferenca entre os
        # dois — e nao ha diferenca. Aqui a informacao e QUANTAS vendas esperam resposta.
        partes.append(f"falta a forma de pagamento de {formas} venda{'s' if formas > 1 else ''}")
    if comprovantes:
        partes.append(
            f"{comprovantes} venda{'s' if comprovantes > 1 else ''} em pix sem comprovante"
        )
    if not partes:
        return None
    # Capitaliza a primeira: esta linha abre frase como as de cima, e "⏳ falta…" em minuscula no
    # meio de um bloco todo capitalizado le como sobra de texto, nao como item.
    corpo = " · ".join(partes)
    return "⏳ " + corpo[0].upper() + corpo[1:] + "."


def _pergunta_da_divergencia(divergencia: Divergencia) -> str:
    """Cada dinheiro sem par vira UMA pergunta com o valor a vista.

    Pergunta e nao alerta: quem sabe o que aquele Pix era e o humano do grupo, e a resposta dele
    (ticket 08 para a Cobranca da agencia) e o que fecha a conta. O agente diz o que viu e para.
    """
    quando = f" · {divergencia.data:%d/%m}" if divergencia.data is not None else ""
    valor = formatar_reais(divergencia.valor)
    if divergencia.tipo == "comprovante_sem_par":
        return f"❓ Tem um comprovante de {valor}{quando} que não fechou venda nenhuma — é de quê?"
    if divergencia.tipo == "credito_da_modelo":
        return f"❓ Sobrou {valor} do comprovante{quando} sem venda pra fechar — é de quê?"
    if divergencia.tipo == "venda_comprovada_a_menor":
        return (
            f"❓ Tem venda dada como paga com Pix menor que ela — faltam {valor} de comprovante. "
            "Confere aí?"
        )
    return f"❓ Chegou {valor} de Pix que nenhuma venda em pix explica — confere aí?"
