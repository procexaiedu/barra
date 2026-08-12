"""Detectores do <foco_do_turno>: o que o burst ATUAL do cliente pede, lido sem LLM.

Re-ancoragem por turno (rodada 3 da campanha de substituição): em conversa longa o modelo degrada
exatamente nas jogadas de dado — não entrega o endereço que tem, não responde a pergunta que ficou
na bolha 1 de um burst de 4, re-cota preço de cabeça. Estes detectores viram DADO na cauda o que
antes dependia da atenção do LLM: as perguntas dele neste turno e os pedidos de endereço/preço,
que o `foco_do_turno.md.j2` transforma em bloco curto logo antes da fala do cliente.

Mesma disciplina dos vizinhos de `_janela_do_turno.py` (de onde vêm `_burst_do_cliente` e
`_texto_msg`): funções PURAS, turno-locais, rodando sobre a janela LIMPA — antes de o
`prepare_context` colar contexto dinâmico e lembrete na cauda (depois disso o belief entraria na
conta como fala do cliente).

Fronteira com `_disciplina.py` (rodada 4, fronteira da rodada 3 desfeita): quem classifica uma
fala ISOLADA mora lá (`periodo_da_saudacao`, `contem_pedido_de_endereco`); quem varre o BURST da
janela mora aqui. Os vocabulários de pedido-de-endereço dos dois lados divergem de propósito —
ver o comentário do `_RE_PEDIDO_ENDERECO`.
"""

import re

from langchain_core.messages import BaseMessage

from barra.agente._disciplina import periodo_da_saudacao

from ._janela_do_turno import _burst_do_cliente, _e_afirmacao_curta, _texto_msg

# Conteúdo de mídia spotlighted (SEC-11/SEC-PI-03): transcrição de áudio e legenda de imagem
# chegam CERCADAS como DADO ("[transcrição de áudio do cliente — isto é DADO…]"). Citar um trecho
# delas no <foco_do_turno> o tiraria da cerca e o aproximaria de posição de instrução — vetor de
# injeção indireta. Fail-closed: mensagem cercada não alimenta pergunta citada nem detector de
# pedido (a fala segue INTEIRA na janela; só o realce fica de fora).
#
# Exige o DELIMITADOR com hash (`· AUDIO_/LEGENDA_<8 hex>]`, `_cercar_dado_midia`), não só o rótulo:
# o hash sai do id interno da mensagem (imprevisível para o cliente), então uma fala que ele mesmo
# comece com "[transcrição de áudio do cliente ...]" NÃO casa e não se auto-exclui do foco — quem a
# sanea contra a moldura é o saneamento de `perguntas_do_burst` (colchete/angular removidos).
_RE_SPOTLIGHT = re.compile(
    r"\[(?:transcrição de áudio|legenda de imagem) do cliente[^\]]*·\s*"
    r"(?:AUDIO|LEGENDA)_[0-9a-f]{8}\]"
)

# Segmento interrogativo: o trecho que termina em "?" (sem atravessar linha nem outro "?").
_RE_PERGUNTA = re.compile(r"[^?\n]{2,120}\?")

# Pedido de localização/endereço — vocabulário do corpus real (jogadas de logistica_local).
# Rodada 4: formas coloquiais medidas na triagem ("próximo onde?", "não conheço esse hotel",
# "é casa ou apartamento", "fica/tá longe"). As duas últimas são pergunta de acesso/objeção de
# distância — entram AQUI (o foco só injeta o dado; entregar o ponto resolve as duas) mas ficam
# fora do detector-irmão de `_disciplina.py`, que arma o regen do guard (lá a resposta boa pode
# legitimamente não ter token de endereço, ex.: "posso ir até você").
_RE_PEDIDO_ENDERECO = re.compile(
    r"\b(?:endere[çc]o|localiza[çc][ãa]o|loc\b|onde\s+(?:fica|[ée]\b|voc[êe]\s+(?:est[áa]|atende)|"
    r"te\s+encontro)|como\s+(?:chego|fa[çc]o\s+pra\s+chegar)|"
    r"(?:manda|passa|envia)r?\s+(?:a\s+loc|o\s+local|a\s+localiza[çc][ãa]o|o\s+endere[çc]o)|"
    r"qual\s+(?:rua|hotel|bairro|regi[ãa]o)|que\s+rua|fica\s+(?:aonde|onde)|"
    r"pr[óo]ximo\s+(?:de\s+|a\s+)?onde|"
    r"n[ãa]o\s+conhe[çc]o\s+(?:esse|este|o|essa|a)\s+(?:hotel|lugar|local|rua)|"
    r"(?:[ée]\s+)?casa\s+ou\s+apartamento|apartamento\s+ou\s+casa|"
    r"(?:seu|teu)\s+[ée]\s+(?:apartamento|casa)|"
    r"(?:fica|t[áa]|muito)\s+longe)\b",
    re.IGNORECASE,
)

# Pergunta de preço — "quanto é/fica/custa/cobra/sai", "qual o valor", "me passa o valor", cachê.
# Rodada 6: "seu presente?"/"presentinho" é a gíria de cachê do corpus (derrota medida: recebia
# autoelogio sem número).
_RE_PEDIDO_PRECO = re.compile(
    r"\b(?:quanto\s+(?:[ée]|fica|custa|cobra|sai|que\s+[ée])|qua[il]s?\s+(?:o\s+)?valor|"
    r"(?:manda|passa|me\s+diz)e?r?\s+o\s+valor|(?:teu|seu)\s+valor|valores\b|"
    r"qual\s+o\s+pre[çc]o|cach[êe]\b|tabela\s+de\s+pre[çc]o|"
    r"(?:seu|teu|qual\s+o)\s+presente\b|presentinho\b)",
    re.IGNORECASE,
)

_MAX_PERGUNTAS = 3

# Pergunta SOCIAL não é pendência: citá-la no foco viraria ruído ("responda 'tudo bem?'").
# Conjunto fechado sobre a forma normalizada (alpha+espaço minúsculo), como as afirmações curtas
# de `_janela_do_turno`.
_PERGUNTAS_SOCIAIS = frozenset(
    {"tudo bem", "td bem", "tudo bom", "como vai", "como voce esta", "como vc ta", "beleza", "blz"}
)


def _normalizar_social(texto: str) -> str:
    limpo = "".join(c for c in texto.lower() if c.isalpha() or c.isspace())
    return " ".join(limpo.split())


def _textos_do_burst(mensagens: list[BaseMessage]) -> list[str]:
    """Textos das bolhas do burst ATUAL do cliente, excluindo conteúdo cercado de mídia."""
    inicio = _burst_do_cliente(mensagens)
    textos: list[str] = []
    for m in mensagens[inicio:]:
        texto = _texto_msg(m)
        if texto and not _RE_SPOTLIGHT.search(texto):
            textos.append(texto)
    return textos


def perguntas_do_burst(mensagens: list[BaseMessage]) -> tuple[str, ...]:
    """As perguntas ("?") do burst atual do cliente, na ordem, sem repetição — até 3.

    É o realce anti-perda em burst: a dúvida da bolha 1 de 4 some da atenção do modelo em conversa
    longa; citada como DADO no <foco_do_turno>, ela volta à posição de recência. Só segmentos
    terminados em "?" (interrogativa sem "?" fica para os detectores de pedido, que não citam).
    """
    vistas: set[str] = set()
    perguntas: list[str] = []
    for texto in _textos_do_burst(mensagens):
        for seg in _RE_PERGUNTA.findall(texto):
            # O match já termina em "?"; corta a cabeça não-interrogativa da mesma linha
            # ("Show. Onde fica?" → "Onde fica?").
            bruto = re.split(r"(?<=[.!…;])\s+", seg.strip())[-1]
            # SEC (F13): a fala dele vira <pergunta> numa moldura CONFIÁVEL do prompt — tira
            # colchete/angular forjado (não fecha a moldura nem vira tag), colapsa whitespace e
            # trunca, o MESMO saneamento do pin de localização (webhook/parser.py).
            pergunta = " ".join(re.sub(r"[\[\]<>]", "", bruto).split())[:120]
            norm = _normalizar_social(pergunta)
            # Sufixo, não igualdade: "oi, tudo bem?" normaliza "oi tudo bem" e segue social.
            if any(norm == s or norm.endswith(" " + s) for s in _PERGUNTAS_SOCIAIS):
                continue
            chave = pergunta.lower()
            if pergunta.strip("?").strip() and chave not in vistas:
                vistas.add(chave)
                perguntas.append(pergunta)
    return tuple(perguntas[:_MAX_PERGUNTAS])


def pediu_endereco_no_burst(mensagens: list[BaseMessage]) -> bool:
    """O burst atual pede localização/endereço? (com ou sem "?")."""
    return any(_RE_PEDIDO_ENDERECO.search(t) for t in _textos_do_burst(mensagens))


def pediu_preco_no_burst(mensagens: list[BaseMessage]) -> bool:
    """O burst atual pergunta preço? (com ou sem "?")."""
    return any(_RE_PEDIDO_PRECO.search(t) for t in _textos_do_burst(mensagens))


# Duração pedida — só formas NUMÉRICAS inequívocas ("3h", "2 horas", "30 min", "meia hora").
# "Pernoite"/"o dia" ficam de fora de propósito: não têm horas canônicas na tabela e chutar a
# linha errada seria pior que nenhuma (mesmo fail-closed do <pacote_em_pauta>).
_RE_DURACAO_HORAS = re.compile(r"\b(\d{1,2})\s*(?:h\b|hs\b|hrs?\b|horas?\b)", re.IGNORECASE)
_RE_DURACAO_MIN = re.compile(r"\b(\d{2,3})\s*(?:min\b|mins\b|minutos?\b)", re.IGNORECASE)
_RE_MEIA_HORA = re.compile(r"\bmeia\s+hora\b", re.IGNORECASE)


def duracao_pedida_no_burst(mensagens: list[BaseMessage]) -> float | None:
    """A duração (em horas) que o burst atual menciona, ou None.

    Rodada 6: derrota medida — cliente pede "3h"/"o valor das 2h" e a IA cota a linha de 1h da
    cabeça (cotação 43% em conversa longa). A ÚLTIMA menção do burst vence (ele pode corrigir a si
    mesmo); a resolução em linha da tabela (e o fail-closed de preço único) fica com o chamador.
    """
    duracao: float | None = None
    for texto in _textos_do_burst(mensagens):
        for m in _RE_DURACAO_HORAS.finditer(texto):
            horas = float(m.group(1))
            if 0 < horas <= 24:
                duracao = horas
        for m in _RE_DURACAO_MIN.finditer(texto):
            minutos = float(m.group(1))
            if 10 <= minutos <= 120:
                duracao = minutos / 60
        if _RE_MEIA_HORA.search(texto):
            duracao = 0.5
    return duracao


def duracao_dita_na_janela(mensagens: list[BaseMessage]) -> bool:
    """O CLIENTE nomeou alguma duração em alguma fala da janela (não só no burst)?

    Irmã da `composicao_na_janela`, e pelo mesmo motivo: a pauta que o burst atual não repete. Serve à
    conduta de SUBIR O TEMPO (vender o pacote maior antes de descer o preço) — a jogada só faz
    sentido enquanto o tempo em pauta é o que ELA cotou. Com "quanto é 1h ?" na janela, o tempo é
    dele: a IA pode oferecer o pacote maior, mas não tem o que sondar.

    Reusa os MESMOS regexes numéricos do `duracao_pedida_no_burst` — a divisória de propósito é a
    janela, não o vocabulário. Falso-positivo aqui só cala uma sondagem (falha benigna); um
    falso-negativo faria a IA perguntar o tempo que ele já disse, que é o tique a evitar.
    """
    for m in mensagens:
        if m.type != "human":
            continue
        texto = _texto_msg(m)
        if not texto or _RE_SPOTLIGHT.search(texto):
            continue
        if (
            _RE_DURACAO_HORAS.search(texto)
            or _RE_DURACAO_MIN.search(texto)
            or _RE_MEIA_HORA.search(texto)
        ):
            return True
    return False


def aceite_curto_no_burst(mensagens: list[BaseMessage]) -> bool:
    """O burst atual é SÓ afirmação curta de aceite (sem pergunta nenhuma)?

    Rodada 6: derrota medida — cliente responde "Perfeito"/"Certo" e a IA repete o preço/pitch já
    dados em vez de avançar (fechamento 77%). Reusa o vocabulário fechado de `_e_afirmacao_curta`
    (o mesmo do A2 do dia); qualquer bolha fora dele (ou com "?") desarma — fail-closed.
    """
    textos = _textos_do_burst(mensagens)
    if not textos:
        return False
    return all(_e_afirmacao_curta(t) and "?" not in t for t in textos)


# Pergunta de restrições/limites — rodada 6 (recusa_limite 71%): "alguma restrição?" recebia
# "Nenhuma amor" (vago e falso) onde a vendedora real responde com a lista concreta do que faz.
# O detector acende o <pergunta_de_restricoes> do foco, que leva os Inclusos dela como DADO.
_RE_PEDIDO_RESTRICOES = re.compile(
    r"\b(?:alguma\s+restri[çc][ãa]o|restri[çc][õo]es\b|algum\s+limite|tem\s+limites?\b|"
    r"quais\s+(?:s[ãa]o\s+)?(?:os\s+)?(?:seus|teus)\s+limites|"
    r"o\s+que\s+(?:voc[êe]|vc)\s+(?:n[ãa]o\s+)?faz\b|faz\s+tudo\b|topa\s+tudo\b|"
    r"o\s+que\s+(?:pode|rola)\s+e\s+o\s+que\s+n[ãa]o)",
    re.IGNORECASE,
)


def pediu_restricoes_no_burst(mensagens: list[BaseMessage]) -> bool:
    """O burst atual pergunta limites/restrições ("alguma restrição?", "o que você não faz?")."""
    return any(_RE_PEDIDO_RESTRICOES.search(t) for t in _textos_do_burst(mensagens))


# Famílias de fetiche/serviço no vocabulário do CLIENTE — rodada 6: a pergunta "faz X?" era
# respondida com esquiva (cota sem responder) ou "pode sim" fantasma. A família detectada aqui é
# resolvida contra o CADASTRO da modelo no prepare_context (incluso / extra pago / por pessoa /
# mora no Completo / fora do cardápio) e o status vira DADO no <servico_em_pauta> do foco.
# Fechado e conservador: só termos inequívocos do corpus; termo ambíguo fica de fora (falso
# positivo aqui injetaria instrução errada na posição de recência).
_FAMILIAS_FETICHE: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("anal", "anal", re.compile(r"\banal\b", re.IGNORECASE)),
    ("grego", "beijo grego", re.compile(r"\bgrego\b", re.IGNORECASE)),
    (
        "oral_sem",
        "oral sem camisinha",
        re.compile(r"\boral\s+sem\b|\bnatural\b", re.IGNORECASE),
    ),
    (
        "beijo_na_boca",
        "beijo na boca",
        re.compile(r"\bbeij(?:o|a|ar)\s+na\s+boca\b", re.IGNORECASE),
    ),
    (
        "finalizar_oral",
        "finalizar no oral",
        re.compile(
            r"\b(?:finaliza(?:r)?|goza(?:r)?|termina(?:r)?)\s+n[ao]\s+(?:boca|oral)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chuva_dourada",
        "chuva dourada",
        re.compile(r"\bchuva\s+dourada\b|\bxixi\b", re.IGNORECASE),
    ),
    ("bdsm", "BDSM", re.compile(r"\bbdsm\b|\bdomina[çc][ãa]o\b|\bsubmiss", re.IGNORECASE)),
    (
        "inversao",
        "inversão de papéis",
        re.compile(r"\binvers[ãa]o\b|\bpegging\b|\bstrap\b", re.IGNORECASE),
    ),
    # --- COMPOSIÇÕES (quem acompanha quem no encontro) -----------------------------------------
    # Uma família POR COMPOSIÇÃO desde 11/08/2026, no lugar da família única `casal` que fundia
    # tudo num regex só (`casal|ménage|dupla|nós dois|duas meninas|eu e minha esposa`). O motivo
    # não é estética: o catálogo global passou a ter um item por composição, e a modelo que não
    # atende UMA delas simplesmente não a tem cadastrada. É a fala do cliente que precisa dizer
    # QUAL item está em pauta — sem isso, "eu e um amigo" casava a mesma família de "eu e minha
    # esposa" e o resolver dava por coberto um item que a modelo não oferece (a Catarina não
    # atende dois homens). Separadas, a ausência no cardápio vira a recusa closed-world que o
    # sistema já sabe fazer sozinho.
    # `ménage` NÃO entra em nenhuma delas de propósito: a palavra significa coisas diferentes
    # (duas mulheres e dois homens, ou uma mulher e um homem) e a política deste módulo é deixar
    # o termo ambíguo de fora. Ela é coberta pelo `_RE_COMPOSICAO` da janela, que só dirige a
    # atenção ("confirme quem vem antes de cravar o número") em vez de afirmar um item.
    (
        "acompanhante_mulher",
        "ele trazer uma mulher junto",
        re.compile(
            r"\bcasal\b"
            r"|\b(?:eu|n[óo]s)\s+e\s+(?:a\s+)?minha\s+"
            r"(?:esposa|namorada|mulher|companheira|noiva|parceira|amiga)\b"
            r"|\b(?:levar|trazer|lev(?:o|ar)|traz(?:er|o))\s+(?:a\s+)?minha\s+"
            r"(?:esposa|namorada|mulher|companheira|noiva|amiga)\b"
            r"|\bcom\s+(?:a\s+)?minha\s+(?:esposa|namorada|mulher|companheira|noiva)\b"
            r"|\bminha\s+(?:esposa|namorada|mulher|companheira|noiva)\s+"
            r"(?:junto|tamb[ée]m|comigo)\b"
            r"|\b(?:eu|n[óo]s)\s+e\s+(?:uma|mais\s+uma)\s+(?:amiga|menina|garota|mulher)\s+minha\b",
            re.IGNORECASE,
        ),
    ),
    (
        "acompanhante_homem",
        "ele trazer outro homem junto",
        re.compile(
            r"\b(?:eu|n[óo]s)\s+e\s+(?:um|mais\s+um|meu|o\s+meu)\s+"
            r"(?:amigo|primo|irm[ãa]o|colega|parceiro|chegado|cara|rapaz|mano)\b"
            r"|\b(?:levar|trazer|lev(?:o|ar)|traz(?:er|o))\s+(?:um|meu)\s+"
            r"(?:amigo|primo|irm[ãa]o|colega)\b"
            r"|\bcom\s+(?:um|meu)\s+(?:amigo|primo|irm[ãa]o|colega)\b"
            r"|\bmeu\s+(?:amigo|primo|irm[ãa]o)\s+(?:e\s+eu|junto|tamb[ée]m|comigo)\b"
            r"|\b(?:dois|2)\s+homens\b|\boutro\s+homem\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dupla_de_modelos",
        "você com outra menina",
        re.compile(
            r"\b(?:voc[êe]|vc|tu)\s+e\s+(?:uma|sua|outra|mais\s+uma)\s+"
            r"(?:amiga|menina|garota|colega|parceira|mulher)\b"
            r"|\buma\s+amiga\s+sua\b|\bvoc[êe]s\s+duas\b|\bdupla\b"
            r"|\bduas\s+(?:meninas|garotas|mulheres|mo[çc]as)\b"
            r"|\bmais\s+uma\s+(?:menina|garota|amiga)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dois_casais",
        "dois casais (vocês duas e eles dois)",
        re.compile(
            r"\b(?:dois|2)\s+casais\b|\bcasal\s+com\s+casal\b"
            r"|\bn[óo]s\s+dois\s+(?:e|com)\s+voc[êe]s\s+duas\b"
            r"|\bvoc[êe]s\s+duas\s+(?:e|com|pra|para)\s+n[óo]s\s+dois\b"
            r"|\beu\s+e\s+(?:um|meu)\s+amigo\s+(?:e|com)\s+voc[êe]s\s+duas\b",
            re.IGNORECASE,
        ),
    ),
    ("voyeur", "voyeur", re.compile(r"\bvoyeur\b", re.IGNORECASE)),
    ("fisting", "fisting", re.compile(r"\bfisting\b", re.IGNORECASE)),
    (
        "sem_camisinha",
        "sem camisinha (penetração)",
        re.compile(r"\bsem\s+(?:camisinha|capa|prote[çc][ãa]o)\b", re.IGNORECASE),
    ),
)
# "sem camisinha" perto de "oral/boquete" é a família oral_sem (que pode estar no cadastro);
# longe, é penetração sem proteção — NUNCA no cardápio, recusa sempre.
_RE_ORAL_PERTO = re.compile(r"\b(?:oral|boquete|chupa)", re.IGNORECASE)
_JANELA_ORAL = 25


# Composições que a de "dois casais" ENGLOBA: "eu e um amigo e vocês duas" casa as três de uma
# vez (o "eu e um amigo", o "vocês duas" e a frase inteira), e as três em pauta ao mesmo tempo
# fariam o foco pedir três itens de cardápio para UM pedido só. A mais específica vence.
_SUBSUMIDAS_POR_DOIS_CASAIS = ("acompanhante_mulher", "acompanhante_homem", "dupla_de_modelos")


def _familias_em(textos: list[str]) -> tuple[str, ...]:
    """As famílias mencionadas nestes textos, na ordem, sem repetição — até 3. PURA.

    Site único da varredura: o burst e a janela usam a MESMA tabela e as mesmas duas correções
    (o "sem camisinha" que vira `oral_sem` quando há oral perto; o "dois casais" que subsume as
    composições que ele engloba). Duas cópias divergiriam, e a janela passaria a classificar
    diferente do burst para a mesma fala.
    """
    chaves: list[str] = []
    for texto in textos:
        for chave, _rotulo, padrao in _FAMILIAS_FETICHE:
            m = padrao.search(texto)
            if not m or chave in chaves:
                continue
            if chave == "sem_camisinha":
                perto = texto[max(0, m.start() - _JANELA_ORAL) : m.end() + _JANELA_ORAL]
                if _RE_ORAL_PERTO.search(perto):
                    chave = "oral_sem"
                    if chave in chaves:
                        continue
            chaves.append(chave)
    if "dois_casais" in chaves:
        chaves = [c for c in chaves if c not in _SUBSUMIDAS_POR_DOIS_CASAIS]
    return tuple(chaves[:3])


def fetiches_no_burst(mensagens: list[BaseMessage]) -> tuple[str, ...]:
    """As famílias de fetiche/serviço que o burst atual menciona, na ordem — até 3.

    Menção basta (não exige "?"): cliente que escreve "anal" está pondo o serviço em pauta, e o
    dado certo (status no cadastro DELA) previne tanto a promessa fantasma quanto a esquiva."""
    return _familias_em(_textos_do_burst(mensagens))


def fetiches_na_janela(mensagens: list[BaseMessage]) -> tuple[str, ...]:
    """As famílias que o cliente mencionou em QUALQUER fala da janela — irmã de
    `composicao_na_janela`, e pelo mesmo motivo: a pauta que o burst atual não repete.

    Serve ao discriminante da parceira (ADR-0042), que precisa sobreviver ao turno do "sim". Ele
    pergunta "faz anal?" num turno, ela oferece a amiga, e o turno seguinte é só "quero sim" — sem
    família nenhuma no burst. Lido só do burst, o bloco da parceira sumiria exatamente no turno em
    que ele topou, e a IA ficaria sem a conduta (e sem a ferramenta) para entregar o que prometeu.

    Largo de propósito, como a `composicao_na_janela`, e seguro pelo mesmo desenho: quem decide o
    que fazer com a família é o discriminante (que cruza cardápio + autorização do par) e as travas
    duráveis do atendimento, não a presença da palavra.
    """
    textos = [
        t
        for m in mensagens
        if m.type == "human" and (t := _texto_msg(m)) and not _RE_SPOTLIGHT.search(t)
    ]
    return _familias_em(textos)


def rotulo_da_familia(chave: str) -> str:
    """O rótulo humano da família ("oral_sem" → "oral sem camisinha")."""
    return next((r for c, r, _p in _FAMILIAS_FETICHE if c == chave), chave)


_FAMILIAS_DE_COMPOSICAO = (
    "acompanhante_mulher",
    "acompanhante_homem",
    "dupla_de_modelos",
    "dois_casais",
)
# Detector LARGO de composição, para a JANELA (não para o cardápio): a união das quatro famílias
# MAIS os termos ambíguos que elas recusam por política ("ménage", "nós dois", "somos dois"). Ele
# não afirma QUAL item está em pauta — só diz que o encontro pode não ser a dois, o que basta para
# a nota condicional do foco ("confirme quem vem antes de cravar o número"). Derivado das próprias
# famílias para não sair de sincronia com elas quando um termo novo entrar.
_RE_COMPOSICAO = re.compile(
    "|".join(p.pattern for c, _r, p in _FAMILIAS_FETICHE if c in _FAMILIAS_DE_COMPOSICAO)
    + r"|\bm[ée]nage\b|\bmenage\b|\bn[óo]s\s+dois\b|\bn[óo]s\s+2\b|\bsomos\s+(?:dois|2)\b",
    re.IGNORECASE,
)


def composicao_na_janela(mensagens: list[BaseMessage]) -> bool:
    """Alguma COMPOSIÇÃO apareceu em fala do CLIENTE na janela (não só no burst)?

    Rodada 6 (cotação 71%): "e qual valor?" turnos depois de "vocês atendem casal?" era cotado
    como individual. A janela inteira (falas dele, sem conteúdo cercado de mídia) cobre a pauta
    que o burst atual não repete; o foco injeta só uma NOTA condicional ("se a cotação é para 2, o
    número é o TOTAL da tabela 'Por pessoa'" — que soma um extra ao pacote, não o dobra), então
    menção antiga não afirma nada errado — só dirige a atenção.

    Largo DE PROPÓSITO, ao contrário das famílias: aqui entra até o termo ambíguo, porque uma nota
    que manda confirmar quem vem não pode errar — e é exatamente do ambíguo que ela protege."""
    for m in mensagens:
        if m.type != "human":
            continue
        texto = _texto_msg(m)
        if texto and not _RE_SPOTLIGHT.search(texto) and _RE_COMPOSICAO.search(texto):
            return True
    return False


def saudacao_do_burst(mensagens: list[BaseMessage]) -> str | None:
    """A saudação de período do burst atual ("bom dia"/"boa tarde"/"boa noite"), ou None.

    Rodada 4: espelhamento determinístico de período — a IA respondia "Boa noite" a quem abriu
    com "boa tarde". Detectada aqui, ela vira DADO no <foco_do_turno> ("espelhe a dele"); o
    relógio não entra na conta de propósito (o período certo a responder é o que ELE usou)."""
    for texto in _textos_do_burst(mensagens):
        periodo = periodo_da_saudacao(texto)
        if periodo:
            return periodo
    return None
