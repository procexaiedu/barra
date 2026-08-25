"""Em que bolso o dinheiro daquela venda caiu (ADR-0047, tickets 14 e 21).

O ADR-0045 §4 dizia que isto era cadastro da modelo (`modelos.recebe_no_proprio_pix` + snapshot).
O ADR-0047 revogou: perguntado sobre as quatro modelos ativas, o dono respondeu *"varia, nao
existe so um padrao — as vezes elas vao receber no dela e vao repassar, as vezes elas vao ficar
com uma quantidade de valor que ja esta na conta dela"*. Um parametro de cadastro que varia por
atendimento nao e parametro: e um palpite congelado dentro da temporada.

Entao o bolso e **fato da venda**, resolvido por EVIDENCIA, nesta precedencia (ADR-0047 §2):

| Evidencia | Bolso |
|---|---|
| Comprovante da modelo -> casa, casando com a venda | `dela` (e a transferencia credita) |
| Comprovante do cliente -> a chave DELA (ticket 04) | `dela` (e nao ha transferencia a creditar) |
| Comprovante do cliente -> casa | `empresa` |
| Fala explicita ("caiu na minha conta", "ficou com voce") | o que foi dito |
| `forma = dinheiro` | `dela`, sempre — especie nao tem outro bolso |
| Nada disso | **`nao_dito`** |

Este modulo e a tabela acima como CODIGO, e so ela: puro, sem I/O, sem banco. Quem colhe as
evidencias (le o comprovante, le a fala, le a forma) e a porta; quem persiste e `repo.py`; quem
soma e `razao.py`. Duas funcoes carregam o modulo inteiro — `resolver_bolso`, para a venda que
NASCE, e `confrontar_bolso`, para a evidencia que chega DEPOIS.

Tres decisoes moram aqui:

* **`nao_dito` e estado legitimo, nao erro** (ADR-0047 §3). Ele viaja pela cobranca consolidada
  da manha que ja existe, ao lado da forma de pagamento que ja e cobrada — mesmo canal, mesma
  frase, **nunca uma pergunta em tempo real**. Uma pergunta a mais por venda e exatamente a
  metralhadora que o dominio proibe.
* **Quem interpreta `nao_dito` e o razao, nao este modulo.** Aqui `nao_dito` continua `nao_dito`
  (a coluna guarda a ignorancia); e `razao.bolso_efetivo` que o le como `dela` por default
  conservador (ADR-0047 §4). Resolver o default aqui apagaria a diferenca entre "ninguem disse" e
  "alguem disse que foi dela" — e e essa diferenca que decide se o agente ainda cobra.
* **Bolso ja AFIRMADO que diverge vira pergunta, nunca reescrita calada** (ticket 14). Mexer no
  bolso muda o SINAL do saldo: a mesma venda de R$ 1.200,00 e a modelo devendo 600 ou a casa
  devendo 600. Trocar isso sozinho, com base numa imagem, e a correcao que ninguem descobre.
  `nao_dito` -> evidencia resolve direto, porque nao ha nada a desmentir.

O que NAO mora aqui: **"ficou com ela" nao e bolso novo nem vale** (ADR-0047 §5). E a venda com
bolso `dela` MAIS a ausencia da transferencia — o razao ja da o numero certo sem conceito algum.
`ValeNoRazao` existe so para o adiantamento FORA de uma venda (ticket 15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.modelos import FormaPagamento
from barra.dominio.grupo_financeiro.pendencia import em_especie
from barra.dominio.grupo_financeiro.razao import Bolso
from barra.dominio.grupo_financeiro.recibo import CONVITE_DE_CORRECAO, formatar_reais

__all__ = [
    "BOLSO_NAO_DITO",
    "PREFIXO_DA_PERGUNTA_DO_BOLSO",
    "ROTULO_DO_BOLSO",
    "Bolso",
    "BolsoResolvido",
    "CondutaDoBolso",
    "Evidencia",
    "MudancaDoBolso",
    "VendaComBolso",
    "confrontar_bolso",
    "montar_pergunta_do_bolso",
    "montar_recibo_do_bolso",
    "resolver_bolso",
]

BOLSO_NAO_DITO: Literal["nao_dito"] = "nao_dito"
"""O estado em que toda venda nasce enquanto nenhuma evidencia apareceu (ADR-0047 §3)."""

Evidencia = Literal[
    "comprovante_dela_para_a_casa",
    "comprovante_do_cliente_para_a_modelo",
    "comprovante_do_cliente_para_a_casa",
    "fala",
    "especie",
    "nenhuma",
]
"""Qual linha da tabela do ADR-0047 §2 decidiu — na ordem em que elas se atropelam.

Viaja junto do bolso (e nao so no log) porque as duas perguntas que o operador faz sobre um saldo
torto sao "em que bolso o agente achou que caiu?" e "por que ele achou isso?". A segunda sem a
primeira e um numero sem defesa.

`comprovante_do_cliente_para_a_modelo` e a quarta classe de comprovante (`entrada_da_modelo`) vista
por este eixo. O ADR-0047 §2 nao lhe deu linha propria porque a tabela foi escrita antes de o papel
da chave existir (ADR-0049): sem saber de QUEM era o destino, "o cliente pagou nela" era um palpite
sobre um nome. Com o registro tipado ela e cadastro, e diz a mesma coisa que a primeira linha diz —
o dinheiro passou pela conta dela — por um caminho diferente (o cliente pagou direto ali, em vez de
ela ter transferido para a casa)."""

CondutaDoBolso = Literal["fixar", "perguntar", "nada"]
"""O que fazer com uma evidencia que chega sobre uma venda que JA existe (ticket 14)."""

ROTULO_DO_BOLSO: dict[Bolso, str] = {
    "dela": "com a modelo",
    "empresa": "na conta da casa",
    "nao_dito": "não dito",
}
"""Como o grupo le cada bolso. Um lugar so formata, entao o recibo e a pergunta nunca divergem —
e nenhum dos dois diz "dela"/"empresa", que sao a grafia da coluna e nao a do humano."""


@dataclass(frozen=True)
class BolsoResolvido:
    """O bolso e a evidencia que o decidiu."""

    bolso: Bolso
    evidencia: Evidencia

    @property
    def dito(self) -> bool:
        """Alguma evidencia falou? `False` = `nao_dito`, que entra na cobranca da manha."""
        return self.bolso != BOLSO_NAO_DITO


@dataclass(frozen=True)
class VendaComBolso:
    """Uma Venda registrada pelos olhos do bolso: valor, forma e o que ja foi afirmado.

    Read model proprio, irmao de `temporada.VendaParaORazao` e pelo mesmo motivo: `VendaRegistrada`
    e a venda que o agente decide e escreve (valor, forma, comprovante) e nao carrega `bolso` —
    juntar as duas obrigaria todo construtor de venda do modulo a saber de bolso para nao mudar
    nada.

    `bolso_mensagem_id` e a auditoria da decisao: quando o saldo estiver torto, e ela que mostra em
    que mensagem o agente se apoiou.
    """

    id: UUID
    modelo_id: UUID
    valor: Decimal
    data: date
    bolso: Bolso = BOLSO_NAO_DITO
    forma_pagamento: FormaPagamento | None = None
    cliente_nome: str | None = None
    bolso_mensagem_id: UUID | None = None

    @property
    def afirmado(self) -> bool:
        """Alguem ja disse (ou provou) onde este dinheiro caiu?"""
        return self.bolso != BOLSO_NAO_DITO


@dataclass(frozen=True)
class MudancaDoBolso:
    """O que fazer com a evidencia nova sobre uma venda que ja existe — e o de->para dela."""

    conduta: CondutaDoBolso
    de: Bolso
    para: Bolso
    evidencia: Evidencia


def resolver_bolso(
    *,
    comprovante_dela_para_a_casa: bool = False,
    comprovante_do_cliente_para_a_modelo: bool = False,
    comprovante_do_cliente_para_a_casa: bool = False,
    fala: Bolso | None = None,
    forma: FormaPagamento | None = None,
) -> BolsoResolvido:
    """A tabela do ADR-0047 §2, de cima para baixo. Para na PRIMEIRA evidencia que fala.

    A ordem nao e estetica — ela e o que cada evidencia PROVA, do mais duro ao mais mole:

    * o comprovante dela -> casa e o extrato de um banco dizendo que o dinheiro passou pela conta
      dela; nao ha o que discutir com ele;
    * o comprovante do cliente -> a chave DELA (a classe `entrada_da_modelo`) diz a mesma coisa
      por outro caminho: o dinheiro caiu na conta dela sem nunca passar pela casa. Nao ha ordem
      a decidir entre os dois — as duas linhas devolvem `dela` —, e por isso ele mora aqui em
      cima, junto da evidencia que tem a mesma dureza (extrato de banco + chave cadastrada);
    * o comprovante do cliente -> casa prova o contrario, e com a mesma forca, mas vem depois
      porque ele e mais facil de casar com a venda errada (o cliente paga o valor cheio, a modelo
      transfere valores compostos);
    * a fala e humana e pode ser um engano de quem digitou;
    * a forma e a regra mais fraca de todas — `dinheiro` e `dela` porque especie **nao tem** outro
      bolso, nao porque alguem afirmou alguma coisa.

    Nada disso -> `nao_dito`, que e estado legitimo: entra na cobranca consolidada da manha ao
    lado da forma de pagamento, sem pergunta nova e sem travar a venda (§3). O que este modulo
    **nao** faz e chutar `dela` aqui — o default conservador e do RAZAO (`bolso_efetivo`), e
    apaga-lo aqui apagaria a diferenca entre "ninguem disse" e "disseram que foi dela".

    As tres formas de cartao (debito, credito, link) seguem a mesma tabela e nao tem linha propria
    (ADR-0047 §6): nao existe `maquininha_da_modelo` no cadastro, entao a maquininha no celular
    dela so aparece aqui pelo comprovante ou pela fala, como tudo o mais.
    """
    if comprovante_dela_para_a_casa:
        return BolsoResolvido("dela", "comprovante_dela_para_a_casa")
    if comprovante_do_cliente_para_a_modelo:
        return BolsoResolvido("dela", "comprovante_do_cliente_para_a_modelo")
    if comprovante_do_cliente_para_a_casa:
        return BolsoResolvido("empresa", "comprovante_do_cliente_para_a_casa")
    if fala is not None and fala != BOLSO_NAO_DITO:
        return BolsoResolvido(fala, "fala")
    if em_especie(forma):
        return BolsoResolvido("dela", "especie")
    return BolsoResolvido(BOLSO_NAO_DITO, "nenhuma")


def confrontar_bolso(atual: Bolso, novo: BolsoResolvido) -> MudancaDoBolso:
    """A evidencia chegou DEPOIS da venda. Fixar, perguntar ou nao fazer nada (ticket 14).

    Uma regra so, e ela e sobre o que ja existe na coluna — nunca sobre qual evidencia e "melhor":

    * evidencia muda -> `nada`. Comprovante ilegivel, foto que nao era comprovante, fala que nao
      falou de bolso: nao ha o que escrever.
    * a coluna ja diz o mesmo -> `nada`. O agente nao ecoa o que ja esta certo; repetir "essa foi
      da casa" a cada comprovante e o eco que transforma o grupo em ruido.
    * a coluna diz `nao_dito` -> **`fixar`**. Nao ha nada a desmentir, entao a evidencia resolve
      direto e sai o recibo de->para. E o caso da esmagadora maioria das vendas, e e por ele que
      "evidencia que chega depois corrige o bolso e o saldo" acontece sem pergunta nenhuma.
    * a coluna ja afirma OUTRO bolso -> **`perguntar`**. Aqui a precedencia da tabela nao decide
      nada de proposito: mexer no bolso muda o SINAL do saldo (a mesma venda de R$ 1.200,00 e a
      modelo devendo 600 ou a casa devendo 600), e reescrever isso sozinho por causa de uma imagem
      e a correcao que ninguem descobre. Uma pergunta custa uma mensagem; o palpite custa um
      fechamento inteiro.
    """
    if not novo.dito:
        return MudancaDoBolso("nada", atual, atual, novo.evidencia)
    if atual == novo.bolso:
        return MudancaDoBolso("nada", atual, atual, novo.evidencia)
    if atual == BOLSO_NAO_DITO:
        return MudancaDoBolso("fixar", atual, novo.bolso, novo.evidencia)
    return MudancaDoBolso("perguntar", atual, novo.bolso, novo.evidencia)


# --- o que o agente diz no grupo -----------------------------------------------------------------

PREFIXO_DA_PERGUNTA_DO_BOLSO = "❓ Esse dinheiro caiu "
"""Assinatura da pergunta do bolso divergente. E por ela que a porta reconhece, no proprio log do
grupo, que ja perguntou — e nao repergunta a cada comprovante que chega (a metralhadora que o
dominio proibe), do mesmo jeito que `PREFIXO_DO_DESEMPATE` faz com a forma."""


def montar_recibo_do_bolso(
    mudanca: MudancaDoBolso,
    *,
    valor: Decimal | None = None,
    cliente_nome: str | None = None,
) -> str:
    """ "💰 Anotei: R$ 600,00 · Cliente Lucas — esse caiu na conta da casa (era: não dito)."

    O de->para inteiro, como o eco da correcao (`correcao.montar_eco_de_correcao`) e pelo mesmo
    motivo: sem o "era", quem le nao distingue "o agente anotou o que eu disse" de "o agente
    entendeu outra coisa". E o bolso e o campo cuja leitura errada inverte o sinal do saldo — o
    mais caro do modulo para se descobrir tarde.

    Sai so quando a conduta e `fixar`. `nada` e mudo de proposito, e `perguntar` tem fala propria.
    """
    partes = [p for p in (formatar_reais(valor) if valor is not None else None, cliente_nome) if p]
    onde = f"{' · '.join(partes)} — " if partes else ""
    return (
        f"💰 Anotei: {onde}esse caiu {ROTULO_DO_BOLSO[mudanca.para]} "
        f"(era: {ROTULO_DO_BOLSO[mudanca.de]}) — {CONVITE_DE_CORRECAO}"
    )


def montar_pergunta_do_bolso(
    mudanca: MudancaDoBolso,
    *,
    valor: Decimal | None = None,
    cliente_nome: str | None = None,
) -> str:
    """ "❓ Esse dinheiro caiu na conta da casa ou com a modelo? R$ 600,00 · Cliente Lucas — está
    anotado como com a modelo, mas o comprovante é o cliente pagando a casa."

    UMA pergunta, e nada e reescrito enquanto ela nao for respondida: o mesmo contrato da pergunta
    minima do anuncio e da pergunta do comprovante sem par — o agente diz o que viu, diz o que nao
    conseguiu concluir, e nao inventa a conclusao.

    Ela nomeia a venda (valor e cliente) porque a resposta precisa saber de qual se fala, e diz o
    que ESTA anotado porque quem responde e quem pode ter dito a coisa errada da primeira vez.
    """
    partes = [p for p in (formatar_reais(valor) if valor is not None else None, cliente_nome) if p]
    quem = f" {' · '.join(partes)}" if partes else ""
    return (
        f"{PREFIXO_DA_PERGUNTA_DO_BOLSO}{ROTULO_DO_BOLSO[mudanca.para]} ou "
        f"{ROTULO_DO_BOLSO[mudanca.de]}?{quem} — está anotado como "
        f"{ROTULO_DO_BOLSO[mudanca.de]}, e {_A_EVIDENCIA[mudanca.evidencia]}."
    )


_A_EVIDENCIA: dict[Evidencia, str] = {
    "comprovante_dela_para_a_casa": "o comprovante é ela transferindo pra casa",
    "comprovante_do_cliente_para_a_modelo": "o comprovante é o cliente pagando na chave dela",
    "comprovante_do_cliente_para_a_casa": "o comprovante é o cliente pagando a casa",
    "fala": "o que foi dito aqui diz outra coisa",
    "especie": "foi em dinheiro",
    "nenhuma": "a evidência nova diz outra coisa",
}
"""Por que o agente esta perguntando, em uma oracao. Sem isto a pergunta seria "de qual bolso?"
sem dizer o que a motivou — e quem le nao teria como saber se o agente entendeu a foto certa."""
