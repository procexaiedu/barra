"""O Vale dito no grupo (spec 0006, ticket 15; ADR-0045 §8, ADR-0047 §5).

Vale e o adiantamento que a casa da a modelo no meio da temporada — *"tem que pagar uma conta de
500 reais, eu adianto"* — e que volta descontado no fechamento. Ele entra por DUAS portas: o
painel (ticket 05, a canonica, com `created_by`) e a fala no grupo, que e esta. A fala existe
porque o vale e dito no grupo o tempo todo ("adiantei 500 pra ela") e obrigar o gestor a abrir o
painel toda vez e a diferenca entre o saldo estar certo e estar mais ou menos certo.

Este modulo e so a LEITURA e as FALAS: puro, sem I/O, sem banco. Quem persiste e `repo.py`
(`registrar_lancamento_manual`, com `origem='grupo'` e `mensagem_id` obrigatorio pelo CHECK); quem
soma e `razao.apurar`, que ja conhece `ValeNoRazao` como debito dela.

Quatro decisoes moram aqui:

* **Vale NAO e Cobranca da agencia, em nenhuma direcao.** Os dois debitam a modelo, e por isso a
  confusao passaria despercebida no saldo — mas so a cobranca espera comprovante (a rotina da
  manha cobra, o Pix que a quita fecha a linha) e so o vale e desconto puro no fechamento. Ler um
  como o outro deixa uma divida cobrada para sempre ou um adiantamento esperando um comprovante
  que nunca vem. As duas allowlists sao DISJUNTAS de proposito: a da cobranca e de rubricas de
  servico ("3RJ", "anuncio", "site", "suporte"), a daqui e de verbos de emprestimo.
* **"Ficou com ela" NAO e vale** (ADR-0047 §5). Quando o gestor declara que a modelo ficou com o
  dinheiro DE UMA VENDA, isso e a venda com bolso `dela` mais a ausencia da transferencia — o
  razao ja da o numero certo. Lancar tambem um vale contaria o mesmo dinheiro DUAS vezes, e o
  erro sairia no fechamento como uma divida inventada no nome dela. A palavra "vale" na fala do
  gestor so vira lancamento quando ha adiantamento **fora** de uma venda.
* **Confianca baixa nao lanca — vira pergunta.** Duas hesitacoes existem e as duas sao sobre o
  NUMERO, nunca sobre o fato: o adiantamento dito sem valor ("adiantei pra ela") e o dito com
  dois valores na mesma frase. Chutar qualquer um deles escreve dinheiro que ninguem confere.
  Fora dessas duas, a leitura e silencio — o grupo e habitado, e uma pergunta sobre uma frase que
  talvez nem fosse vale seria o agente interrogando a gestora sobre a conversa dela.
* **O vale e sempre DELA.** Nao ha "de quem?" a resolver: o grupo e o da modelo, e vale de outra
  pessoa nao existe ali. Mesma razao da cobranca, e o que dispensa a pergunta de desempate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA
from barra.dominio.grupo_financeiro.recibo import CONVITE_DE_CORRECAO, formatar_reais

__all__ = [
    "DESCRICAO_PADRAO",
    "MAX_DESCRICAO",
    "MotivoDaHesitacao",
    "ValeHesitante",
    "ValeLido",
    "chave_de_conteudo_do_vale",
    "e_pergunta_do_vale",
    "ler_vale",
    "montar_aviso_de_vale_duplicado",
    "montar_pergunta_do_vale",
    "montar_recibo_do_vale",
]

# Os verbos e substantivos de EMPRESTIMO. Allowlist FECHADA, disjunta da da cobranca: a agencia
# cobra por servico ("3RJ", "site"), a casa adianta dinheiro. Entrada nova aqui exige uma
# mensagem real do grupo, nunca antecipacao — cada palavra a mais e uma frase social a mais que
# pode virar debito no nome de alguem.
_MARCADORES = (
    # "adiantei 500 pra ela", "eu adianto", "adiantamos", "ja foi adiantado", "adiantamento de 500"
    re.compile(r"\badiant(?:ei|amos|ou|o|ado|ada|amento)\b"),
    # "emprestei 400 pra ela", "e um emprestimo"
    re.compile(r"\bempresto?\b|\bemprest(?:ei|amos|ou|ado|ada)\b|\bemprestimos?\b"),
    # O substantivo "vale" — e SO ele. "vale a pena", "nao vale", "quanto vale isso" sao a mesma
    # palavra em funcao de verbo, e sao o que o grupo diz o dia inteiro. Exigir o artigo antes ou
    # a preposicao depois e o que separa as duas sem inventar analise sintatica.
    re.compile(
        r"\b(?:um|uns|o|os|esse|este|outro|mais um)\s+vales?\b|\bvales?\s+(?:de|pra|para)\b"
    ),
)

# O que este modulo NAO le, mesmo com marcador presente. Cada linha existe por um caminho que ja
# tem dono, e roubar o gesto dele custaria dinheiro contado duas vezes.
_FORA_DO_VALE = (
    # ADR-0047 §5: a venda que ficou na mao dela e bolso + ausencia de transferencia, e o razao ja
    # acerta. "aquilo ali foi um vale" dito SOBRE uma venda casa este padrao e sai calado.
    re.compile(r"\bficou\s+(?:com|pra|para)\b|\bficaram\s+(?:com|pra|para)\b"),
    # Deslocamento (ticket 12) tem lancamento proprio, com dois valores e quem pagou o Uber.
    # "adiantei 100 do uber dela" ali e reembolso de custo, nunca emprestimo.
    re.compile(r"\buber\b|\btaxi\b|\bcorrida\b|\btransporte\b|\bdeslocamento\b"),
    # Negacao: "nao adiantei nada", "nao vou adiantar". O texto tem o marcador e diz o oposto.
    re.compile(r"\bnao\s+(?:vou\s+)?(?:adiant|empresta?|dei|mandei|passei)"),
)

_BENEFICIARIA = re.compile(r"\b(?:pra|para|pro|p/)\s+(?:a\s+)?\w+|\bpara\s+ela\b|\bpra\s+ela\b")
"""A quem o dinheiro foi. Nao resolve modelo nenhuma (o vale e sempre da dona do grupo) — serve
so para separar "adiantei pra ela" (adiantamento sem valor, que vira pergunta) de "adiantei o
horario" (frase que tem o verbo e nao fala de dinheiro, e sai calada)."""

_VALOR = re.compile(
    r"(?<![\d,.])(?:r\$\s*)?(?P<inteiro>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<centavos>\d{2}))?(?!\d|[,.]\d)"
)
"""Dinheiro escrito como o grupo escreve: "500", "R$ 500", "1.200", "R$ 1.200,00".

A cauda proibe so o que CONTINUARIA o numero (outro digito, ou separador seguido de digito) — e
nao qualquer virgula. "adiantei 500, na verdade 300" traz a virgula colada no valor, e a versao
estrita perdia o 500 ali: a frase virava um vale de R$ 300,00 sem hesitacao nenhuma, que e o
palpite exato que este modulo existe para nao dar."""

_UNIDADE_QUE_NAO_E_DINHEIRO = re.compile(r"^\s*(?:h|hs|hr|hrs|hora|horas|min|minutos?|dias?|%)\b")
"""O que vem DEPOIS do numero e o que diz se ele e dinheiro. "2 horas", "3 dias" e "19h" moram na
mesma frase que o vale ("adiantei 500 pra ela, o de 2 horas") e nenhum deles e valor."""

MAX_DESCRICAO = 120
"""Teto da frase guardada. A descricao e o que o extrato do painel mostra ao lado da origem
`grupo`: um paragrafo inteiro ali viraria parede de texto na tela de fechamento."""

DESCRICAO_PADRAO = "Vale adiantado"
"""O que fica na linha quando a fala nao sobra nada legivel. Mesmo texto que `temporada.py` usa
como default do vale sem descricao — um so rotulo, para painel e grupo nao divergirem."""

MotivoDaHesitacao = Literal["sem_valor", "valor_ambiguo"]
"""Por que a leitura parou. As duas sao sobre o NUMERO — nunca sobre o fato de ser vale."""


@dataclass(frozen=True)
class ValeLido:
    """O adiantamento que a mensagem afirma, antes de virar linha no banco.

    `descricao` e a fala do gestor na grafia dele, cortada no teto: e o que o extrato mostra para
    quem confere e o unico jeito de o painel explicar de onde veio um debito que nasceu no grupo.
    """

    valor: Decimal
    descricao: str


@dataclass(frozen=True)
class ValeHesitante:
    """A mensagem e vale, e o valor nao esta decidido. NAO lanca — pergunta.

    `valores` traz os candidatos quando ha mais de um, porque a pergunta os NOMEIA: "de qual?" sem
    repetir os numeros e o agente devolvendo ao grupo a pergunta que o grupo acabou de responder.
    """

    motivo: MotivoDaHesitacao
    valores: tuple[Decimal, ...] = ()
    descricao: str = DESCRICAO_PADRAO
    """A fala que abriu a pergunta. Ela sobrevive a hesitacao porque e ela que vira a descricao do
    vale quando a resposta chegar — sem isso, o vale nascido de "adiantei pra ela" + "500" ficaria
    no painel como uma linha anonima, e ninguem saberia mais de onde veio o debito."""


def ler_vale(texto: str) -> ValeLido | ValeHesitante | None:
    """A mensagem declara um Vale? `None` = nao (o caso da imensa maioria).

    Exige marcador de emprestimo da allowlist fechada **e** dinheiro na mesma mensagem. Marcador
    sozinho so vira pergunta quando ha tambem a beneficiaria ("adiantei pra ela") — sem ela, uma
    frase como "adiantei o horario dela" tem o verbo e nao fala de dinheiro nenhum, e perguntar
    "quanto foi?" ali seria o agente inventando uma divida para confirmar.

    Dois valores distintos na mesma frase ("adiantei 500, na verdade 300") tambem nao lancam: qual
    dos dois vale e exatamente o que o agente nao sabe, e o que ele escolher some da conferencia.
    """
    limpo = " ".join(linha.strip() for linha in texto.splitlines() if linha.strip())
    if not limpo:
        return None
    normalizado = normalizar(limpo)

    if not any(marcador.search(normalizado) for marcador in _MARCADORES):
        return None
    if any(fora.search(normalizado) for fora in _FORA_DO_VALE):
        return None

    valores = _valores(normalizado)
    if not valores:
        if _BENEFICIARIA.search(normalizado):
            return ValeHesitante(motivo="sem_valor", descricao=_descricao(limpo))
        return None
    if len(valores) > 1:
        return ValeHesitante(motivo="valor_ambiguo", valores=valores, descricao=_descricao(limpo))
    return ValeLido(valor=valores[0], descricao=_descricao(limpo))


def chave_de_conteudo_do_vale(
    *, data: date, valor: Decimal, modelo_id: UUID, descricao: str
) -> str:
    """ "vale|2026-08-20|500.00|<modelo>|adiantei 500 pra ela" — a identidade do FATO.

    Mesmo remedio do anuncio (`dedup.py`) e da cobranca: o gestor apaga e reposta a mesma frase, ou
    a repete no outro grupo da modelo, e o adiantamento nao pode virar dois debitos. Chave legivel
    e nao hash pelo mesmo motivo de la — quando um vale "sumir" no dedup, quem investiga le a chave
    no banco e ve na hora com o que ela colidiu.

    A descricao entra na chave por assimetria de erro: dois vales de R$ 500,00 no mesmo dia, ditos
    com palavras diferentes, sao dois fatos — e engoli-los como um esconderia dinheiro adiantado.
    Ditos com as MESMAS palavras, sao repost em toda leitura razoavel do gesto.
    """
    return "|".join(
        ["vale", f"{data:%Y-%m-%d}", f"{valor:.2f}", str(modelo_id), normalizar(descricao)]
    )


# --- o que o agente diz no grupo ----------------------------------------------------------------


def montar_recibo_do_vale(*, valor: Decimal, data: date) -> str:
    """ "💸 Registrei o vale: R$ 500,00 · 20/08 — desconto no fechamento. corrige aí se algo
    estiver errado"

    Emoji PROPRIO, diferente do 🧾 da Cobranca da agencia, e a diferenca e o ponto: os dois debitam
    a modelo e so um espera comprovante. Quem confere de relance precisa ver, sem ler a linha
    inteira, que este dinheiro nao entra na fila de comprovacao de manha.

    O convite a correcao vem junto porque o recibo E a porta de correcao (ticket 15): o valor dito
    de cabeca no meio de uma conversa e o que mais nasce errado neste modulo.
    """
    return (
        f"💸 Registrei o vale: {formatar_reais(valor)} · {data:%d/%m} — desconto no fechamento. "
        f"{CONVITE_DE_CORRECAO}"
    )


def montar_aviso_de_vale_duplicado(*, valor: Decimal, data: date) -> str:
    """ "♻️ Esse vale já estava registrado: R$ 500,00 · 20/08 — não lancei de novo."

    Mesma conduta do anuncio e da cobranca duplicados: o agente responde em vez de engolir calado.
    Quem repostou precisa saber que o adiantamento esta no sistema — e ver QUAL foi reconhecido,
    porque e por esta mensagem que o grupo descobre se o dedup pegou o fato errado.
    """
    return (
        f"♻️ Esse vale já estava registrado: {formatar_reais(valor)} · {data:%d/%m} — "
        "não lancei de novo."
    )


def montar_pergunta_do_vale(hesitacao: ValeHesitante) -> str:
    """A pergunta minima do vale — o mesmo prefixo, o mesmo teto de uma pergunta so.

    "❓ Só falta saber: quanto foi o adiantamento?"
    "❓ Só falta saber: o adiantamento foi de R$ 500,00 ou R$ 300,00?"

    Reusa `PREFIXO_DA_PERGUNTA` de proposito: de relance o grupo ja sabe o que aquela assinatura
    significa (o agente esta esperando UMA palavra), e uma segunda gramatica de pergunta so
    ensinaria o grupo a ignorar as duas.
    """
    if hesitacao.motivo == "sem_valor" or not hesitacao.valores:
        return f"{PREFIXO_DA_PERGUNTA}quanto foi o adiantamento?"
    ditos = [formatar_reais(valor) for valor in hesitacao.valores]
    alternativas = f"{', '.join(ditos[:-1])} ou {ditos[-1]}"
    return f"{PREFIXO_DA_PERGUNTA}o adiantamento foi de {alternativas}?"


def e_pergunta_do_vale(texto: str) -> bool:
    """Esta fala do agente e a pergunta do vale? — o que faz o "500" seguinte ter dono.

    A pergunta minima do modulo e uma so por assinatura visual, e o grupo responde a ELA com uma
    palavra. Sem reconhecer a propria pergunta no log, o "500" que a responde cairia no leitor de
    valor avulso e iria completar um anuncio de venda incompleto — o adiantamento viraria receita.

    Casa as DUAS formas ("quanto foi o adiantamento?" e "o adiantamento foi de X ou Y?") por uma
    palavra que so aparece aqui, e nao pelo texto inteiro: a frase e feita para ser lida por
    humano e vai mudar de redacao; o que nao pode mudar e ela continuar reconhecivel.
    """
    normalizado = normalizar(texto)
    return normalizado.startswith(normalizar(PREFIXO_DA_PERGUNTA)) and "adiantamento" in normalizado


# --- interno ------------------------------------------------------------------------------------


def _valores(normalizado: str) -> tuple[Decimal, ...]:
    """Os valores DISTINTOS ditos na frase, na ordem em que aparecem.

    Distintos porque "adiantei 500 pra ela, os 500" e um valor so repetido — tratar isso como
    ambiguidade transformaria enfase em pergunta.
    """
    achados: list[Decimal] = []
    for achado in _VALOR.finditer(normalizado):
        if _UNIDADE_QUE_NAO_E_DINHEIRO.match(normalizado[achado.end() :]):
            continue
        inteiro = achado.group("inteiro").replace(".", "")
        valor = Decimal(f"{inteiro}.{achado.group('centavos') or '00'}")
        if valor > 0 and valor not in achados:
            achados.append(valor)
    return tuple(achados)


def _descricao(limpo: str) -> str:
    """A fala do gestor, em uma linha e cortada no teto. Vazia nunca — vira o rotulo padrao."""
    frase = limpo.strip()
    if not frase:
        return DESCRICAO_PADRAO
    if len(frase) <= MAX_DESCRICAO:
        return frase
    return frase[: MAX_DESCRICAO - 1].rstrip() + "…"
