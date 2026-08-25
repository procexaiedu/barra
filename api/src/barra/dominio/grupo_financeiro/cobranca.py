"""Cobranca da agencia (spec 0005, ticket 08).

O gesto real, de 13/08: um gestor posta no grupo "*3RJ Suporte/Anuncio:* / 3 DIAS | R$ 385,80 /
envia para o site e envia o comprovante", a modelo pergunta a chave, paga e posta o comprovante.
Hoje ninguem registra nada — a divida da modelo com a agencia vive na memoria do gestor, e o Pix
que a quita e, para o sistema, indistinguivel de um Pix de fechamento de vendas.

Quatro decisoes moram aqui:

* **Cobranca e DEBITO da modelo, nunca receita.** Ela nao e uma "venda negativa" (poluiria as tres
  colunas do Fechamento, a receita do Modulo Financeiro e o dedup de conteudo) e nao e
  `financeiro_despesas` (despesa e da CASA; isto e divida DELA). E um eixo a parte: entra no
  extrato como coluna de debito e sai de la quando o comprovante chega.
* **A triagem e allowlist FECHADA, e o anuncio de venda vence sempre.** O grupo e social: sem uma
  lista fechada de rubricas o agente transformaria qualquer frase com cifra em divida da modelo.
  A cobranca exige DUAS coisas na mesma mensagem — uma linha com rubrica conhecida e uma cifra
  escrita com "R$" — e a porta so chega aqui depois de descartar o anuncio de venda.
* **Quitar e um fato COM PROVA.** Nao existe "marcar como paga": a cobranca se fecha amarrada ao
  Comprovante de transferencia que a pagou. E esse par que explica, no extrato, para onde foi o
  R$ 385,80 que antes aparecia como divergencia `comprovante_sem_par` (ticket 09).
* **Na duvida entre cobranca e venda, o agente PERGUNTA.** Um comprovante que tanto quitaria a
  cobranca quanto abateria vendas pix abertas fica retido com uma pergunta. Chutar aqui move
  dinheiro entre dois eixos que nunca mais se cruzam: a venda "comprovada" por engano some da
  fila e a cobranca segue cobrada — e nenhum dos dois erros aparece para ninguem.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.recibo import formatar_reais

# As rubricas que a agencia cobra pelo grupo. Allowlist FECHADA, como a dos acompanhantes do
# pedido de fechamento: rubrica que este modulo nao conhece significa que a mensagem e sobre outra
# coisa, e o silencio erra menos que uma divida inventada no nome da modelo. Rubrica nova entra
# aqui por EVIDENCIA (uma mensagem real do grupo), nunca por antecipacao.
_MARCADORES_DA_COBRANCA = frozenset({"3rj", "anuncio", "anuncios", "suporte", "site"})

# A cifra COM "R$" e a segunda metade da triagem, e ela e deliberadamente mais estrita que a do
# anuncio: o valor de uma venda mora sozinho na linha ("700 1h"), o da cobranca vem escrito como
# dinheiro ("R$ 385,80"). Exigir o "R$" e o que impede "3 DIAS" ou um numero de torre de virar
# debito da modelo.
_CIFRA = re.compile(
    r"r\$\s*(?P<inteiro>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<centavos>\d{2}))?",
    re.IGNORECASE,
)

_TOKEN = re.compile(r"[0-9a-z]+")
_ORNAMENTO = re.compile(r"^[\s*_~`]+|[\s*_~`]+$")
"""Negrito/italico do WhatsApp em volta da rubrica ("*3RJ Suporte/Anuncio:*"). Sai da leitura e
sai da descricao — o que se guarda e o que o gestor escreveu, nao como ele formatou."""

MAX_DESCRICAO = 120
"""Teto da rubrica guardada. Descricao e o que o recibo ecoa e o que identifica a cobranca no
extrato: um paragrafo inteiro ali viraria parede de texto no grupo e no painel."""


@dataclass(frozen=True)
class CobrancaLida:
    """O que a mensagem diz — antes de virar linha no banco.

    `descricao` e a rubrica na grafia do gestor, SEM a cifra ("3RJ Suporte/Anúncio: 3 DIAS"): e o
    que o recibo ecoa e o que identifica a cobranca para quem le o extrato.
    """

    descricao: str
    valor: Decimal


@dataclass(frozen=True)
class CobrancaDaAgencia:
    """Uma Cobranca da agencia ja persistida: debito da modelo para com a agencia.

    `quitada_em` e `comprovante_id` andam juntos (o banco tem o CHECK): quitar e um fato com
    prova, e um booleano `paga` perderia a prova exatamente no dado que existe para provar
    pagamento.
    """

    id: UUID
    grupo_id: UUID
    modelo_id: UUID
    mensagem_id: UUID
    descricao: str
    valor: Decimal
    data: date
    comprovante_id: UUID | None = None
    quitada_em: datetime | None = None
    anulada_em: datetime | None = None

    @property
    def aberta(self) -> bool:
        """Ainda cobra alguma coisa? Anulada (mensagem-fonte apagada) nao cobra; quitada, tampouco."""
        return self.quitada_em is None and self.anulada_em is None


def ler_cobranca(texto: str) -> CobrancaLida | None:
    """A mensagem e uma Cobranca da agencia? `None` = nao e (o caso da imensa maioria).

    Exige rubrica conhecida **e** cifra com "R$" na mesma mensagem. As duas juntas, porque cada
    uma sozinha e comum no grupo: "envia para o site" e conversa, "R$ 385,80" pode ser conferencia
    de fechamento, e virar divida da modelo e uma decisao que ninguem revisa depois.

    Rubrica sem cifra tambem devolve `None` — e silencio, nao pergunta minima: perguntar "quanto?"
    sobre uma mensagem que talvez nem fosse cobranca seria interrogar a gestora sobre a propria
    conversa dela. Quando a cobranca vier de verdade, ela vem com o valor (e sempre veio).
    """
    linhas = [_sem_ornamento(linha) for linha in texto.splitlines()]
    linhas = [linha for linha in linhas if linha]
    if not linhas:
        return None

    rubrica = next((linha for linha in linhas if _tem_marcador(linha)), None)
    if rubrica is None:
        return None

    for linha in linhas:
        achado = _CIFRA.search(linha)
        if achado is None:
            continue
        valor = _valor(achado)
        if valor is None:
            continue
        return CobrancaLida(descricao=_descricao(rubrica, linha, achado.start()), valor=valor)
    return None


def chave_de_conteudo_da_cobranca(
    *, data: date, valor: Decimal, modelo_id: UUID, descricao: str
) -> str:
    """ "2026-08-13|385.80|<modelo>|3rj suporte/anuncio: 3 dias" — a identidade do FATO.

    Mesmo gesto e mesmo remedio da Venda registrada (dedup.py): a cobranca repostada, ou postada
    nos dois grupos da mesma modelo, nao pode virar dois debitos. Chave legivel e nao hash pelo
    mesmo motivo de la — quando uma cobranca "sumir" no dedup, quem investiga le a chave no banco
    e ve na hora por que ela colidiu.
    """
    return "|".join([f"{data:%Y-%m-%d}", f"{valor:.2f}", str(modelo_id), normalizar(descricao)])


@dataclass(frozen=True)
class CasamentoDaCobranca:
    """A quem este comprovante pertence — a cobranca, ou a fila de vendas.

    Os dois campos nunca vem preenchidos juntos: `quitada` e a cobranca que o comprovante fecha,
    `ambigua` e a que impede o agente de concluir (o mesmo dinheiro fecharia venda tambem). Ambos
    vazios = o comprovante nao tem nada a ver com cobranca, e o caminho e o de sempre (FIFO das
    vendas pix, ticket 07).
    """

    quitada: CobrancaDaAgencia | None = None
    ambigua: CobrancaDaAgencia | None = None


def escolher_cobranca(
    *, valor: Decimal, abertas: Sequence[CobrancaDaAgencia], abate_venda: bool
) -> CasamentoDaCobranca:
    """Este comprovante quita alguma cobranca aberta? Casamento por valor EXATO.

    Exato porque a cobranca e um numero fechado que a agencia mandou e a modelo pagou ao centavo
    ("R$ 385,80"); tolerancia aqui seria o agente decidir que um Pix parecido "deve ser" o
    pagamento — e o que ele decidir some da conta dos dois lados.

    `abate_venda` e o veredito do plano de abate (ticket 07) sobre a MESMA quantia: se o dinheiro
    tambem fecharia venda pix aberta, a leitura e ambigua e o agente pergunta em vez de escolher.

    Duas cobrancas abertas do mesmo valor: quita a mais ANTIGA (`abertas` ja vem nessa ordem). E o
    mesmo FIFO das vendas e nao ha palpite envolvido — as duas cobram a mesma quantia, e a divida
    mais velha e a que o pagamento naturalmente baixa.
    """
    candidata = next((c for c in abertas if c.aberta and c.valor == valor), None)
    if candidata is None:
        return CasamentoDaCobranca()
    if abate_venda:
        return CasamentoDaCobranca(ambigua=candidata)
    return CasamentoDaCobranca(quitada=candidata)


# --- o que o agente diz no grupo ----------------------------------------------------------------


def montar_recibo_da_cobranca(*, descricao: str, valor: Decimal, data: date) -> str:
    """ "🧾 Registrei a cobrança: 3RJ Suporte/Anúncio: 3 DIAS · R$ 385,80 · 13/08 — te aviso quando
    o comprovante chegar."

    Emoji proprio (e nao o ✅ da venda) porque o que aconteceu aqui e o oposto de uma venda: entrou
    uma divida da modelo, nao dinheiro dela. A promessa no fim existe para o gestor parar de
    lembrar a modelo — que e a razao de a cobranca ser rastreada (spec 0005, user story 10).
    """
    partes = [descricao, formatar_reais(valor), f"{data:%d/%m}"]
    return f"🧾 Registrei a cobrança: {' · '.join(partes)} — te aviso quando o comprovante chegar."


def montar_aviso_de_cobranca_duplicada(*, descricao: str, valor: Decimal, data: date) -> str:
    """ "♻️ Essa cobrança já estava registrada: … — não lancei de novo."

    Mesma conduta do anuncio duplicado (recibo.py): o agente responde em vez de engolir calado.
    Quem repostou a cobranca precisa saber que ela esta no sistema — e ver QUAL foi reconhecida,
    porque e por esta mensagem que o grupo descobre se o dedup pegou o fato errado.
    """
    partes = [descricao, formatar_reais(valor), f"{data:%d/%m}"]
    return f"♻️ Essa cobrança já estava registrada: {' · '.join(partes)} — não lancei de novo."


def montar_confirmacao_de_quitacao(
    *, cobranca: CobrancaDaAgencia, valor: Decimal, data: date | None
) -> str:
    """ "✅ Comprovante conferido: R$ 385,80 · 13/08 — quitei a cobrança 3RJ Suporte/Anúncio: 3
    DIAS. Nenhuma venda foi abatida."

    A ultima frase nao e redundancia: e o unico lugar onde o grupo ve que o Pix da cobranca NAO
    entrou no fechamento das vendas. Sem ela, quem confere de cabeca continuaria descontando esse
    dinheiro do que a modelo ainda deve comprovar — que e exatamente o erro que este ticket existe
    para tirar da operacao.
    """
    partes = [formatar_reais(valor)]
    if data is not None:
        partes.append(f"{data:%d/%m}")
    return (
        f"✅ Comprovante conferido: {' · '.join(partes)} — quitei a cobrança {cobranca.descricao}. "
        "Nenhuma venda foi abatida."
    )


def montar_pergunta_do_comprovante_ambiguo(
    *, cobranca: CobrancaDaAgencia, valor: Decimal, data: date | None
) -> str:
    """ "❓ Recebi um comprovante de R$ 385,80 · 13/08 — é o pagamento da cobrança 3RJ … ou
    fechamento de venda? Me diz aí que eu lanço."

    A pergunta NOMEIA a cobranca candidata, como a cobranca da manha nomeia a venda: quem le
    "é de quê?" sem saber do que o agente esta falando responde qualquer coisa. O comprovante fica
    retido enquanto isso — retido e visivel vale mais do que classificado errado.
    """
    partes = [formatar_reais(valor)]
    if data is not None:
        partes.append(f"{data:%d/%m}")
    return (
        f"❓ Recebi um comprovante de {' · '.join(partes)} — é o pagamento da cobrança "
        f"{cobranca.descricao} ou fechamento de venda? Me diz aí que eu lanço."
    )


# --- interno ------------------------------------------------------------------------------------


def _sem_ornamento(linha: str) -> str:
    return _ORNAMENTO.sub("", linha.strip())


def _tem_marcador(linha: str) -> bool:
    return any(token in _MARCADORES_DA_COBRANCA for token in _TOKEN.findall(normalizar(linha)))


def _valor(achado: re.Match[str]) -> Decimal | None:
    inteiro = achado.group("inteiro").replace(".", "")
    valor = Decimal(f"{inteiro}.{achado.group('centavos') or '00'}")
    return valor if valor > 0 else None


def _descricao(rubrica: str, linha_da_cifra: str, ate: int) -> str:
    """A rubrica sem a cifra: "*3RJ Suporte/Anúncio:*" + "3 DIAS | R$ 385,80" -> "…: 3 DIAS".

    O que vem DEPOIS da cifra fica de fora de proposito ("envia para o site e envia o
    comprovante" e instrucao a modelo, nao identidade da cobranca).
    """
    antes = _sem_ornamento(linha_da_cifra[:ate]).strip(" |-–—:")
    if linha_da_cifra == rubrica:
        return _cortar(antes or rubrica.strip(" :"))
    cabeca = rubrica.strip(" :")
    return _cortar(f"{cabeca}: {antes}" if antes else cabeca)


def _cortar(descricao: str) -> str:
    if len(descricao) <= MAX_DESCRICAO:
        return descricao
    return descricao[: MAX_DESCRICAO - 1].rstrip() + "…"
