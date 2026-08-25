"""A Temporada e a PERSISTENCIA do razao (ADR-0045 §7, ADR-0047, ticket 02).

O `razao.py` e a conta: funcao pura, sem periodo, sem I/O. Este arquivo e a outra metade — as
entidades que o banco guarda e o **leitor** que traduz linha de tabela em `Lancamento`. Sem ele o
razao nao tem de onde vir: `apurar` sabe somar, mas nada sabe que `vendas_registradas.bolso` e o
que decide o debito, que so o comprovante de `fechamento` credita, ou que o vale mora numa tabela
propria.

**A Temporada nao congela o calculo** (ADR-0045 §7). Nao ha coluna de saldo, de fechamento nem de
snapshot, e nao e esquecimento: o saldo segue derivado, e comprovante que chega depois de a
temporada estar "fechada" recalcula. O que ela guarda como fato sao os **pagamentos feitos**
(`financeiro_repasses_pagos.temporada_id`), e a diferenca contra o saldo e o "falta pagar R$ X"
do `FechamentoDaTemporada`. Congelar criaria dois numeros concorrentes para a mesma temporada.

**O pagamento feito NAO entra no razao como lancamento**, e isso e deliberado.
`financeiro_repasses_pagos` e, desde o ADR-0011, a tabela de repasse da modelo do Modulo
Financeiro inteiro — inclusive dos Atendimentos, que sao outra fonte de receita (ADR-0043).
Soma-la dentro de `apurar` faria um repasse de atendimento abater o razao do grupo, calado. Aqui
so o recorte inequivoco entra: os pagamentos que apontam para ESTA temporada, subtraidos do saldo
no `FechamentoDaTemporada` — mesma aritmetica, sem misturar contas.

**O recorte por periodo mora no leitor, nunca no `apurar`.** `lancamentos_do_razao` filtra pelas
datas dos FATOS (a venda, a cobranca, o vale, a venda do deslocamento, a transferencia) e so
depois entrega ao razao, que continua sem saber o que e periodo. Sem `inicio`/`fim` o resultado e
o saldo corrente continuo de sempre.

Direcao das dependencias: `repo.py` importa daqui (entidades e read models), e este arquivo NAO
importa `repo.py`. A composicao "le do banco -> traduz -> `apurar`" e do `service.py`, como toda
orquestracao de leitura deste modulo (ver o cabecalho do `service.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from barra.dominio.grupo_financeiro.cobranca import CobrancaDaAgencia
from barra.dominio.grupo_financeiro.comprovante import Classificacao
from barra.dominio.grupo_financeiro.razao import (
    ZERO,
    Bolso,
    CobrancaNoRazao,
    DeslocamentoNoRazao,
    Lancamento,
    Razao,
    TransferenciaNoRazao,
    ValeNoRazao,
    VendaNoRazao,
    apurar,
    bolso_efetivo,
)

EstadoDaTemporada = Literal["aberta", "fechada", "cancelada"]
"""Marca de ROTINA, nunca trava de calculo (ADR-0045 §7): `fechada` diz que o dono mandou fechar e
o pagamento foi feito, nao que o numero parou de mudar. Nao existe reabertura porque nunca houve
congelamento."""

ParteDoDeslocamento = Literal["casa", "modelo"]
"""Quem recebeu o antecipado / quem pagou o Uber. `modelo` e a modelo DA VENDA (ou a
`recebido_por_modelo_id` dela) — a tabela nao tem coluna propria de modelo de proposito."""

TipoDeLancamentoManual = Literal["vale", "ajuste"]
SentidoDoLancamento = Literal["debito", "credito"]
OrigemDoLancamento = Literal["painel", "grupo"]

TRANSFERENCIA_PARA_A_CASA: Classificacao = "fechamento"
"""A UNICA classificacao de comprovante que credita o razao dela.

`cobranca` nao credita porque o debito que ela paga tambem nao entra: o razao le so as Cobrancas
da agencia ABERTAS (`CobrancaDaAgencia.aberta`), entao a quitada ja saiu dos dois lados e somar o
comprovante aqui creditaria a modelo por uma divida que ninguem esta mais cobrando.
`entrada_da_modelo` e dinheiro ENTRANDO na conta dela (o cliente pagando-a) — e evidencia de
bolso (ticket 21), nunca transferencia para a casa. `nao_classificado` e `ilegivel` ja sao
divergencia no extrato: dinheiro que ninguem sabe de onde e nao vira credito calado."""


# --- a Temporada ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Temporada:
    """A viagem da modelo para uma cidade por N dias — a unidade de PAGAMENTO do negocio.

    "Fecha pra mim a temporada da fulana, do dia tal ao dia tal". Entidade propria (ADR-0045 §7)
    e, deliberadamente, sem nenhum numero de dinheiro: cidade e datas sao o recorte, o saldo e
    derivado. Fechar e acao do PAINEL, nunca frase solta no grupo (§8) — move dinheiro de verdade
    e a modelo esta no grupo.
    """

    id: UUID
    modelo_id: UUID
    cidade: str
    data_inicio: date
    data_fim: date
    estado: EstadoDaTemporada = "aberta"
    observacao: str | None = None
    fechada_em: datetime | None = None

    @property
    def aberta(self) -> bool:
        return self.estado == "aberta"

    @property
    def cancelada(self) -> bool:
        """A viagem nao aconteceu. Nao ha o que apurar — nem saldo, nem pagamento."""
        return self.estado == "cancelada"

    @property
    def dias(self) -> int:
        """Quantos dias a temporada cobre, com as duas pontas dentro (7/10/14 na pratica)."""
        return (self.data_fim - self.data_inicio).days + 1

    def contem(self, dia: date) -> bool:
        return self.data_inicio <= dia <= self.data_fim


@dataclass(frozen=True)
class PagamentoDaTemporada:
    """Um pagamento da casa para a modelo (`financeiro_repasses_pagos`) marcado com a temporada.

    Reusa a tabela do ADR-0011 em vez de ganhar uma propria: duas tabelas com o mesmo significado
    ("a casa pagou a modelo") obrigariam todo somatorio a lembrar das duas, e a primeira soma que
    esquecesse uma pagaria a modelo duas vezes — ou nenhuma.
    """

    id: UUID
    modelo_id: UUID
    valor: Decimal
    data_pagamento: date
    temporada_id: UUID | None = None
    forma_pagamento: str | None = None
    observacao: str | None = None


# --- o que o banco guarda e o razao le ----------------------------------------------------------


@dataclass(frozen=True)
class VendaParaORazao:
    """A Venda registrada pelos olhos do razao: bruto, bolso, snapshot e QUEM recebeu.

    E um read model separado de `VendaRegistrada` de proposito. Aquela e a venda que o agente
    decide e escreve (valor, forma, comprovante); esta traz as tres colunas que so o razao usa
    (`bolso`, `percentual_repasse_snapshot`, `recebido_por_modelo_id`) e nenhuma que ele nao usa.
    Juntar as duas faria o extrato de tres colunas carregar campos que ele nao le e obrigaria
    todo construtor de venda do modulo a saber de bolso.
    """

    id: UUID
    modelo_id: UUID
    valor: Decimal
    """O BRUTO — a taxa de cartao fica DENTRO (ADR-0045 §3)."""
    data: date
    bolso: Bolso = "nao_dito"
    percentual_repasse_snapshot: Decimal | None = None
    recebido_por_modelo_id: UUID | None = None
    cliente_nome: str | None = None

    @property
    def recebedor(self) -> UUID:
        """De quem e o DEBITO do bruto (ADR-0045 §6). Ninguem disse -> a propria modelo da venda."""
        return self.recebido_por_modelo_id or self.modelo_id


@dataclass(frozen=True)
class TransferenciaParaORazao:
    """Um Comprovante pelos olhos do razao: valor, classificacao e uma data que SEMPRE existe.

    A data vem do banco como `COALESCE(data_transferencia, created_at em BRT)` porque o OCR pode
    nao ter lido a data do comprovante, e um credito sem data seria dinheiro que nenhum recorte de
    temporada consegue enxergar — some da conta sem ninguem procurar.
    """

    id: UUID
    valor: Decimal
    data: date
    classificacao: Classificacao


@dataclass(frozen=True)
class DeslocamentoParaORazao:
    """O deslocamento da venda com as DUAS atribuicoes (ADR-0046 §6) e a modelo ja resolvida.

    `modelo_id` aqui e a modelo EFETIVA da venda (a `recebido_por_modelo_id`, ou a da venda): a
    tabela `deslocamentos_da_venda` nao tem coluna de modelo para nao criar uma segunda verdade
    sobre de quem e o lancamento, entao o JOIN e que resolve.
    """

    id: UUID
    venda_id: UUID
    modelo_id: UUID
    data: date
    valor_antecipado: Decimal = ZERO
    valor_transporte: Decimal = ZERO
    recebedor_do_antecipado: ParteDoDeslocamento = "casa"
    pagador_do_transporte: ParteDoDeslocamento = "casa"


@dataclass(frozen=True)
class LancamentoManual:
    """Vale adiantado ou ajuste — a unica linha do ADR-0045 §1 sem fato proprio em outra tabela.

    `valor` e SEMPRE positivo e a direcao mora em `sentido`: numero negativo em coluna de dinheiro
    e a forma mais barata de somar errado calado. Vale e sempre `debito` (o banco exige).

    ⚠️ "Ficou com ela", dito sobre uma venda, NAO e vale (ADR-0047 §5): e a venda com bolso `dela`
    mais a ausencia da transferencia. Lancar tambem um vale contaria o mesmo dinheiro duas vezes.
    """

    id: UUID
    modelo_id: UUID
    tipo: TipoDeLancamentoManual
    sentido: SentidoDoLancamento
    valor: Decimal
    data: date
    origem: OrigemDoLancamento = "painel"
    descricao: str | None = None
    mensagem_id: UUID | None = None
    temporada_id: UUID | None = None


# --- o leitor: linha de tabela -> lancamento do razao --------------------------------------------


def lancamentos_do_razao(
    *,
    modelo_id: UUID,
    vendas: Sequence[VendaParaORazao] = (),
    transferencias: Sequence[TransferenciaParaORazao] = (),
    cobrancas: Sequence[CobrancaDaAgencia] = (),
    deslocamentos: Sequence[DeslocamentoParaORazao] = (),
    manuais: Sequence[LancamentoManual] = (),
    inicio: date | None = None,
    fim: date | None = None,
) -> tuple[Lancamento, ...]:
    """Traduz o que o banco guarda nos lancamentos que `razao.apurar` soma. Puro.

    `modelo_id` e DE QUEM e o razao, e nao um filtro redundante: a mesma venda entra diferente
    para duas modelos (ver `_venda_no_razao`), e sem saber de quem e a conta o leitor nao decide
    quem carrega o debito da festinha.

    `inicio`/`fim` sao o recorte da Temporada, aplicado aqui e nao no `apurar` — o razao continua
    sem periodo (ADR-0045 §7). Ambos nulos = saldo corrente continuo, como o Fechamento sempre
    foi. As duas pontas entram (a temporada "do dia 10 ao dia 20" inclui os dois dias).
    """
    lancamentos: list[Lancamento] = []
    for venda in _no_periodo(vendas, inicio, fim):
        lancado = _venda_no_razao(venda, modelo_id=modelo_id)
        if lancado is not None:
            lancamentos.append(lancado)
    lancamentos += [
        TransferenciaNoRazao(valor=t.valor, origem_id=t.id, descricao="Transferência para a casa")
        for t in _no_periodo(transferencias, inicio, fim)
        if t.classificacao == TRANSFERENCIA_PARA_A_CASA and t.valor > ZERO
    ]
    lancamentos += [
        CobrancaNoRazao(valor=c.valor, origem_id=c.id, descricao=c.descricao)
        for c in _no_periodo(cobrancas, inicio, fim)
        if c.aberta
    ]
    lancamentos += [
        DeslocamentoNoRazao(
            valor_antecipado=d.valor_antecipado,
            recebido_por_ela=d.recebedor_do_antecipado == "modelo",
            valor_transporte=d.valor_transporte,
            pago_por_ela=d.pagador_do_transporte == "modelo",
            origem_id=d.id,
            descricao="Deslocamento",
        )
        for d in _no_periodo(deslocamentos, inicio, fim)
        if d.modelo_id == modelo_id
    ]
    lancamentos += [_manual_no_razao(m) for m in _no_periodo(manuais, inicio, fim)]
    return tuple(lancamentos)


def apurar_o_razao(
    *,
    modelo_id: UUID,
    vendas: Sequence[VendaParaORazao] = (),
    transferencias: Sequence[TransferenciaParaORazao] = (),
    cobrancas: Sequence[CobrancaDaAgencia] = (),
    deslocamentos: Sequence[DeslocamentoParaORazao] = (),
    manuais: Sequence[LancamentoManual] = (),
    inicio: date | None = None,
    fim: date | None = None,
) -> Razao:
    """O saldo com sinal a partir do que foi lido do banco — leitor + `apurar`, numa chamada so.

    Existe para que nenhum chamador monte a lista de lancamentos por conta propria: dois lugares
    traduzindo tabela em lancamento sao dois lugares onde uma classe nova pode ser esquecida, e o
    sintoma disso e um saldo que fecha errado sem nenhuma linha de erro.
    """
    return apurar(
        lancamentos_do_razao(
            modelo_id=modelo_id,
            vendas=vendas,
            transferencias=transferencias,
            cobrancas=cobrancas,
            deslocamentos=deslocamentos,
            manuais=manuais,
            inicio=inicio,
            fim=fim,
        )
    )


def _venda_no_razao(venda: VendaParaORazao, *, modelo_id: UUID) -> VendaNoRazao | None:
    """A mesma venda vista por quem RECEBEU e por quem TRABALHOU (ADR-0045 §6).

    Numa festinha em que uma modelo recebe por todas, cada venda continua sendo da sua modelo (e
    e ela quem ganha a comissao), mas o debito do bruto vai inteiro para quem ficou com o
    dinheiro. Entao, para a modelo `modelo_id`:

    * venda dela, dinheiro na mao dela -> debito do bruto + credito da comissao;
    * venda dela, dinheiro com a casa **ou com outra modelo** -> so o credito da comissao;
    * venda de outra, dinheiro na mao dela -> so o debito do bruto, sem comissao (a comissao e de
      quem atendeu);
    * venda de outra que nao passou pela mao dela -> nada.

    O bolso `empresa` no caso do meio nao e um dado inventado: e como o razao DELA le "o dinheiro
    nao caiu na minha mao" — o unico efeito de `bolso` em `razao.py` e ligar ou desligar o debito.
    """
    dela = bolso_efetivo(venda.bolso) == "dela" and venda.recebedor == modelo_id
    if venda.modelo_id != modelo_id:
        if not dela:
            return None
        return VendaNoRazao(
            valor=venda.valor,
            bolso="dela",
            percentual_repasse_snapshot=None,
            origem_id=venda.id,
            descricao=venda.cliente_nome,
        )
    return VendaNoRazao(
        valor=venda.valor,
        bolso="dela" if dela else "empresa",
        percentual_repasse_snapshot=venda.percentual_repasse_snapshot,
        origem_id=venda.id,
        descricao=venda.cliente_nome,
    )


def _manual_no_razao(manual: LancamentoManual) -> Lancamento:
    """Vale -> `ValeNoRazao`. Ajuste -> a classe de mesmo SENTIDO, com o rotulo na descricao.

    ⚠️ Aproximacao consciente, e a unica deste arquivo: `razao.py` ainda nao tem
    `AjusteNoRazao` (nem `TipoDeLinha` "ajuste"), e a classe nao nasce aqui porque o razao puro e
    de outro ticket. O SALDO sai exato nos dois sentidos — que e o numero que o gestor pede —, mas
    a linha de um ajuste aparece com `tipo` "vale" (debito) ou "transferencia" (credito). A
    descricao vai prefixada com "Ajuste:" justamente para que a linha nao minta na tela.
    Alternativa descartada: ignorar o ajuste, que faria dinheiro sumir da conta em silencio — o
    erro mais caro deste modulo.
    """
    if manual.tipo == "vale":
        return ValeNoRazao(
            valor=manual.valor, origem_id=manual.id, descricao=manual.descricao or "Vale adiantado"
        )
    descricao = f"Ajuste: {manual.descricao}" if manual.descricao else "Ajuste"
    if manual.sentido == "debito":
        return ValeNoRazao(valor=manual.valor, origem_id=manual.id, descricao=descricao)
    return TransferenciaNoRazao(valor=manual.valor, origem_id=manual.id, descricao=descricao)


class _ComData(Protocol):
    """O minimo que o recorte por periodo exige de um fato: a data em que ele aconteceu."""

    @property
    def data(self) -> date: ...


def _no_periodo[T: _ComData](fatos: Sequence[T], inicio: date | None, fim: date | None) -> list[T]:
    """O recorte da Temporada, pela data do FATO. Sem pontas = tudo (saldo corrente continuo)."""
    return [
        fato
        for fato in fatos
        if (inicio is None or fato.data >= inicio) and (fim is None or fato.data <= fim)
    ]


# --- o fechamento da temporada ------------------------------------------------------------------


@dataclass(frozen=True)
class FechamentoDaTemporada:
    """O que o painel mostra quando o dono manda "fecha a temporada da fulana": saldo x ja pago.

    Nao e snapshot de nada (ADR-0045 §7): `razao` foi apurado AGORA, sobre os fatos de agora. Um
    comprovante que chegar amanha muda este mesmo objeto amanha, e a diferenca contra o que ja foi
    pago e o que aparece como "falta pagar R$ X". Nao existe reabertura porque nunca houve
    congelamento.
    """

    temporada: Temporada
    razao: Razao
    pagamentos: tuple[PagamentoDaTemporada, ...] = ()

    @property
    def pago(self) -> Decimal:
        """Quanto a casa JA pagou por esta temporada — o unico fato que a temporada guarda."""
        return sum((p.valor for p in self.pagamentos), ZERO)

    @property
    def saldo(self) -> Decimal:
        """O saldo do razao DEPOIS de descontar o que ja foi pago. Positivo = a casa ainda deve."""
        return self.razao.saldo - self.pago

    @property
    def falta_pagar(self) -> Decimal:
        """Quanto a casa ainda deve a ela (zero quando o saldo esta a favor da casa)."""
        return self.saldo if self.saldo > ZERO else ZERO

    @property
    def ela_deve(self) -> Decimal:
        """Quanto ela deve a casa — inclusive quando a casa pagou a MAIS (ADR-0045 §7)."""
        return -self.saldo if self.saldo < ZERO else ZERO
