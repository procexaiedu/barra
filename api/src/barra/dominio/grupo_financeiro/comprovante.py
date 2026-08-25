"""Comprovante de transferencia de fechamento (spec 0005, ticket 07).

A modelo posta a foto do Pix no Grupo financeiro e, hoje, um gestor confere no olho. Aqui esse
gesto vira conta: o comprovante e lido por OCR, **classificado** e abatido das vendas pix abertas
dela, da mais antiga para a mais nova.

Tres decisoes moram neste modulo, e as tres sao sobre o que o agente faz quando NAO tem certeza:

* **O abate e FIFO e por venda inteira.** Saldo corrente continuo, sem periodos estanques
  (docs/dominio, "Fechamento"): o comprovante entra na fila das vendas pix abertas e vai baixando
  enquanto o dinheiro cobre a proxima. Ele NAO pula uma venda cara para alcancar uma barata mais
  adiante — pular seria escolher qual atendimento foi pago, que e um palpite sobre dinheiro. O
  que sobra fica no comprovante (credito da modelo no saldo), sem picar venda em pedacos.
* **Comprovante que nao casa nao some.** Ele e a prova de que dinheiro saiu da modelo: fica
  retido como `nao_classificado`, com UMA pergunta no grupo — retido e visivel vale mais do que
  classificado errado. O R$ 385,80 de 13/08 deixou de cair aqui no ticket 08: ele casa com uma
  **Cobranca da agencia** aberta e a quita (`cobranca.py`), sem tocar em venda nenhuma. Continua
  caindo aqui o que nao casa com nada — e o que casaria com as DUAS coisas.
* **Chave desconhecida sinaliza UMA vez, e nunca trava.** Destino fora do cadastro da casa e erro
  de digitacao ou golpe, e o valor de pegar isso esta em avisar cedo — nao em segurar o abate.
  Mesma filosofia do Pix duvidoso do agente de venda: sempre avanca. Desde o ticket 05 o aviso sai
  so na PRIMEIRA aparicao daquele destino: o mesmo ⚠️ toda semana pela mesma divida pessoal dela
  treinou o gestor a ignorar o alarme. A repeticao nao some, muda de canal — vira a fila de
  sugestoes do painel (`sugestoes_de_cadastro`), onde tem contagem, periodo e um botao.

* **Cartao entra pelo MESMO mecanismo, por outro campo.** O print da maquininha nao tem chave
  Pix, mas tem o nome do estabelecimento — e a pergunta que ele responde e a mesma ("de quem e
  este destino?"), com a mesma resposta (`PapelResolvido`) e as mesmas classes de entrada. O que
  ele nunca faz e abater venda em pix ou quitar cobranca: no cartao quem paga e o cliente, e
  nenhum centavo saiu da conta da modelo. E por isso que o cadastro nao precisou de
  `maquininha_da_modelo` (que o ADR-0047 revogou) nem de um campo novo na ficha.

* **O "Pix duvidoso" tem UM vocabulario, e ele vale nos dois caminhos** (ticket 07). O Pix de
  deslocamento (`workers/pix.py`) ja media plausibilidade, valor e destino com palavras proprias;
  aqui as mesmas duvidas nao tinham nome, e a plausibilidade nao era nem lida. `MotivoDeSuspeita`,
  `PRECEDENCIA_DA_SUSPEITA` e `marcar_suspeita` moram neste modulo pela mesma razao que
  `normalizar_chave` mora: sao dominio puro que os DOIS consomem, e duas copias de um vocabulario
  sao duas leituras do mesmo comprovante esperando divergir.

Venda em **dinheiro nao existe** para este modulo: ela fica em especie com a modelo e nunca entra
na fila de abate (cobrar comprovante de dinheiro vivo e pedir o que nao existe).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.bolso import BolsoResolvido, resolver_bolso
from barra.dominio.grupo_financeiro.modelos import VendaRegistrada
from barra.dominio.grupo_financeiro.recibo import formatar_reais

Classificacao = Literal[
    "fechamento",
    "cobranca",
    "entrada_da_modelo",
    "cliente_para_a_casa",
    "nao_classificado",
    "ilegivel",
]
"""O que o agente concluiu sobre a imagem. `ilegivel` e o unico que pede algo de volta (reenvio);
`nao_classificado` faz UMA pergunta e retem; `fechamento` abateu venda; `cobranca` quitou uma
Cobranca da agencia (ticket 08) — abate a cobranca, NUNCA as vendas; `entrada_da_modelo` e o
comprovante que aponta para o lado CONTRARIO (o cliente pagando a modelo) e por isso nao abate
nada; `cliente_para_a_casa` e a irma dela (o cliente pagando a CASA) e nao abate nem quita — ela
so fixa o **bolso** da venda em `empresa` (ADR-0047 §2, ticket 14).

As quatro classes que nao sao `nao_classificado`/`ilegivel` se distinguem pelas MESMAS duas
perguntas, sempre juntas — **quem pagou** e **quem recebeu**:

| pagou | recebeu | classe | efeito |
|---|---|---|---|
| a modelo | a casa | `fechamento` / `cobranca` | abate venda pix (FIFO) ou quita cobranca |
| o cliente | a modelo | `entrada_da_modelo` | nada: prova que a venda foi paga |
| o cliente | a casa | `cliente_para_a_casa` | nada: fixa o bolso da venda em `empresa` |

Uma condicao so nunca basta: num fechamento legitimo quem paga tambem e ela, e o destino sozinho
faria toda transferencia dela virar a classe errada."""

# Espaco, pontuacao e sinal saem: "+55 71 99984 0879" e "+5571999840879" sao a MESMA chave, e o
# OCR le a grafia da tela do banco, que nunca e a grafia de quem cadastrou.
#
# Esta e a UNICA normalizacao de chave Pix do sistema desde o ticket 03: `workers/pix.py::
# _chaves_compativeis` tinha uma copia do regex e agora delega para ca. Duas copias da mesma
# comparacao sao duas politicas de aceitacao esperando divergir no primeiro caractere novo.
RUIDO_DA_CHAVE = r"[\s.\-+()/]"
"""A classe de caracteres que NAO distingue chave, como texto — porque o SQL tambem precisa dela.

`repo.py` normaliza chave dentro do Postgres (`regexp_replace`) para agrupar comprovante por
destino sem trazer a tabela inteira para a memoria. Passar ESTE literal como parametro da query,
em vez de reescrever o regex la, e o que impede as duas normalizacoes de divergirem no primeiro
caractere novo — a mesma armadilha que o ticket 03 fechou entre o dominio e `workers/pix.py`. A
sintaxe de classe e comum a `re` e ao regex do Postgres (verificado no `barra_test`)."""

_RUIDO_DA_CHAVE = re.compile(RUIDO_DA_CHAVE)


def normalizar_chave(chave: str) -> str:
    """A forma de comparacao de chave Pix: sem ruido de digitacao, em minusculo."""
    return _RUIDO_DA_CHAVE.sub("", chave).lower()


@dataclass(frozen=True)
class LeituraDoComprovante:
    """O que o OCR viu na imagem — antes de qualquer decisao sobre o que ela significa.

    `e_comprovante=False` e o caso comum do grupo real: ali circulam foto do site, print do
    perfil, sticker. Sem esse campo o agente pediria reenvio de toda imagem que nao fosse recibo,
    virando o ruido que o dominio proibe.

    `legivel=False` distingue "isto e um comprovante e nao consegui ler" de "isto nao e um
    comprovante" — o primeiro pede reenvio, o segundo pede silencio.

    ⚠️ `e_comprovante` e `e_de_cartao` sao EXCLUSIVOS, e a exclusividade e uma trava de dinheiro,
    nao arrumacao (ticket 06). `e_comprovante` significa uma coisa so — **transferencia** (Pix ou
    TED): dinheiro que saiu de uma conta e entrou noutra, que e o unico documento capaz de abater
    venda em pix ou quitar Cobranca da agencia. O print da maquininha nao e isso: ele prova que o
    CLIENTE pagou no cartao, e nenhum centavo saiu da conta da modelo. Se ele chegasse com
    `e_comprovante=True`, o abate FIFO daria por comprovada uma transferencia que nunca existiu —
    e a venda sairia da fila de cobranca pelo motivo errado. Por isso `como_leitura` (o leitor)
    forca `e_comprovante=False` quando o modelo marca os dois.
    """

    e_comprovante: bool
    legivel: bool = False
    valor: Decimal | None = None
    data: date | None = None
    pagador: str | None = None
    chave_destino: str | None = None
    titular_destino: str | None = None
    e_de_cartao: bool = False
    """O print e de maquininha/cartao (debito, credito, aproximacao) — nao e transferencia."""
    plausivel: bool = True
    """A imagem parece um documento REAL — ou e montagem, print de outro app, recibo manuscrito?

    O sinal que o Pix de deslocamento ja extraia (`ExtracaoPix.plausibilidade_visual`) e que este
    lado nao tinha (ticket 07). Sao coisas diferentes e as duas cabem no mesmo comprovante:
    `legivel` e sobre a NOSSA capacidade de ler ("cortado, desfocado") e pede reenvio; `plausivel`
    e sobre a FE do documento ("montagem") e nao pede nada — pedir reenvio de uma montagem so
    ensina a fazer uma melhor.

    ⚠️ Nasce `True` de proposito: ausencia de sinal nao e acusacao. Enquanto o leitor
    (`agente_financeiro/comprovante.py`) nao preencher o campo, toda leitura continua plausivel e
    NADA muda de comportamento — a alternativa (default `False`) transformaria o silencio do OCR
    em suspeita de fraude sobre todo comprovante do grupo."""
    motivo_se_implausivel: str | None = None
    """O motivo curto que o OCR deu quando `plausivel=False` — a prosa que o painel mostra.

    Nao vira fala no grupo: ver `deve_falar_no_grupo`."""
    estabelecimento: str | None = None
    """O nome do estabelecimento impresso no comprovante do cartao — "PagBank", "InfinitePay".

    E o campo que faz o cartao entrar pelo MESMO mecanismo da chave Pix (ADR-0049 §6): a pergunta
    e a mesma ("de quem e este destino?"), so o campo que a responde muda. Sem ele o cartao
    exigiria um campo novo na ficha — que a ata proibe — ou um cadastro de confianca por modelo,
    que o ADR-0047 revogou."""


@dataclass(frozen=True)
class ComprovanteDoGrupo:
    """Um Comprovante de transferencia ja persistido, com a classificacao que ele recebeu."""

    id: UUID
    grupo_id: UUID
    mensagem_id: UUID
    classificacao: Classificacao
    valor: Decimal | None = None
    data_transferencia: date | None = None
    pagador: str | None = None
    chave_destino: str | None = None
    titular_destino: str | None = None
    chave_conhecida: bool = False
    valor_abatido: Decimal = Decimal("0.00")
    estabelecimento: str | None = None
    """O nome do estabelecimento, quando a imagem era um print de maquininha (ticket 06).

    Mora na MESMA tabela do comprovante de transferencia, e nao numa tabela propria, porque o
    cartao nao e outro fluxo: ele responde as mesmas duas perguntas (quem pagou x quem recebeu),
    cai nas mesmas classes (`entrada_da_modelo` / `cliente_para_a_casa`) e precisa do mesmo dedup
    por foto. O que muda e o campo que identifica quem recebeu — `estabelecimento` no lugar de
    `chave_destino`."""

    @property
    def sobra(self) -> Decimal:
        """O que este comprovante pagou alem das vendas que ele fechou — credito da modelo."""
        if self.valor is None:
            return Decimal("0.00")
        return self.valor - self.valor_abatido


@dataclass(frozen=True)
class PlanoDeAbate:
    """Quais vendas este comprovante fecha, e o que fica faltando depois dele."""

    abatidas: tuple[VendaRegistrada, ...] = ()
    valor_abatido: Decimal = Decimal("0.00")
    sobra: Decimal = Decimal("0.00")
    """Dinheiro do comprovante que nao coube em nenhuma venda inteira (segue como credito)."""
    a_comprovar: Decimal = Decimal("0.00")
    """Soma das vendas pix que continuam abertas DEPOIS deste abate — a coluna que falta fechar."""


def planejar_abate(valor: Decimal | None, abertas: Sequence[VendaRegistrada]) -> PlanoDeAbate:
    """FIFO: baixa as vendas pix abertas mais antigas enquanto o comprovante as cobrir.

    `abertas` ja vem na ordem da fila (mais antiga primeiro) e **so com venda pix** — dinheiro
    nunca entra na expectativa de abate.

    Para de propósito na primeira venda que nao cabe, em vez de procurar adiante uma que caiba: o
    R$ 1.200,00 de 12/08 fecha as duas de R$ 600,00 porque elas SAO as duas mais antigas; se a
    proxima fosse de R$ 700,00, escolher a de R$ 600,00 tres semanas depois seria o agente
    decidindo qual atendimento o cliente pagou.
    """
    if valor is None or valor <= 0:
        return PlanoDeAbate(a_comprovar=sum((v.valor for v in abertas), Decimal("0.00")))

    restante = valor
    abatidas: list[VendaRegistrada] = []
    for venda in abertas:
        if venda.valor > restante:
            break
        abatidas.append(venda)
        restante -= venda.valor

    abatido = valor - restante
    faltando = sum(
        (v.valor for v in abertas if v not in abatidas),
        Decimal("0.00"),
    )
    return PlanoDeAbate(
        abatidas=tuple(abatidas), valor_abatido=abatido, sobra=restante, a_comprovar=faltando
    )


# --- de quem e esta chave? (ADR-0049 §1, ticket 03) ---------------------------------------------

PapelCadastrado = Literal["casa", "modelo", "telefonista", "terceiro"]
"""Os quatro papeis que o CADASTRO grava (`barravips.papel_da_chave_enum`, ticket 02)."""

PapelDaChave = Literal["casa", "modelo", "telefonista", "terceiro", "desconhecida"]
"""A RESPOSTA a pergunta "de quem e esta chave" — os quatro papeis cadastraveis mais o quinto,
que nao e gravavel: `desconhecida` e a **ausencia de linha**, nao um valor.

O booleano que isto substitui (`chave_e_conhecida`) era a raiz da confusao operacional: "nao esta
na lista da casa" engolia num unico aviso a chave da PROPRIA modelo (informacao que resolve o
bolso da venda, ADR-0047) e a chave de um terceiro qualquer (ruido). O gestor aprendia a ignorar
o ⚠️ porque ele disparava igual nos dois."""


@dataclass(frozen=True)
class ChaveComDono:
    """Uma linha do registro de chaves, reduzida ao que a pergunta do papel precisa.

    E o formato que `repo.registro_de_chaves` entrega e que `papel_da_chave` consome — de
    proposito uma estrutura burra, sem banco: a regra de "de quem e esta chave" fica testavel sem
    Postgres, e os DOIS caminhos que hoje duplicam a comparacao (grupo financeiro e Pix de
    deslocamento) passam a chamar a mesma funcao.

    `titular` e o nome impresso no extrato e nao se confunde com `dono_nome`: o dono de uma chave
    com `papel='modelo'` e a modelo (nome artistico, o que o painel mostra), enquanto o titular e
    o nome civil da conta, que e com o que o OCR compara.

    `ativo=False` NAO some do registro: a chave desligada continua tendo dono e continua
    explicando comprovante antigo. Quem pergunta "este destino esta autorizado HOJE?" — e nao "de
    quem e?" — filtra por `ativo` do lado de fora (é o que `workers/pix.py` faz).
    """

    chave: str
    papel: PapelCadastrado
    dono_id: UUID | None = None
    dono_nome: str | None = None
    titular: str | None = None
    ativo: bool = True


@dataclass(frozen=True)
class PapelResolvido:
    """De quem e a chave que apareceu neste comprovante — papel e, quando o papel pede, QUEM."""

    papel: PapelDaChave
    dono_id: UUID | None = None
    dono_nome: str | None = None

    @property
    def e_conhecida(self) -> bool:
        """Alguem do cadastro responde por esta chave? (o antigo `chave_e_conhecida`, ampliado)"""
        return self.papel != "desconhecida"

    @property
    def e_da_casa(self) -> bool:
        """O dinheiro caiu numa conta da CASA — o unico papel que fecha venda em pix."""
        return self.papel == "casa"

    def e_da_modelo(self, modelo_id: UUID | None) -> bool:
        """A chave e desta modelo especifica? (a de OUTRA modelo nao serve de resposta aqui)"""
        return self.papel == "modelo" and modelo_id is not None and self.dono_id == modelo_id


DESCONHECIDA = PapelResolvido(papel="desconhecida")
"""O closed-world em uma constante: sem linha no cadastro, sem dono."""


def papel_da_chave(chave: str | None, registro: Sequence[ChaveComDono]) -> PapelResolvido:
    """Closed-world: o que nao esta no cadastro nao e de ninguem — inclusive a chave ausente.

    Comprovante em que o OCR nao achou a chave de destino volta `desconhecida` de proposito. O
    contrario (assumir a casa quando nao se leu o destino) esconderia exatamente o comprovante que
    mais merece um olho humano — e, depois do ticket 04, fixaria o bolso da venda em `empresa` sem
    evidencia nenhuma.

    A comparacao passa por `normalizar_chave` dos DOIS lados, sempre: o OCR le a grafia da tela do
    banco ("+5571999840879") e o cadastro guarda a grafia de quem digitou ("+55 71 99984-0879").

    Registro vazio devolve `desconhecida` para tudo — e o estado de producao em 20/08/2026, e nada
    quebra por causa dele.
    """
    alvo = normalizar_chave(chave) if chave else ""
    if not alvo:
        # Ausente, vazia ou so pontuacao — a normalizacao pode zerar a string, e "" nunca pode
        # casar com uma linha do cadastro que tambem tenha zerado.
        return DESCONHECIDA
    for cadastrada in registro:
        if normalizar_chave(cadastrada.chave) == alvo:
            return PapelResolvido(
                papel=cadastrada.papel,
                dono_id=cadastrada.dono_id,
                dono_nome=cadastrada.dono_nome,
            )
    return DESCONHECIDA


# --- e o cartao? o mesmo mecanismo, pelo nome do estabelecimento (ADR-0049 §6, ticket 06) -------

_RUIDO_DO_ESTABELECIMENTO = re.compile(r"[^a-z0-9]+")


def normalizar_estabelecimento(nome: str) -> str:
    """A forma de comparacao de nome de estabelecimento: sem acento, sem pontuacao, em minusculo.

    **Nao e `normalizar_chave`, e nao pode ser.** Chave Pix e identificador digitado (telefone,
    CPF, e-mail) e perde so o ruido de digitacao; nome de estabelecimento e texto lido de um cupom,
    com acento, espaco duplo e o asterisco que a operadora imprime. Normalizar os dois pela mesma
    regra e guarda-los no mesmo registro faria uma chave Pix `pagbank@...` responder pela
    maquininha — e a maquininha responder por um destino de Pix. Sao duas perguntas com a mesma
    forma e conteudos que nunca se encontram, entao sao dois registros.

    A comparacao e EXATA sobre esta forma — nao ha prefixo, nao ha "contem". E possivel porque o
    cadastro nasce do proprio texto que o OCR leu: a fila de sugestoes (`sugestoes_de_cadastro`)
    mostra ao gestor a grafia lida, e e ela que ele classifica. Casar por prefixo faria
    "PAGBANK * ELITE" e "PAGBANK * OUTRA COISA" virarem a mesma maquininha, que e um palpite sobre
    de quem e o dinheiro.
    """
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _RUIDO_DO_ESTABELECIMENTO.sub("", sem_acento.lower())


@dataclass(frozen=True)
class EstabelecimentoComDono:
    """Uma linha do registro de estabelecimentos — irma de `ChaveComDono`, e de proposito.

    O cartao nao tem chave, mas tem o nome que a maquininha imprime, e a pergunta que ele responde
    e a mesma: **de quem e este destino?** Por isso o tipo de RESPOSTA e o mesmo (`PapelResolvido`)
    e os papeis sao os mesmos (`PapelCadastrado`) — quem le "de quem foi esse dinheiro" nao devia
    precisar de dois vocabularios so porque a evidencia veio noutro campo.

    Na pratica so `casa` e `modelo` aparecem (ADR-0049 §6): a maquininha ou e da operacao ou esta
    no celular dela (*"a mina tem a maquina no celular dela, que e aquele PagBank/InfinitePay"*).
    Os outros dois papeis continuam validos porque restringi-los custaria uma migration no dia em
    que um telefonista tiver maquininha — e valem a mesma coisa que valem na chave: `terceiro`
    existe para PARAR de alarmar, nao para atribuir dinheiro.

    `ativo=False` NAO some do registro, pelo mesmo motivo da chave: a maquininha devolvida mes
    passado continua explicando o print de tres semanas atras.
    """

    nome: str
    papel: PapelCadastrado
    dono_id: UUID | None = None
    dono_nome: str | None = None
    ativo: bool = True


def papel_do_estabelecimento(
    nome: str | None, registro: Sequence[EstabelecimentoComDono]
) -> PapelResolvido:
    """De quem e a maquininha que imprimiu este print? Closed-world, como `papel_da_chave`.

    Duas funcoes e nao uma porque a NORMALIZACAO e o registro sao outros (ver
    `normalizar_estabelecimento`) — mas a politica e literalmente a mesma, e e ela que nao pode
    divergir: sem linha no cadastro a resposta e `desconhecida`, nunca "da casa por omissao", e
    nome ausente/vazio tambem e `desconhecida`. Assumir a casa aqui fixaria o bolso da venda em
    `empresa` sem evidencia nenhuma, que e o erro que ninguem descobre olhando o grupo.
    """
    alvo = normalizar_estabelecimento(nome) if nome else ""
    if not alvo:
        return DESCONHECIDA
    for cadastrado in registro:
        if normalizar_estabelecimento(cadastrado.nome) == alvo:
            return PapelResolvido(
                papel=cadastrado.papel,
                dono_id=cadastrado.dono_id,
                dono_nome=cadastrado.dono_nome,
            )
    return DESCONHECIDA


def classificacao_do_cartao(papel: PapelResolvido, *, modelo_id: UUID | None) -> Classificacao:
    """Em que classe cai um print de maquininha — e sao as classes que JA existem.

    Quem pagou um cartao e sempre o CLIENTE (a modelo nao passa cartao para a casa), entao das
    quatro classes so as duas de entrada podem sair daqui, e a maquininha decide qual:

    | maquininha | classe | efeito |
    |---|---|---|
    | dela | `entrada_da_modelo` | o dinheiro caiu com ela — bolso `dela` |
    | da casa | `cliente_para_a_casa` | o dinheiro caiu na conta da casa — bolso `empresa` |
    | desconhecida / de terceiro | `nao_classificado` | retido, com a pergunta |

    Nenhuma delas abate venda em pix nem quita Cobranca da agencia — e por isso o cartao entra
    "pelo mesmo mecanismo" sem risco: as duas classes de entrada ja existem exatamente para o
    documento que prova pagamento sem mover dinheiro entre a modelo e a casa.
    """
    if papel.e_da_modelo(modelo_id):
        return "entrada_da_modelo"
    if papel.e_da_casa:
        return "cliente_para_a_casa"
    return "nao_classificado"


def bolso_do_cartao(papel: PapelResolvido, *, modelo_id: UUID | None) -> BolsoResolvido:
    """O print da maquininha resolvendo o bolso pela MESMA tabela do Pix (ADR-0047 §2).

    Nao ha regra nova aqui, e e esse o ponto do ticket: a evidencia do cartao entra na tabela de
    precedencia como as outras — `resolver_bolso` e a mesma funcao, as `Evidencia` sao as mesmas
    duas (`comprovante_do_cliente_para_a_modelo` / `comprovante_do_cliente_para_a_casa`), e o
    razao nao aprende palavra nenhuma. Foi assim que o ADR-0047 §6 pediu ("as tres formas de
    cartao seguem a mesma tabela e nao tem linha propria") e e o que dispensa
    `maquininha_da_modelo` no cadastro.

    Maquininha desconhecida devolve `nao_dito`, que e estado legitimo (ADR-0047 §3): entra na
    cobranca da manha e sai de la quando alguem classificar a maquininha na fila de sugestoes.
    """
    return resolver_bolso(
        comprovante_do_cliente_para_a_modelo=papel.e_da_modelo(modelo_id),
        comprovante_do_cliente_para_a_casa=papel.e_da_casa,
    )


# --- o vocabulario do comprovante duvidoso (ADR-0049 §5, ticket 07) -----------------------------

MotivoDeSuspeita = Literal[
    "imagem_repetida",
    "sem_leitura",
    "imagem_implausivel",
    "imagem_ilegivel",
    "valor_abaixo_do_esperado",
    "destino_desconhecido",
    "titular_divergente",
]
"""Por que ESTE comprovante ficou duvidoso — e sao as mesmas sete palavras nos DOIS caminhos.

O dono levantou a mesma coisa duas vezes na reuniao de 20/08 (*"pra ver se o cliente talvez nao
mandou o Pix zoando"*, *"a gente tem uma forma de identificar se o Pix foi duvidoso"*). A
capacidade existia pela METADE e so de um lado: `workers/pix.py` ja extraia
`plausibilidade_visual` do OCR e nomeava a duvida com um vocabulario proprio ("plausibilidade",
"legibilidade", "valor", "chave", "titular", "midia", "vision"), enquanto o comprovante do Grupo
financeiro tinha caminho proprio, dedup por foto proprio e nenhum sinal de plausibilidade. E o
painel tinha um TERCEIRO conjunto de slugs (`valor_divergente`, `ocr_falhou`) que o backend nunca
escreveu — a linha do motivo na lista de Pix renderizava vazia por causa disso.

| motivo | de onde vem | quem emite hoje |
|---|---|---|
| `imagem_repetida` | a MESMA foto ja foi contada (sha256 do conteudo) | Grupo financeiro |
| `sem_leitura` | falha NOSSA: midia nao subiu, provider fora, resposta truncada | os dois |
| `imagem_implausivel` | o OCR marcou montagem / print de outro app / recibo manuscrito | os dois |
| `imagem_ilegivel` | e comprovante e nao deu para ler (cortado, desfocado, valor ilegivel) | os dois |
| `valor_abaixo_do_esperado` | pagou menos do que a operacao esperava daquele documento | deslocamento |
| `destino_desconhecido` | o destino nao e de ninguem da operacao (`papel_da_chave`) | os dois |
| `titular_divergente` | o nome no destino nao bate com nenhum titular conhecido | deslocamento |

Mora aqui, e nao num modulo de HTTP, pela mesma razao que `normalizar_chave` mora aqui desde o
ticket 03: e dominio puro que os dois caminhos consomem, e a borda (`dominio/pix/schemas.py`) o
importa para traduzi-lo em opcao de rejeicao. O contrario — dominio importando o `schemas` de
outro contexto — e o que `dominio/CLAUDE.md` proibe.

⚠️ **Suspeita NUNCA trava o registro.** Nos dois caminhos o comprovante e gravado, o atendimento
avanca (01 §6.1) e o abate FIFO acontece; o que a suspeita produz e uma flag no painel e, quando
couber, UMA pergunta. Um vocabulario de suspeita que bloqueia vira paralisia da operacao — e o
comprovante que vai para a chave errada e, justamente, dinheiro que ja saiu."""

PRECEDENCIA_DA_SUSPEITA: tuple[MotivoDeSuspeita, ...] = (
    "imagem_repetida",
    "sem_leitura",
    "imagem_implausivel",
    "imagem_ilegivel",
    "valor_abaixo_do_esperado",
    "destino_desconhecido",
    "titular_divergente",
)
"""Qual duvida SAI quando varias disparam — da mais grave para a mais fraca.

Nao e uma ordem nova: e a que `workers/pix.py` ja executava como cadeia `if/elif`
(plausibilidade -> legibilidade -> valor -> chave -> titular), com os dois motivos do Grupo
financeiro encaixados por cima. Escrever a ordem uma vez e o que impede os dois caminhos de
discordarem sobre qual e a duvida principal do mesmo documento.

O raciocinio, de cima para baixo:

* **`imagem_repetida`** ganha de tudo porque nao ha fato novo nenhum: a foto ja foi contada, e
  qualquer outra duvida sobre ela ja foi levantada na primeira vez.
* **`sem_leitura`** vem antes das duvidas de conteudo porque nao HA conteudo: nada foi lido.
* **`imagem_implausivel`** ganha das duvidas de campo porque, se a imagem e montagem, o valor e a
  chave dela sao ficcao — reportar "valor a menor" de um comprovante falso e discutir o numero
  errado.
* **`valor_abaixo_do_esperado`** vem antes de identidade: dinheiro faltando e mais duro do que
  nome que nao bate.
* **`titular_divergente`** e a mais fraca — o OCR erra nome com frequencia, e o titular sozinho
  nunca foi motivo para desconfiar de um comprovante que bate em tudo o mais."""

MOTIVOS_DE_SUSPEITA: frozenset[str] = frozenset(PRECEDENCIA_DA_SUSPEITA)
"""Os mesmos valores como conjunto de runtime — e o que `ler_suspeita` usa para reconhecer um
prefixo. Derivado de `PRECEDENCIA_DA_SUSPEITA` de proposito: uma lista escrita a mao aqui seria a
quarta copia do vocabulario, e ela ficaria para tras no dia em que um motivo entrasse."""

SEPARADOR_DA_SUSPEITA = ": "
"""O que separa o motivo do detalhe em `comprovantes_pix.motivo_em_revisao`."""


def marcar_suspeita(motivo: MotivoDeSuspeita, detalhe: str) -> str:
    """ "valor_abaixo_do_esperado: valor extraido 80.00 < esperado R$100" — slug + prosa.

    `comprovantes_pix.motivo_em_revisao` e uma coluna de texto livre, e ate aqui ela guardava SO
    prosa. Prosa e o que o revisor precisa ler (o numero, a chave como foi lida) e e exatamente o
    que nenhum filtro consegue agrupar: o painel tipava aquele campo como um slug fechado que o
    backend jamais escreveu, e por isso a linha do motivo na lista de Pix renderizava VAZIA —
    `motivoRevisaoLabel[prosa]` e `undefined`.

    Carimbar o motivo canonico na frente resolve os dois lados sem migration e sem perder nada: o
    slug e agrupavel e o detalhe continua inteiro depois dele. O separador e `": "` porque a prosa
    de hoje ja usa `":"` internamente ("vision inconclusivo: finish_reason=..."), e so o PRIMEIRO
    e limite — `ler_suspeita` corta uma vez so.
    """
    return f"{motivo}{SEPARADOR_DA_SUSPEITA}{detalhe}"


def ler_suspeita(motivo_em_revisao: str | None) -> tuple[MotivoDeSuspeita | None, str]:
    """Desfaz `marcar_suspeita`: `(motivo, detalhe)`. Prosa antiga volta `(None, a prosa inteira)`.

    Fail-open de proposito. Toda linha gravada antes do ticket 07 tem prosa crua, e um parser que
    exigisse o prefixo transformaria o historico inteiro em "motivo desconhecido". Quem le mostra
    o detalhe do mesmo jeito; o que falta e so a etiqueta.
    """
    if not motivo_em_revisao:
        return None, ""
    cabeca, separador, resto = motivo_em_revisao.partition(SEPARADOR_DA_SUSPEITA)
    if separador and cabeca in MOTIVOS_DE_SUSPEITA:
        motivo: MotivoDeSuspeita = cabeca  # type: ignore[assignment]
        return motivo, resto
    return None, motivo_em_revisao


def suspeita_mais_grave(motivos: Iterable[MotivoDeSuspeita | None]) -> MotivoDeSuspeita | None:
    """Das duvidas que dispararam, a que o comprovante ostenta — pela `PRECEDENCIA_DA_SUSPEITA`.

    `None` quando nenhuma disparou (o comprovante limpo). Existe para o caminho que calcula os
    sinais TODOS antes de escolher — o Grupo financeiro, que ja leu a imagem inteira quando
    pergunta. O Pix de deslocamento continua parando no primeiro sinal, e nao por estilo: checar a
    chave custa uma ida ao banco que o comprovante a menor nao precisa pagar.
    """
    presentes = {m for m in motivos if m is not None}
    if not presentes:
        return None
    return next(motivo for motivo in PRECEDENCIA_DA_SUSPEITA if motivo in presentes)


# --- o Pix duvidoso, com as MESMAS palavras dos dois lados (ADR-0049 §5, ticket 07) -------------


def suspeita_do_comprovante(
    leitura: LeituraDoComprovante | None,
    *,
    destino: PapelResolvido = DESCONHECIDA,
    repetida: bool = False,
) -> MotivoDeSuspeita | None:
    """Por que este comprovante do grupo e duvidoso — no vocabulario do Pix de deslocamento.

    Uma funcao e nao uma cadeia `if/elif` no meio da porta porque o outro caminho ja tinha a
    cadeia, com outras palavras: `workers/pix.py` chamava a mesma duvida de "plausibilidade",
    "legibilidade", "valor", "chave", e aqui ela nao tinha nome nenhum. Duas leituras da mesma
    coisa com dois vocabularios e o defeito que o ADR-0049 conserta na chave, repetido na
    suspeita — e o gestor que recebe os dois avisos nao tem como cruzar um com o outro.

    A ordem de desempate NAO e desta funcao: e `PRECEDENCIA_DA_SUSPEITA`, a mesma dos dois lados
    (`suspeita_mais_grave`). Aqui os sinais sao calculados TODOS antes de escolher, ao contrario
    do Pix de deslocamento, que para no primeiro — la conferir a chave custa uma ida ao banco que
    o comprovante a menor nao precisa pagar; aqui a imagem inteira ja foi lida quando se pergunta.

    Os argumentos, e o que cada um significa:

    * **`leitura=None`** e falha NOSSA (provider fora, resposta truncada) -> `sem_leitura`. Nao e
      duvida sobre a modelo, e por isso ela nao vira fala no grupo (`deve_falar_no_grupo`).
    * **`destino`** e a resposta de `papel_da_chave` OU de `papel_do_estabelecimento` — o cartao
      entra por aqui sem uma linha propria, porque a pergunta e a mesma. `terceiro` NAO e suspeito:
      o papel existe justamente para o cadastro poder dizer "conheco esta chave e ela nao e da
      operacao" e parar de alarmar (ADR-0049 §5).

      ⚠️ Quando outra fonte ja explica o destino — a chave que o proprio GRUPO ensinou
      (`dados_cadastrais`, ticket 12) —, quem chama passa
      `PapelResolvido(papel="modelo", dono_id=<a modelo do grupo>)`. O registro aprende devagar e o
      grupo aprende de graca; as duas fontes somam, e esta funcao ve uma so resposta.
    * **`repetida`** e a MESMA foto de novo, que o dedup por `conteudo_hash` ja pega. Ela ganha de
      tudo: nao ha fato novo, e qualquer duvida sobre aquela imagem ja foi levantada na primeira
      vez.

    ⚠️ `valor_abaixo_do_esperado` nao sai daqui, e nunca vai sair: um comprovante de fechamento
    nao tem valor esperado (ele abate FIFO o que cobrir, e o que sobra vira credito dela).
    Inventar uma expectativa seria o agente decidindo qual atendimento a modelo quis pagar.

    ⚠️ **Nada disto trava coisa alguma.** A funcao e pura, nao escreve, e quem a chama ja gravou
    (ou vai gravar) o comprovante do mesmo jeito: o abate FIFO acontece, a Cobranca e quitada, o
    atendimento avanca. O que a suspeita produz e uma flag e, quando `deve_falar_no_grupo`, UMA
    linha.
    """
    if repetida:
        return "imagem_repetida"
    if leitura is None:
        return "sem_leitura"
    sinais: list[MotivoDeSuspeita | None] = [
        "imagem_implausivel" if not leitura.plausivel else None,
        "imagem_ilegivel"
        if not leitura.legivel or leitura.valor is None or leitura.valor <= 0
        else None,
        "destino_desconhecido" if not destino.e_conhecida else None,
    ]
    return suspeita_mais_grave(sinais)


_CALA_NO_GRUPO: frozenset[MotivoDeSuspeita] = frozenset({"imagem_implausivel", "sem_leitura"})
"""As duas duvidas que o agente NAO leva ao grupo — e as razoes sao opostas.

* **`imagem_implausivel`** e uma acusacao de fraude, e quem postou a foto e a modelo (ou a
  gestora dela). "Esse comprovante parece montagem" dito num grupo de trabalho e uma acusacao
  publica feita por um robo a partir de um palpite de OCR — e, se ela estiver certa, avisar so
  ensina a fazer uma montagem melhor. A duvida vale muito, mas vale para o painel, onde tem um
  humano, o historico e o poder de decidir.
* **`sem_leitura`** e falha NOSSA (provider fora, chave que sumiu no redeploy). Pedir reenvio
  enquanto o OpenRouter esta fora e um loop que ela paga com paciencia e a casa nao ganha nada —
  e a mesma regra que a porta ja aplica hoje ao comprovante que nao deu para ler por nossa causa.

O resto FALA, e ja falava antes deste ticket: `imagem_ilegivel` pede reenvio (`PEDIDO_DE_REENVIO`),
`imagem_repetida` diz que nao contou de novo, e `destino_desconhecido` sai uma vez so por destino
(`deve_avisar_destino_fora_da_casa`, ticket 05) — esta funcao NAO substitui aquela decisao, ela
vem antes."""


def deve_falar_no_grupo(motivo: MotivoDeSuspeita | None) -> bool:
    """A suspeita vira linha no WhatsApp, ou fica so no painel?

    Suspeita nunca trava (o criterio do ticket), mas "nao travar" nao quer dizer "falar sempre":
    o alarme que sai toda vez e o alarme que o gestor aprende a ignorar — foi por isso que o
    ticket 05 calou a repeticao do ⚠️ de chave. Aqui a pergunta e outra e anterior: ha duvidas que
    nao devem sair NENHUMA vez naquele canal.
    """
    return motivo is not None and motivo not in _CALA_NO_GRUPO


# --- chave desconhecida RECORRENTE: sugestao, nao alarme (ADR-0049 §5, ticket 05) ---------------


@dataclass(frozen=True)
class QuemMandou:
    """A modelo em cujo grupo o comprovante apareceu — o "sempre recebendo da Yasmin" da sugestao."""

    modelo_id: UUID
    nome: str


@dataclass(frozen=True)
class ChaveVista:
    """O que os comprovantes ja mostraram sobre UMA chave de destino — contagem crua, sem juizo.

    E o unico dado novo que este ticket precisa, e ele ja existia: `comprovantes_do_grupo` guarda
    `chave_destino` desde sempre. Nao ha tabela de sugestoes, nao ha coluna `visto_em`, e isso e
    uma decisao — uma fila materializada teria que ser invalidada quando o gestor cadastra a chave,
    e "a sugestao sumiu na hora" (criterio do ticket) sairia de graca so se a fila for DERIVADA.
    Enquanto for uma consulta, cadastrar e o proprio ato de tirar a linha da fila.
    """

    chave: str
    """A grafia mais recente que o OCR leu — e ela que o gestor compara com a tela do banco.

    Desde o ticket 06 este campo carrega os DOIS destinos que um comprovante pode ter: a chave Pix
    ou o nome do estabelecimento do print de cartao. A fila e a mesma de proposito — para o gestor
    e uma pergunta so ("de quem e isso?"), e duplicar o tipo duplicaria a tela, a ordenacao e a
    frase. Quem monta a lista e que sabe de qual registro ela veio (`sugestoes_de_cadastro` ou
    `sugestoes_de_estabelecimento`)."""
    vezes: int
    primeiro_em: date
    ultimo_em: date
    valor_total: Decimal = Decimal("0.00")
    titulares: tuple[str, ...] = ()
    """Os nomes que o OCR leu no destino: mais de um costuma ser variacao de leitura, nao troca
    de titular."""
    quem_mandou: tuple[QuemMandou, ...] = ()

    @property
    def dias(self) -> int:
        """O tamanho da janela em que ela apareceu — 0 quando tudo caiu no mesmo dia."""
        return max((self.ultimo_em - self.primeiro_em).days, 0)

    @property
    def de_uma_modelo_so(self) -> QuemMandou | None:
        """A modelo unica, quando ha uma so: e o palpite de dono que o painel pre-seleciona."""
        return self.quem_mandou[0] if len(self.quem_mandou) == 1 else None


MINIMO_PARA_SUGERIR = 2
"""A partir do SEGUNDO aparecimento (ticket 05). A primeira vez ja teve o alarme no grupo; a
sugestao existe para a chave que voltou — o alarme repetido e que treinava o gestor a ignorar."""


def sugestoes_de_cadastro(
    vistas: Sequence[ChaveVista],
    registro: Sequence[ChaveComDono],
    *,
    minimo: int = MINIMO_PARA_SUGERIR,
) -> tuple[ChaveVista, ...]:
    """As chaves que o cadastro ainda nao explica e que ja voltaram — a fila do painel.

    **Sugestao nunca vira cadastro sozinha** (criterio do ticket): esta funcao nao escreve nada e
    nao existe caminho que a transforme em linha de `chaves_pix_conhecidas`. Ela produz uma
    PERGUNTA; quem responde e o gestor, pelo mesmo `POST /chaves-pix` de sempre.

    O filtro por `registro` usa `papel_da_chave`, e nao uma comparacao propria, pelo motivo de
    sempre: duas comparacoes de chave sao duas politicas esperando divergir. Chave INATIVA conta
    como explicada — ela tem dono, so nao recebe mais; sugerir cadastro de novo seria pedir ao
    gestor que classificasse duas vezes a mesma conta.

    Ordem: a que mais apareceu primeiro, desempatada pela mais recente — a fila e curta e o que
    o gestor quer ver em cima e o que mais custa deixar sem nome.
    """
    return _fila_de_sugestoes(
        vistas, explica=lambda alvo: papel_da_chave(alvo, registro).e_conhecida, minimo=minimo
    )


def sugestoes_de_estabelecimento(
    vistas: Sequence[ChaveVista],
    registro: Sequence[EstabelecimentoComDono],
    *,
    minimo: int = MINIMO_PARA_SUGERIR,
) -> tuple[ChaveVista, ...]:
    """A MESMA fila, para a maquininha que o cadastro ainda nao explica (ticket 06).

    O dono ja disse que **nao sabe** de quem e cada maquininha (*"a maquininha esta na conta dela
    ou na da empresa? — nao sei te responder"*). Perguntar isso de uma vez, no cadastro, e pedir um
    dado que nao existe; a fila pergunta uma maquininha por vez, quando ela ja apareceu duas vezes
    e portanto e a que mais custa deixar sem nome. E o mesmo aprendizado-pelo-uso do ticket 05,
    pelo mesmo caminho e com a mesma frase — o gestor nao precisa saber que existem dois registros.
    """
    return _fila_de_sugestoes(
        vistas,
        explica=lambda alvo: papel_do_estabelecimento(alvo, registro).e_conhecida,
        minimo=minimo,
    )


def _fila_de_sugestoes(
    vistas: Sequence[ChaveVista], *, explica: Callable[[str], bool], minimo: int
) -> tuple[ChaveVista, ...]:
    """O corte e a ordem da fila, uma vez so para os dois registros.

    Separado porque a unica diferenca entre a fila da chave e a da maquininha e QUEM responde "o
    cadastro ja explica isto" — o resto (o minimo de aparicoes, a ordem, o desempate) e politica de
    fila, e duas copias dela divergiriam na primeira vez que alguem mexesse numa so.
    """
    fila = [vista for vista in vistas if vista.vezes >= minimo and not explica(vista.chave)]
    fila.sort(key=lambda v: (-v.vezes, -v.ultimo_em.toordinal(), v.chave))
    return tuple(fila)


def deve_avisar_destino_fora_da_casa(*, da_modelo: bool, vezes_antes: int) -> bool:
    """O ⚠️ do grupo sai? So na PRIMEIRA vez — depois disso ele e a fila do painel (ADR-0049 §5).

    O aviso de chave fora da lista disparava a cada comprovante, e por isso o gestor aprendeu a
    ignora-lo. A ata mostra os casos legitimos que viravam ruido semana apos semana: a modelo
    pagando uma divida pessoal, um fornecedor, a chave nova dela depois de trocar de banco. Nenhum
    deles e novidade na segunda vez — e um alarme que nao e novidade nao e alarme.

    O que sobrevive e o caso que merece: **destino desconhecido aparecendo pela primeira vez**.
    Da segunda em diante a informacao nao some, ela muda de canal — vai para a fila de sugestoes,
    onde tem contagem, periodo e um botao que resolve a duvida de vez.

    `da_modelo=True` e a excecao e continua falando SEMPRE: aquela linha nao e alarme, e a
    atribuicao do dinheiro ("esse Pix caiu na conta dela"), e ela vale por comprovante — e o que
    diz ao grupo que aquela venda nao foi para o caixa da casa.
    """
    if da_modelo:
        return True
    return vezes_antes == 0


def _periodo_em_palavras(dias: int) -> str:
    """ "no mesmo dia" / "em 5 dias" / "em 3 semanas" / "em 2 meses" — a janela da recorrencia.

    Arredondar e proposital: o gestor decide de quem e a chave, nao audita o calendario. "em 21
    dias" faz ele contar; "em 3 semanas" ele ja entendeu.
    """
    if dias <= 0:
        return "no mesmo dia"
    if dias < 14:
        return f"em {dias} dia{'s' if dias > 1 else ''}"
    if dias < 60:
        semanas = round(dias / 7)
        return f"em {semanas} semana{'s' if semanas > 1 else ''}"
    meses = round(dias / 30)
    return f"em {meses} {'meses' if meses > 1 else 'mês'}"


def montar_pergunta_da_sugestao(vista: ChaveVista) -> str:
    """ "Apareceu 4 vezes em 3 semanas, sempre recebendo da Yasmin — de quem é?"

    A frase do ADR-0049 §5, montada com o que a contagem sabe. Ela e uma PERGUNTA e nao um
    veredito porque o sistema honestamente nao sabe: chave fora do cadastro pode ser a conta nova
    da modelo, o fornecedor ou o golpe, e as tres tem a mesma cara num extrato.

    O nome da modelo entra quando ha uma so — "sempre recebendo da Yasmin" e o que transforma a
    pergunta em algo que o gestor responde de cabeca. Com varias, contar quantas ja e o suficiente:
    a mesma chave desconhecida recebendo de tres modelos e outra conversa.
    """
    quantas = f"{vista.vezes} vez{'es' if vista.vezes > 1 else ''}"
    partes = [f"Apareceu {quantas} {_periodo_em_palavras(vista.dias)}"]
    uma = vista.de_uma_modelo_so
    if uma is not None:
        partes.append(f"sempre recebendo da {uma.nome}")
    elif vista.quem_mandou:
        partes.append(f"recebendo de {len(vista.quem_mandou)} modelos")
    return f"{', '.join(partes)} — de quem é?"


def e_do_cliente_para_a_casa(
    leitura: LeituraDoComprovante,
    *,
    pagador_e_a_modelo: bool,
    destino_e_da_casa: bool,
) -> bool:
    """O cliente pagou a CASA direto — o dinheiro nunca passou pela mao da modelo (ticket 14).

    Irma de `_e_entrada_da_modelo` e reconhecida pelo mesmo criterio de duas pernas (quem pagou e
    quem recebeu), so que com o destino invertido: la o destino e ela, aqui e a casa.

    O efeito e o oposto do que o agente faz hoje com um comprovante para a casa. Ele NAO abate
    venda em pix (nao e transferencia dela: ela nao transferiu nada) e NAO quita Cobranca da
    agencia — ele fixa o **bolso** da venda em `empresa` (ADR-0047 §2). Se o bolso ficasse como
    `dela` (inclusive pelo default de "nao dito"), o saldo dela estaria torto em silencio: o razao
    debitaria dela um bruto que ela nunca teve na mao.

    **Exige o pagador POSITIVAMENTE lido**, e e o detalhe que impede uma regressao cara. O OCR
    falha no nome do pagador com frequencia; sem esta linha, "pagador desconhecido + destino da
    casa" — que e como metade dos fechamentos legitimos chega — deixaria de abater FIFO e a fila
    de comprovante nunca mais andaria. Nome ilegivel volta ao comportamento de hoje, que e o lado
    seguro: o comprovante ainda vale pelo VALOR, que e o que abate venda.
    """
    if not destino_e_da_casa:
        return False
    if pagador_e_a_modelo:
        return False
    return bool(leitura.pagador)


# --- o que o agente diz no grupo ----------------------------------------------------------------

PEDIDO_DE_REENVIO = (
    "📷 Não consegui ler esse comprovante — dá pra reenviar a imagem inteira, por favor?"
)
"""Unica coisa que o agente PEDE de volta. So sai quando a imagem parece um comprovante e nao deu
para ler: pedir reenvio de uma foto qualquer do grupo seria cobrar o que ninguem prometeu."""


def montar_confirmacao_de_abate(plano: PlanoDeAbate, *, valor: Decimal, data: date | None) -> str:
    """ "✅ Comprovante conferido: R$ 1.200,00 · 12/08 — baixei 2 vendas em pix. Falta comprovar: …"

    Curta, porque quem postou ja sabe o que mandou: o que ela nao sabe e o que AINDA falta. O
    "falta comprovar" e o Fechamento (ticket 09) aparecendo uma linha por vez, no momento em que
    a conta muda — e o unico numero do modulo que o gestor hoje faz de cabeca.
    """
    partes = [formatar_reais(valor)]
    if data is not None:
        partes.append(f"{data:%d/%m}")
    quantas = len(plano.abatidas)
    baixa = f"baixei {quantas} venda{'s' if quantas > 1 else ''} em pix"
    if plano.sobra > 0:
        baixa += f" (sobrou {formatar_reais(plano.sobra)})"
    return (
        f"✅ Comprovante conferido: {' · '.join(partes)} — {baixa}. "
        f"Falta comprovar: {formatar_reais(plano.a_comprovar)}."
    )


def montar_aviso_de_comprovante_repetido(anterior: ComprovanteDoGrupo) -> str:
    """ "♻️ Esse comprovante eu já tinha conferido: R$ 700,00 · 20/08 — não contei de novo."

    A mesma foto chegou outra vez (reenvio, encaminhamento). Falar e obrigatorio: quem reenvia
    reenvia porque acha que a primeira nao chegou, e o silencio faria ela mandar uma terceira. E o
    "não contei de novo" e a parte que importa — diz que o dedup fez o trabalho dele, em vez de
    deixar a duvida de se o dinheiro entrou duas vezes.
    """
    partes = [formatar_reais(anterior.valor)] if anterior.valor is not None else []
    if anterior.data_transferencia is not None:
        partes.append(f"{anterior.data_transferencia:%d/%m}")
    onde = f": {' · '.join(partes)}" if partes else ""
    return f"♻️ Esse comprovante eu já tinha conferido{onde} — não contei de novo."


def montar_pergunta_do_comprovante(*, valor: Decimal | None, data: date | None) -> str:
    """ "❓ Recebi um comprovante de R$ 385,80 · 13/08, mas não achei venda em pix aberta que ele
    feche. É de quê?"

    UMA pergunta, e o comprovante fica retido: e o mesmo contrato da pergunta minima do anuncio —
    o agente diz o que viu, diz o que nao conseguiu concluir, e nao inventa a conclusao.
    """
    partes = [formatar_reais(valor)] if valor is not None else []
    if data is not None:
        partes.append(f"{data:%d/%m}")
    onde = f" de {' · '.join(partes)}" if partes else ""
    return (
        f"❓ Recebi um comprovante{onde}, mas não achei venda em pix aberta que ele feche. "
        "É de quê?"
    )


def montar_aviso_de_entrada_da_modelo(
    *, valor: Decimal | None, data: date | None, pagador: str | None
) -> str:
    """ "📥 Esse comprovante de R$ 658,07 · 06/08 é dinheiro que ENTROU pra modelo (de Vanessa Melo
    De Oliveira) — não é transferência pra casa, então não abati nada."

    O comprovante que aponta para o lado contrario nao pode receber nem a pergunta do comprovante
    sem par ("é de quê?") nem o aviso de chave fora da lista: os dois dizem a mesma coisa errada —
    que ela tem uma transferencia para explicar. Quem tem que explicar essa e a venda, nao ela.
    """
    partes = [formatar_reais(valor)] if valor is not None else []
    if data is not None:
        partes.append(f"{data:%d/%m}")
    onde = f" de {' · '.join(partes)}" if partes else ""
    de_quem = f" (de {pagador})" if pagador else ""
    return (
        f"📥 Esse comprovante{onde} é dinheiro que ENTROU pra modelo{de_quem} — não é "
        "transferência pra casa, então não abati nada."
    )


def montar_aviso_de_chave_desconhecida(*, chave: str | None, titular: str | None = None) -> str:
    """ "⚠️ Esse Pix foi pra uma chave fora da lista da casa (3RJ … · +55 71 99984 0879) — confere aí."

    Sinalizacao, nao bloqueio: o abate ja aconteceu quando esta linha e escrita. Ela mostra a
    chave COMO FOI LIDA (e nao "chave divergente") porque quem confere precisa comparar com o que
    esta na tela do banco — um aviso sem o dado nao deixa ninguem fazer nada.

    ⚠️ Desde o ticket 05 quem decide se ela SAI e `deve_avisar_destino_fora_da_casa`: so na
    primeira aparicao daquele destino. Montar o texto continua sendo de graca — a funcao e pura e
    nao sabe de recorrencia —, mas chama-la sem passar por aquela decisao devolve o alarme
    repetido que o ADR-0049 §5 veio calar.
    """
    alvo = " · ".join(p for p in (titular, chave) if p) or "destino que o comprovante não mostrou"
    return f"⚠️ Esse Pix foi pra uma chave fora da lista da casa ({alvo}) — confere aí."


def montar_aviso_de_cliente_para_a_casa(
    *, valor: Decimal | None, data: date | None, pagador: str | None
) -> str:
    """ "🏦 Esse comprovante de R$ 600,00 · 12/08 é o cliente (Lucas Prado) pagando a CASA — não
    passou por você, então não abati nada e marquei essa venda como recebida pela empresa."

    Espelha `montar_aviso_de_entrada_da_modelo` porque as duas classes precisam da mesma defesa: a
    pergunta do comprovante sem par ("é de quê?") e o aviso de chave fora da lista dizem, os dois,
    que ela tem uma transferencia para explicar — e ela nao tem. Quem tem que explicar essa e a
    venda.

    Diz o efeito ("não abati nada") e nao so a leitura, porque o silencio sobre o abate e
    exatamente o que faria a modelo perguntar depois se o dinheiro entrou.
    """
    partes = [formatar_reais(valor)] if valor is not None else []
    if data is not None:
        partes.append(f"{data:%d/%m}")
    onde = f" de {' · '.join(partes)}" if partes else ""
    de_quem = f" ({pagador})" if pagador else ""
    return (
        f"🏦 Esse comprovante{onde} é o cliente{de_quem} pagando a CASA — não passou por você, "
        "então não abati nada."
    )
