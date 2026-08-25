"""Pendencia de uma Venda registrada (spec 0005, ticket 03).

**Pendencia bloqueia a CONCILIACAO daquela venda, nunca o registro nem o resto do extrato**
(docs/dominio/grupo-financeiro.md). E por isso que ela e DERIVADA do estado da venda em vez de
morar numa tabela de "coisas pendentes": uma linha propria poderia ficar orfa da venda que a
originou, e uma pendencia orfa e exatamente o que vira trava — o agente cobraria algo que ja foi
resolvido. Enquanto a fonte da verdade for a coluna da venda, "resolver a pendencia" e um UPDATE
so, e nao existe estado a reconciliar.

Do ticket 03 saiu a pendencia de **forma de pagamento nao dita** (a mais comum: o anuncio sempre
precede o pagamento no grupo real). Do ticket 07 sai a de **comprovante nao enviado**, derivada
do mesmo jeito — de coluna da venda (`comprovante_id IS NULL` numa venda pix), nunca de tabela
propria.

**Cobranca da agencia nao paga (ticket 08) NAO mora aqui**, e pelo mesmo criterio que trouxe as
outras duas: `Pendencia` existe porque falta de forma e falta de comprovante nao tem linha propria
em lugar nenhum — sao coluna nula de uma venda. A Cobranca da agencia aberta JA e uma linha, com
id, valor e descricao (`cobranca.py`), e o extrato a carrega inteira (`Extrato.cobrancas`).
Derivar dela um segundo objeto so criaria duas versoes do mesmo debito para discordarem.

**Nome de anuncio desconhecido nao mora aqui** (ticket 04): sem saber de quem e a venda nao ha
Venda registrada a que prender a pendencia, e `Pendencia` e sempre presa a uma. Ela vive como a
pergunta sem resposta no log do grupo — e derivada dali (a porta nao repergunta pelo mesmo nome)
exatamente como esta e derivada da coluna.

**Em especie**: venda paga em dinheiro conta no vendido, fica "em especie com a modelo" e sai da
expectativa de comprovante — cobrar comprovante de dinheiro vivo e pedir o que nao existe, e o
acerto do cash e da operacao (fora do sistema, como o repasse).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.modelos import FormaPagamento, VendaRegistrada

TipoDePendencia = Literal["forma_pagamento", "comprovante"]

EM_ESPECIE_COM_A_MODELO = "em espécie com a modelo"
"""Como a casa chama a venda paga em dinheiro. Texto unico para o recibo, o fechamento (ticket
09) e o painel (11) dizerem a mesma coisa."""


@dataclass(frozen=True)
class Pendencia:
    """O que falta para UMA venda conciliar. Sempre presa a venda — nunca solta no grupo."""

    venda_id: UUID
    tipo: TipoDePendencia


def pendencias_da_venda(venda: VendaRegistrada) -> tuple[Pendencia, ...]:
    """As pendencias vivas desta venda, agora. Vazio = conciliavel.

    Uma de cada vez, e nunca as duas: enquanto nao se sabe COMO a venda foi paga, cobrar
    comprovante e a metralhadora de perguntas que o dominio proibe — pode nem haver Pix a
    comprovar. Descoberta a forma, a pendencia troca: pix passa a esperar comprovante, dinheiro
    fica em especie com a modelo e nao espera nada.

    Venda **anulada** (ticket 05) nao tem pendencia nenhuma: cobrar a forma de pagamento de um
    registro que o grupo apagou e exatamente a pendencia orfa que este modulo se recusa a criar.
    """
    if venda.anulada_em is not None:
        return ()
    if venda.forma_pagamento is None:
        return (Pendencia(venda.id, "forma_pagamento"),)
    if espera_comprovante_da_venda(venda) and venda.comprovante_id is None:
        return (Pendencia(venda.id, "comprovante"),)
    return ()


EstadoDeConciliacao = Literal[
    "anulada", "aguardando_forma", "em_especie", "aguardando_comprovante", "conciliada"
]
"""Em que pe esta UMA venda — o que o painel (ticket 11) mostra na coluna de estado.

Nao e status novo nem coluna nova: e o mesmo fato que `pendencias_da_venda` ja diz, dito como
UMA palavra em vez de uma lista. Derivar o estado da pendencia (e nao ao contrario) e o que
garante que a linha do painel e a cobranca da manha nunca discordem sobre a mesma venda.
"""


def estado_de_conciliacao(venda: VendaRegistrada) -> EstadoDeConciliacao:
    """A venda em uma palavra. `em_especie` NAO e pendencia: dinheiro vivo nao espera nada.

    Venda no cartao cai em `conciliada`, e nao numa palavra propria: para ESTE modulo — que existe
    para saber o que ainda e cobravel no grupo — ela nao espera nada mesmo, e inventar um estado
    obrigaria todo consumidor do Literal a decidir o que fazer com ele para nao mudar nada. Quem
    precisa distinguir as tres formas de cartao e a conferencia do painel, e ela le a FORMA
    (`no_cartao`), que e o dado, em vez de um estado derivado dela."""
    if venda.anulada_em is not None:
        return "anulada"
    for pendencia in pendencias_da_venda(venda):
        return (
            "aguardando_forma" if pendencia.tipo == "forma_pagamento" else "aguardando_comprovante"
        )
    return "em_especie" if em_especie(venda.forma_pagamento) else "conciliada"


def em_especie(forma: FormaPagamento | None) -> bool:
    """Dinheiro fica com a modelo — nao ha o que comprovar, so o que conferir no fechamento.

    So `dinheiro`. Cartao nao e especie por mais que a maquininha seja dela: o dinheiro do cartao
    ainda vai cair numa conta, com data e extrato, e chamar isso de "em especie com a modelo"
    diria ao operador que nao ha nada a conferir num dinheiro que tem exatamente onde conferir.
    """
    return forma == "dinheiro"


def no_cartao(forma: FormaPagamento | None) -> bool:
    """Debito, credito ou link — as tres formas que nasceram do desmembramento de "cartao".

    Existe como PREDICADO e nao como comparacao solta porque as tres andam juntas em toda decisao
    deste modulo (nao esperam comprovante Pix, nao quitam Cobranca da agencia, conciliam no
    extrato da adquirente) e separadas so na conferencia do painel, que e onde a diferenca entre
    elas importa. Espalhar `forma in ("debito", "credito", "link")` por tres arquivos e como uma
    quarta forma de cartao entra em dois deles e some do terceiro.
    """
    return forma in ("debito", "credito", "link")


def espera_comprovante(forma: FormaPagamento | None) -> bool:
    """So venda em PIX gera expectativa de comprovante.

    Venda sem forma dita ainda nao gera: a pendencia dela e outra (descobrir a forma), e cobrar
    comprovante antes de saber se houve pix e a metralhadora de perguntas que o dominio proibe.

    **Cartao tambem nao gera** (ticket 11). A prova da venda no cartao e o print da maquininha, e
    ele nao e Comprovante de transferencia: nao passa pelo OCR de Pix, nao abate venda em pix e
    nao quita Cobranca da agencia. Cobrar "o comprovante" de uma venda no credito pediria um
    documento que nao existe neste modulo — e a modelo mandaria o print, que ninguem leria, e a
    cobranca voltaria identica amanha.
    """
    return forma == "pix"


def espera_comprovante_da_venda(venda: VendaRegistrada) -> bool:
    """Idem, mas para ESTA venda — inclui quem ficou com o dinheiro (ticket 13).

    Na festinha em que uma modelo recebeu por todas, as outras tres nao tem comprovante nenhum a
    mandar: o dinheiro delas foi para a amiga, e o repasse entre modelos fica fora do sistema
    (ADR-0045 §6). Cobra-las seria a cobranca que volta identica todo dia sem que exista gesto
    capaz de fecha-la — e a venda delas nao some da conta: ela migra para a fila de abate de quem
    recebeu (`repo.vendas_pix_a_comprovar`), que e quem pode mandar o comprovante.

    Recebe a venda (e nao a forma) porque a resposta depende de dois campos, e a versao por forma
    continua existindo para quem so tem a forma na mao (o fechamento por coluna, o recibo).
    """
    if venda.recebido_por_modelo_id not in (None, venda.modelo_id):
        return False
    return espera_comprovante(venda.forma_pagamento)
