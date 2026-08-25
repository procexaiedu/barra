"""As tres Fichas do telefonista (spec 0006, ticket 06; ADR-0044/0046).

O telefonista posta um card padronizado **antes** do servico. Ele nao e receita — a Venda
registrada nasce depois, no pagamento (ADR-0044 §2) — e e gravado **calado**: ninguem pediu
confirmacao de nada.

Sao **tres** documentos, nao um (ADR-0046 §1, `docs/dominio/fichas-do-telefonista.md`), porque a
ficha completa e escrita para o SISTEMA e o comunicado e escrito para a MODELO:

| Documento    | Marca de reconhecimento                                        |
|--------------|----------------------------------------------------------------|
| individual   | tem `( )` para marcar e tem `Valor total` + `Valor desta modelo` |
| grupo        | idem, mais a lista `Modelo 1:` `Modelo 2:` ...                  |
| comunicado   | **nao** tem `( )` e **nao** tem `Valor total` — tem `Valor do job` |

**O parser e determinístico, por rotulo, e tem precedencia sobre o texto livre.** Sem LLM: a
grafia e um formulario que a propria casa distribuiu, e um extrator deterministico e o unico que
da para PROVAR contra o template (a mesma licao de `anuncio.py`). Nao casando nenhum dos tres, a
mensagem cai no leitor de anuncio que ja existe — o telefonista vai esquecer o card, e o sistema
nao pode ficar mudo quando ele escrever solto.

**Ler e tolerante; decidir e estrito.** O card degradado (campo vazio, secao faltando, "X" fora do
parentese, rotulo abreviado) nao pode derrubar a leitura dos campos que ESTAO la — no dia de pico
com quatro clientes subindo, o card sai torto. Por isso todo campo e independente e volta `None`
quando nao deu para ler, e nenhuma leitura levanta. O que continua estrito e o vocabulario
fechado: opcao que nao esta na lista do card nao vira enum por aproximacao, e duas opcoes marcadas
na mesma linha nao viram sorteio — viram `None`.

O que este modulo NAO decide: quem e a modelo (resolver closed-world em `nomes.py`, chamado por
`planejar_ficha`), onde a ficha foi postada (o escopo do alvo e por MODELO, nunca por grupo —
ADR-0046 §2) e se a ficha ja existe (a chave de conteudo, mais abaixo).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.modelos import FormaPagamento
from barra.dominio.grupo_financeiro.nomes import (
    CadastroDeNomes,
    OrigemDoAnuncio,
    separar_origem,
)
from barra.dominio.grupo_financeiro.pergunta import Falta
from barra.dominio.grupo_financeiro.razao import Bolso
from barra.dominio.grupo_financeiro.recibo import (
    CONVITE_DE_CORRECAO,
    formatar_duracao,
    formatar_reais,
)

TipoDeDocumento = Literal["individual", "grupo", "comunicado"]
"""Qual dos tres a mensagem e. `individual` e `grupo` sao a ficha COMPLETA (escrita para o
sistema); `comunicado` e o resumo que a modelo recebe para trabalhar."""

EstadoDaFicha = Literal["aberta", "confirmada", "realizada", "cancelada"]
"""`aberta -> confirmada -> realizada | cancelada` (ADR-0044 §1).

`confirmada` nasce hoje de UMA porta so — o quote "confirmado" (ticket 09) —, porque depois do
ADR-0046 §5 o ✅ do telefonista promove a venda em vez de confirmar o combinado. Se ninguem usar
essa porta em producao, o estado some e a maquina vira `aberta -> realizada | cancelada`."""

TipoDeEventoDaFicha = Literal["alteracao", "confirmacao", "realizacao", "cancelamento"]
"""O que aconteceu com uma Ficha de agendamento depois de gravada — o rastro APPEND-ONLY.

`alteracao` troca UM campo (uma linha por campo, e a unica que exige `campo`); as outras tres
movem o ESTADO e nao tem campo. `realizacao` e a promocao a Venda registrada (ticket 07), venha
ela da fala da modelo ou do ✅ do telefonista: e um fato so, com um evento so."""

# `OrigemDoAnuncio` vem de `nomes.py` (e reexportado aqui): o card e a marca colada ao nome
# ("fake Bianca") sao duas portas do MESMO campo, e dois Literais iguais em modulos diferentes
# divergem no dia em que alguem acrescentar um valor num so.
TipoDeLocal = Literal["casa", "hotel", "motel", "festa", "passeio", "jantar_almoco"]

TipoDeAtendimento = Literal["interno", "externo", "remoto"]
"""O `( ) Local proprio  ( ) Saida` do card, no vocabulario que `atendimentos.tipo_atendimento` ja
usa: interno = no local dela, externo = ela se desloca. `remoto` existe no enum do banco e NAO
aparece no card — video-chamada nao gera ficha de telefonista."""

FormaDaFicha = Literal["dinheiro", "pix", "debito", "credito", "link"]
"""As CINCO formas do card (ADR-0046 §4). "Cartao" nao existe mais: debito, credito e link sao
formas distintas porque so o credito tem taxa de parcelamento e so o link nao passa maquininha.

Literal PROPRIO, e nao o `FormaPagamento` de `modelos.py` (que ainda e `pix | dinheiro`): a ficha
le o card e o card ja tem cinco. Unificar os dois e o ticket 11 — ate la, o que a ficha guarda e o
que o telefonista marcou, e a coluna do banco e `text` com CHECK, nao enum."""

FormaDoAntecipado = Literal["pix", "link"]
"""Como o cliente mandou o antecipado do transporte. Dinheiro nao entra: antecipado e o que chega
ANTES, e dinheiro so chega na hora."""

# --- vocabularios fechados do card --------------------------------------------------------------
#
# Fechados de proposito e sem aproximacao: cada um destes veredictos vira coluna de enum no banco.
# Palavra que nao esta aqui devolve `None` (o campo fica vazio e a ficha vive sem ele), nunca o
# vizinho mais parecido — errar o tipo de local por similaridade manda a modelo para o lugar
# errado, e ninguem revisa um campo que o sistema preencheu sozinho.

_ORIGENS: dict[str, OrigemDoAnuncio] = {
    "proprio": "proprio",
    "propria": "proprio",
    "perfil proprio": "proprio",
    "fake": "fake",
    "perfil fake": "fake",
}

_TIPOS_DE_LOCAL: dict[str, TipoDeLocal] = {
    "casa": "casa",
    "residencia": "casa",
    "hotel": "hotel",
    "motel": "motel",
    "festa": "festa",
    "festinha": "festa",
    "passeio": "passeio",
    "jantar/almoco": "jantar_almoco",
    "jantar / almoco": "jantar_almoco",
    "jantar almoco": "jantar_almoco",
    "jantar": "jantar_almoco",
    "almoco": "jantar_almoco",
}

_TIPOS_DE_ATENDIMENTO: dict[str, TipoDeAtendimento] = {
    "local proprio": "interno",
    "nosso local": "interno",
    "saida": "externo",
}

_FORMAS: dict[str, FormaDaFicha] = {
    "dinheiro": "dinheiro",
    "din": "dinheiro",
    "especie": "dinheiro",
    "pix": "pix",
    "debito": "debito",
    "cartao de debito": "debito",
    "credito": "credito",
    "cartao de credito": "credito",
    "link": "link",
    "link de pagamento": "link",
}

_FORMAS_DO_ANTECIPADO: dict[str, FormaDoAntecipado] = {"pix": "pix", "link": "link"}

# --- o site, que NAO e vocabulario fechado ------------------------------------------------------

_SITES_CONHECIDOS: dict[str, str] = {
    "barra vips": "Barra Vips",
    "barravips": "Barra Vips",
    "gsex": "GSEX",
    "g sex": "GSEX",
    "viva local": "Viva Local",
    "vivalocal": "Viva Local",
    "garota com local": "Garota com Local",
    "garotacomlocal": "Garota com Local",
    "instagram": "Instagram",
    "insta": "Instagram",
    "ig": "Instagram",
    "tinder": "Tinder",
}
"""A grafia canonica das plataformas que a casa nomeou na reuniao de 20/08 — um dicionario de
APELIDOS, nao um enum.

O site e a metrica mais fina que a origem ("por qual site a venda entrou", spec 0006 §68) e por
isso ele precisa AGRUPAR: "barravips", "Barra Vips" e "BARRA VIPS" digitados em tres cards sao uma
plataforma so, e tres linhas no relatorio do dono nao respondem onde investir.

E aberto de proposito (`text` no banco, sem CHECK): a casa anuncia onde quiser, e um site novo nao
pode esperar migration nem virar `None` — ele entra com a grafia que o telefonista escreveu, so com
os espacos arrumados. Perder o dado por nao reconhece-lo seria pior do que ter que juntar duas
grafias no painel depois.
"""


def normalizar_site(texto: str | None) -> str | None:
    """A plataforma por onde a venda entrou, na grafia canonica. `None` = nao foi dito.

    Site em branco NAO bloqueia nada (ticket 16): a ficha nasce sem ele, a venda nasce sem ele, e a
    unica consequencia e uma fatia "nao dito" no relatorio por site.

    O que este parser NAO faz e deduzir a origem a partir do site. O dono disse que "o fake so vai
    ser sites especificos", mas a lista de quais nao esta escrita em lugar nenhum do repositorio —
    derivar `fake` de "GSEX" aqui seria inventar a metrica que a leitura existe para medir. Site e
    origem sao DOIS campos, e um nao preenche o outro.
    """
    if texto is None:
        return None
    limpo = " ".join(texto.split())
    if not limpo:
        return None
    return _SITES_CONHECIDOS.get(normalizar(limpo), limpo)


_LOCAL_DA_FICHA: dict[TipoDeLocal, str] = {
    "casa": "casa",
    "hotel": "hotel",
    "motel": "motel",
    "festa": "festa",
    "passeio": "passeio",
    "jantar_almoco": "jantar/almoço",
}
"""Como o tipo de local do card e dito no recibo que volta para o grupo (`local_da_ficha`)."""

# --- rotulos ------------------------------------------------------------------------------------
#
# O rotulo e o que vem antes do primeiro ":" da linha, normalizado e sem o ornamento do WhatsApp.
# Casamento EXATO sobre a forma normalizada, com apelidos declarados: e a mesma disciplina de
# allowlist fechada do resto do modulo. Um rotulo desconhecido nao vira campo por parecido — a
# linha e simplesmente ignorada, e a ficha nasce sem aquele campo.

_CAMPO_POR_ROTULO: dict[str, str] = {
    # 👤 CLIENTE
    "nome": "cliente_nome",
    "nome do cliente": "cliente_nome",
    "cliente": "cliente_nome",
    "whatsapp": "cliente_whatsapp",
    "whats": "cliente_whatsapp",
    "zap": "cliente_whatsapp",
    "telefone": "cliente_whatsapp",
    "whatsapp do cliente": "cliente_whatsapp",
    # 📝 CONTRATACAO
    "nome do perfil/anuncio": "nome_anuncio",
    "nome do perfil / anuncio": "nome_anuncio",
    "nome do perfil": "nome_anuncio",
    "nome do anuncio": "nome_anuncio",
    "perfil/anuncio": "nome_anuncio",
    "perfil": "nome_anuncio",
    "anuncio": "nome_anuncio",
    "site": "site",
    "plataforma": "site",
    "origem": "origem",
    "nome da modelo": "nome_da_modelo",
    "modelo": "nome_da_modelo",
    "acompanhante": "nome_da_modelo",
    # 🕒 HORARIO
    "data": "data",
    "dia": "data",
    "hora": "hora",
    "horario": "hora",
    "duracao": "duracao",
    "tempo": "duracao",
    # 📍 LOCAL
    "tipo": "tipo_local",
    "tipo de local": "tipo_local",
    "tipo do local": "tipo_local",
    "local": "local",
    "endereco": "endereco",
    "end": "endereco",
    "numero / bloco / complemento": "endereco_complemento",
    "numero/bloco/complemento": "endereco_complemento",
    "numero": "endereco_complemento",
    "complemento": "endereco_complemento",
    "bloco": "endereco_complemento",
    # 💰 VALORES
    "valor total": "valor_total",
    "total": "valor_total",
    "valor desta modelo": "valor_da_modelo",
    "valor de cada modelo": "valor_da_modelo",
    "valor de cada uma": "valor_da_modelo",
    "valor da modelo": "valor_da_modelo",
    "valor do job": "valor_da_modelo",
    "valor": "valor_da_modelo",
    "valor do transporte": "valor_transporte",
    "valor transporte": "valor_transporte",
    "transporte": "valor_transporte",
    "valor antecipado": "valor_antecipado",
    "valor do antecipado": "valor_antecipado",
    "antecipado": "valor_antecipado",
    "forma do antecipado": "forma_antecipado",
    "forma antecipado": "forma_antecipado",
    # 💳 PAGAMENTO
    "pagamento": "forma_pagamento",
    "forma": "forma_pagamento",
    "forma de pagamento": "forma_pagamento",
    "forma do pagamento": "forma_pagamento",
    # ✏️ OBSERVACOES
    "observacoes": "observacoes",
    "observacao": "observacoes",
    "obs": "observacoes",
}

_MODELO_NUMERADA = re.compile(r"^modelo\s*(\d{1,2})$")
"""`Modelo 1:` ... `Modelo 6:` — a lista da ficha de GRUPO. E ela, e nao um campo "quantidade de
modelos", que diz quantas sao: o card nao tem esse campo de proposito ("voce colocando o nome
delas, acho que ja e suficiente")."""

MIN_ROTULOS_DA_FICHA = 4
"""Quantos rotulos conhecidos uma mensagem precisa ter para ser um dos tres documentos.

Quatro, e nao um: o grupo escreve "Nome: João" no meio da conversa, e uma linha com dois pontos
nao pode virar ficha. Card degradado sobrevive com folga — o comunicado, que e o mais curto dos
tres, tem nove rotulos, e a ficha completa tem vinte. Abaixo do piso a mensagem segue para o
leitor de anuncio de sempre, que e o comportamento de hoje."""

MAX_OBSERVACOES = 500
"""Teto do que se guarda de observacao. E o campo que o telefonista usa como bloco de notas ("o
cliente pediu para nao passar perfume"); um romance ali viraria parede de texto no painel."""

_MARCAS = frozenset({"x", "✓", "✔", "✅", "☑", "•", "*"})
"""O que conta como "marcado" num `( )`. Inclui o que a operacao digita quando o parentese ja
esta preenchido no template e ela nao consegue apaga-lo."""

_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?")
_DATA = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_DATA_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_HORA = re.compile(r"\b(\d{1,2})\s*(?::|h)\s*(\d{2})?")
_HORA_SOZINHA = re.compile(r"^(\d{1,2})$")
_DURACAO_H = re.compile(r"(\d{1,2})\s*h(?:oras?)?\s*(?:(\d{1,2})\s*(?:min\w*)?)?")
_DURACAO_MIN = re.compile(r"(\d{1,3})\s*min\w*")
_DURACAO_SO_NUMERO = re.compile(r"^(\d{1,3})$")
_PARENTESE = re.compile(r"\(([^)]*)\)")
_ORNAMENTO_A_ESQUERDA = re.compile(r"^[^0-9a-zA-ZÀ-ɏ]+")
_ORNAMENTO_A_DIREITA = re.compile(r"[\s*_~`:.\-]+$")

MESES_DE_TOLERANCIA_DA_DATA = 2
"""Quanto uma data sem ano pode estar no passado antes de virar o ano que vem.

"Data: 02/01" postada em 28/12 e o atendimento da semana que vem, nao um de onze meses atras — a
ficha nasce ANTES do servico. Dois meses de folga cobrem a virada do ano sem transformar um card
atrasado (o telefonista postando hoje o que rolou anteontem) num agendamento fantasma."""


@dataclass(frozen=True)
class FichaLida:
    """O que o card DIZ — antes de qualquer resolucao contra o cadastro ou o banco.

    Espelho de `AnuncioDeVenda` para o outro leitor do modulo: aqui tambem nada e resolvido, nada
    e validado contra o mundo e nenhum campo ausente e erro. `nomes_das_modelos` sao os tokens
    crus na ordem do card (`Nome da modelo`, ou `Modelo 1..N`) — quem decide a quem pertencem e o
    resolver closed-world, nunca este modulo.
    """

    documento: TipoDeDocumento
    cliente_nome: str | None = None
    cliente_whatsapp: str | None = None
    nome_anuncio: str | None = None
    """O nome fantasia sob o qual o cliente comprou ("Sofia") — SEM a marca de origem.

    "fake Sofia" entra aqui como "Sofia" e a palavra vai para `origem`. Guardar "fake Sofia" como
    Nome de anuncio criaria um segundo apelido para a mesma mulher, que so casaria quando o
    telefonista repetisse a palavra (docs/dominio/grupo-financeiro.md, _Avoid_)."""
    site: str | None = None
    """A plataforma por onde a venda entrou, na grafia canonica (`normalizar_site`). Em branco NAO
    bloqueia a ficha — e so uma fatia "nao dito" no relatorio por site."""
    origem: OrigemDoAnuncio | None = None
    """Proprio x fake — o eixo binario com que o dono decide investimento (spec 0006 §45).

    Duas portas, nesta precedencia: o campo `Origem: ( ) Proprio ( ) Fake` marcado no card e, se
    ninguem marcou, a marca colada ao nome ("fake Sofia"). O campo vence porque e a resposta que o
    telefonista deu a uma pergunta; a marca no nome e o jeito antigo, o que o backfill le.

    Ninguem disse = `None`, e `None` fica. Nem o site preenche este campo (`normalizar_site`)."""
    nomes_das_modelos: tuple[str, ...] = ()
    data: date | None = None
    hora: time | None = None
    duracao_minutos: int | None = None
    tipo_atendimento: TipoDeAtendimento | None = None
    tipo_local: TipoDeLocal | None = None
    endereco: str | None = None
    endereco_complemento: str | None = None
    valor_total: Decimal | None = None
    valor_da_modelo: Decimal | None = None
    """O `Valor desta modelo` (individual), o `Valor de cada modelo` (grupo) ou o `Valor` do
    comunicado. NAO e derivado de `valor_total / N`: o rateio e do telefonista e pode ser
    desigual — supor rateio igual e o que `rateio.py` ja proibe do outro lado."""
    valor_transporte: Decimal | None = None
    """Quanto o Uber custou — CUSTO. Distinto de `valor_antecipado` (ADR-0046 §6): guardar um
    numero so apaga a diferenca entre "o cliente mandou 100 e o Uber custou 60" e "o cliente nao
    mandou nada e o Uber custou 15"."""
    valor_antecipado: Decimal | None = None
    forma_antecipado: FormaDoAntecipado | None = None
    forma_pagamento: FormaDaFicha | None = None
    observacoes: str | None = None

    @property
    def tem_conteudo(self) -> bool:
        """A ficha diz alguma coisa alem de existir?

        O template em branco, repostado no grupo para alguem copiar, casa todos os rotulos e nao
        carrega fato nenhum. Gravar isso criaria uma ficha vazia no nome da dona do grupo, que
        depois apareceria no painel como atendimento previsto e na cobranca da manha como "o de
        ontem rolou?". Silencio e a conduta certa.
        """
        return any(
            campo is not None
            for campo in (
                self.cliente_nome,
                self.data,
                self.hora,
                self.valor_total,
                self.valor_da_modelo,
                self.endereco,
            )
        )


@dataclass(frozen=True)
class ParticipanteDaFicha:
    """Uma modelo da ficha, com o valor DELA. A modelo nunca e coluna da ficha (ADR-0046 §1).

    Ficha individual e o caso N=1: uma linha aqui, sempre. Dois lugares onde a modelo aparece
    (uma coluna na ficha mais esta lista) divergiriam exatamente na festinha, que e o caso em que
    isso importa.
    """

    modelo_id: UUID
    valor: Decimal | None = None
    ordem: int = 1
    nome: str | None = None
    """Nome VERDADEIRO da modelo (o do cadastro). JOIN de leitura para o painel e para a fala do
    agente; nunca entra de volta no resolver de nomes."""


@dataclass(frozen=True)
class FichaDeAgendamento:
    """Uma Ficha de agendamento ja persistida — o combinado, que ainda NAO e receita.

    Nao e "venda em estado previsto" (alternativa rejeitada no ADR-0044): misturar combinado com
    recebido faz toda consulta de receita depender de filtrar estado, e o primeiro `WHERE`
    esquecido soma dinheiro que nao aconteceu.
    """

    id: UUID
    estado: EstadoDaFicha
    mensagem_id: UUID
    chave_conteudo: str
    participantes: tuple[ParticipanteDaFicha, ...] = ()
    vendedor_id: UUID | None = None
    cliente_nome: str | None = None
    cliente_whatsapp: str | None = None
    nome_anuncio: str | None = None
    site: str | None = None
    origem: OrigemDoAnuncio | None = None
    data: date | None = None
    hora: time | None = None
    duracao_minutos: int | None = None
    tipo_atendimento: TipoDeAtendimento | None = None
    tipo_local: TipoDeLocal | None = None
    endereco: str | None = None
    endereco_complemento: str | None = None
    valor_total: Decimal | None = None
    valor_transporte: Decimal | None = None
    valor_antecipado: Decimal | None = None
    forma_antecipado: FormaDoAntecipado | None = None
    forma_pagamento: FormaDaFicha | None = None
    observacoes: str | None = None

    @property
    def viva(self) -> bool:
        return self.estado != "cancelada"

    @property
    def aberta(self) -> bool:
        """Ainda espera desfecho? E esta a lista que a LLM enxerga numerada (ADR-0046 §2)."""
        return self.estado in ("aberta", "confirmada")

    def valor_de(self, modelo_id: UUID) -> Decimal | None:
        """Quanto ESTA modelo recebe nesta ficha — o unico numero que ela pode ver.

        E o valor da participante, nunca o `valor_total`: numa festinha de R$ 2.000 com tres
        modelos, mostrar 2.000 para uma delas entrega a conta da outra (spec 0006: cada uma ve o
        que e dela)."""
        for p in self.participantes:
            if p.modelo_id == modelo_id:
                return p.valor
        return None


@dataclass(frozen=True)
class DivergenciaDeDona:
    """O card nomeia uma modelo e o grupo em que ele caiu e de OUTRA (ticket 19).

    Acontece no arranjo com Grupo de fichas: o telefonista posta a ficha da Duda no grupo
    individual da Yasmin (dedo trocado no dia de pico, ou o card colado no grupo errado). As duas
    saidas silenciosas sao ruins e por motivos opostos — gravar pela dona registraria o
    atendimento da Duda no nome da Yasmin, e gravar pelo card poria uma ficha da Duda dentro do
    grupo da Yasmin, que e o isolamento cross-modelo cedendo. Por isso vira **pergunta**.
    """

    dona: UUID
    nome_da_dona: str | None
    nomeadas: tuple[str, ...]
    """Os nomes VERDADEIROS que o card nomeia — e nao os tokens crus. Quem responde a pergunta e
    o telefonista, e o nome do cadastro e o que ele reconhece."""


@dataclass(frozen=True)
class PlanoDaFicha:
    """O que a ficha rende: quem sao as participantes e o que impede grava-la."""

    participantes: tuple[ParticipanteDaFicha, ...] = ()
    nomes_desconhecidos: tuple[str, ...] = ()
    """Tokens que o cadastro nao conhece. Nome desconhecido NAO vira participante por palpite:
    vira a pergunta minima de sempre ("'fran loira' e quem?")."""
    ambiguo: bool = False
    """Algum nome bateu em mais de um cadastro. Nao vira pergunta — repetir o nome nao desempata
    homonimo; isso e erro de cadastro e se resolve no painel."""
    divergencia: DivergenciaDeDona | None = None
    """O card nomeia so modelo(s) que nao sao a dona deste grupo. As participantes continuam
    resolvidas (o resolver e o mesmo), mas gravar sem perguntar seria escolher entre dois erros —
    quem decide o que fazer com isso e a porta, e no Grupo de fichas ele nem existe (nao ha
    dona)."""

    @property
    def faltas(self) -> tuple[Falta, ...]:
        """O que impede gravar. Só `modelo`: valor e opcional na ficha (ela nao e receita)."""
        return ("modelo",) if not self.participantes and self.nomes_desconhecidos else ()


CasamentoDoComunicado = Literal["vincula", "cria", "ambiguo"]
"""O que fazer com um comunicado da modelo diante das fichas abertas dela (ADR-0046 §2 + spec):

* `vincula` — ele e o resumo de uma ficha que ja existe. NAO cria uma segunda.
* `cria` — nao ha ficha correspondente: e o arranjo sem Grupo de fichas, ou o telefonista pulou a
  ficha completa. O comunicado vira a ficha.
* `ambiguo` — casa com mais de uma ficha aberta. Nao escolhe: quem desempata e uma pergunta
  (ticket 19)."""


# --- leitura ------------------------------------------------------------------------------------


def parece_ficha_do_telefonista(texto: str) -> bool:
    """Triagem barata: esta mensagem tem a forma de um dos tres documentos?

    Conta rotulos conhecidos, e mais nada — sem regex de valor, sem cadastro, sem banco. E o
    portao que mantem a conversa do grupo ("Nome: João", "hora: já vou") fora do parser e continua
    valendo se um dia o leitor ficar caro.
    """
    return _conta_rotulos(texto) >= MIN_ROTULOS_DA_FICHA


def ler_ficha(texto: str, *, hoje: date | None = None) -> FichaLida | None:
    """Le o card linha a linha. `None` = a mensagem nao e nenhum dos tres documentos.

    Nunca levanta: campo que nao apareceu (ou que apareceu ilegivel) volta `None`, e o resto da
    ficha e lido do mesmo jeito. E o requisito do dia de pico — o card sai torto e o que esta la
    tem que entrar.

    `hoje` e o dia (BRT) em que a mensagem chegou, e serve so para completar o ANO de uma data
    escrita como "22/08". Sem ele, data sem ano volta `None`: chutar o ano dentro de um parser
    puro seria inventar um agendamento.

    `Site` e `Origem` sao DOIS campos (ticket 16), e o site nao preenche a origem: ele e mais fino
    e "em geral determina" o eixo binario, mas quais sites sao fake nao esta escrito em lugar
    nenhum. A origem sai do campo marcado ou, faltando ele, da marca colada ao `Nome do
    perfil/anuncio` — que e como o telefonista escrevia antes de o card existir.
    """
    linhas = [linha for linha in texto.splitlines() if linha.strip()]
    campos: dict[str, str] = {}
    modelos_numeradas: list[tuple[int, str]] = []
    marcadas: dict[str, str] = {}
    rotulos = 0
    tem_parentese = False
    indice_de_observacoes: int | None = None

    for i, linha in enumerate(linhas):
        if _PARENTESE.search(linha):
            tem_parentese = True
        rotulo, valor = _partir(linha)
        if rotulo is None:
            # Linha sem ":" — linha solta de opcoes ("( ) Dinheiro  ( ) Pix", que o template
            # escreve sem rotulo), cabecalho de secao ("✏️ *OBSERVACOES*", que e o rotulo com o
            # conteudo EMBAIXO) ou texto corrido.
            campo, escolhida = _linha_de_opcoes_sem_rotulo(linha)
            if campo is not None and escolhida is not None:
                marcadas.setdefault(campo, escolhida)
                rotulos += 1
                continue
            rotulo, valor = _sem_ornamento(linha) or None, ""
            if rotulo is None or rotulo not in _CAMPO_POR_ROTULO:
                continue

        numerada = _MODELO_NUMERADA.match(rotulo)
        if numerada is not None:
            rotulos += 1
            if valor:
                modelos_numeradas.append((int(numerada.group(1)), valor))
            continue

        campo = _CAMPO_POR_ROTULO.get(rotulo)
        if campo is None:
            continue
        rotulos += 1
        if campo == "observacoes":
            indice_de_observacoes = i
        if valor:
            campos.setdefault(campo, valor)

    if rotulos < MIN_ROTULOS_DA_FICHA:
        return None

    observacoes = _observacoes(campos.get("observacoes"), linhas, indice_de_observacoes)
    nomes = _nomes_das_modelas(campos, modelos_numeradas)
    documento: TipoDeDocumento = (
        "grupo"
        if modelos_numeradas
        else ("individual" if (tem_parentese or "valor_total" in campos) else "comunicado")
    )
    endereco, tipo_local = _local(campos)
    marca_no_nome, nome_anuncio = separar_origem(_texto(campos.get("nome_anuncio")) or "")

    return FichaLida(
        documento=documento,
        cliente_nome=_texto(campos.get("cliente_nome")),
        cliente_whatsapp=_texto(campos.get("cliente_whatsapp")),
        nome_anuncio=nome_anuncio or None,
        site=normalizar_site(_texto(campos.get("site"))),
        origem=_opcao(campos.get("origem"), _ORIGENS) or marca_no_nome,
        nomes_das_modelos=nomes,
        data=_data(campos.get("data"), hoje=hoje),
        hora=_hora(campos.get("hora")),
        duracao_minutos=_duracao(campos.get("duracao")),
        tipo_atendimento=_opcao(marcadas.get("tipo_atendimento"), _TIPOS_DE_ATENDIMENTO),
        tipo_local=tipo_local,
        endereco=endereco,
        endereco_complemento=_texto(campos.get("endereco_complemento")),
        valor_total=_dinheiro(campos.get("valor_total")),
        valor_da_modelo=_dinheiro(campos.get("valor_da_modelo")),
        valor_transporte=_dinheiro(campos.get("valor_transporte")),
        valor_antecipado=_dinheiro(campos.get("valor_antecipado")),
        forma_antecipado=_opcao(campos.get("forma_antecipado"), _FORMAS_DO_ANTECIPADO),
        forma_pagamento=_opcao(
            campos.get("forma_pagamento") or marcadas.get("forma_pagamento"), _FORMAS
        ),
        observacoes=observacoes,
    )


# --- do que o card diz para quem ele nomeia -----------------------------------------------------


def planejar_ficha(
    ficha: FichaLida,
    *,
    cadastro: CadastroDeNomes,
    dona_do_grupo: UUID | None,
) -> PlanoDaFicha:
    """Quem sao as participantes desta ficha, e quanto e de cada uma. Nunca levanta.

    Tres regras, todas herdadas de `rateio.py` para que os dois leitores do modulo respondam a
    mesma coisa sobre nome:

    * **O card nomeia = o card manda.** O nome vem de `Nome da modelo` (real) ou da lista
      `Modelo 1..N`; faltando os dois, do `Nome do perfil/anuncio` — que e o vocabulario de
      `modelo_nomes_anuncio` e resolve pelo mesmo indice. Isso e o que faz a ficha postada num
      **Grupo de fichas** (que nao tem dona) encontrar a modelo (ADR-0046 §2).
    * **Ninguem nomeado = a dona do grupo.** E o caso do comunicado no grupo individual dela: o
      vinculo grupo<->modelo e closed-world, entao nao ha palpite.
    * **Nome desconhecido nao vira participante.** Volta em `nomes_desconhecidos` e a porta
      pergunta — nunca cadastra por aproximacao, nunca sorteia homonimo.
    * **Com dona, o nome que nao decide nao desloca ninguem** (ticket 19: no grupo individual "o
      campo, se presente, tem que casar com a modelo do grupo; divergir e pergunta"). Homonimo e
      `Nome do perfil/anuncio` fora do cadastro caem na dona em vez de derrubar o card; so o
      `Nome da modelo` desconhecido — o que e ensinavel — continua virando pergunta, e so o nome
      que resolve para OUTRA mulher vira `divergencia`.

    O valor de cada participante e o `Valor desta modelo` / `Valor de cada modelo`. Com UMA
    participante e sem ele, o `Valor total` serve de valor dela (num atendimento de uma modelo so
    os dois numeros sao o mesmo dinheiro); com varias, nao ha fallback — dividir o total por N
    suporia rateio igual, e supor e o que o dominio proibe. Valor ausente NAO impede a ficha: ela
    nao e receita, e a coluna aceita nulo.
    """
    tokens = ficha.nomes_das_modelos or ((ficha.nome_anuncio,) if ficha.nome_anuncio else ())
    if not tokens:
        if dona_do_grupo is None:
            return PlanoDaFicha()
        return _plano_da_dona(ficha, cadastro=cadastro, dona_do_grupo=dona_do_grupo)

    sozinha = len(tokens) == 1
    participantes: list[ParticipanteDaFicha] = []
    desconhecidos: list[str] = []
    ambiguo = False
    ja_planejadas: set[UUID] = set()

    for token in tokens:
        resolucao = cadastro.resolver((token,))
        if resolucao.veredito == "ambiguo":
            ambiguo = True
            continue
        if resolucao.veredito != "resolvido" or resolucao.modelo_id is None:
            desconhecidos.extend(resolucao.nomes_nao_resolvidos or (token,))
            continue
        if resolucao.modelo_id in ja_planejadas:
            # O card repetiu a mesma mulher em duas linhas (`Modelo 1` e `Modelo 3` com o nome
            # real e o do perfil). Uma modelo entra uma vez: a UNIQUE (ficha_id, modelo_id) do
            # banco diria o mesmo, so que como erro no meio da transacao.
            continue
        ja_planejadas.add(resolucao.modelo_id)
        participantes.append(
            ParticipanteDaFicha(
                modelo_id=resolucao.modelo_id,
                valor=_valor_da_participante(ficha, sozinha=sozinha),
                ordem=len(participantes) + 1,
                nome=resolucao.nome,
            )
        )

    if not participantes and dona_do_grupo is not None and sozinha:
        # O card nomeou UMA modelo, o nome nao decidiu, e este grupo TEM dona. Duas situacoes
        # caem aqui, e nenhuma delas justifica descartar o combinado:
        #
        # * **homonimo** (`ambiguo`): dois cadastros com o mesmo nome. Perguntar nao desempata —
        #   a resposta seria o mesmo nome de novo — e o vinculo grupo<->modelo e um fato
        #   closed-world, nao um palpite. Ficar com a dona nao escolhe entre as homonimas: ignora
        #   um cadastro que nao distingue ninguem e usa o unico dado que distingue.
        # * **o token veio do `Nome do perfil/anuncio`** e o cadastro nao o conhece. O nome
        #   fantasia e vocabulario de marketing e o cadastro dele e incompleto por natureza;
        #   perguntar "'Sofia' e quem?" DENTRO do grupo da Sofia e ruido, nao pergunta.
        #
        # * **o nome e uma forma curta do nome DELA** ("Yasmin" no grupo da "Yasmin
        #   Nascimento"). O resolver nao o casa porque ele casa exato — e casa exato porque
        #   escolhe entre todas as mulheres do cadastro. Aqui nao ha escolha: a candidata e uma
        #   so, dada pelo vinculo grupo<->modelo, e a pergunta e apenas se o card CASA com ela
        #   (ticket 19). Casou: e ela.
        #
        # O que NAO cai aqui e o `Nome da modelo` (o nome REAL) desconhecido que nao nomeia a
        # dona ("fran loira" no grupo da Yasmin): aquele e ensinavel, a resposta vira Nome de
        # anuncio no cadastro, e por isso continua virando pergunta. E a distincao que o ticket
        # 19 pede — um nome que nao aponta para NINGUEM nao diverge da dona, e um nome que
        # aponta para OUTRA mulher ja saiu resolvido daqui e vira `divergencia`.
        if ambiguo or not ficha.nomes_das_modelos or cadastro.nomeia(tokens[0], dona_do_grupo):
            return _plano_da_dona(ficha, cadastro=cadastro, dona_do_grupo=dona_do_grupo)

    return PlanoDaFicha(
        participantes=tuple(participantes),
        nomes_desconhecidos=tuple(desconhecidos),
        ambiguo=ambiguo,
        divergencia=_divergencia(participantes, cadastro=cadastro, dona_do_grupo=dona_do_grupo),
    )


def _plano_da_dona(
    ficha: FichaLida, *, cadastro: CadastroDeNomes, dona_do_grupo: UUID
) -> PlanoDaFicha:
    """A ficha e da dona deste grupo — o unico caminho que nao precisa do cadastro de nomes.

    Sozinha por construcao: um grupo financeiro tem UMA modelo, e uma festinha que a nomeia junto
    com outras chega pela lista `Modelo 1..N`, que nunca passa por aqui.
    """
    return PlanoDaFicha(
        participantes=(
            ParticipanteDaFicha(
                modelo_id=dona_do_grupo,
                valor=_valor_da_participante(ficha, sozinha=True),
                ordem=1,
                nome=cadastro.nome_verdadeiro.get(dona_do_grupo),
            ),
        )
    )


def _divergencia(
    participantes: Sequence[ParticipanteDaFicha],
    *,
    cadastro: CadastroDeNomes,
    dona_do_grupo: UUID | None,
) -> DivergenciaDeDona | None:
    """O card caiu no grupo de uma modelo e nomeia SO outras? (ADR-0046 §2, ticket 19)

    Nao ha divergencia quando a dona esta entre as nomeadas: a festinha da Yasmin com a Bianca,
    postada no grupo da Yasmin, e o caso normal do card de grupo — cada uma ve o valor dela.
    Tambem nao ha no Grupo de fichas, que nao tem dona: la o card nomear outra modelo e
    exatamente o que ele existe para fazer.
    """
    if dona_do_grupo is None or not participantes:
        return None
    if any(p.modelo_id == dona_do_grupo for p in participantes):
        return None
    return DivergenciaDeDona(
        dona=dona_do_grupo,
        nome_da_dona=cadastro.nome_verdadeiro.get(dona_do_grupo),
        nomeadas=tuple(p.nome for p in participantes if p.nome),
    )


def casar_comunicado(
    comunicado: FichaLida,
    *,
    modelo_id: UUID,
    abertas: Sequence[FichaDeAgendamento],
) -> tuple[CasamentoDoComunicado, FichaDeAgendamento | None]:
    """O comunicado da modelo e o resumo de qual ficha aberta DELA? (ADR-0046 §2, spec 0006)

    O comunicado **vincula, nunca cria uma segunda ficha**. Se a ficha completa foi para o Grupo
    de fichas, a modelo vai citar o COMUNICADO ao pagar, e o alvo esta no outro grupo — duas
    fichas para o mesmo atendimento cobrariam duas vezes e apareceriam duas vezes no painel.

    O casamento e por `modelo + cliente + valor`, e nao pela chave de conteudo do modulo: o
    comunicado **nao tem data** ("a hora nao precisa porque e uma previa"), entao a chave nunca
    fecha inteira. Comparacao so entre campos que os DOIS lados tem — o que falta de um lado nao
    desqualifica nem confirma —, e pelo menos uma comparacao real tem que acontecer: casar por
    ausencia daria qualquer ficha aberta para qualquer comunicado.

    `ambiguo` com mais de uma candidata, sempre: escolher a primeira e o palpite que o dominio
    proibe, e as duas fichas sao dinheiro de dias diferentes.
    """
    candidatas = candidatas_do_comunicado(comunicado, modelo_id=modelo_id, abertas=abertas)
    if len(candidatas) == 1:
        return "vincula", candidatas[0]
    if len(candidatas) > 1:
        return "ambiguo", None
    return "cria", None


def candidatas_do_comunicado(
    comunicado: FichaLida,
    *,
    modelo_id: UUID,
    abertas: Sequence[FichaDeAgendamento],
) -> tuple[FichaDeAgendamento, ...]:
    """As fichas abertas DELA que este comunicado pode estar resumindo, na ordem em que vieram.

    E o mesmo filtro que `casar_comunicado` usa para decidir, exposto porque quem vai PERGUNTAR
    precisa nomear as candidatas — e nomear outras (todas as abertas, por exemplo) faria a
    pergunta oferecer atendimentos que nem batem com o comunicado.
    """
    return tuple(f for f in abertas if _comunicado_bate(comunicado, f, modelo_id=modelo_id))


PREFIXO_DA_DIVERGENCIA = "❓ Essa ficha "
"""Assinatura da pergunta de divergencia, do mesmo naipe do "❓ So falta saber:" e do "❓ Foi".

Prefixo PROPRIO porque a tranca contra reperguntar e por assunto: o card que caiu no grupo errado
costuma ser repostado igual (o telefonista tenta de novo), e uma pergunta por repost seria a
metralhadora que o dominio proibe — mas ela nao pode ser calada pela pergunta de nome, que e outra
conversa."""

PREFIXO_DO_COMUNICADO = "❓ Esse comunicado "
"""Assinatura da pergunta de desempate do comunicado. Idem: assunto proprio, tranca propria."""

MAX_FICHAS_NOMEADAS = 3
"""Quantas fichas a pergunta de desempate nomeia. A resposta e um NOME de cliente, e o de qualquer
ficha aberta serve — nomear as tres mais recentes e o atalho do caso comum; listar sete
transformaria uma pergunta de uma palavra num formulario."""


def montar_pergunta_da_divergencia(divergencia: DivergenciaDeDona) -> str | None:
    """ "❓ Essa ficha é da Duda ou da Yasmin? Ela veio no grupo da Yasmin."

    Objetiva como toda pergunta deste modulo: se responde com um nome. `None` quando nao ha nome
    nenhum a oferecer — sem as duas pontas a frase viraria "essa ficha e de quem?", que e a
    pergunta que o card ja respondeu e ninguem saberia reler.

    Nao vaza nada: os nomes que ela repete sao os que o proprio card, ja postado neste grupo,
    escreveu — e quem tem que responder e o telefonista que o postou.
    """
    if not divergencia.nomeadas:
        return None
    dona = divergencia.nome_da_dona
    if dona is None:
        return None
    quem = " / ".join(divergencia.nomeadas)
    return f"{PREFIXO_DA_DIVERGENCIA}é da {quem} ou da {dona}? Ela veio no grupo da {dona}."


def montar_pergunta_do_comunicado_ambiguo(
    *, candidatas: Sequence[FichaDeAgendamento], modelo_id: UUID
) -> str | None:
    """ "❓ Esse comunicado é de qual atendimento? Igor (R$ 700,00) · … — me diz o nome do cliente."

    O comunicado que casa com DUAS fichas abertas dela (mesmo cliente, mesmo valor, dias
    diferentes) nao escolhe e nao cria uma terceira: pergunta. Escolher seria vincular o resumo ao
    atendimento errado, e o erro so apareceria no pagamento — a modelo cita o comunicado, o
    sistema fecha a ficha do outro dia e a certa continua aberta sendo cobrada.

    So fichas DELA entram na lista (`abertas` ja vem escopada por modelo) e o valor mostrado e o
    **dela** (`valor_de`): numa festinha, ecoar o total entrega a conta da outra.
    """
    if len(candidatas) < 2:
        return None
    ordenadas = sorted(candidatas, key=lambda f: f.data or date.min, reverse=True)
    itens = " · ".join(_opcao_da_ficha(f, modelo_id) for f in ordenadas[:MAX_FICHAS_NOMEADAS])
    resto = len(candidatas) - min(len(candidatas), MAX_FICHAS_NOMEADAS)
    cauda = f" (e mais {resto})" if resto > 0 else ""
    return (
        f"{PREFIXO_DO_COMUNICADO}é de qual atendimento? {itens}{cauda} — me diz o nome do cliente."
    )


def _opcao_da_ficha(ficha: FichaDeAgendamento, modelo_id: UUID) -> str:
    """Uma ficha aberta como opcao de resposta: o cliente primeiro, que e o que se responde.

    Sem cliente no card, o dia do combinado — o outro jeito de dizer qual ("o de ontem"). Gemea de
    `_candidata_da_ficha` (pagamento.py) e com a mesma forma de proposito: duas listas de fichas
    com grafias diferentes fariam a mesma resposta parecer duas conversas.
    """
    if ficha.cliente_nome:
        quem = ficha.cliente_nome
    elif ficha.data:
        quem = f"{ficha.data:%d/%m}"
    else:
        quem = "sem cliente"
    valor = ficha.valor_de(modelo_id)
    return f"{quem} ({formatar_reais(valor)})" if valor is not None else quem


def chave_de_conteudo_da_ficha(
    *,
    data: date | None,
    hora: time | None,
    cliente: str | None,
    modelo_ids: Iterable[UUID],
) -> str:
    """A identidade do FATO combinado — o que faz o REPOST do card nao virar um segundo
    atendimento.

    Nao entra valor nenhum, de proposito: o repost EXISTE para mudar o valor ("o cliente negociou
    desconto"). Com o valor na chave, cada negociacao criaria uma ficha nova e a antiga ficaria
    viva cobrando um numero morto — o oposto do que o gesto quer dizer. Quem transforma a colisao
    em alteracao com rastro e o ticket 09.

    As modelos entram ORDENADAS porque a mesma festinha postada em dois grupos tem que produzir a
    mesma chave, e a ordem em que o telefonista digitou os nomes muda entre um post e outro.

    Texto legivel e nao hash, como a chave da venda: quando uma ficha "sumir" no dedup, quem for
    investigar le a chave no banco e ve na hora por que ela colidiu.
    """
    return "|".join(
        [
            "ficha",
            f"{data:%Y-%m-%d}" if data else "",
            f"{hora:%H:%M}" if hora else "",
            normalizar(cliente or ""),
            ",".join(sorted(str(m) for m in modelo_ids)),
        ]
    )


# --- promocao: a ficha vira Venda registrada (ticket 07) -----------------------------------------
#
# A Venda registrada nasce no PAGAMENTO (ADR-0044 §2), herdando da ficha valor, cliente, duracao,
# local, perfil e origem. O que o pagamento acrescenta e a FORMA e o BOLSO — o resto o telefonista
# ja digitou, e reperguntar seria a metralhadora que o dominio proibe.
#
# **A origem do gesto e parametro, nunca premissa** (ADR-0046 §5): a fala da modelo ("recebi, foi
# dinheiro") e uma das duas portas; o ✅ do telefonista e a outra (ticket 20) e vem pelo MESMO
# caminho. O que vier primeiro promove; o segundo bate na chave de conteudo da venda e nao
# duplica.

OrigemDaPromocao = Literal["modelo", "telefonista"]
"""Quem fez o gesto que promoveu a ficha (ADR-0046 §5).

Nao muda o que e escrito na venda — muda a AUDITORIA: quando o valor estiver errado, e ela que
diz se quem afirmou o fato foi quem recebeu o dinheiro ou quem vendeu o atendimento. O ticket 20
acrescenta `telefonista` como caminho real; ele ja existe aqui para que a segunda porta seja um
argumento, e nao um segundo caminho de escrita."""


def bolso_da_promocao(
    forma: FormaPagamento | None, *, comprovante_da_modelo: bool = False
) -> Bolso:
    """Em que bolso o dinheiro DESTA venda caiu, com o que se sabe no ato da promocao (ADR-0047).

    So as duas evidencias que a promocao tem na mao:

    * **comprovante dela -> casa** casando com a ficha: o dinheiro passou pela conta dela (`dela`),
      e a transferencia credita no razao;
    * **forma = dinheiro**: `dela` sempre — especie nao tem outro bolso.

    Todo o resto e `nao_dito`, que e estado LEGITIMO e nao erro: entra na cobranca consolidada da
    manha ao lado da forma que ja e cobrada, sem pergunta nova (ADR-0047 §3). O razao trata
    `nao_dito` como `dela` por default conservador, e nada aqui chuta.

    A tabela completa de evidencia — fala explicita ("caiu na minha conta", "ficou com voce") e
    comprovante do cliente -> casa — e o ticket 21, e entra ACIMA destas duas linhas. Este e o
    piso, nao o teto.
    """
    if comprovante_da_modelo:
        return "dela"
    if forma == "dinheiro":
        return "dela"
    return "nao_dito"


def local_da_ficha(ficha: FichaDeAgendamento) -> str | None:
    """O local do atendimento como o recibo o diz — o `local` que o anuncio livre traz em texto.

    A ficha guarda o local em tres campos (`tipo_atendimento`, `tipo_local`, `endereco`) e a Venda
    registrada tem UM campo de texto livre. O endereco NAO entra: ele e onde a modelo trabalha e
    mora, e o recibo volta para o grupo — o que se confere de relance e "foi aqui ou foi saida".
    """
    if ficha.tipo_atendimento == "interno":
        return "no nosso local"
    rotulo = _LOCAL_DA_FICHA.get(ficha.tipo_local) if ficha.tipo_local else None
    if ficha.tipo_atendimento == "externo":
        return f"saída · {rotulo}" if rotulo else "saída"
    return rotulo


@dataclass(frozen=True)
class PromocaoDaFicha:
    """O que a Venda registrada herda da ficha, ja resolvido — sem banco e sem I/O.

    Uma promocao e SEMPRE de uma modelo so: numa festinha, cada participante tem o valor dela e
    vira a venda dela (o rateio e do telefonista, e `ficha_participantes` ja o guarda). Quem
    recebeu por todas e o ticket 13, e e coluna da venda, nao deste plano.
    """

    ficha_id: UUID
    modelo_id: UUID
    valor: Decimal
    data: date
    origem_do_gesto: OrigemDaPromocao
    cliente_nome: str | None = None
    local_atendimento: str | None = None
    duracao_minutos: int | None = None
    forma_pagamento: FormaPagamento | None = None
    bolso: Bolso = "nao_dito"
    origem: OrigemDoAnuncio | None = None
    site: str | None = None
    vendedor_id: UUID | None = None
    nome_da_modelo: str | None = None
    """Nome VERDADEIRO da modelo, para o recibo. Vem da participante (JOIN de leitura), nunca do
    `nome_anuncio` — o recibo do modulo sempre nomeia a mulher, nao o perfil."""


def planejar_promocao(
    ficha: FichaDeAgendamento,
    *,
    modelo_id: UUID,
    origem_do_gesto: OrigemDaPromocao,
    dia_do_gesto: date,
    forma: FormaPagamento | None = None,
    comprovante_da_modelo: bool = False,
) -> PromocaoDaFicha | None:
    """O que gravar quando esta ficha vira venda. `None` = falta o valor DELA, e sem valor nao ha
    venda (a coluna exige `> 0`).

    Valor ausente nao e erro da promocao: a ficha nao e receita e nasce podendo estar incompleta.
    O que ela vira e a pergunta consolidada da manha (ticket 10), nunca uma venda de R$ 0,00.

    **A data e a do COMBINADO, nao a do gesto.** A modelo avisa que recebeu as 22h de um
    atendimento das 19h — as duas sao o mesmo dia —, mas ela tambem avisa no dia seguinte, e a
    venda pertence ao dia em que o atendimento aconteceu. E tambem o que faz as duas portas
    (ADR-0046 §5) produzirem a MESMA chave de conteudo: o ✅ do telefonista pode chegar noutro dia
    que a venda continua sendo a mesma, e a segunda porta nao duplica.

    **A forma vem de quem a disser, nunca do card.** `fichas_de_agendamento.forma_pagamento` e o
    que foi COMBINADO ("vai ser no pix"), e o combinado muda na porta do cliente — herda-lo seria
    afirmar um fato que ninguem afirmou. Sem forma dita, a venda nasce com a pendencia de sempre e
    entra na cobranca da manha (o caso do ✅ solto, ticket 20).
    """
    valor = ficha.valor_de(modelo_id)
    if valor is None or valor <= Decimal("0"):
        return None
    participante = next((p for p in ficha.participantes if p.modelo_id == modelo_id), None)
    return PromocaoDaFicha(
        ficha_id=ficha.id,
        modelo_id=modelo_id,
        valor=valor,
        data=ficha.data or dia_do_gesto,
        origem_do_gesto=origem_do_gesto,
        cliente_nome=ficha.cliente_nome,
        local_atendimento=local_da_ficha(ficha),
        duracao_minutos=ficha.duracao_minutos,
        forma_pagamento=forma,
        bolso=bolso_da_promocao(forma, comprovante_da_modelo=comprovante_da_modelo),
        origem=ficha.origem,
        site=ficha.site,
        vendedor_id=ficha.vendedor_id,
        nome_da_modelo=participante.nome if participante else None,
    )


# --- alteracao: o combinado muda depois de gravado (ticket 09) -----------------------------------
#
# O combinado muda o tempo todo — o cliente negocia desconto, o horario anda, o atendimento fura.
# O telefonista tem dois gestos para isso que NAO dependem de evento novo de webhook (a reacao
# depende, e e o ticket 08): **repostar** o card com o campo trocado e **responder** a ficha por
# quote ("mudou pra 800", "nao veio", "confirmado").
#
# Os dois mexem no MESMO combinado, entao a alteracao e uma so — o que muda e quem a LEU (o parser
# do card no repost; o leitor de quote de `correcao.py` no texto) e se o agente ECOA:
#
# * o **repost** e calado, como a gravacao da ficha (ADR-0044 §1): o telefonista acabou de olhar
#   para o formulario que ele mesmo mandou, e um "✏️ alterei" por card transformaria o grupo num
#   eco. O rastro fica no evento `alteracao`, append-only, e no painel;
# * o **quote** ecoa o de->para. Quem escreve uma frase espera resposta, e a correcao mal
#   entendida e pior que o erro original — a mesma licao que fez o recibo de venda ecoar.
#
# O que NAO e alteracao: repostar mudando **data, hora ou cliente**. Esses tres sao a identidade do
# fato (`chave_de_conteudo_da_ficha`), entao o card repostado com outra data e outro combinado e
# nasce como ficha propria — e a de ontem continua viva ate alguem cancela-la. Deixar a chave
# absorver a data faria "adiei pra sexta" apagar o atendimento de quinta em silencio.

VAZIO = "—"
"""Como um campo ausente aparece no eco e no rastro. Melhor que "None" para quem le no grupo."""

CampoDaFicha = Literal[
    "valor",
    "valor_total",
    "data",
    "hora",
    "duracao",
    "cliente",
    "forma_pagamento",
    "transporte",
    "antecipado",
    "endereco",
    "observacoes",
]
"""O que uma alteracao pode trocar. Fechado de proposito: cada campo aqui precisa de uma forma
legivel no eco (`_como_texto`), e campo sem forma legivel vira "None → None" na tela do grupo."""

ROTULO_DO_CAMPO: dict[CampoDaFicha, str] = {
    "valor": "valor",
    "valor_total": "valor total",
    "data": "data",
    "hora": "horário",
    "duracao": "duração",
    "cliente": "cliente",
    "forma_pagamento": "forma de pagamento",
    "transporte": "transporte",
    "antecipado": "antecipado",
    "endereco": "endereço",
    "observacoes": "observações",
}


@dataclass(frozen=True)
class AlteracaoDaFicha:
    """O que o gesto QUER mudar no combinado — antes de encostar na ficha.

    Campo nulo = o gesto nao falou dele, e o que ele nao falou nao muda. Nao ha como APAGAR um
    campo por aqui, e e deliberado: "sem cliente" nao e uma frase que o grupo diz, e apagamento
    silencioso e o tipo de escrita que ninguem confere (a mesma regra de `correcao.Correcao`).

    `valor` e o da MODELO (`ficha_participantes.valor`) e `valor_total` e o do atendimento. Numa
    ficha de uma modelo so os dois sao o mesmo dinheiro e andam juntos; na festinha sao numeros
    diferentes, e e por isso que sao dois campos e nao um.
    """

    valor: Decimal | None = None
    valor_total: Decimal | None = None
    data: date | None = None
    hora: time | None = None
    duracao_minutos: int | None = None
    cliente: str | None = None
    forma_pagamento: FormaDaFicha | None = None
    valor_transporte: Decimal | None = None
    valor_antecipado: Decimal | None = None
    endereco: str | None = None
    observacoes: str | None = None

    @property
    def vazia(self) -> bool:
        """O gesto nao disse nada que se possa gravar."""
        return all(
            campo is None
            for campo in (
                self.valor,
                self.valor_total,
                self.data,
                self.hora,
                self.duracao_minutos,
                self.cliente,
                self.forma_pagamento,
                self.valor_transporte,
                self.valor_antecipado,
                self.endereco,
                self.observacoes,
            )
        )

    @property
    def mexe_no_valor(self) -> bool:
        """Mexe em dinheiro? E a pergunta que decide se a festinha desempata ou pergunta."""
        return self.valor is not None or self.valor_total is not None


@dataclass(frozen=True)
class MudancaNaFicha:
    """Um campo que de fato mudou, ja em texto legivel — o eco no grupo e o rastro no banco.

    Texto (e nao valor tipado) porque os dois consumidores sao humanos lendo: o telefonista de
    relance no grupo e quem for auditar a linha no painel. Um so lugar formata, entao a fala e o
    rastro nunca divergem — espelho de `correcao.Mudanca`, para os dois gestos de correcao do
    modulo (recibo e ficha) contarem a mesma historia.
    """

    campo: CampoDaFicha
    de: str
    para: str


def alterar_ficha(ficha: FichaDeAgendamento, alteracao: AlteracaoDaFicha) -> FichaDeAgendamento:
    """A ficha como ela FICA depois da alteracao. Puro: nao escreve, so devolve o estado novo.

    O `valor` da alteracao vale para TODAS as participantes, e nao para a primeira: no card de
    festinha o numero e o `Valor de cada modelo`, um so para todas, e num card individual so ha
    uma. Quem impede que isso escreva por cima de um rateio DESIGUAL e `valor_alteravel`, chamado
    antes — dividir o dinheiro de uma com a outra e o erro que ninguem mais descobre.
    """
    participantes = ficha.participantes
    if alteracao.valor is not None:
        participantes = tuple(replace(p, valor=alteracao.valor) for p in ficha.participantes)
    return replace(
        ficha,
        participantes=participantes,
        valor_total=_ou(alteracao.valor_total, ficha.valor_total),
        data=_ou(alteracao.data, ficha.data),
        hora=_ou(alteracao.hora, ficha.hora),
        duracao_minutos=_ou(alteracao.duracao_minutos, ficha.duracao_minutos),
        cliente_nome=_ou(alteracao.cliente, ficha.cliente_nome),
        forma_pagamento=_ou(alteracao.forma_pagamento, ficha.forma_pagamento),
        valor_transporte=_ou(alteracao.valor_transporte, ficha.valor_transporte),
        valor_antecipado=_ou(alteracao.valor_antecipado, ficha.valor_antecipado),
        endereco=_ou(alteracao.endereco, ficha.endereco),
        observacoes=_ou(alteracao.observacoes, ficha.observacoes),
    )


def mudancas_na_ficha(
    antes: FichaDeAgendamento, depois: FichaDeAgendamento
) -> tuple[MudancaNaFicha, ...]:
    """O que REALMENTE mudou entre os dois estados — vazio quando o gesto repetiu o que ja era.

    Comparar os dois estados (em vez de confiar no que o gesto disse) e o que mantem o eco e o
    rastro honestos: o card repostado identico e o gesto mais comum do grupo, e dizer "alterei"
    ali seria mentir para quem confere de relance. E e tambem o que decide, sozinho, se houve
    substituicao ou se o repost caiu no dedup.
    """
    encontradas: list[MudancaNaFicha] = []
    for campo, de, para in (
        ("valor", _valor_visivel(antes), _valor_visivel(depois)),
        ("transporte", antes.valor_transporte, depois.valor_transporte),
        ("antecipado", antes.valor_antecipado, depois.valor_antecipado),
    ):
        if de != para:
            encontradas.append(MudancaNaFicha(cast(CampoDaFicha, campo), _reais(de), _reais(para)))
    if len(depois.participantes) > 1 and antes.valor_total != depois.valor_total:
        # So na festinha: com uma modelo so, `valor_total` e `valor` sao o mesmo dinheiro e ecoar
        # os dois diria duas vezes a mesma coisa.
        encontradas.append(
            MudancaNaFicha("valor_total", _reais(antes.valor_total), _reais(depois.valor_total))
        )
    if antes.data != depois.data:
        encontradas.append(MudancaNaFicha("data", _dia(antes.data), _dia(depois.data)))
    if antes.hora != depois.hora:
        encontradas.append(MudancaNaFicha("hora", _relogio(antes.hora), _relogio(depois.hora)))
    if antes.duracao_minutos != depois.duracao_minutos:
        encontradas.append(
            MudancaNaFicha(
                "duracao",
                _duracao_legivel(antes.duracao_minutos),
                _duracao_legivel(depois.duracao_minutos),
            )
        )
    for campo, texto_antes, texto_depois in (
        ("cliente", antes.cliente_nome, depois.cliente_nome),
        ("forma_pagamento", antes.forma_pagamento, depois.forma_pagamento),
        ("endereco", antes.endereco, depois.endereco),
        ("observacoes", antes.observacoes, depois.observacoes),
    ):
        if texto_antes != texto_depois:
            encontradas.append(
                MudancaNaFicha(
                    cast(CampoDaFicha, campo), texto_antes or VAZIO, texto_depois or VAZIO
                )
            )
    return tuple(encontradas)


def valor_alteravel(ficha: FichaDeAgendamento) -> bool:
    """Da para trocar o valor desta ficha sem adivinhar de quem e o dinheiro?

    Nao da quando a festinha tem rateio DESIGUAL: "mudou pra 800" nao diz de qual das tres, e
    escolher move dinheiro de uma mulher para a outra. Com todas no mesmo valor (o caso do "cada
    uma", que e como o card e escrito) a troca cabe nas duas — a mesma regra que
    `correcao._alvos_da_correcao` ja aplica no recibo de duas modelos.
    """
    valores = {p.valor for p in ficha.participantes}
    return len(valores) <= 1


def alteracao_do_repost(
    ficha: FichaDeAgendamento,
    lida: FichaLida,
    *,
    participantes: Sequence[ParticipanteDaFicha],
) -> AlteracaoDaFicha:
    """O que o card REPOSTADO quer mudar na ficha que ja existe (ADR-0044 §1, ticket 09).

    Chega aqui quem colidiu na chave de conteudo, e a chave nao tem valor nenhum de proposito: o
    repost EXISTE para mudar o valor. Com o valor na chave, cada negociacao criaria uma ficha nova
    e a antiga ficaria viva cobrando um numero morto — o oposto do que o gesto quer dizer.

    O que o card repostado nao diz nao muda: o telefonista que apaga a linha do transporte para
    caber a pressa nao esta pedindo para zerar o transporte. Apagar campo e gesto de painel.
    """
    return AlteracaoDaFicha(
        valor=_valor_da_participante(lida, sozinha=len(participantes) <= 1),
        valor_total=lida.valor_total,
        data=lida.data,
        hora=lida.hora,
        duracao_minutos=lida.duracao_minutos,
        cliente=lida.cliente_nome,
        forma_pagamento=lida.forma_pagamento,
        valor_transporte=lida.valor_transporte,
        valor_antecipado=lida.valor_antecipado,
        endereco=lida.endereco,
        observacoes=lida.observacoes,
    )


def montar_eco_da_alteracao(mudancas: Sequence[MudancaNaFicha]) -> str:
    """ "✏️ Alterei: valor R$ 700,00 → R$ 800,00 — corrige aí se algo estiver errado".

    Mesma forma do eco da correcao do recibo, e de proposito: sao o mesmo gesto sobre coisas
    diferentes (o combinado e o dinheiro ja recebido), e quem le o grupo nao precisa aprender duas
    gramaticas. Sem o "de", ninguem distingue "o agente alterou o que eu pedi" de "o agente
    entendeu outra coisa".
    """
    corpo = " · ".join(f"{ROTULO_DO_CAMPO[m.campo]} {m.de} → {m.para}" for m in mudancas)
    return f"✏️ Alterei: {corpo} — {CONVITE_DE_CORRECAO}"


def nome_do_atendimento(ficha: FichaDeAgendamento) -> str:
    """Como uma pergunta NOMEIA esta ficha ("Igor · R$ 700,00").

    Quem le "anulo a venda?" sem saber de qual atendimento se fala responde qualquer coisa, e a
    resposta cai no atendimento errado. Cliente e valor bastam: sao o que o telefonista tem na
    cabeca quando reage a um card.
    """
    valor = _valor_visivel(ficha)
    partes = [p for p in (ficha.cliente_nome, _reais(valor) if valor is not None else None) if p]
    return " · ".join(partes) if partes else "essa ficha"


# --- interno ------------------------------------------------------------------------------------


def _conta_rotulos(texto: str) -> int:
    """Quantos rotulos do card esta mensagem tem. Barato: um split por linha e um dict."""
    total = 0
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        rotulo, _ = _partir(linha)
        if rotulo is None:
            campo, escolhida = _linha_de_opcoes_sem_rotulo(linha)
            total += 1 if campo is not None and escolhida is not None else 0
            continue
        if rotulo in _CAMPO_POR_ROTULO or _MODELO_NUMERADA.match(rotulo):
            total += 1
    return total


def _partir(linha: str) -> tuple[str | None, str]:
    """ "📝 *Valor total:* R$ 700" -> ("valor total", "R$ 700"). Sem ":", rotulo `None`."""
    if ":" not in linha:
        return None, ""
    bruto, _, valor = linha.partition(":")
    rotulo = _sem_ornamento(bruto)
    # "Hora: 19:00" parte no PRIMEIRO ":" — o resto da linha volta inteiro, com a hora dentro.
    return (rotulo or None), valor.strip()


def _sem_ornamento(bruto: str) -> str:
    """A forma de casamento do rotulo: sem emoji, sem negrito do WhatsApp, sem acento, minusculo.

    O emoji sai porque o template inteiro e emoji + asterisco ("👤 *CLIENTE*"), e o rotulo util
    e a palavra. Sai so da BORDA: um emoji no meio de um rotulo nao existe no card e, se
    aparecer, o certo e nao reconhecer a linha em vez de reconhecer meia.
    """
    limpo = _ORNAMENTO_A_ESQUERDA.sub("", bruto)
    limpo = _ORNAMENTO_A_DIREITA.sub("", limpo)
    return normalizar(limpo)


def _texto(valor: str | None) -> str | None:
    """O valor cru do campo, sem os `( )` vazios que o template deixa quando ninguem preenche."""
    if valor is None:
        return None
    limpo = _PARENTESE.sub(" ", valor) if _so_parenteses_vazios(valor) else valor
    limpo = " ".join(limpo.split())
    return limpo or None


def _so_parenteses_vazios(valor: str) -> bool:
    return any(not m.strip() for m in _PARENTESE.findall(valor))


def _opcoes(valor: str) -> list[tuple[str, bool]]:
    """As opcoes `( ) Casa  (x) Hotel` de uma linha, como (nome normalizado, marcada).

    Vazio quando a linha nao tem parentese nenhum — e o comunicado, que ja escreve o valor
    resolvido ("Tipo: Hotel"), e quem chama cai no vocabulario direto.

    **O "X" fora do parentese e caso NORMAL**, nao degradacao rara: quem preenche no celular nao
    consegue clicar dentro de `( )` e escreve ao lado. Sao aceitas as tres grafias que aparecem —
    dentro (`(x)`), logo depois (`( ) X Hotel`) e no fim do nome (`( ) Hotel X`) — mais a marca
    no comeco da linha, antes do primeiro parentese (`X ( ) Hotel`).

    A marca colada no FIM de um nome pertence a ele, mesmo havendo outra opcao adiante: em
    "( ) Casa X ( ) Hotel" o X esta ao lado de Casa. E ambiguidade real da grafia manual, e a
    escolha e ficar com a adjacencia, que e como um humano le.
    """
    pedacos = _PARENTESE.split(valor)
    if len(pedacos) == 1:
        return []
    opcoes: list[tuple[str, bool]] = []
    for i in range(1, len(pedacos), 2):
        dentro = pedacos[i]
        seguinte = pedacos[i + 1] if i + 1 < len(pedacos) else ""
        nome, marca_no_texto = _nome_da_opcao(seguinte)
        marcada = _e_marca(dentro) or marca_no_texto
        if i == 1 and _e_marca(pedacos[0]):
            marcada = True
        if nome:
            opcoes.append((nome, marcada))
    return opcoes


def _nome_da_opcao(seguinte: str) -> tuple[str, bool]:
    """O nome da opcao que vem depois do parentese, e se ele carrega a marca."""
    tokens = [t for t in normalizar(seguinte).replace("|", " ").split() if t]
    marcada = False
    while tokens and tokens[0] in _MARCAS:
        tokens.pop(0)
        marcada = True
    while tokens and tokens[-1] in _MARCAS:
        tokens.pop()
        marcada = True
    return " ".join(tokens).strip(" -"), marcada


def _e_marca(trecho: str) -> bool:
    limpo = normalizar(trecho)
    return bool(limpo) and all(c in _MARCAS for c in limpo.split())


def _opcao[T: str](valor: str | None, vocabulario: dict[str, T]) -> T | None:
    """A opcao escolhida na linha — `None` quando nenhuma, mais de uma, ou fora do vocabulario.

    Duas marcadas devolvem `None` de proposito: o card marcado duas vezes e um card em que o
    telefonista mudou de ideia e nao apagou, e sortear entre debito e credito e mover dinheiro
    entre duas contas diferentes. Campo vazio e o custo certo — ele volta na pergunta da manha.
    """
    if valor is None:
        return None
    opcoes = _opcoes(valor)
    if opcoes:
        marcadas = [nome for nome, marcada in opcoes if marcada]
        if len(marcadas) != 1:
            return None
        return vocabulario.get(marcadas[0])
    return vocabulario.get(normalizar(valor).strip(" .-"))


def _linha_de_opcoes_sem_rotulo(linha: str) -> tuple[str | None, str | None]:
    """As duas linhas do template que sao so opcoes, sem rotulo antes do ":".

    Sao o `( ) Local proprio  ( ) Saida` e o `( ) Dinheiro  ( ) Pix  ( ) Debito ...`. Quem
    identifica cada uma e o VOCABULARIO das opcoes, nao a secao em que a linha esta: secao some no
    card degradado, opcao nao.
    """
    opcoes = _opcoes(linha)
    if not opcoes:
        return None, None
    nomes = [nome for nome, _ in opcoes]
    if any(nome in _TIPOS_DE_ATENDIMENTO for nome in nomes):
        return "tipo_atendimento", linha
    if any(nome in _FORMAS for nome in nomes):
        return "forma_pagamento", linha
    return None, None


def _nomes_das_modelas(campos: dict[str, str], numeradas: list[tuple[int, str]]) -> tuple[str, ...]:
    """Os tokens de nome do card, na ordem em que o telefonista os escreveu.

    A lista `Modelo 1..N` vence o campo `Nome da modelo` quando os dois aparecem: um card de
    festinha com o campo individual sobrando do template copiado teria a modelo errada como
    unica participante.
    """
    if numeradas:
        return tuple(nome for _, nome in sorted(numeradas))
    individual = _texto(campos.get("nome_da_modelo"))
    return (individual,) if individual else ()


def _local(campos: dict[str, str]) -> tuple[str | None, TipoDeLocal | None]:
    """Endereco e tipo de local — com o rotulo ambiguo `Local:` decidido pelo VALOR.

    O template tem `Tipo:` e `Endereco:` separados, mas quem digita escreve "Local: Hotel" e
    "Local: Rua X, 200" com a mesma palavra. O vocabulario desempata: "hotel" e tipo, "Rua X" e
    endereco. Nao havendo desempate, endereco — perder o tipo custa um campo, perder o endereco
    manda a modelo para lugar nenhum.
    """
    endereco = _texto(campos.get("endereco"))
    tipo = _opcao(campos.get("tipo_local"), _TIPOS_DE_LOCAL)
    solto = campos.get("local")
    if solto is not None:
        candidato = _opcao(solto, _TIPOS_DE_LOCAL)
        if candidato is not None and tipo is None:
            tipo = candidato
        elif candidato is None and endereco is None:
            endereco = _texto(solto)
    return endereco, tipo


def _observacoes(valor: str | None, linhas: Sequence[str], indice: int | None) -> str | None:
    """O que a modelo tem que saber para nao chegar boiando.

    O card escreve `✏️ *OBSERVACOES*` e o texto EMBAIXO, entao o valor na propria linha do rotulo
    costuma ser vazio: aqui as linhas seguintes que nao sao rotulo entram como o conteudo. A
    varredura para no primeiro rotulo conhecido — observacao e sempre a ultima secao, e engolir a
    secao seguinte transformaria um card fora de ordem num paragrafo de lixo.
    """
    if valor:
        return valor[:MAX_OBSERVACOES]
    if indice is None:
        return None
    corpo: list[str] = []
    for linha in linhas[indice + 1 :]:
        rotulo, _ = _partir(linha)
        if rotulo is not None and (rotulo in _CAMPO_POR_ROTULO or _MODELO_NUMERADA.match(rotulo)):
            break
        corpo.append(linha.strip())
    texto = " ".join(p for p in corpo if p).strip()
    return texto[:MAX_OBSERVACOES] or None


def _valor_da_participante(ficha: FichaLida, *, sozinha: bool) -> Decimal | None:
    if ficha.valor_da_modelo is not None:
        return ficha.valor_da_modelo
    return ficha.valor_total if sozinha else None


def _comunicado_bate(comunicado: FichaLida, ficha: FichaDeAgendamento, *, modelo_id: UUID) -> bool:
    if not any(p.modelo_id == modelo_id for p in ficha.participantes):
        # A modelo tem que ESTAR na ficha. A lista ja chega escopada por ela, e esta e a segunda
        # tranca do isolamento cross-modelo: sem ela, uma lista mais larga (um SELECT novo que
        # esquecesse o JOIN) faria o comunicado da Yasmin vincular a ficha da Bianca pelo nome do
        # cliente, e o pagamento de uma fecharia o atendimento da outra.
        return False
    comparacoes = 0
    cliente_do_comunicado = normalizar(comunicado.cliente_nome or "")
    cliente_da_ficha = normalizar(ficha.cliente_nome or "")
    if cliente_do_comunicado and cliente_da_ficha:
        if cliente_do_comunicado != cliente_da_ficha:
            return False
        comparacoes += 1
    valor_da_ficha = ficha.valor_de(modelo_id)
    if comunicado.valor_da_modelo is not None and valor_da_ficha is not None:
        if comunicado.valor_da_modelo != valor_da_ficha:
            return False
        comparacoes += 1
    return comparacoes > 0


def _dinheiro(valor: str | None) -> Decimal | None:
    """ "R$ 1.200,00" -> Decimal("1200.00"). Zero e valido (o Uber que a casa bancou)."""
    if not valor:
        return None
    m = _VALOR.search(valor.replace("R$", " ").replace("r$", " "))
    if m is None:
        return None
    try:
        achado = Decimal(f"{m.group(1).replace('.', '')}.{m.group(2) or '00'}")
    except InvalidOperation:  # pragma: no cover - a regex ja garante o formato
        return None
    return achado if achado >= 0 else None


def _data(valor: str | None, *, hoje: date | None) -> date | None:
    """ "22/08/2026", "22/08/26", "2026-08-22" e — com `hoje` — "22/08"."""
    if not valor:
        return None
    iso = _DATA_ISO.search(valor)
    if iso is not None:
        return _monta_data(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    m = _DATA.search(valor)
    if m is None:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    if ano is not None:
        completo = int(ano)
        return _monta_data(completo + 2000 if completo < 100 else completo, mes, dia)
    if hoje is None:
        return None
    candidato = _monta_data(hoje.year, mes, dia)
    if candidato is None:
        return None
    atrasada = (hoje.year - candidato.year) * 12 + (hoje.month - candidato.month)
    return (
        _monta_data(hoje.year + 1, mes, dia)
        if atrasada > MESES_DE_TOLERANCIA_DA_DATA
        else candidato
    )


def _monta_data(ano: int, mes: int, dia: int) -> date | None:
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _hora(valor: str | None) -> time | None:
    """ "19:00", "19h", "19h30", "19". Minuto ausente e :00 — o card escreve hora cheia."""
    if not valor:
        return None
    limpo = normalizar(valor)
    m = _HORA.search(limpo)
    if m is None:
        sozinha = _HORA_SOZINHA.match(limpo)
        if sozinha is None:
            return None
        hora, minuto = int(sozinha.group(1)), 0
    else:
        hora, minuto = int(m.group(1)), int(m.group(2) or 0)
    if hora > 23 or minuto > 59:
        return None
    return time(hour=hora, minute=minuto)


def _duracao(valor: str | None) -> int | None:
    """ "1h", "1h30", "90min", "2 horas" -> minutos. Numero solto: <= 12 e hora, acima e minuto."""
    if not valor:
        return None
    limpo = normalizar(valor)
    m = _DURACAO_H.search(limpo)
    if m is not None:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    minutos = _DURACAO_MIN.search(limpo)
    if minutos is not None:
        return int(minutos.group(1))
    solto = _DURACAO_SO_NUMERO.match(limpo)
    if solto is None:
        return None
    numero = int(solto.group(1))
    return numero * 60 if numero <= 12 else numero


def _ou[T](novo: T | None, atual: T | None) -> T | None:
    """O campo novo quando ele foi dito; o de sempre quando nao. Nao ha como apagar por aqui."""
    return atual if novo is None else novo


def _valor_visivel(ficha: FichaDeAgendamento) -> Decimal | None:
    """O numero que representa esta ficha para quem le no grupo.

    O valor DA MODELO quando todas estao no mesmo (o caso do "cada uma", e o caso individual);
    o total quando o rateio e desigual e nao ha um numero unico que sirva. Nunca o total no lugar
    do valor de uma: numa festinha de R$ 2.000 com tres modelos, ecoar 2.000 para uma delas
    entrega a conta da outra.
    """
    valores = {p.valor for p in ficha.participantes if p.valor is not None}
    if len(valores) == 1:
        return valores.pop()
    return ficha.valor_total


def _reais(valor: Decimal | None) -> str:
    return formatar_reais(valor) if valor is not None else VAZIO


def _dia(quando: date | None) -> str:
    return f"{quando:%d/%m}" if quando else VAZIO


def _relogio(quando: time | None) -> str:
    return f"{quando:%H:%M}" if quando else VAZIO


def _duracao_legivel(minutos: int | None) -> str:
    return formatar_duracao(minutos) if minutos else VAZIO


# --- a metrica que estes dois campos existem para render (ticket 16) ----------------------------
#
# Read models da PERGUNTA do dono — *"quanto que o anuncio fake esta fazendo e quanto que o anuncio
# original esta fazendo"* (spec 0006 §45) e, mais fino, por qual site a venda entrou (§68). Moram
# aqui, ao lado do vocabulario de contratacao que os alimenta, porque `origem` e `site` sao o mesmo
# par de campos do card do comeco (o telefonista marcando) ao fim (o dono decidindo onde investir).
#
# **A fatia "nao dito" e uma linha do relatorio, nao um filtro.** Sem ela, dois anuncios sem origem
# no periodo fariam o fake parecer maior do que e — e o relatorio nao mostraria que a diferenca e
# ignorancia, nao mercado.


@dataclass(frozen=True)
class FaturamentoPorOrigem:
    """Quanto cada eixo (proprio x fake x nao dito) faturou no periodo."""

    origem: OrigemDoAnuncio | None
    vendas: int
    total: Decimal


@dataclass(frozen=True)
class FaturamentoPorSite:
    """Quanto cada plataforma faturou no periodo. `site=None` = a venda nao disse por onde entrou."""

    site: str | None
    vendas: int
    total: Decimal
