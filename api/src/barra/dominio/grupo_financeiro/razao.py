"""O razao: a conta corrente unica da modelo com a casa (ADR-0045 §1, ADR-0047, ticket 02).

O gestor nao quer tres colunas, quer UM numero com sinal: *"a casa te deve R$ 600"* ou *"voce
deve R$ 600 pra casa"*. Este modulo e a fonte de verdade dessa conta — funcao **pura**, sem I/O,
sem banco, sem repo: recebe os lancamentos ja lidos e devolve o saldo e as linhas que o
explicam. Persistir, ler e postar no grupo e problema de quem chama.

A tabela canonica (ADR-0045 §1, com o deslocamento revisto pelo ADR-0046 §6):

| Lancamento | Debito dela | Credito dela |
|---|---|---|
| Venda cujo dinheiro caiu na mao dela (`bolso == dela`) | bruto | — |
| Comissao da venda (de QUALQUER venda, inclusive bolso `empresa`) | — | `percentual x bruto` |
| Venda paga no Pix/cartao da empresa | — | — |
| Transferencia dela -> casa (comprovante) | — | valor transferido |
| Cobranca da agencia (3RJ, site) | valor | — |
| Vale adiantado | valor | — |
| Deslocamento | `antecipado com ela - transporte pago por ela`, com sinal | |

`saldo > 0` -> a casa deve a ela; `saldo < 0` -> ela deve a casa.

Quatro decisoes moram aqui:

* **O bolso e fato da VENDA, nunca cadastro da modelo** (ADR-0047, que revoga o ADR-0045 §4). O
  razao apenas LE `bolso` (`dela | empresa | nao_dito`); quem o preenche por evidencia e a porta.
  `nao_dito` conta como `dela` (ADR-0047 §4): errar para esse lado mostra a modelo devendo,
  alguem confere e o comprovante corrige — errar para o outro esconde dinheiro na mao dela e
  ninguem procura. Dinheiro em especie e `dela` como qualquer outra venda (ADR-0045 §2): deixa-lo
  fora faria a casa "dever" o liquido inteiro de quem esta com o bruto na mao.
* **Taxa de cartao nao e descontada** (ADR-0045 §3, decisao do dono do produto): bruto = valor do
  card, e a comissao incide sobre ele. E o oposto de `financeiro/calculos.py`, que desconta a taxa
  antes do repasse (ADR-0013) — sao duas contas diferentes, do grupo e do Modulo Financeiro, e
  unifica-las aqui seria trocar a regra que o dono ditou pela do outro modulo.
* **"Ficou com ela" nao e conceito novo** (ADR-0047 §5): e a venda com bolso `dela` MAIS a
  ausencia da transferencia. O saldo ja da o numero certo sem lancamento especial. `Vale` existe
  so para o adiantamento FORA de uma venda.
* **Somar uma classe de lancamento e acrescentar uma linha, nao reescrever a funcao** (ticket 02):
  cada tipo sabe virar linha(s) em `_linhas_de`, e `apurar` so soma. A comissao do telefonista
  (ADR-0048) e o pagamento de temporada entram assim.

O que NAO mora aqui: a Temporada (que nao congela calculo nenhum — o saldo segue derivado,
ADR-0045 §7), a persistencia e a leitura. O razao nao tem periodo: quem quiser o recorte da
temporada filtra os lancamentos ANTES de chamar `apurar`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, assert_never
from uuid import UUID

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

Bolso = Literal["dela", "empresa", "nao_dito"]
"""Em que bolso o dinheiro da venda caiu. Fato da venda, nunca do cadastro (ADR-0047 §1)."""

BOLSO_PADRAO: Literal["dela"] = "dela"
"""Como o razao le `nao_dito` (ADR-0047 §4) — o certo, segundo o dono, e ela receber e enviar."""

TipoDeLinha = Literal["venda", "comissao", "transferencia", "cobranca", "vale", "deslocamento"]


def bolso_efetivo(bolso: Bolso) -> Literal["dela", "empresa"]:
    """Resolve `nao_dito` para `dela` (ADR-0047 §4). "Nao dito" e estado legitimo, nao erro."""
    return "empresa" if bolso == "empresa" else BOLSO_PADRAO


# --- os lancamentos ------------------------------------------------------------------------


@dataclass(frozen=True)
class VendaNoRazao:
    """Uma Venda registrada como o razao a le: bruto, bolso e o percentual COM SNAPSHOT.

    `percentual_repasse_snapshot` e o percentual congelado na venda (ADR-0045 §3): 50% e default
    de cadastro, nunca constante de codigo, e promover uma modelo nao pode reescrever temporada
    passada em silencio. `None` (venda antiga, sem snapshot) -> **sem credito de comissao**, a
    mesma escolha de `financeiro/calculos.py`; o saldo erra para o lado conservador (ela devendo)
    e o operador ve a linha faltando.
    """

    valor: Decimal
    """O BRUTO da venda — o valor do card, com a taxa de cartao dentro (ADR-0045 §3)."""
    bolso: Bolso = "nao_dito"
    percentual_repasse_snapshot: Decimal | None = None
    """Em pontos percentuais (`Decimal("50")` = 50%), como `modelos.percentual_repasse`."""
    origem_id: UUID | None = None
    descricao: str | None = None


@dataclass(frozen=True)
class TransferenciaNoRazao:
    """Um Comprovante de transferencia dela -> casa. Credita o valor lido no comprovante.

    O regime de repasse (mandar o valor inteiro x so a parte da casa) NAO e parametro daqui
    (ADR-0045, alternativas rejeitadas): o razao absorve qualquer valor transferido.
    """

    valor: Decimal
    origem_id: UUID | None = None
    descricao: str | None = None


@dataclass(frozen=True)
class CobrancaNoRazao:
    """Cobranca da agencia (3RJ, site): debito dela, e nunca abate venda nenhuma (ticket 08)."""

    valor: Decimal
    origem_id: UUID | None = None
    descricao: str | None = None


@dataclass(frozen=True)
class ValeNoRazao:
    """Adiantamento FORA de uma venda ("adiantei 500 pra ela"), descontado no fim (ADR-0045 §8).

    Dinheiro que a modelo ficou DENTRO de uma venda nao e vale: e bolso `dela` sem transferencia
    (ADR-0047 §5). Lancar as duas coisas debitaria o mesmo dinheiro duas vezes.
    """

    valor: Decimal
    origem_id: UUID | None = None
    descricao: str | None = None


@dataclass(frozen=True)
class DeslocamentoNoRazao:
    """O Uber da modelo em DOIS valores (ADR-0046 §6, ticket 12), nunca um so.

    `valor_antecipado` e o que o cliente mandou (receita); `valor_transporte` e o que o Uber
    custou (custo). Com um numero so, "cliente mandou 100 e o Uber custou 60" seria indistinguivel
    de "ninguem mandou nada e o Uber custou 15" — e o segundo caso e **credito** dela.

    Efeito no razao = `antecipado recebido por ela - transporte pago por ela`; positivo = debito.
    Recebido e pago pela casa -> zero, nao toca o razao dela. **Nunca entra na base de comissao**:
    e reembolso de custo, nao servico (ADR-0045 §5).
    """

    valor_antecipado: Decimal = ZERO
    recebido_por_ela: bool = False
    valor_transporte: Decimal = ZERO
    pago_por_ela: bool = False
    origem_id: UUID | None = None
    descricao: str | None = None


Lancamento = (
    VendaNoRazao | TransferenciaNoRazao | CobrancaNoRazao | ValeNoRazao | DeslocamentoNoRazao
)


# --- o resultado ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinhaDoRazao:
    """Uma linha do extrato: de onde veio, quanto debitou e quanto creditou.

    Debito e credito ficam em campos SEPARADOS (e nao um valor com sinal) porque o extrato mostra
    as duas colunas, e porque a venda de bolso `dela` rende as DUAS linhas — o debito do bruto e o
    credito da comissao — que juntas dizem por que o saldo deu o que deu.
    """

    tipo: TipoDeLinha
    debito: Decimal = ZERO
    credito: Decimal = ZERO
    origem_id: UUID | None = None
    descricao: str | None = None

    @property
    def efeito(self) -> Decimal:
        """Quanto esta linha move o saldo: positivo = a casa devendo mais a ela."""
        return self.credito - self.debito


@dataclass(frozen=True)
class Razao:
    """O saldo com sinal e as linhas que o explicam."""

    linhas: tuple[LinhaDoRazao, ...] = ()
    debitos: Decimal = ZERO
    creditos: Decimal = ZERO
    saldo: Decimal = ZERO
    """`creditos - debitos`. Positivo = a casa deve a ela; negativo = ela deve a casa."""

    @property
    def a_casa_deve(self) -> Decimal:
        """Quanto a casa deve a ela (zero quando o saldo esta a favor da casa)."""
        return self.saldo if self.saldo > ZERO else ZERO

    @property
    def ela_deve(self) -> Decimal:
        """Quanto ela deve a casa (zero quando o saldo esta a favor dela)."""
        return -self.saldo if self.saldo < ZERO else ZERO


def apurar(lancamentos: Iterable[Lancamento]) -> Razao:
    """O saldo com sinal da modelo. Puro: nao le banco, nao filtra periodo, nao escreve nada.

    Os lancamentos ja chegam do recorte que interessa (uma modelo, uma temporada ou a vida
    inteira) — o razao nao tem periodo proprio, porque periodo que "fecha" e exatamente o que o
    dominio proibe (ADR-0045 §7).
    """
    linhas = tuple(linha for lancamento in lancamentos for linha in _linhas_de(lancamento))
    debitos = sum((linha.debito for linha in linhas), ZERO)
    creditos = sum((linha.credito for linha in linhas), ZERO)
    return Razao(
        linhas=linhas,
        debitos=debitos,
        creditos=creditos,
        saldo=creditos - debitos,
    )


def _linhas_de(lancamento: Lancamento) -> tuple[LinhaDoRazao, ...]:
    """O despacho: cada classe de lancamento vira linha(s). Classe nova = mais um ramo aqui."""
    if isinstance(lancamento, VendaNoRazao):
        return _linhas_da_venda(lancamento)
    if isinstance(lancamento, TransferenciaNoRazao):
        return (
            LinhaDoRazao(
                tipo="transferencia",
                credito=_centavos(lancamento.valor),
                origem_id=lancamento.origem_id,
                descricao=lancamento.descricao,
            ),
        )
    if isinstance(lancamento, CobrancaNoRazao):
        return (
            LinhaDoRazao(
                tipo="cobranca",
                debito=_centavos(lancamento.valor),
                origem_id=lancamento.origem_id,
                descricao=lancamento.descricao,
            ),
        )
    if isinstance(lancamento, ValeNoRazao):
        return (
            LinhaDoRazao(
                tipo="vale",
                debito=_centavos(lancamento.valor),
                origem_id=lancamento.origem_id,
                descricao=lancamento.descricao,
            ),
        )
    if isinstance(lancamento, DeslocamentoNoRazao):
        return _linhas_do_deslocamento(lancamento)
    assert_never(lancamento)


def _linhas_da_venda(venda: VendaNoRazao) -> tuple[LinhaDoRazao, ...]:
    """Ate duas linhas: o debito do bruto (so se o bolso e dela) e o credito da comissao (sempre).

    A comissao existe mesmo quando a venda caiu no Pix da empresa — e por isso que "Pix da
    empresa, sem transferencia" fecha em +600 e nao em zero (ADR-0045 §1).
    """
    bruto = _centavos(venda.valor)
    linhas: list[LinhaDoRazao] = []
    if bolso_efetivo(venda.bolso) == "dela":
        linhas.append(
            LinhaDoRazao(
                tipo="venda",
                debito=bruto,
                origem_id=venda.origem_id,
                descricao=venda.descricao,
            )
        )
    comissao = _comissao(bruto, venda.percentual_repasse_snapshot)
    if comissao != ZERO:
        linhas.append(
            LinhaDoRazao(
                tipo="comissao",
                credito=comissao,
                origem_id=venda.origem_id,
                descricao=venda.descricao,
            )
        )
    return tuple(linhas)


def _linhas_do_deslocamento(deslocamento: DeslocamentoNoRazao) -> tuple[LinhaDoRazao, ...]:
    """Uma conta, nao uma tabela de quatro casos (ticket 12).

    `efeito = antecipado com ela - transporte pago por ela`; positivo = debito dela. O que a casa
    recebeu e o que a casa pagou simplesmente nao entram — o razao e dela.
    """
    recebido = _centavos(deslocamento.valor_antecipado) if deslocamento.recebido_por_ela else ZERO
    pago = _centavos(deslocamento.valor_transporte) if deslocamento.pago_por_ela else ZERO
    efeito = recebido - pago
    if efeito == ZERO:
        return ()
    return (
        LinhaDoRazao(
            tipo="deslocamento",
            debito=efeito if efeito > ZERO else ZERO,
            credito=-efeito if efeito < ZERO else ZERO,
            origem_id=deslocamento.origem_id,
            descricao=deslocamento.descricao,
        ),
    )


def _comissao(bruto: Decimal, percentual: Decimal | None) -> Decimal:
    """`percentual x bruto`, em centavos. Sem snapshot -> zero (nunca 50% chutado no codigo)."""
    if percentual is None:
        return ZERO
    return _centavos(bruto * percentual / Decimal("100"))


def _centavos(valor: Decimal) -> Decimal:
    """Dinheiro com duas casas, arredondado como o banco arredonda."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
