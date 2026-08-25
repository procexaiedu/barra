"""A conferencia das DUAS fontes: o caixa dos telefonistas x a Venda registrada (ticket 17).

O gestor pediu a segunda fonte com estas palavras: *"legal a gente fazer uma conferencia dos dois,
ate mesmo para saber se as informacoes estao batendo"*. O **caixa dos telefonistas** e o grupo onde
ele confere o dia com todas as modelos juntas — e o mesmo atendimento que ja foi anunciado no grupo
individual reaparece la, dito de novo, por outra pessoa.

Duas coisas moldam este arquivo inteiro:

* **A IA entra em LEITURA** (spec 0006, "Out of Scope: escrita no grupo do caixa dos
  telefonistas"). Nada nasce do caixa: nem venda, nem ficha, nem cobranca, nem pendencia. A porta
  unica ja fecha essa porta por roteamento (`_processar_no_grupo_sem_dona` devolve
  `grupo_em_leitura` antes de qualquer leitura de dinheiro) e este modulo nao tem uma unica funcao
  que escreva. O que ele produz e **derivado na hora**, como o Fechamento — nao ha tabela de
  "linha do caixa" de proposito: materializar o que o caixa diz criaria uma terceira fonte para
  divergir das outras duas.
* **A mesma venda nao pode ser contada duas vezes.** E o risco que o ticket nomeia, e ele nao se
  evita somando com cuidado: se evita nunca somando. `total_no_caixa` e `total_no_sistema` sao
  DUAS colunas e ficam duas — somar as duas e o bug que este modulo existe para tornar impossivel
  de escrever sem querer. O par que bate vira `conferidas`, nao receita.

**O que este modulo NAO sabe** e a grafia do caixa. O export real dos grupos individuais esta no
projeto; o do caixa, nao. Entao a leitura aqui e feita pelo MESMO leitor do anuncio do grupo
(`anuncio.py` + `rateio.planejar` + o resolver closed-world de `nomes.py`), e linha que nao casa
com essa gramatica volta como `nao_lidas` — nunca como divergencia. Errar para o lado de "nao deu
para conferir" e recuperavel; errar para o lado de "falta uma venda de R$ 700" manda o gestor
procurar dinheiro que existe.

A modelo vem SEMPRE do texto (`Perfil ...`), nunca do grupo: no caixa estao todas, e `dona_do_grupo`
e `None` pelo mesmo motivo que no Grupo de fichas (ADR-0046 §2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import (
    AnuncioDeVenda,
    extrair_anuncio,
    parece_anuncio_de_venda,
)
from barra.dominio.grupo_financeiro.modelos import MensagemRegistrada, VendaRegistrada
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes
from barra.dominio.grupo_financeiro.rateio import planejar
from barra.dominio.grupo_financeiro.voz import e_fala_do_agente

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

ExtratorDeAnuncio = Callable[[str], AnuncioDeVenda]
"""Quem le o texto do caixa. Mesmo formato do `extrair` da porta unica, declarado AQUI porque
`dominio/` nunca importa a camada de agente (dominio/CLAUDE.md, "Direcao das dependencias").

Injetavel pelo mesmo motivo de la: o dia em que a grafia do caixa escapar do determinista, o LLM
entra por este parametro sem que nada mais neste arquivo mude."""


@dataclass(frozen=True)
class LinhaDoCaixa:
    """Um atendimento COMO O CAIXA o conta — a segunda fonte, lida e nunca gravada.

    Tem `mensagem_id` e nao `venda_id` de proposito: esta linha nao e uma venda e nunca vira uma.
    O que ela enderecca e a mensagem do caixa que a produziu, para o operador que vir a divergencia
    no painel poder ir ler o que estava escrito la.
    """

    modelo_id: UUID
    valor: Decimal
    data: date
    mensagem_id: UUID
    cliente_nome: str | None = None


@dataclass(frozen=True)
class LeituraDoCaixa:
    """O que deu para ler do caixa numa janela — e o que nao deu.

    `nao_lidas` nao e erro nem divergencia: e a mensagem que PARECE anuncio (passou a triagem) e
    mesmo assim nao rendeu linha — nome que o cadastro nao conhece, valor fora de linha propria,
    festinha sem o "cada uma". Ela vai a vista junto da conferencia porque muda o que o numero
    significa: dez divergencias com trinta linhas nao lidas nao sao dez erros, sao trinta leituras
    que faltaram.
    """

    linhas: tuple[LinhaDoCaixa, ...] = ()
    nao_lidas: tuple[UUID, ...] = ()


TipoDaDivergenciaDoCaixa = Literal["so_no_caixa", "so_no_sistema"]
"""De que lado o atendimento ficou sozinho.

* `so_no_caixa` — o caixa conta um atendimento que o sistema nao registrou. Em geral e o anuncio
  que nunca chegou ao grupo individual (ou chegou e nao virou venda: nome desconhecido, valor
  faltando). E o lado que esconde receita.
* `so_no_sistema` — a Venda registrada existe e o caixa nao a menciona. Em geral e a conferencia
  do gestor que ficou incompleta; as vezes e uma venda registrada em duplicidade no individual.

Nenhum dos dois trava nada: os dois sao flag de painel (o ticket manda "sem travar nada"), e
nenhum deles muda uma linha de venda. Quem corrige e o humano, na fonte que estiver errada.
"""


@dataclass(frozen=True)
class DivergenciaDoCaixa:
    """Um atendimento que aparece numa fonte e nao na outra. Sempre com valor, data e modelo.

    Sem o valor a vista a linha nao deixa ninguem fazer nada — a mesma regra da `Divergencia` do
    Fechamento (`fechamento.py`), e o motivo de ela ter tipo proprio: aquela compara **venda x
    comprovante** dentro do sistema; esta compara **sistema x caixa**, dois eixos que nunca devem
    ser lidos como a mesma lista.
    """

    tipo: TipoDaDivergenciaDoCaixa
    modelo_id: UUID
    valor: Decimal
    data: date
    cliente_nome: str | None = None
    venda_id: UUID | None = None
    """Preenchido em `so_no_sistema`: a Venda registrada que o caixa nao mencionou."""
    mensagem_id: UUID | None = None
    """Preenchido em `so_no_caixa`: a mensagem do caixa que conta o atendimento que falta."""


@dataclass(frozen=True)
class ConferenciaDoCaixa:
    """As duas fontes lado a lado numa janela — leitura pura, nada materializado.

    **As duas colunas nunca se somam.** `total_no_caixa` e `total_no_sistema` sao o MESMO dinheiro
    contado por duas bocas; a soma delas nao e receita nenhuma, e e exatamente a conta errada que o
    ticket 17 existe para impedir. Receita continua saindo de uma fonte so (`vendas_registradas`,
    ADR-0043).
    """

    de: date
    ate: date
    conferidas: int = 0
    """Pares que bateram: um atendimento contado nas duas fontes. Conta como UM."""
    linhas_do_caixa: int = 0
    vendas_no_sistema: int = 0
    total_no_caixa: Decimal = ZERO
    total_no_sistema: Decimal = ZERO
    divergencias: tuple[DivergenciaDoCaixa, ...] = field(default_factory=tuple)
    nao_lidas: tuple[UUID, ...] = field(default_factory=tuple)

    @property
    def bate(self) -> bool | None:
        """A flag do painel. `None` = **nao da para afirmar**, e nunca "bateu".

        Sem nenhuma linha lida do caixa nao houve segunda fonte nesta janela — dizer `True` ali
        seria o mesmo tipo de mentira que um saldo zero para quem ninguem apurou: o painel
        mostraria "conferido" para um dia em que ninguem conferiu nada.
        """
        if self.linhas_do_caixa == 0:
            return None
        return not self.divergencias

    @property
    def diferenca(self) -> Decimal:
        """`caixa - sistema` — o tamanho do desencontro, com sinal. Positivo = o caixa conta mais.

        E leitura de apoio, nao a flag: duas divergencias de mesmo valor em lados opostos se
        cancelam aqui e continuam sendo duas linhas para o humano olhar.
        """
        return self.total_no_caixa - self.total_no_sistema


def ler_caixa(
    mensagens: Iterable[MensagemRegistrada],
    *,
    cadastro: CadastroDeNomes,
    extrair: ExtratorDeAnuncio | None = None,
) -> LeituraDoCaixa:
    """As mensagens do caixa viradas em linhas — pelo MESMO leitor do grupo individual.

    Reusar `parece_anuncio_de_venda` + `extrair_anuncio` + `rateio.planejar` nao e economia: e a
    unica forma de a conferencia comparar como o registro registra. Um segundo leitor "so para o
    caixa" divergiria do primeiro justamente nos casos de borda (festinha, apelido novo, valor com
    duracao colada), e a divergencia relatada seria a dos dois PARSERS, nao a das duas fontes.

    Tres cortes, nesta ordem:

    1. **eco** — `de_mim` e a fala do proprio agente. No caixa ele nunca fala, entao isto e tranca
       defensiva pelo mesmo motivo de `voz.py`: `fromMe` se inverte quando quem entrega o evento e
       a instancia da modelo, e sem o corte o recibo do agente (que tem gramatica de anuncio)
       viraria linha da segunda fonte;
    2. **triagem** — o que nao parece anuncio e conversa de telefonista ("subiu?", "ela chegou") e
       sai sem virar `nao_lida`: nao ha nada ali para ler;
    3. **plano** — `dona_do_grupo=None` SEMPRE. No caixa estao todas as modelos; herdar a modelo do
       grupo daria o atendimento de qualquer uma para a dona que o caixa nao tem.
    """
    ler = extrair or extrair_anuncio
    linhas: list[LinhaDoCaixa] = []
    nao_lidas: list[UUID] = []
    for msg in mensagens:
        texto = msg.texto or ""
        if msg.de_mim or e_fala_do_agente(texto):
            continue
        if not parece_anuncio_de_venda(texto):
            continue
        anuncio = ler(texto)
        plano = planejar(anuncio, cadastro=cadastro, dona_do_grupo=None)
        if not plano.linhas:
            nao_lidas.append(msg.id)
            continue
        linhas.extend(
            LinhaDoCaixa(
                modelo_id=linha.modelo_id,
                valor=_centavos(linha.valor),
                data=msg.dia(),
                mensagem_id=msg.id,
                cliente_nome=anuncio.cliente,
            )
            for linha in plano.linhas
        )
    return LeituraDoCaixa(linhas=tuple(linhas), nao_lidas=tuple(nao_lidas))


def conferir(
    *,
    linhas_do_caixa: Sequence[LinhaDoCaixa],
    vendas: Sequence[VendaRegistrada],
    de: date,
    ate: date,
    nao_lidas: Sequence[UUID] = (),
) -> ConferenciaDoCaixa:
    """As duas fontes casadas atendimento a atendimento. Puro, e nunca levanta.

    **O casamento e em dois passos, e o segundo e o que salva a flag de virar ruido.** Primeiro
    par exato por `(modelo, dia, valor)`; depois, para o que sobrou, par por `(modelo, valor)` em
    qualquer dia da janela. O caixa e escrito no fim do dia ou na manha seguinte, e a data que a
    Venda registrada carrega e a do anuncio no grupo individual: exigir o mesmo dia pintaria de
    vermelho toda conferencia feita depois da meia-noite — e uma flag que acende sempre e uma flag
    que ninguem le.

    Casou = `conferidas`, nunca receita: o par e a MESMA venda dita duas vezes.

    **Sem linha lida do caixa nao ha divergencia nenhuma.** Um dia em que o gestor nao escreveu no
    caixa devolveria uma divergencia `so_no_sistema` por venda do dia — dezenas de alarmes sobre
    uma fonte que simplesmente nao falou. Nesse caso a conferencia sai com `bate is None`, que e o
    "nao da para afirmar" que o painel mostra em vez da flag.
    """
    conferencia = ConferenciaDoCaixa(
        de=de,
        ate=ate,
        linhas_do_caixa=len(linhas_do_caixa),
        vendas_no_sistema=len(vendas),
        total_no_caixa=_soma(linha.valor for linha in linhas_do_caixa),
        total_no_sistema=_soma(venda.valor for venda in vendas),
        nao_lidas=tuple(nao_lidas),
    )
    if not linhas_do_caixa:
        return conferencia

    sobra_no_sistema = list(vendas)
    sobra_no_caixa: list[LinhaDoCaixa] = []
    conferidas = 0
    for linha in linhas_do_caixa:
        par = _casar(linha, sobra_no_sistema)
        if par is None:
            sobra_no_caixa.append(linha)
            continue
        sobra_no_sistema.remove(par)
        conferidas += 1

    divergencias = [
        DivergenciaDoCaixa(
            tipo="so_no_caixa",
            modelo_id=linha.modelo_id,
            valor=linha.valor,
            data=linha.data,
            cliente_nome=linha.cliente_nome,
            mensagem_id=linha.mensagem_id,
        )
        for linha in sobra_no_caixa
    ] + [
        DivergenciaDoCaixa(
            tipo="so_no_sistema",
            modelo_id=venda.modelo_id,
            valor=_centavos(venda.valor),
            data=venda.data,
            cliente_nome=venda.cliente_nome,
            venda_id=venda.id,
        )
        for venda in sobra_no_sistema
    ]
    return ConferenciaDoCaixa(
        de=conferencia.de,
        ate=conferencia.ate,
        conferidas=conferidas,
        linhas_do_caixa=conferencia.linhas_do_caixa,
        vendas_no_sistema=conferencia.vendas_no_sistema,
        total_no_caixa=conferencia.total_no_caixa,
        total_no_sistema=conferencia.total_no_sistema,
        divergencias=tuple(divergencias),
        nao_lidas=conferencia.nao_lidas,
    )


def _casar(linha: LinhaDoCaixa, candidatas: Sequence[VendaRegistrada]) -> VendaRegistrada | None:
    """A venda que esta linha do caixa descreve — mesmo dia primeiro, qualquer dia depois.

    Cliente NAO entra no casamento: no caixa ele e abreviado ou nem aparece, e casar por nome
    faria "Gabriel" e "gabriel do 2706" divergirem sozinhos. Ele viaja na divergencia so para o
    humano reconhecer do que se trata.
    """
    mesmos = [
        venda
        for venda in candidatas
        if venda.modelo_id == linha.modelo_id and _centavos(venda.valor) == linha.valor
    ]
    if not mesmos:
        return None
    for venda in mesmos:
        if venda.data == linha.data:
            return venda
    return min(mesmos, key=lambda venda: abs((venda.data - linha.data).days))


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO)


def _soma(valores: Iterable[Decimal]) -> Decimal:
    total = ZERO
    for valor in valores:
        total += _centavos(valor)
    return total
