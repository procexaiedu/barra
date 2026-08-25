"""Entidades do Grupo financeiro (spec 0005).

`MensagemDoGrupo` e o TIPO DE ENTRADA da porta unica — o formato que o webhook, os testes e o
futuro replay do export da Yasmin constroem. De proposito ele NAO e o `MensagemEvolution` do
webhook: a porta precisa ser alimentavel por quem nao tem envelope da Evolution (uma linha de
`_chat.txt` nao tem `instance`, nem `key.id`, nem base64), e o replay so vale como prova se
entrar pela mesma porta que a producao (licao do harness fiel).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

TipoMensagem = Literal["texto", "audio", "imagem"]

FormaPagamento = Literal["pix", "dinheiro", "debito", "credito", "link"]
"""Como a venda foi paga. `None` na Venda registrada e a **Pendencia** mais comum do grupo: o
anuncio SEMPRE precede o pagamento ("Foi pix ou din ?" chega horas ou dias depois).

**"Cartao" nao existe** (ADR-0046 §4, ticket 11): ele foi desmembrado em `debito`, `credito` e
`link`, porque sao operacoes diferentes e cada uma concilia no seu extrato — o credito tem taxa de
parcelamento, o link nem passa maquininha. Guardar "cartao" como guarda-chuva obrigaria o operador
a abrir a venda para saber em qual extrato procurar, que e exatamente a conferencia que ele faz.

As cinco sao as MESMAS do `( ) Dinheiro ( ) Pix ( ) Debito ( ) Credito ( ) Link` do card
(`FormaDaFicha`, `ficha.py`) e as mesmas do CHECK de `vendas_registradas.forma_pagamento` — que e
`text` com CHECK, e nao enum, justamente para crescer sem migration de tipo.

Nenhuma das tres formas de cartao espera comprovante Pix (`pendencia.espera_comprovante`) nem
quita Cobranca da agencia: a prova do cartao e o print da maquininha, que nao passa pelo OCR de
comprovante. O que decide se ela DEBITA a modelo e o `bolso` da venda (ADR-0047), por evidencia —
nunca a forma, e nunca o cadastro dela."""

# O grupo vive em horario de Brasilia e anuncia a venda no MESMO dia — muitas vezes de madrugada
# ("[10/08/2026, 01:09:08] Atendimento no nosso local"). Datar pelo UTC jogaria toda venda
# anunciada depois das 21h para o dia seguinte e desalinharia o Fechamento do que a gestora conta.
BRT = ZoneInfo("America/Sao_Paulo")

# Largura do balde temporal da chave de conteudo (mensagem sem id). A entrega dupla do router
# chega com 1-56 ms de diferenca (vault myeye/ia-notas-resposta-duplicada-janela-1s); 5 s cobre
# isso com folga de fila. Tradeoff aceito, o mesmo do myEYE: duas mensagens IDENTICAS, do mesmo
# autor, de proposito, dentro do mesmo balde contam como uma.
BUCKET_DEDUP_S = 5


def _agora() -> datetime:
    return datetime.now(UTC)


def dia_brt(momento: datetime) -> date:
    """Dia (BRT) de um instante — a data com que o grupo conta a venda.

    Vive solto (e nao so como metodo de `MensagemDoGrupo`) porque a Venda registrada que nasce
    de uma resposta a pergunta minima (ticket 03) e datada pelo dia do ANUNCIO, e o anuncio ali
    e uma mensagem ja persistida (`MensagemRegistrada`), nao a que acabou de chegar.
    """
    return momento.astimezone(BRT).date()


PapelDoGrupo = Literal["modelo", "fichas", "caixa_telefonistas"]
"""Para que serve este grupo cadastrado (`grupos_financeiros.papel`, ADR-0046 §2).

* `modelo` — o Grupo financeiro individual de sempre: uma modelo, os gestores e a IA. O JID
  resolve a dona, e e dela todo dinheiro que passa por ali.
* `fichas` — o **Grupo de fichas**, so dos telefonistas, onde a ficha COMPLETA e postada enquanto
  o grupo individual recebe so o Comunicado. **Nao tem dona**: a modelo do card vem do campo
  `Nome da modelo` pelo resolver closed-world, nunca do JID. Arranjo em teste (a reuniao de 20/08
  disse "a gente pode testar"), e e justamente por isso que o codigo nao pode deduzir a modelo do
  grupo em que o card caiu.
* `caixa_telefonistas` — a conferencia, todas as modelos num lugar so. Entra **em leitura**
  apenas (spec 0006); a IA nunca escreve la.
"""


@dataclass(frozen=True)
class GrupoSemDona:
    """Grupo cadastrado que NAO pertence a uma modelo — o Grupo de fichas e o caixa.

    Tipo proprio, e nao `GrupoFinanceiro` com `modelo_id=None`, porque a diferenca entre os dois e
    exatamente o que quebra calado: `modelo_id` atravessa este modulo inteiro (a venda e dela, a
    cobranca e dela, a pendencia e dela) e um `None` escorregando por ali viraria "a modelo None"
    numa escrita, sem levantar em lugar nenhum. Com dois tipos, quem esquecer o caso novo nao
    compila — que e o mesmo motivo pelo qual o banco poe um CHECK entre `papel` e `modelo_id`.
    """

    id: UUID
    papel: Literal["fichas", "caixa_telefonistas"]
    """`modelo` nao cabe aqui de proposito: se coubesse, este tipo seria so um `GrupoFinanceiro`
    esquecido."""
    jid: str
    nome: str


@dataclass(frozen=True)
class GrupoFinanceiro:
    """Vinculo closed-world grupo<->modelo. Sem linha ativa, o grupo nao existe para o agente."""

    id: UUID
    modelo_id: UUID
    jid: str
    nome: str
    numero_modelo: str | None = None
    """O WhatsApp cadastrado da modelo — o unico jeito de saber se quem escreveu no grupo foi ELA
    (ticket 12: so a dona do grupo ensina a propria chave Pix). Opcional porque quem varre grupos
    pelo relogio (a rotina da manha) nao precisa dele; ausente, a resposta e sempre "nao foi ela",
    que e o lado seguro."""


GrupoCadastrado = GrupoFinanceiro | GrupoSemDona
"""O que `grupos_financeiros` pode devolver para um JID. Quem so sabe lidar com a modelo continua
pedindo `GrupoFinanceiro` (`buscar_grupo_por_jid`) e recebe `None` para os outros papeis — o
mesmo silencio de sempre, que e o default seguro do numero compartilhado."""


AUDIO_SEM_TRANSCRICAO = "[audio que nao consegui ouvir]"
"""O que fica no log de origem quando o audio nao rendeu texto (mesma frase do agente de venda).

Um carimbo, e nao a linha vazia: quem abrir o log do grupo no painel para entender por que uma
venda nao foi registrada precisa ver que houve um audio e que ele nao foi ouvido. E deliberado que
ele nao pareca fala — nenhum leitor deste modulo o confunde com anuncio, valor ou forma de
pagamento, entao ele atravessa o contexto sem significar nada."""


@dataclass(frozen=True)
class AudioDoGrupo:
    """O audio que veio junto com a mensagem — bytes ja decifrados, prontos para ouvir.

    Os bytes viajam AQUI, e nao numa URL, porque a `media_url` da Evolution aponta para o CDN
    cifrado do WhatsApp (inutil sem a mediaKey) e a EvoGo nem isso entrega: quem sabe buscar a
    midia e o webhook, e ele ja a tem na mao quando chama a porta. E conteudo da mensagem, nao
    transporte — o mesmo motivo pelo qual `texto` mora aqui.

    Sem MinIO de proposito: o audio do Grupo financeiro nao vira objeto guardado. O que este
    modulo precisa guardar do audio e o que foi DITO nele, e isso vai para `texto` no log de
    origem; reter o arquivo seria acumular a voz da modelo sem nenhum uso previsto.
    """

    conteudo: bytes
    mimetype: str | None = None


@dataclass(frozen=True)
class ImagemDoGrupo:
    """A imagem que veio com a mensagem — bytes ja decifrados, prontos para ler (ticket 07).

    Gemea de `AudioDoGrupo` e pelos mesmos motivos (os bytes viajam aqui porque quem sabe busca-los
    e o webhook; sem MinIO porque nao ha uso previsto para o arquivo depois de lido). Tipo proprio
    e nao um `AudioDoGrupo` renomeado: sao dois destinos diferentes (STT x OCR) e o dia em que um
    ganhar um campo o outro nao deve herda-lo.

    O que fica guardado da imagem e o que ela DIZ — o comprovante lido em
    `comprovantes_do_grupo`, nao a foto.
    """

    conteudo: bytes
    mimetype: str | None = None


@dataclass(frozen=True)
class MensagemDoGrupo:
    """Uma mensagem crua de um Grupo financeiro, ja normalizada e sem envelope de transporte."""

    grupo_jid: str
    texto: str
    tipo: TipoMensagem = "texto"
    audio: AudioDoGrupo | None = None
    """Preenchido quando `tipo == "audio"` e o webhook conseguiu os bytes. Ausente com
    `tipo == "audio"` (MinIO fora, download barrado) e o mesmo caso de transcricao que falhou: a
    mensagem existe no log, nao diz nada, e o que dependia dela continua pendente."""
    imagem: ImagemDoGrupo | None = None
    """Idem para `tipo == "imagem"`: sem bytes nao ha OCR, e o comprovante fica esperando o
    reenvio que o agente pede."""
    evolution_message_id: str | None = None
    autor_jid: str | None = None
    autor_nome: str | None = None
    de_mim: bool = False
    caption: str | None = None
    media_url: str | None = None
    quoted_message_id: str | None = None
    recebida_em: datetime = field(default_factory=_agora)

    def chave_dedup(self) -> str:
        """Chave de idempotencia da ENTREGA (uma por mensagem, nunca nula).

        O router do numero ProceX entrega a mesma requisicao duas vezes e o app e quem absorve.
        Com id de mensagem a chave e ele. Sem id — envelope da EvoGo que nao expoe o ID, replay,
        import do export — cai no conteudo + balde de tempo: a alternativa (gravar NULL) NAO
        deduplica, porque no Postgres cada NULL e distinto e o indice unico nunca colide. Foi
        esse detalhe que deixou o myEYE respondendo 2x com o indice ja aplicado.

        **O corpo precisa dos discriminadores de MIDIA.** Para audio e imagem, `texto` ainda e ""
        neste ponto (a transcricao so e gravada depois, quando a porta ja decidiu pagar STT) e
        `caption` costuma ser nula: sem `tipo` e sem os bytes, dois comprovantes DIFERENTES
        postados em sequencia dentro do mesmo balde de 5 s produziriam a mesma chave, e o segundo
        morreria como entrega duplicada — dinheiro que nunca abate venda, sem uma linha de erro em
        lugar nenhum. Os bytes entram como digest (nao como conteudo) porque a chave e curta e
        legivel por design; a `media_url` entra junto porque e o unico discriminador que sobra
        quando os bytes nao vieram.
        """
        if self.evolution_message_id:
            return f"evo:{self.evolution_message_id}"
        balde = int(self.recebida_em.timestamp()) // BUCKET_DEDUP_S
        corpo = "|".join(
            [
                self.grupo_jid,
                self.autor_jid or "",
                self.tipo,
                self.texto,
                self.caption or "",
                self.media_url or "",
                self._digest_da_midia(),
                str(balde),
            ]
        )
        return f"conteudo:{hashlib.sha256(corpo.encode('utf-8')).hexdigest()}"

    def _digest_da_midia(self) -> str:
        """Impressao digital dos bytes que vieram junto — "" quando nao veio nenhum."""
        conteudo = (
            self.audio.conteudo if self.audio else (self.imagem.conteudo if self.imagem else None)
        )
        if not conteudo:
            return ""
        return hashlib.sha256(conteudo).hexdigest()[:32]

    def dia_brt(self) -> date:
        """Dia (BRT) em que a mensagem chegou — a data DEFAULT da Venda registrada.

        O grupo anuncia a venda no dia em que ela aconteceu e nao escreve data nenhuma; o dia da
        mensagem e, na pratica, o dado. Data dita no texto e correcao (ticket 05), nao extracao.
        """
        return dia_brt(self.recebida_em)


@dataclass(frozen=True)
class MensagemRegistrada:
    """Uma mensagem do grupo JA persistida — o contexto que a porta relê para se situar.

    E o que sustenta os dois vai-e-vens do ticket 03 SEM tabela de estado nova: o "600" solto
    que responde a pergunta minima e o "Sim" que responde "Foi pix tambem amiga ?" so significam
    alguma coisa a luz do que veio antes, e o que veio antes ja esta no log de origem. Estado
    derivado do log sobrevive a restart do worker; estado em memoria, nao.

    `tem_venda` e o que distingue anuncio JA registrado de anuncio esperando o que falta.
    """

    id: UUID
    texto: str
    de_mim: bool
    recebida_em: datetime
    evolution_message_id: str | None = None
    """O id da mensagem NA PLATAFORMA — o unico endereco que o WhatsApp entende para citar.

    Sem ele a porta so sabe apontar para a mensagem que acabou de entrar, e o recibo de uma venda
    que nasceu da resposta a pergunta minima ("600") citaria o "600" em vez do ANUNCIO. Quem
    corrigisse respondendo esse recibo nao acharia venda nenhuma: a venda esta ancorada no
    anuncio. Nulo para a fala reservada da rotina da manha, que nasce sem passar pela plataforma.
    """
    tem_venda: bool = False

    def dia(self) -> date:
        return dia_brt(self.recebida_em)


@dataclass(frozen=True)
class VendaRegistrada:
    """Uma Venda registrada ja persistida (ADR-0043): o minimo e modelo + valor + data.

    Cliente e TEXTO LIVRE e nunca vira linha em `clientes` — o Cliente do sistema e telefone
    E.164 e no grupo nao existe telefone. Local, duracao e forma de pagamento sao opcionais: a
    falta deles gera Pendencia (tickets 03 em diante), nunca ausencia de registro.
    """

    id: UUID
    modelo_id: UUID
    valor: Decimal
    data: date
    mensagem_id: UUID
    cliente_nome: str | None = None
    local_atendimento: str | None = None
    duracao_minutos: int | None = None
    forma_pagamento: FormaPagamento | None = None
    comprovante_id: UUID | None = None
    """O Comprovante de transferencia que abateu esta venda (ticket 07). Nulo numa venda **pix** e
    a **Pendencia de comprovante**; em dinheiro nao significa nada (o cash fica com a modelo e
    nunca entra na expectativa de comprovante)."""
    anulada_em: datetime | None = None
    """Preenchido = a mensagem-fonte foi apagada no grupo e a venda nao vale mais (ticket 05).
    Toda leitura do modulo devolve so linha VIVA; a anulada existe para o rastro e para o painel.
    """
    recebido_por_modelo_id: UUID | None = None
    """Quem ficou com o dinheiro DESTA venda, quando nao foi a propria modelo (ticket 13).

    `None` = ela mesma, que e o caso de quase toda venda. Preenchido so na **festinha em que uma
    recebeu por todas**: as N vendas continuam sendo N linhas, uma por modelo e cada uma no valor
    dela (ADR-0043) — o faturamento individual nao se mexe —, mas o DEBITO do bruto vai para quem
    esta com o dinheiro na mao (ADR-0045 §6).

    Consequencia imediata aqui: quem nao recebeu nao tem comprovante a mandar, entao ela sai da
    expectativa de comprovante (`pendencia.pendencias_da_venda`) e a venda dela entra na fila de
    abate de QUEM recebeu (`repo.vendas_pix_a_comprovar`). Cobrar comprovante das tres que nunca
    viram o dinheiro e a cobranca que volta identica todo dia sem que ninguem possa resolve-la.

    O repasse ENTRE modelos fica fora do sistema (ADR-0045 §6): a casa fecha com cada uma."""


@dataclass(frozen=True)
class VendaNoPainel:
    """Uma Venda registrada como o operador a le (ticket 11): a venda + o que so o painel mostra.

    Composicao e nao heranca/campo novo: `VendaRegistrada` e o que o agente decide sobre dinheiro,
    e nada aqui pode virar entrada dele. O nome da modelo e a chave de destino do comprovante sao
    JOIN de leitura — existem para o humano conferir, nunca para o resolver de nomes ou para a
    classificacao de comprovante lerem de volta.
    """

    venda: VendaRegistrada
    modelo_nome: str
    tem_comprovante: bool = False
    chave_destino: str | None = None
    """A chave Pix de destino COMO O OCR LEU no comprovante que fechou esta venda. Vai a vista, e
    nao so como flag, pelo mesmo motivo do aviso no grupo: quem confere precisa comparar com o que
    esta na tela do banco (`comprovante.py::montar_aviso_de_chave_desconhecida`)."""
    chave_conhecida: bool = False

    @property
    def chave_desconhecida(self) -> bool:
        """Flag do painel: esta venda foi fechada por um Pix que saiu da lista da casa.

        So existe quando HA comprovante — venda ainda sem comprovante nao tem chave para ser
        desconhecida, e marca-la assim confundiria "falta comprovar" com "confere esse destino".
        """
        return self.tem_comprovante and not self.chave_conhecida


TipoDeEvento = Literal["correcao", "anulacao", "abate_desfeito"]
"""O que aconteceu com uma Venda registrada depois de gravada. Correcao troca UM campo (uma linha
de evento por campo); anulacao mata a venda inteira (uma linha so, sem campo); abate_desfeito e o
unico que nao nasce de um gesto sobre ESTA venda — o comprovante que a fechava foi apagado no
grupo, e ela voltou para a fila de "falta comprovar"."""


@dataclass(frozen=True)
class EventoDaVenda:
    """Uma linha do rastro de auditoria — o que mudou, quando e por causa de qual mensagem.

    Append-only: o evento nunca e reescrito nem apagado (o GRANT do banco tira UPDATE/DELETE de
    `authenticated`). E o unico lugar onde se ve que um numero JA foi outro — a venda so guarda o
    estado de agora.
    """

    id: UUID
    venda_id: UUID
    tipo: TipoDeEvento
    campo: str | None
    valor_anterior: str | None
    valor_novo: str | None
    mensagem_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class DelecaoNoGrupo:
    """O evento de delecao da plataforma: "esta mensagem foi apagada para todos".

    Entra pela PORTA do modulo como um irmao da mensagem, e nao como um `MensagemDoGrupo` de tipo
    especial: nada aqui e conteudo (nao ha texto, nem autor que "disse" algo), e o unico dado util
    e QUAL mensagem morreu. Tratar delecao como mensagem obrigaria todo leitor de texto do modulo
    a saber que existe um texto que nao e texto.
    """

    grupo_jid: str
    evolution_message_id: str
    autor_jid: str | None = None
    ocorrida_em: datetime = field(default_factory=_agora)
