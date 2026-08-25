"""O Deslocamento da venda: o Uber da modelo em DOIS valores (ADR-0046 §6, ticket 12).

O Uber ida-e-volta e cobrado do cliente — tipicamente R$ 100, por Pix ao telefonista. Sem
rastrear **quem recebeu** esse dinheiro e **quem pagou** o Uber, os R$ 100 somem do caixa e a
conta nao bate no fim da temporada.

**Sao dois valores, e eles divergem.** `valor_antecipado` e o que o cliente mandou (receita);
`valor_transporte` e o que o Uber custou (custo). O caso que prova e o do proprio dono: *"quando e
muito perto, tipo 15 reais de Uber, eu pago"* — antecipado zero, transporte nao. Com um numero so,
"o cliente mandou 100 e o Uber custou 60" e indistinguivel de "ninguem mandou nada e o Uber custou
15", e o segundo caso e **credito** dela. Um numero so apaga a margem e apaga o prejuizo.

Com dois valores os quatro casos deixam de ser uma tabela e viram uma conta, que mora em
`razao.py` e nao aqui:

    efeito no razao dela = (antecipado recebido por ela) - (transporte pago por ela)

| Antecipado | Recebeu | Transporte | Pagou | Efeito |
|---|---|---|---|---|
| 100 | ela   | 100 | casa  | **debito 100** — ela esta com dinheiro da casa |
| 100 | casa  | 100 | casa  | **zero** — nao toca o razao dela |
| 100 | ela   |  60 | ela   | **debito 40** — sobrou 40 com ela |
|   0 | —     |  15 | ela   | **credito 15** — a casa deve a ela |

Este modulo e o lado da ESCRITA: o que gravar quando a ficha vira venda. O lado da leitura (do
banco para o razao) e `temporada.DeslocamentoParaORazao` + `repo.deslocamentos_para_o_razao`, e a
conta e `razao.DeslocamentoNoRazao`. Tres pecas, um fato — e a mesma divisao que a venda ja tem.

Duas regras que nao se negociam:

* **Nunca entra na base de comissao**, nem da modelo nem do telefonista (ADR-0045 §5, ADR-0048):
  e reembolso de custo, nao servico vendido. Quem quiser comissao soma vendas, e deslocamento nao
  e venda — por isso ele e lancamento proprio e nao um campo da venda.
* **Nao se soma ao vendido.** No extrato ele aparece separado; misturado, o faturamento da modelo
  cresce R$ 100 por atendimento com transporte e nenhuma conferencia bate.

O que este modulo NAO sabe: quem recebeu e quem pagou. O card do telefonista
(`docs/dominio/fichas-do-telefonista.md`) tem `Valor do transporte`, `Valor antecipado` e
`Forma do antecipado` — e **nao** tem campo de recebedor nem de pagador. O default do dominio (e
da coluna) e `casa` nos dois, que e o arranjo tipico: o cliente manda o Pix ao telefonista e a
casa chama o carro. Quando foi diferente, alguem diz — e quem diz passa o parametro.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.ficha import FichaDeAgendamento, FormaDoAntecipado
from barra.dominio.grupo_financeiro.razao import ZERO, DeslocamentoNoRazao
from barra.dominio.grupo_financeiro.temporada import ParteDoDeslocamento

PARTE_PADRAO: ParteDoDeslocamento = "casa"
"""Quem recebe o antecipado e quem paga o Uber quando ninguem disse (ADR-0046 §6).

`casa` nos dois, e nao `modelo`: o antecipado chega por Pix **ao telefonista** e e a casa que
chama o carro — e esse par e o unico que nao toca o razao dela, entao errar para ca nao move
dinheiro no extrato de ninguem. O default oposto inventaria um debito de R$ 100 toda vez que o
telefonista esquecesse de dizer quem recebeu.
"""


@dataclass(frozen=True)
class PlanoDoDeslocamento:
    """O que gravar em `deslocamentos_da_venda` — os dois valores e as duas pontas.

    Plano e nao entidade: ele existe entre "li a ficha" e "gravei a linha", que e onde o
    recebedor e o pagador ainda podem ser ditos. Depois de gravado, o que se le de volta e
    `temporada.DeslocamentoParaORazao`, que ja vem com a modelo resolvida pelo JOIN.
    """

    valor_antecipado: Decimal = ZERO
    """O que o CLIENTE mandou pelo transporte — receita. Zero e caso normal, nao falta de dado."""
    valor_transporte: Decimal = ZERO
    """O que o Uber CUSTOU. Zero e caso normal (nao houve deslocamento, ou ninguem anotou)."""
    forma_antecipado: FormaDoAntecipado | None = None
    """`pix` ou `link`. Dinheiro nao entra: antecipado e o que chega ANTES, e dinheiro so chega
    na hora — o CHECK da coluna diz o mesmo."""
    recebedor_do_antecipado: ParteDoDeslocamento = PARTE_PADRAO
    pagador_do_transporte: ParteDoDeslocamento = PARTE_PADRAO

    @property
    def registravel(self) -> bool:
        """Ha o que gravar? Os dois valores zerados nao viram linha.

        Nao e so economia de linha: a coluna tem `CHECK (valor_antecipado > 0 OR valor_transporte
        > 0)`, e uma linha de deslocamento sem nenhum valor diria no painel que houve transporte
        neste atendimento — sem numero nenhum para conferir.
        """
        return self.valor_antecipado > ZERO or self.valor_transporte > ZERO

    def no_razao(self, *, origem_id: UUID | None = None) -> DeslocamentoNoRazao:
        """O plano como o razao o le. A conta em si e de `razao.py` — aqui so a traducao.

        As duas pontas viram dois booleanos porque o razao **e dela**: o que a casa recebeu e o
        que a casa pagou nao entram na conta, e carregar o enum ate la faria a funcao pura ter de
        saber o vocabulario do banco para descartar metade dele.
        """
        return DeslocamentoNoRazao(
            valor_antecipado=self.valor_antecipado,
            recebido_por_ela=self.recebedor_do_antecipado == "modelo",
            valor_transporte=self.valor_transporte,
            pago_por_ela=self.pagador_do_transporte == "modelo",
            origem_id=origem_id,
        )


def planejar_deslocamento(
    ficha: FichaDeAgendamento,
    *,
    recebedor_do_antecipado: ParteDoDeslocamento = PARTE_PADRAO,
    pagador_do_transporte: ParteDoDeslocamento = PARTE_PADRAO,
) -> PlanoDoDeslocamento | None:
    """O deslocamento que esta ficha manda gravar. `None` = nao houve (os dois valores vazios).

    Le a ficha e mais nada. As duas pontas sao parametro porque o card **nao as tem** (ver o
    cabecalho do modulo): inferi-las do tipo de atendimento — "saida logo ela se deslocou, logo
    ela pagou" — seria escrever no razao dela um fato que ninguem afirmou, e o erro so apareceria
    no fechamento, como R$ 100 que ela nao deve.

    Campo vazio na ficha vale ZERO e nao "desconhecido": o telefonista deixa o `Valor antecipado`
    em branco quando o cliente nao antecipou nada, que e o caso mais comum. Tratar branco como
    falta transformaria toda ficha sem transporte numa pendencia a cobrar de manha.
    """
    plano = PlanoDoDeslocamento(
        valor_antecipado=ficha.valor_antecipado or ZERO,
        valor_transporte=ficha.valor_transporte or ZERO,
        forma_antecipado=ficha.forma_antecipado,
        recebedor_do_antecipado=recebedor_do_antecipado,
        pagador_do_transporte=pagador_do_transporte,
    )
    return plano if plano.registravel else None
