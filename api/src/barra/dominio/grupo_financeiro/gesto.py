"""O gesto emoji sobre a Ficha de agendamento: o ✅ e o ❌ do telefonista (spec 0006, tickets 08/20).

Funcao **pura**, sem I/O: entra o emoji que caiu sobre uma mensagem e o retrato da ficha que ela
originou, sai a DECISAO — promover, cancelar, reabrir, desfazer, perguntar ou ignorar. Persistir,
ler a ficha e falar no grupo e problema de quem chama, como no `razao.py`.

Ela existe separada da ficha por um motivo de fronteira: o TRANSPORTE do gesto (a grafia do evento
de reacao da EvoGo) **ainda nao foi capturado em producao** e nao e adivinhavel — o webhook nao
consegue construir uma reacao hoje (ver `webhook/parser.py::extrair_gesto` e
`.scratch/agente-financeiro-v2/PAYLOAD-EVOGO.md`). O que NAO depende da grafia e a regra, e a regra
e isto aqui: escrita, testada e pronta para ser ligada no dia em que o envelope real chegar.

O que o dominio diz, e que este modulo implementa:

* **O ✅ e a SEGUNDA PORTA do mesmo fato** (ADR-0046 §5). Ele nao significa "o cliente confirmou":
  o telefonista o da DEPOIS de a modelo avisar que recebeu (*"depois que ela mandar o OK, o
  selo"*). Entao ele **promove a ficha a Venda registrada** — e o que vier primeiro promove; o
  segundo nao duplica. Por isso `so_marcar_realizada` existe como efeito proprio: e o caso em que
  a fala da modelo ja criou a linha e o ✅ chega depois. Nenhuma porta cria a segunda linha.
* **A promocao e CALADA.** O ✅ nao rende recibo em tempo real: a venda nasce sem forma de
  pagamento, e a forma e cobrada uma vez por dia pela rotina da manha, no mesmo lugar em que ela
  ja e cobrada (`pendencia.py` -> `rotina.py`). Metralhar a modelo na hora e o que o dominio
  proibe.
* **Nunca apagar dinheiro em silencio.** ❌ sobre ficha que **ja virou venda** nao anula nada:
  devolve UMA pergunta que nomeia o atendimento. Mesma disciplina do comprovante ambiguo.
* **Nem criar dinheiro em silencio.** ✅ sobre ficha **cancelada** tambem vira pergunta: os dois
  gestos se contradizem, e o desempate por palpite e o erro que ninguem mais descobre.
* **Remover a reacao desfaz o que ELA causou, e so isso** (ticket 20). Se a venda nasceu da fala
  da modelo, tirar o ✅ nao mexe no dinheiro — ele nunca foi a porta daquela linha.
* **Emoji fora do vocabulario e ignorado com log**, sem tocar em estado nenhum. O grupo reage com
  ❤️, 👏 e 🔥 o tempo todo.

Duas decisoes de gravacao que evitam migration nova (o schema da onda 20260820 ja esta escrito):

* **Quem promoveu fica no `campo` do evento `realizacao`** (`PORTA_DA_REACAO` x
  `PORTA_DO_PAGAMENTO`). O CHECK da tabela so *exige* `campo` para `alteracao` — nao o proibe nos
  outros tipos. Sem esse carimbo nao da para saber se o ✅ pode ou nao desfazer a venda, e a
  alternativa (adivinhar pelo `mensagem_id` nulo) confunde o gesto com o lancamento do painel.
* **O desfazer e uma `alteracao` do campo `estado`**, com de->para. Os tipos permitidos sao
  `alteracao | confirmacao | realizacao | cancelamento`: nao ha "reabertura", e inventa-la exigiria
  mexer numa migration ja escrita. A `alteracao` diz exatamente o que aconteceu — um campo mudou —
  e mantem a auditoria append-only legivel.
  Pelo mesmo motivo `cancelamento` e `realizacao` levam `valor_anterior`: e dali que sai o estado
  para o qual a ficha VOLTA quando a reacao e removida.

O que NAO mora aqui: quem e o dono da ficha (resolver closed-world por modelo, ADR-0046 §2), a
leitura do card, a escrita da venda e a pergunta chegando de volta. E, deliberadamente, **nao ha
regra de papel do autor**: "o ❌ e so do telefonista" nao vira gate porque `vendedores.whatsapp_jid`
e closed-world e nasce vazio — negar por autor desconhecido desligaria o recurso no primeiro dia, e
um ✅ dado pela propria modelo e o mesmo fato dito pela outra voz (ADR-0048: autor desconhecido ->
sem vendedor, nunca chute). O unico gate de autoria e na REMOCAO, onde ela e barata e necessaria:
quem tira uma reacao so pode tirar a que ele mesmo pos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.dedup import chave_de_conteudo
from barra.dominio.grupo_financeiro.recibo import formatar_reais

EstadoDaFicha = Literal["aberta", "confirmada", "realizada", "cancelada"]
"""Espelho de `barravips.ficha_estado_enum` (migration 20260820121000).

Duplicado aqui de proposito enquanto `ficha.py` nao publica o dele: Literal e estrutural no mypy,
entao os dois sao o MESMO tipo para quem chama, e um modulo puro nao pode depender de outro que
ainda esta sendo escrito. Quando a ficha publicar `EstadoDaFicha`, este vira alias daquele.
"""

ESTADO_INICIAL: EstadoDaFicha = "aberta"

ESTADOS_COBRAVEIS: tuple[EstadoDaFicha, ...] = ("aberta", "confirmada")
"""Ficha que a rotina da manha ainda cobra ("o do Igor de ontem rolou?").

E o outro lado do ❌: cancelar tem que **parar a cobranca**, e o unico jeito de as duas metades
nunca discordarem e a lista viver num lugar so. Espelha o indice parcial
`fichas_de_agendamento_abertas_idx ... WHERE estado IN ('aberta','confirmada')`.
"""

SinalDoGesto = Literal["check", "cancela"]
"""O que o emoji QUER dizer, ja normalizado. O vocabulario e fechado por decisao: emoji que nao
esta nele nao e sinal nenhum, e virar palpite ("👍 deve ser um ✅") criaria venda por engano."""

PORTA_DA_REACAO = "reacao"
"""Carimbo de quem promoveu a ficha, gravado em `ficha_de_agendamento_eventos.campo`."""

PORTA_DO_PAGAMENTO = "pagamento"
"""O outro valor do mesmo carimbo — a fala da modelo (ticket 07). Vive aqui para as duas portas
lerem a MESMA constante: e por ele que a remocao do ✅ sabe se pode ou nao desfazer a venda."""

CAMPO_DO_ESTADO = "estado"
"""`campo` do evento de `alteracao` que registra o desfazer (de->para do proprio estado)."""

# Emoji com a mesma intencao. Guardados SEM seletor de variacao (U+FE0F): "✔️" e "✔" chegam dos
# dois jeitos conforme o teclado, e a diferenca e invisivel para o humano que reagiu.
_CHECK = frozenset({"✅", "✔", "☑", "🆗"})
_CANCELA = frozenset({"❌", "❎", "✖", "🚫"})

# Seletores de variacao, ZWJ e tons de pele: enfeite de renderizacao que nao muda a intencao.
_ENFEITES = frozenset({"\ufe0f", "\ufe0e", "\u200d", *(chr(c) for c in range(0x1F3FB, 0x1F400))})


def _limpar(emoji: str) -> str:
    return "".join(c for c in emoji.strip() if c not in _ENFEITES)


def ler_sinal(emoji: str) -> SinalDoGesto | None:
    """O que este emoji significa para a ficha — `None` quando nao significa nada.

    `None` tambem para a string VAZIA, e isso e proposital: emoji vazio nao e "emoji desconhecido",
    e a REMOCAO da reacao (a plataforma avisa que a reacao saiu mandando o texto vazio). Quem
    precisa dessa distincao usa `GestoNaFicha.eh_remocao`.
    """
    limpo = _limpar(emoji)
    if not limpo:
        return None
    if limpo in _CHECK:
        return "check"
    if limpo in _CANCELA:
        return "cancela"
    return None


@dataclass(frozen=True)
class GestoNaFicha:
    """A reacao como o dominio a ve: um emoji, de alguem, sobre a mensagem de uma ficha.

    Nao e o evento do webhook (`ReacaoEvolution`) nem o da porta (`ReacaoNoGrupo`): esses carregam
    envelope, e este carrega intencao. A traducao entre eles e de quem liga o transporte — e e a
    unica parte que espera a grafia real da EvoGo.
    """

    emoji: str
    autor_jid: str | None = None

    @property
    def eh_remocao(self) -> bool:
        """Reacao RETIRADA. A plataforma nao diz qual emoji saiu (o texto vem vazio) — quem diz e
        o estado da ficha, que so chegou onde esta por causa da reacao que estava la."""
        return not _limpar(self.emoji)


@dataclass(frozen=True)
class AlvoDoGesto:
    """O retrato da ficha que o gesto atingiu — so o que a decisao precisa saber.

    Projecao de LEITURA, montada por quem chama a partir da ficha e do rastro dela. Deliberadamente
    magra: se este dataclass crescer para o card inteiro, a decisao passa a depender de campo que
    nao muda decisao nenhuma, e o teste da tabela vira preenchimento de formulario.
    """

    estado: EstadoDaFicha
    venda_id: UUID | None = None
    """Venda registrada VIVA nascida desta ficha. Preenchida = o fato ja entrou pela outra porta,
    e o gesto nao pode criar a segunda linha."""
    promovida_por: str | None = None
    """`PORTA_DA_REACAO` ou `PORTA_DO_PAGAMENTO` — o `campo` do evento `realizacao`. E o que
    autoriza (ou proibe) a remocao do ✅ a desfazer a venda."""
    estado_anterior: EstadoDaFicha | None = None
    """Para onde a ficha VOLTA se a reacao for removida: o `valor_anterior` do ultimo evento de
    `realizacao`/`cancelamento`. Ausente = `aberta`, que e onde toda ficha nasce."""
    autor_do_gesto_vigente: str | None = None
    """Quem pos a reacao que esta valendo. So a remocao usa: reacao e por pessoa, e a saida da
    reacao de um nao pode desfazer a decisao do outro."""
    cliente: str | None = None
    valor: Decimal | None = None
    """Cliente e valor entram so para a pergunta NOMEAR o atendimento — quem le "anulo a venda?"
    sem saber qual responde qualquer coisa, e a resposta cai na venda errada."""


EfeitoDoGesto = Literal[
    "promover_a_venda",
    "so_marcar_realizada",
    "cancelar",
    "reabrir",
    "desfazer_promocao",
    "perguntar",
    "ignorar",
]
"""O que quem chama tem que FAZER. Um efeito = uma acao, sem sobreposicao: `promover_a_venda` cria
a linha, `so_marcar_realizada` nunca cria (a linha ja existe pela outra porta), `desfazer_promocao`
anula a que o proprio ✅ criou."""

MotivoDoGesto = Literal[
    "sem_ficha_alvo",
    "emoji_fora_do_vocabulario",
    "check_do_telefonista",
    "venda_ja_registrada",
    "cancelamento_do_telefonista",
    "cancelamento_com_venda",
    "check_sobre_ficha_cancelada",
    "remocao_do_check",
    "remocao_do_cancelamento",
    "remocao_de_outro_autor",
    "venda_de_outra_porta",
    "gesto_sem_efeito",
]
"""Por que o efeito foi esse — o que vai para o log e para o `ResultadoDaPorta` quando o transporte
existir. Espelha o `MotivoSemVenda` da porta: motivo visivel e o que impede o gesto ignorado de
virar um bug mudo."""

TipoDeEventoDaFicha = Literal["alteracao", "confirmacao", "realizacao", "cancelamento"]
"""Espelho do CHECK de `ficha_de_agendamento_eventos.tipo`."""


@dataclass(frozen=True)
class EventoDaFicha:
    """A linha de auditoria que este gesto manda gravar — append-only, como a da venda."""

    tipo: TipoDeEventoDaFicha
    campo: str | None = None
    valor_anterior: str | None = None
    valor_novo: str | None = None


@dataclass(frozen=True)
class DecisaoDoGesto:
    """O que fazer com a ficha. `estado_resultante is None` = nao mexe no estado."""

    efeito: EfeitoDoGesto
    motivo: MotivoDoGesto
    estado_resultante: EstadoDaFicha | None = None
    evento: EventoDaFicha | None = None
    pergunta: str | None = None
    """UMA pergunta, so nos dois casos em que o silencio erraria com dinheiro. Nos outros e `None`
    — o gesto e calado, como a gravacao da ficha."""


def decidir_gesto(gesto: GestoNaFicha, alvo: AlvoDoGesto | None) -> DecisaoDoGesto:
    """A decisao inteira do ✅/❌, em uma funcao pura.

    `alvo is None` e o caso COMUM, nao o excepcional: a maior parte das reacoes do grupo cai sobre
    mensagem que nao e ficha nenhuma (o recibo, a foto do comprovante, a conversa). Sai ignorada.
    """
    if alvo is None:
        return DecisaoDoGesto("ignorar", "sem_ficha_alvo")
    if gesto.eh_remocao:
        return _decidir_remocao(gesto, alvo)
    sinal = ler_sinal(gesto.emoji)
    if sinal is None:
        return DecisaoDoGesto("ignorar", "emoji_fora_do_vocabulario")
    if sinal == "check":
        return _decidir_check(alvo)
    return _decidir_cancelamento(alvo)


def _decidir_check(alvo: AlvoDoGesto) -> DecisaoDoGesto:
    if alvo.estado == "cancelada":
        # Os dois gestos se contradizem. Ressuscitar em silencio criaria receita sobre um "nao
        # rolou" deliberado; calar esconderia o ✅. Uma pergunta, e o humano desempata.
        return DecisaoDoGesto(
            "perguntar",
            "check_sobre_ficha_cancelada",
            pergunta=_pergunta_do_check_sobre_cancelada(alvo),
        )
    if alvo.venda_id is not None:
        # A outra porta chegou primeiro (ADR-0046 §5). O ✅ nao duplica: no maximo alinha o estado
        # da ficha, quando a promocao veio de fora dela.
        if alvo.estado == "realizada":
            return DecisaoDoGesto("ignorar", "venda_ja_registrada")
        return DecisaoDoGesto(
            "so_marcar_realizada",
            "venda_ja_registrada",
            estado_resultante="realizada",
            evento=_evento_de_realizacao(alvo.estado),
        )
    return DecisaoDoGesto(
        "promover_a_venda",
        "check_do_telefonista",
        estado_resultante="realizada",
        evento=_evento_de_realizacao(alvo.estado),
    )


def _decidir_cancelamento(alvo: AlvoDoGesto) -> DecisaoDoGesto:
    if alvo.estado == "cancelada":
        return DecisaoDoGesto("ignorar", "gesto_sem_efeito")
    if alvo.venda_id is not None:
        return DecisaoDoGesto(
            "perguntar", "cancelamento_com_venda", pergunta=_pergunta_do_cancelamento(alvo)
        )
    return DecisaoDoGesto(
        "cancelar",
        "cancelamento_do_telefonista",
        estado_resultante="cancelada",
        evento=EventoDaFicha("cancelamento", valor_anterior=alvo.estado, valor_novo="cancelada"),
    )


def _decidir_remocao(gesto: GestoNaFicha, alvo: AlvoDoGesto) -> DecisaoDoGesto:
    if (
        gesto.autor_jid is not None
        and alvo.autor_do_gesto_vigente is not None
        and gesto.autor_jid != alvo.autor_do_gesto_vigente
    ):
        # Reacao e por pessoa: o 👏 que a modelo tirou da mesma mensagem nao pode desfazer o ✅ do
        # telefonista. Sem os dois autores nao da para afirmar nada, e o gesto segue.
        return DecisaoDoGesto("ignorar", "remocao_de_outro_autor")
    if alvo.estado == "cancelada":
        return DecisaoDoGesto(
            "reabrir",
            "remocao_do_cancelamento",
            estado_resultante=_volta_para(alvo),
            evento=_evento_de_volta("cancelada", _volta_para(alvo)),
        )
    if alvo.estado != "realizada":
        return DecisaoDoGesto("ignorar", "gesto_sem_efeito")
    if alvo.venda_id is not None and alvo.promovida_por != PORTA_DA_REACAO:
        # A venda nasceu da fala da modelo. Tirar o ✅ desfaz o que o ✅ causou — e ele nao causou
        # essa linha. Apagar dinheiro aqui seria desfazer a palavra de quem recebeu.
        return DecisaoDoGesto("ignorar", "venda_de_outra_porta")
    return DecisaoDoGesto(
        "desfazer_promocao",
        "remocao_do_check",
        estado_resultante=_volta_para(alvo),
        evento=_evento_de_volta("realizada", _volta_para(alvo)),
    )


def _volta_para(alvo: AlvoDoGesto) -> EstadoDaFicha:
    """Para onde a ficha volta. Cancelada nunca e destino de volta: o gesto que se desfez foi
    justamente o que a levou ate la, e reabrir para `cancelada` seria nao reabrir."""
    anterior = alvo.estado_anterior
    if anterior is None or anterior == alvo.estado or anterior == "cancelada":
        return ESTADO_INICIAL
    return anterior


def _evento_de_realizacao(estado: EstadoDaFicha) -> EventoDaFicha:
    return EventoDaFicha(
        "realizacao",
        campo=PORTA_DA_REACAO,
        valor_anterior=estado,
        valor_novo="realizada",
    )


def _evento_de_volta(de: EstadoDaFicha, para: EstadoDaFicha) -> EventoDaFicha:
    return EventoDaFicha("alteracao", campo=CAMPO_DO_ESTADO, valor_anterior=de, valor_novo=para)


def _nome_do_alvo(alvo: AlvoDoGesto) -> str:
    partes = [p for p in (alvo.cliente, alvo.valor and formatar_reais(alvo.valor)) if p]
    return " · ".join(partes) if partes else "essa ficha"


def _pergunta_do_cancelamento(alvo: AlvoDoGesto) -> str:
    return f"❌ em {_nome_do_alvo(alvo)}, que já está registrado. Anulo a venda?"


def _pergunta_do_check_sobre_cancelada(alvo: AlvoDoGesto) -> str:
    return f"✅ em {_nome_do_alvo(alvo)}, que está como cancelado. Registro assim mesmo?"


def chave_da_venda_da_ficha(
    *,
    data_da_ficha: date,
    valor: Decimal,
    modelo_id: UUID,
    cliente: str | None,
) -> str:
    """A chave de conteudo da venda que NASCE de uma ficha — a mesma pelas DUAS portas.

    E aqui que a idempotencia do ticket 20 se decide, e e aqui que o bug moraria. A chave do modulo
    e `data | valor | modelo | cliente` (`dedup.chave_de_conteudo`), e `data` e o campo perigoso:
    a fala da modelo chega no dia do pagamento e o ✅ pode vir no outro, entao datar pelo dia do
    GESTO faria as duas portas calcularem chaves diferentes e nascerem DUAS vendas do mesmo
    atendimento — com o indice unico parcial achando tudo em ordem.

    Por isso a venda que herda de uma ficha e datada pela **data da ficha**, venha ela de que porta
    vier. Quem promover pelo pagamento (ticket 07) chama esta funcao, nao a de baixo.
    """
    return chave_de_conteudo(data=data_da_ficha, valor=valor, modelo_id=modelo_id, cliente=cliente)
