"""Detectores determinísticos sobre a JANELA do turno — leitura da conversa, sem LLM.

Saíram do `prepare_context` (spec de manutenibilidade da camada de contexto): ele monta o contexto,
estes leem a conversa para decidir o que o turno EVIDENCIA. São a outra metade da família de
`_disciplina.py` — lá moram os classificadores de uma fala isolada (`contem_hora_explicita`,
`classificar_recuo`, `_PROBE_DIA_HOJE`), aqui a mecânica de JANELA que os aplica ao lugar certo: o
burst atual do cliente e as bolhas contíguas da IA que o antecedem (o antecedente ao qual uma
afirmação curta dele se refere).

Todos são PUROS e turno-locais de propósito — rodam sobre a janela LIMPA, antes de o
`prepare_context` colar contexto dinâmico e lembrete na cauda do último HumanMessage: depois disso
o belief entraria na conta como se fosse fala do cliente (o horário renderizado viraria "hora
explícita dele", e uma negativa curta deixaria de ser curta).
"""

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .._disciplina import (
    _PEDE_FECHAMENTO,
    _PERGUNTA_DE_HORARIO,
    _PROBE_DIA_HOJE,
    _RE_CONTEXTO_DE_PRECO,
    _RE_FAIXA_ABERTA,
    _TOKEN_OUTRO_DIA,
    _VERBO_DE_POSSIBILIDADE,
    classificar_recuo,
    contem_contraproposta,
    contem_hora_explicita,
    contem_pedido_de_infos,
    contem_sondagem_imediatismo,
)
from .._normalizar import normalizar
from .._texto_turno import e_marca_pausa

# A2 (captura determinística do dia — display-only): o abridor social "seria hoje?" (persona.md:32)
# seguido de afirmação curta do cliente CONFIRMA que o encontro é hoje. Mas a extração forçada roda
# no Haiku barato (nos/llm.py) e ele não faz essa correferência ("sim" → data_desejada=hoje) enterrada
# na description do campo — então o belief não traz o dia em <ja_combinado> e a IA REPETE "seria hoje?"
# no turno do preço (persona.md:18 e regras.md.j2:17 proíbem). Detectamos o par deterministicamente
# (zero LLM, zero crédito) e assumimos hoje SÓ no render do belief, sem persistir: a agenda já usa hoje
# por default (criar_bloqueio_previo: data = data_desejada or hoje), o estado real não diverge, e o
# belief é artefato derivado recomputado todo turno. Gated por evidência: só dispara DEPOIS do "sim",
# então não suprime o abridor no turno 1. (`_PROBE_DIA_HOJE` vem de agente/_disciplina.py — mesma
# fonte que o write-time usa p/ carimbar `dia_sondado_em`.)
# Cliente citou OUTRO dia → não assume hoje (deixa a extração capturar o dia explícito). O regex
# `_TOKEN_OUTRO_DIA` mudou de casa (campanha 13/08, ciclo 7): mora em `_disciplina`, junto do
# `_MARCADOR_DE_DIA`, porque a pauta de horas da conversa (`horas_em_pauta_da_conversa`) precisa da
# MESMA fronteira para não pôr a hora de amanhã no piso de hoje.
# Afirmação curta que confirma a sondagem (conjunto fechado; texto normalizado p/ alpha+espaço).
_AFIRMACOES = frozenset(
    {
        "sim",
        "isso",
        "isso mesmo",
        "isso ai",
        "pode ser",
        "pode",
        "claro",
        "com certeza",
        "aham",
        "ahan",
        "uhum",
        "é",
        "eh",
        "sim sim",
        # "perfeito" fecha a correferência do #34 ("Posso confirmar às 18h" → "Perfeito"), e vale
        # igual para o dia — é aceite, não recuo.
        "perfeito",
        # Fechos de negociação (F6, auditoria 11/08): "fechado então" era o aceite mais comum do
        # corpus e NÃO estava aqui — sem ele o <ele_topou> não renderiza, o endereço não libera e a
        # escada por dia atrasa um turno inteiro. Mesma família semântica das afirmações acima
        # (aceite do que a IA acabou de propor), mesmo veto de `_TOKEN_OUTRO_DIA`.
        "fechado",
        "fechou",
        "combinado",
        "beleza",
        "ok",
        "bora",
        # Campanha 13/08 ciclo 2 (eb02:19134800761083 t7): "Topo" respondendo a "Consigo 350 sim /
        # Te espero às 14h então" não contava — o aceite ficava invisível para o gatilho 2 E para o
        # co-sinal do `aceita_valor` (`_aceite_tem_cossinal` reusa esta função), e a IA re-pedia
        # confirmação já dada. Só as formas VERBAIS inequívocas entram, e só no conjunto EXATO
        # (bolha curta): "topo" como SUBSTANTIVO ("no topo", "topo de linha", "topo da lista")
        # nunca colapsa nelas — e "topo" NÃO vira cabeça forte de propósito, porque cabeça forte
        # tolera cauda livre e "topo de linha essa massagem" contaria.
        "topo",
        "eu topo",
        "topo sim",
        # Gírias de aceite (avaliadas na mesma campanha): "dale" solto só existe como aceite;
        # "demorou" solto é o "fechou" da gíria — a leitura de reclamação vem sempre com cauda
        # ("demorou pra responder hein", "demorou em"), que o conjunto EXATO já deixa de fora.
        # Nenhuma das duas vira cabeça forte: "dale mas só meia hora" e "demorou pra responder"
        # passariam pela cauda livre (nenhum token de `_RE_CAUDA_QUE_DESFAZ`).
        "dale",
        "demorou",
    }
)
# Primeira palavra forte o bastante p/ valer mesmo seguida de vocativo ("sim amor", "claro vida").
# Os fechos entram aqui pelo mesmo motivo ("fechado então", "beleza amor"), MENOS "bora": em
# posição de cabeça ele costuma abrir uma PROPOSTA dele ("bora marcar", "bora ver as fotos"), não
# aceitar a da IA — sozinho ("bora", "bora sim") o conjunto exato acima já cobre.
_AFIRMACOES_FORTES = frozenset(
    {
        "sim",
        "isso",
        "claro",
        "aham",
        "uhum",
        "ahan",
        "perfeito",
        "fechado",
        "fechou",
        "combinado",
        "beleza",
        "ok",
    }
)


def _texto_msg(msg: BaseMessage) -> str:
    return msg.content if isinstance(msg.content, str) else ""


def _normalizar_afirmacao(texto: str) -> str:
    """Reduz a alpha+espaço minúsculo (descarta emoji/pontuação): 'Sim 😊' → 'sim'."""
    limpo = "".join(c for c in texto.lower() if c.isalpha() or c.isspace())
    return " ".join(limpo.split())


# Cauda que DESFAZ a afirmação de cabeça forte ("claro que não", "beleza vou pensar"): negação ou
# adiamento depois do "ok" viram outra fala — aceitar pela primeira palavra fabricava um "hoje"
# que o cliente nunca confirmou (loop-massa r1, eixo explorador_ambiguo: "ok\nqual a sua altura?"
# contado como aceite da sondagem de dia).
_RE_CAUDA_QUE_DESFAZ = re.compile(
    r"\b(?:n[ãa]o|vou|vamos|depois|pens(?:ar|o|a)|ver|vejo|talvez|sei\s+l[áa]|quem\s+sabe)\b"
)

# Cabeças de DOIS tokens ("tá bem então", "tá bom amor"): o aceite que faltava no léxico
# (loop-massa r3, eixo remarcacao). Nenhuma das duas estruturas existentes resolve — o conjunto
# EXATO não cobre a cauda ("Tá bem então") e a cabeça FORTE compara UM token, então pôr "tá" lá
# seria desastroso ("tá caro", "tá longe", "tá difícil"). Daí a família própria.
# As DUAS grafias entram porque `_normalizar_afirmacao` NÃO tira acento (só filtra por `isalpha`),
# exatamente como já acontece com "é"/"eh" no conjunto exato.
_AFIRMACOES_DE_DOIS_TOKENS = frozenset(
    {
        "ta bem",
        "tá bem",
        "ta bom",
        "tá bom",
        "ta ok",
        "tá ok",
        # Campanha 13/08 (eb02:30472893644814 t9): "seria 10h então ?" → "Vou sim" não contava —
        # a cabeça "vou" não é forte (e é token de DESFAZ: "beleza vou pensar"), então o aceite
        # mais direto de todos ("vou sim") reprovava e a venda ganha morria em Qualificado. Como
        # cabeça de DOIS tokens com cauda restrita a vocativo, "vou sim amor" conta e "vou sim,
        # mas semana que vem" segue fora.
        "vou sim",
        # Campanha 13/08 ciclo 2 (eb02:19134800761083 t10): "Tá fechado então" — a cabeça "tá"
        # sozinha seria desastrosa como forte ("tá caro", "tá longe"), mas o PAR "tá fechado" é
        # aceite inequívoco, com a mesma cauda restrita a vocativo que já protege "tá bem" ("tá
        # fechado o portão" fica fora porque "o portão" não é vocativo; "tá fechado ?" cai no veto
        # de "?"). "tamo/tamos fechado" é a mesma família na 1ª pessoa do plural. As duas grafias
        # de "tá" entram porque `_normalizar_afirmacao` preserva acento (precedente "tá bem").
        "ta fechado",
        "tá fechado",
        "tamo fechado",
        "tamos fechado",
    }
)
# A cauda destas cabeças é RESTRITA a vocativo/partícula — e é só isso que fecha a armadilha do
# "bem" INTENSIFICADOR: com a cauda livre que as cabeças de um token usam, "tá bem caro", "ta bem
# caro pra mim", "tá bem longe" e "tá bem apertado hoje" viravam aceite (medido).
# "tudo bem" fica de FORA de propósito: é pergunta social (`_PERGUNTAS_SOCIAIS`, _foco_do_turno).
_CAUDA_DE_VOCATIVO = frozenset({"amor", "vida", "linda", "gata", "então", "entao", "sim"})

# Veto por FORMA (loop-massa r3): afirmação curta não carrega número. O `_normalizar_afirmacao`
# descarta dígitos, e o estrago atinge os DOIS caminhos — "Fechado então\n200 as 20h" colapsava em
# "fechado então" (cabeça forte) e "fechado 200" colapsava no próprio "fechado" do conjunto EXATO.
# Contraproposta virava aceite de cabeça, fixando dia/hora que o cliente não confirmou. Nem
# `_RE_CAUDA_QUE_DESFAZ` (negação/adiamento) nem `_TOKEN_OUTRO_DIA` cobriam número.
# Perda aceita e nomeada: "fechado 20h" deixa de ser afirmação curta — mas
# `contem_hora_explicita("fechado 20h")` é True, então o gatilho 1 cobre o turno de qualquer jeito.
_RE_DIGITO = re.compile(r"\d")


def _e_afirmacao_curta(texto: str) -> bool:
    """True se a msg do cliente é uma afirmação curta de 'sim' SEM citar outro dia nem número.

    A cabeça forte ("sim amor", "fechado então") tolera só vocativo/partícula: pergunta na mesma
    msg ("ok\\nqual a sua altura?"), negação ("claro que não") ou adiamento ("beleza vou pensar")
    NÃO são aceite — o custo do falso positivo aqui é fixar dia/hora/endereço que o cliente nunca
    confirmou, bem maior que o falso negativo (a extração LLM ainda captura o aceite verboso).
    A cabeça de DOIS tokens ("tá bem") é mais apertada ainda: só vocativo depois dela."""
    # Pergunta NUNCA é aceite — o veto de "?" valia só para as cabeças, e pela via EXATA
    # "combinado ?" / "pode ?" (o cliente PERGUNTANDO exatamente o que a via trata como resposta)
    # contava como aceite e evidenciava a hora pelo gatilho 2 (campanha 13/08, achado do teste
    # negativo do aceite de fechamento). Subiu para o topo: vale igual para as três vias.
    if "?" in texto or _RE_DIGITO.search(texto) or _TOKEN_OUTRO_DIA.search(texto.lower()):
        return False
    norm = _normalizar_afirmacao(texto)
    if not norm:
        return False
    if norm in _AFIRMACOES:
        return True
    tokens = norm.split()
    if len(tokens) >= 2 and " ".join(tokens[:2]) in _AFIRMACOES_DE_DOIS_TOKENS:
        return all(t in _CAUDA_DE_VOCATIVO for t in tokens[2:])
    if tokens[0] not in _AFIRMACOES_FORTES:
        return False
    return _RE_CAUDA_QUE_DESFAZ.search(norm) is None


def _burst_do_cliente(mensagens: list[BaseMessage]) -> int:
    """Índice onde começa o burst ATUAL do cliente (HumanMessages contíguas no fim da janela);
    `len(mensagens)` quando o último a falar não foi ele.

    PARA na marca de pausa: o burst é a fala contígua dele AGORA, e a marca é fronteira estrutural
    entre dois momentos da Conversa cliente — uma bolha de seis dias atrás não é fala dele neste
    turno (incidente 29/07, trace 06db4298). Sem isso a própria marca (HumanMessage sintética)
    entraria no burst e os detectores a leriam como fala do cliente.
    """
    i = len(mensagens)
    while i > 0:
        anterior = mensagens[i - 1]
        if not isinstance(anterior, HumanMessage) or e_marca_pausa(anterior):
            break
        i -= 1
    return i


def _bolhas_ia_antes_do_burst(mensagens: list[BaseMessage], inicio_burst: int) -> list[AIMessage]:
    """Bolhas contíguas da IA imediatamente ANTES do burst do cliente — o antecedente ao qual a
    afirmação curta dele se refere (a IA quebra a fala em várias bolhas)."""
    j = inicio_burst - 1
    bolhas: list[AIMessage] = []
    while j >= 0 and isinstance(mensagens[j], AIMessage):
        bolhas.append(mensagens[j])  # type: ignore[arg-type]
        j -= 1
    return bolhas


# Faixa ABERTA na bolha da IA ("estou livre hoje a partir das 19:30", "estou livre depois das 22h",
# "atendo das 14h as 23h"): é DISPONIBILIDADE dela, não proposta de horário. O gatilho 2 creditava
# a hora do piso/intervalo a uma afirmação curta dele e a reserva nascia às 19:30 com a conversa
# correndo em 20h (loop-massa r3, eixo remarcacao t3: "Isso, hoje mesmo" depois da bolha de
# disponibilidade). É a MESMA fronteira que o gatilho 3 já documenta abaixo — "a partir das" é
# PISO, não ponto, e aceitá-lo carimba evidência sobre um horário que ninguém propôs.
#
# O regex MUDOU DE CASA (campanha 13/08, ciclo 7): mora em `_disciplina` com o resto da gramática
# de hora, porque as horas em pauta da fala dela (`horas_em_pauta_da_fala_dela`, o número que o
# piso do <horario_minimo> respeita) precisam da MESMA fronteira — duas cópias divergiriam.
def _bolha_da_ia_propoe_hora(texto: str) -> bool:
    """A bolha da IA põe uma hora como PROPOSTA (e não como faixa de disponibilidade)?"""
    return contem_hora_explicita(texto) and _RE_FAIXA_ABERTA.search(texto) is None


# Fala de VINDA/CONFIRMAÇÃO do cliente (campanha 13/08, eb02:30472893644814 t10-t13): "Confirmado
# sim", "To no caminho", "Até daqui a pouco" são compromissos com o ENCONTRO COMBINADO como um
# todo — não correferência à bolha contígua. O gatilho 2 exigia a hora na bolha imediatamente
# anterior da IA, e a partir do momento em que a conversa segue ("Confirmado" → "Confirmado sim")
# a evidência ficava INALCANÇÁVEL: o cliente teria de redigitar a hora. Conjunto fechado e
# deliberadamente mais estreito que `_AFIRMACOES`: só falas que não fazem sentido SEM um encontro
# marcado. "até mais"/"até logo" ficam FORA (são despedida, não vinda).
_RE_FALA_DE_VINDA = re.compile(
    r"\b(?:t[ôo]|estou)\s+(?:no\s+caminho|indo|a\s+caminho|chegando|saindo\s+(?:daqui|de\s+casa))\b"
    r"|\ba\s+caminho\b|\bchegando\s+(?:a[ií]|em)\b"
    r"|\bat[ée]\s+(?:daqui\s+a\s+pouco|j[áa]\b|jajá|ja\s*ja)"
    r"|\bconfirmado\b",
    re.IGNORECASE,
)


def _fala_de_vinda(texto: str) -> bool:
    """A fala do cliente confirma que ele VEM ao encontro combinado? (sem pergunta, sem outro dia —
    os mesmos vetos da afirmação curta; número não veta porque o gatilho 1 já cobre esse caso)."""
    return (
        _RE_FALA_DE_VINDA.search(texto) is not None
        and "?" not in texto
        and _TOKEN_OUTRO_DIA.search(texto.lower()) is None
    )


# Aceite EXPLÍCITO de fechamento (campanha 13/08 — ciclo1 eb04:187007389155571 t6 e retenção
# eb04:211711990710521 t7): "Consigo às 18h, fecha ?" → "Fecha" e "Me confirma 10h" → "Confirmo
# sim" mantinham Qualificado — NENHUMA estrutura reconhecia o aceite. O léxico exato tem
# "fechado"/"fechou" mas não o presente ("fecha"/"fecho"), e "confirmo" não é cabeça forte nem é
# "confirmado" (fala de vinda). Pior: no caso da retenção o gatilho 2 nem serviria com o token —
# a bolha CONTÍGUA da IA ("Me confirma 10h que eu te passo o número certinho") não é proposta pela
# régua de `contem_hora_explicita`, e a proposta real ("Consigo hoje às 10h, fecha ?") estava
# turnos atrás. Por isso a família mora no GATILHO 4 (varredura da janela inteira), não no 2.
# Conjunto = a lemma do próprio empurrão do prompt ("fecha ?") + "confirmo"/"combinado" dos casos
# reais. "bora" fica FORA de propósito: solto no meio da fala ele abre PROPOSTA dele ("bora ver as
# fotos") — mesma razão da exclusão em `_AFIRMACOES_FORTES`; sozinho, o conjunto exato + gatilho 2
# já o cobrem. "confirmado" já mora em `_RE_FALA_DE_VINDA`.
# O INFINITIVO ("pode fechar") entrou na campanha 13/08 (diagnóstico da degradação tardia, M5):
# `re.search(padrão, "pode fechar")` era None e o turno em que o cliente FECHOU — a fala de aceite
# mais frequente do corpus depois de "fechado" — não evidenciava. No caso-farol
# (c3-lote/eb02:139384791793838) isso sozinho move a evidência do t12 para o t9: os três turnos em
# que a IA cobrou confirmação já dada ("Me confirma que eu te passo o endereço", duas vezes) somem.
_RE_ACEITE_DE_FECHAMENTO = re.compile(
    r"\b(?:fecha(?:do|mos|r)?|fecho|fechou|combinado|confirmo)\b", re.IGNORECASE
)

# "Topo" na CABEÇA da mensagem (campanha 13/08 ciclo 2, eb02:19134800761083 t7): o verbo é aceite
# ("Topo", "Topo, me passa o endereço"), mas o token solto no meio da fala é quase sempre o
# SUBSTANTIVO ("me espera no topo do prédio") — por isso ele NÃO entra em
# `_RE_ACEITE_DE_FECHAMENTO`, que varre a mensagem inteira. A forma de aceite é posicional
# (início da mensagem, com "eu" opcional), e o lookahead corta a leitura substantiva que sobra
# nessa posição: "Topo da lista", "Topo do prédio", "Topo de linha" (verbo "topar" não rege
# "de/da/do"; perda aceita e nomeada: o "topo de boa" da gíria fica fora — recall menor que
# falso positivo). Os vetos inteiros de `_aceite_de_fechamento` continuam por cima ("topo ?",
# "topo se for 300", "topo amanhã", "topo mas vou ver").
_RE_TOPO_EM_CABECA = re.compile(r"^\s*(?:eu\s+)?topo\b(?!\s+d[aeo]\b)", re.IGNORECASE)


# ADIAMENTO da confirmação — "eu confirmo DEPOIS" é o contrário de "eu confirmo". A família mora
# aqui porque nenhuma das duas estruturas vizinhas a pega: `_RE_CAUDA_QUE_DESFAZ` tem "vou" (mata
# "vou confirmar") mas não "vendo" nem "te confirmo", e `classificar_recuo` (_disciplina) tem "te
# avis" na LISTA NEGATIVA — lá "te aviso quando sair" é aviso, não recuo, e isso está certo para o
# recuo: quem avisa ainda quer. Só que para o ACEITE a leitura se inverte — quem vai avisar ainda
# não fechou. Medido no corpus da campanha: 5 turnos em que `_aceite_de_fechamento` lia como aceite
# um adiamento explícito ("Tô vendo aqui e te confirmo", "Te chamo e te confirmo", "Te confirmo
# assim que finalizar aqui", "Só um minutinho, já te confirmo certinho") — todos pelo token
# `confirmo`, todos com o cliente dizendo o oposto. "Confirmo sim" (sem o "te") segue sendo aceite.
_RE_ADIAMENTO_DA_CONFIRMACAO = re.compile(
    r"\b(?:vou\s+(?:confirmar|ver|pensar|olhar|checar)|(?:t[ôo]|to|estou)\s+vendo"
    r"|te\s+(?:aviso|confirmo|chamo|falo)|deixa\s+eu\s+ver|s[óo]\s+vou\s+saber)\b",
    re.IGNORECASE,
)


def _aceite_de_fechamento(texto: str) -> bool:
    """A fala do cliente FECHA o combinado que a IA propôs? Vetos inteiros da família curta:
    pergunta não é aceite ("fecha por 500 ?" é contraproposta, "combinado ?" é sondagem DELE),
    número é contraproposta ("fecha por 500" — e "fecha 20h" segue coberto pelo gatilho 1), outro
    dia é adiamento, e negação/adiamento na mesma fala desfazem ("não fecho", "vou pensar se
    fecha", "te confirmo assim que finalizar" — `_RE_ADIAMENTO_DA_CONFIRMACAO`)."""
    return (
        (
            _RE_ACEITE_DE_FECHAMENTO.search(texto) is not None
            or _RE_TOPO_EM_CABECA.search(texto) is not None
        )
        and _RE_ADIAMENTO_DA_CONFIRMACAO.search(texto) is None
        and "?" not in texto
        and _RE_DIGITO.search(texto) is None
        and _TOKEN_OUTRO_DIA.search(texto.lower()) is None
        and _RE_CAUDA_QUE_DESFAZ.search(_normalizar_afirmacao(texto)) is None
    )


# COBRANÇA de fechamento DELA — o antecedente do gatilho 5. `_PEDE_FECHAMENTO` (_disciplina) cobre
# as formas interrogativas do prompt ("Consigo às 22h, fecha ?", "Fechamos 15h então ?") porque
# exige o "?"; a cobrança IMPERATIVA do fechamento não tem "?" e é a que mais aparece na fase de
# logística ("Me confirma que eu te passo o endereço certinho", "Me confirma o horário").
# Léxico DELA, não dele: as formas saem do prompt (conjunto fechado que nós controlamos) — é o
# oposto do léxico de aceite do CLIENTE, que é open-world e onde alargar vira corrida armamentista.
_RE_COBRANCA_DE_FECHAMENTO = re.compile(
    r"\bme\s+confirm[ae]\b|\bconfirma\s+(?:pra\s+mim|o\s+hor[áa]rio)\b", re.IGNORECASE
)


def _bolha_da_ia_cobra_o_fechamento(texto: str) -> bool:
    """A bolha da IA COBRA o fechamento (pergunta do empurrão ou cobrança imperativa)?"""
    return (
        _PEDE_FECHAMENTO.search(normalizar(texto)) is not None
        or _RE_COBRANCA_DE_FECHAMENTO.search(texto) is not None
    )


# Adesão pelo VERBO DA COBRANÇA ("Consigo às 11h, fecha ?" -> "Consigo sim"; "Posso te esperar às
# 20h ?" -> "Pode sim"): o cliente responde ecoando o verbo de possibilidade que ELA usou. Não é
# léxico novo de aceite — o conjunto é o `_VERBO_DE_POSSIBILIDADE` que `_disciplina` já mantém para
# ler a hora da agenda DELE, e o "sim" é o mesmo de sempre. Foi o ÚNICO padrão que a triagem das
# falas curtas do corpus classificou como aceite em 3 de 3 leituras (`Consigo sim` 2x, `Posso sim`);
# `certo`/`entendi`/`legal`/`ótimo`, os candidatos "óbvios", ficaram FORA porque a leitura mostrou
# 5 de 8 ocorrências em que o cliente continua qualificando ou hedgeando depois deles.
#
# Vive SÓ dentro do gate do gatilho 5 (âncora + correferência + nada reaberto): solto ele repetiria
# o erro que a medição já condenou. A cauda é a mesma restrita a vocativo da família de dois tokens
# — "consigo sim, mas só amanhã" não conta.
_RE_POSSIBILIDADE_SIM = re.compile(rf"^(?:eu\s+)?(?:{_VERBO_DE_POSSIBILIDADE})\s+sim\b")


def _adesao_por_eco_do_verbo(texto: str) -> bool:
    """ "Consigo sim" / "Pode sim" — aceite ecoando o verbo da cobrança dela. Vetos da família
    curta: pergunta, número, outro dia e adiamento."""
    if "?" in texto or _RE_DIGITO.search(texto) or _TOKEN_OUTRO_DIA.search(texto.lower()):
        return False
    if _RE_ADIAMENTO_DA_CONFIRMACAO.search(texto):
        return False
    norm = normalizar(texto)
    casou = _RE_POSSIBILIDADE_SIM.match(norm)
    if not casou:
        return False
    return all(t in _CAUDA_DE_VOCATIVO for t in norm[casou.end() :].split())


def _bursts_do_cliente_depois(
    mensagens: list[BaseMessage], ancora: int, fim: int
) -> list[tuple[list[str], list[str]]]:
    """Turnos do cliente entre `ancora` (exclusivo) e `fim` (inclusivo), cada um com as bolhas
    contíguas da IA que o antecedem — o par que `classificar_recuo` e a correferência esperam.

    Um "turno" dele é o burst (HumanMessages contíguas), a mesma unidade de `_burst_do_cliente`; a
    marca de pausa NÃO abre burst (é fronteira estrutural, não fala dele)."""
    bursts: list[tuple[list[str], list[str]]] = []
    falas: list[str] = []
    bolhas_ia: list[str] = [_texto_msg(mensagens[ancora])]
    for msg in mensagens[ancora + 1 : fim + 1]:
        if isinstance(msg, HumanMessage) and not e_marca_pausa(msg):
            falas.append(_texto_msg(msg))
            continue
        if falas:
            bursts.append((falas, bolhas_ia))
            falas, bolhas_ia = [], []
        if isinstance(msg, AIMessage):
            bolhas_ia.append(_texto_msg(msg))
    if falas:
        bursts.append((falas, bolhas_ia))
    return bursts


def _reabre_a_negociacao(fala: str) -> bool:
    """A fala do cliente REABRE o que a hora fecharia? Vetos do gatilho 5, todos já existentes:
    outra hora (`contem_hora_explicita`), outro dia (`_TOKEN_OUTRO_DIA`), preço de volta à mesa
    (`_RE_CONTEXTO_DE_PRECO` / `contem_contraproposta`), a hora re-perguntada
    (`_PERGUNTA_DE_HORARIO` — quem pergunta "que horas te espero ?" não combinou hora nenhuma) e o
    pedido da apresentação (`contem_pedido_de_infos`, que volta a conversa para antes da cotação).
    Recuo NÃO entra aqui: `classificar_recuo` precisa do burst inteiro + o antecedente dela."""
    normalizada = normalizar(fala)
    return (
        contem_hora_explicita(fala)
        or _RE_ADIAMENTO_DA_CONFIRMACAO.search(fala) is not None
        or _TOKEN_OUTRO_DIA.search(fala.lower()) is not None
        or _RE_CONTEXTO_DE_PRECO.search(normalizada) is not None
        or _PERGUNTA_DE_HORARIO.search(normalizada) is not None
        or contem_contraproposta(fala)
        or contem_pedido_de_infos(fala)
    )


def _aceite_por_continuidade(mensagens: list[BaseMessage], inicio_burst: int) -> bool:
    """Gatilho 5 — o aceite dele vale para a hora que ficou na mesa, não só para a bolha contígua.

    O defeito que ele fecha (diagnóstico da degradação tardia, 14/08): a ÚNICA porta para o fato
    "ele confirmou a hora" era turno-local, e cada turno perdido trava a FSM em `Qualificado` para
    sempre — o belief passa a mandar "ofereça esta hora e espere o sim" com o cliente já combinando
    hotel e estacionamento (papagaio medido: `<proximo_passo>` byte-idêntico por até 17 turnos).
    Aqui o aceite é transportado pela ESTRUTURA da conversa: se ela cobrou o fechamento de uma hora
    que ela mesma propôs e, desde então, nada dele reabriu a negociação, a afirmação que ele deu a
    uma cobrança POSTERIOR (que já não repete a hora) é aceite DAQUELA hora.

    Cumulativo, e cada peça é um freio medido sobre o corpus da campanha (dumps c1-c6: 122
    conversas / 954 turnos com fala do cliente, detector rodado offline, zero LLM):
      (a) ÂNCORA: bolha dela que PROPÕE a hora *e* COBRA o fechamento. Faixa de disponibilidade
          ("a partir das 10h") e promessa ("te espero") não ancoram — mesma fronteira do gatilho 2;
      (b) CONTINUIDADE: ≥2 turnos dele desde a âncora (o atual conta) — dispensada só quando a
          adesão é o ECO do verbo da própria cobrança, que é resposta direta à pergunta dela;
      (c) ADESÃO dele: aceite de fechamento, fala de vinda, ou — CORREFERIDA a uma bolha dela que
          propõe a hora ou cobra o fechamento — afirmação curta ou eco do verbo dela
          (`_adesao_por_eco_do_verbo`). A correferência é o freio que a medição exigiu: sem ela,
          "Sim" respondendo a "sou de fora, cheguei recente aqui na Barra" virava aceite de 21h;
      (d) NADA REABRIU nem foi ADIADO desde a âncora: nenhum burst com recuo, outra hora, outro
          dia, preço, contraproposta, pedido de infos, hora re-perguntada ou adiamento da
          confirmação ("vou confirmar", "tô vendo", "te confirmo").

    O léxico de (c) foi derivado dos DADOS, não da intuição: a triagem de todas as falas curtas do
    corpus correferidas a uma âncora classificou uma a uma. Só o ECO do verbo dela passou em 3 de 3
    leituras. Os candidatos "óbvios" reprovaram e ficaram FORA — "Certo" 1 aceite / 2 acknowledgment
    ("Certo, qual o valor do seu atendimento ?"), "Entendi" 1/3 ("Entendi, deixa eu ver aqui",
    "Entendi, meu orçamento está apertado"), "Legal" 0/2 ("Legal, duas finalizações ?" — ele só
    fecha três turnos depois), "Ótimo" 0/1, "Não tenho dúvidas" 0/1 (conversa perdida por objeção).

    Por que a versão SEM (c) — "continuou falando ≥2 turnos, logo aceitou" — foi descartada: medida
    sobre o corpus ela evidencia 52 turnos a mais, e a leitura fala a fala mostra que boa parte é
    cliente AINDA QUALIFICANDO sob a hora ("essas fotos são suas mesmo ?", "tu é do Rio ?", "vc faz
    anal", "Qto fica 1h ?"). O custo do falso positivo aqui não é cosmético: `horario_evidenciado`
    promove `Qualificado -> Aguardando_confirmacao`, que RESERVA o slot da agenda e muda a conduta
    para pedir Pix/foto de portaria — bloquear agenda de quem ainda pergunta o preço é pior que
    esperar mais um turno pelo aceite."""
    leitura = _leitura_da_continuidade(mensagens, inicio_burst)
    if leitura is None:
        return False
    n_bursts, aderiu, eco_da_ancora = leitura
    # A continuidade de ≥2 turnos é dispensada quando a adesão é o ECO do verbo da cobrança: aí a
    # fala dele é a RESPOSTA DIRETA à pergunta dela ("Consigo às 14h, fecha ?" -> "Consigo sim"),
    # a mesma correferência que o gatilho 2 já trata como suficiente — o gatilho 2 só não a pega
    # porque o eco não está no léxico dele. Exigir mais um turno aqui carimbaria a evidência UM
    # TURNO DEPOIS do aceite (medido: c4-lote/eb03:197499826503682 t5 e eb04:19134800761083 t7),
    # que é exatamente o atraso que este fix existe para eliminar.
    return aderiu and (n_bursts >= 2 or eco_da_ancora)


def _leitura_da_continuidade(
    mensagens: list[BaseMessage], inicio_burst: int
) -> tuple[int, bool, bool] | None:
    """Núcleo compartilhado pelo gatilho 5 e pelo sinal fraco: lê a janela DESDE a âncora.

    Devolve `(nº de turnos dele desde a âncora, houve adesão, a adesão foi eco da âncora)`, ou
    `None` quando não há âncora, não há fala dele desde ela, ou algum burst REABRIU/ADIOU (recuo,
    outra hora, outro dia, preço, contraproposta, pedido de infos, hora re-perguntada, hedge).

    Existe para que os dois leitores nunca divirjam: o que promove estado
    (`_aceite_por_continuidade`) e o que só modula a redação (`aceite_provavel_sem_confirmacao`)
    diferem APENAS na exigência de adesão, e essa diferença tem de ficar visível num lugar só."""
    inicio = next(
        (i + 1 for i in range(inicio_burst - 1, -1, -1) if e_marca_pausa(mensagens[i])), 0
    )
    ancora = next(
        (
            j
            for j in range(inicio_burst - 1, inicio - 1, -1)
            if isinstance(mensagens[j], AIMessage)
            and _bolha_da_ia_propoe_hora(_texto_msg(mensagens[j]))
            and _bolha_da_ia_cobra_o_fechamento(_texto_msg(mensagens[j]))
        ),
        None,
    )
    if ancora is None:
        return None
    bursts = _bursts_do_cliente_depois(mensagens, ancora, len(mensagens) - 1)
    if not bursts:
        return None
    aderiu = eco_da_ancora = False
    for posicao, (falas, bolhas_ia) in enumerate(bursts):
        if any(_reabre_a_negociacao(f) for f in falas):
            return None
        if classificar_recuo(falas, bolhas_ia) is not None:
            return None
        correferido = any(
            _bolha_da_ia_propoe_hora(b) or _bolha_da_ia_cobra_o_fechamento(b) for b in bolhas_ia
        )
        eco = correferido and any(_adesao_por_eco_do_verbo(f) for f in falas)
        # Só o PRIMEIRO burst responde à âncora (é ela que abre suas `bolhas_ia`, por construção).
        eco_da_ancora = eco_da_ancora or (eco and posicao == 0)
        aderiu = (
            aderiu
            or eco
            or any(
                _aceite_de_fechamento(f)
                or _fala_de_vinda(f)
                or (correferido and _e_afirmacao_curta(f))
                for f in falas
            )
        )
    return len(bursts), aderiu, eco_da_ancora


def _horario_evidenciado_no_turno(mensagens: list[BaseMessage]) -> bool:
    """True se a janela do turno EVIDENCIA o horário: existe fala do cliente que o sustenta.

    Os três gatilhos da spec (extracao-proveniencia-horario) + o gatilho 4 da campanha 13/08
    (fala de vinda / aceite explícito de fechamento), todos no corpus de produção:
      1. hora explícita numa bolha do burst atual do cliente ("Umas 16 horas" — #24);
      2. confirmação curta do cliente logo após bolha da IA que PROPÕE uma hora ("Posso confirmar
         às 18h" → "Perfeito" — #34); mesma mecânica de correferência já usada para o dia. Faixa
         aberta na bolha dela não conta (`_RE_FAIXA_ABERTA`): disponibilidade não é proposta;
      3. o mesmo par, com a bolha da IA sendo a sondagem de IMEDIATISMO ("Seria agora ?" → "sim"
         — #35): o número vem do fallback, mas a intenção é dele;
      5. aceite por CONTINUIDADE (`_aceite_por_continuidade`, diagnóstico 14/08): a afirmação dele
         vale para a hora que ELA cobrou antes na janela, não só para a bolha contígua, quando nada
         reabriu a negociação desde a cobrança. É o gatilho que impede um turno perdido de travar a
         FSM em `Qualificado` para sempre — os 1-4 são todos turno-locais e de conjunto fechado.

    O gatilho 3 usa `contem_sondagem_imediatismo`, NÃO a família inteira de sondagem do dia
    (`_PROBE_DIA_HOJE`, que também acende no "seria hoje ?"): aquele par crava o DIA e não a HORA —
    aceitá-lo carimbaria evidência sobre um horário que o fallback sintetizou, reabrindo o #25.

    EVENTO do turno, não estado: quem preserva a marca entre turnos é a coluna
    `horario_evidenciado` (o valor só perde a evidência quando MUDA sem evidência nova,
    dominio/atendimentos/service.py). Restrito ao burst atual, uma hora dita dez turnos atrás não
    revalida o palpite que o sistema gravou depois — e, como a evidência também promove a
    `intencao`, um "sim" antigo não segue forçando `agendamento` depois de o cliente recuar.

    Por que NÃO é write-time como as flags A2 (agente/CLAUDE.md): aquelas rastreiam o que a IA já
    fez (carimbáveis quando ela fala); esta lê a fala do CLIENTE e é consumida no MESMO turno, pelo
    `extrair`, junto da gravação do horário. Nunca deriva do payload da extração — é justamente o
    canal contaminado pelo eco do belief (o extrator relê o horário colado na cauda e o devolve
    como observação nova).
    """
    i = _burst_do_cliente(mensagens)
    burst = mensagens[i:]
    if not burst:  # último turno não é do cliente -> não há fala nova a sustentar o horário
        return False
    if any(contem_hora_explicita(_texto_msg(m)) for m in burst):
        return True
    # Gatilho 4 (campanha 13/08, eb02:30472893644814): fala de VINDA ("Confirmado sim", "To no
    # caminho") ou aceite EXPLÍCITO de fechamento ("Fecha", "Confirmo sim" — ciclo1
    # eb04:187007389155571 t6, retenção eb04:211711990710521 t7) + alguma bolha da IA na JANELA
    # INTEIRA que propôs hora. A adjacência do gatilho 2 não serve aqui: o compromisso é com o
    # encontro combinado, não com a última bolha — e depois do primeiro "Confirmado" da IA (sem
    # hora) a evidência ficava inalcançável, segurando a FSM em Qualificado com o cliente a
    # caminho (na retenção, a bolha contígua "Me confirma 10h..." nem conta como proposta). O
    # freio do #25 se mantém: só bolha da IA que PROPÕE hora conta (`_bolha_da_ia_propoe_hora` —
    # palpite renderizado no belief não entra na janela limpa, e faixa de disponibilidade segue
    # excluída).
    if any(
        _fala_de_vinda(_texto_msg(m)) or _aceite_de_fechamento(_texto_msg(m)) for m in burst
    ) and any(
        isinstance(m, AIMessage) and _bolha_da_ia_propoe_hora(_texto_msg(m)) for m in mensagens[:i]
    ):
        return True
    if any(_e_afirmacao_curta(_texto_msg(m)) for m in burst) and any(
        _bolha_da_ia_propoe_hora(_texto_msg(m)) or contem_sondagem_imediatismo(_texto_msg(m))
        for m in _bolhas_ia_antes_do_burst(mensagens, i)
    ):
        return True
    # Gatilho 5 (diagnóstico da degradação tardia, 14/08) — aceite por CONTINUIDADE: a adjacência
    # do gatilho 2 é o que faz um único turno perdido travar a FSM para sempre. Ver
    # `_aceite_por_continuidade` para as quatro condições e para o que a medição descartou.
    return _aceite_por_continuidade(mensagens, i)


def aceite_provavel_sem_confirmacao(mensagens: list[BaseMessage]) -> bool:
    """Sinal FRACO: a hora que ela cobrou provavelmente está de pé, mas NÃO foi confirmada por uma
    fala que o detector reconheça. É o gatilho 5 sem a exigência de adesão — âncora + o cliente
    seguiu conversando (≥2 turnos) + nada reabriu nem adiou.

    ⚠️ NUNCA use isto para promover estado, gravar `horario_evidenciado`, reservar agenda ou pedir
    Pix. A medição que separou os dois é a razão de existirem em funções diferentes: sobre o corpus
    da campanha este critério acende em ~50 turnos a mais que a evidência, e a leitura fala a fala
    mostra que boa parte é cliente AINDA QUALIFICANDO sob a hora ("essas fotos são suas mesmo ?",
    "tu é do Rio ?", "vc faz anal"). Como `horario_evidenciado` promove
    `Qualificado -> Aguardando_confirmacao` — que RESERVA o slot da agenda da modelo e vira conduta
    de Pix/foto de portaria —, um falso positivo ali custa agenda bloqueada de quem não combinou
    nada. Por isso o estado continua exigindo `_aceite_por_continuidade` (com adesão).

    Para a REDAÇÃO do contexto o cálculo se inverte, e é para isso que este sinal existe. Hoje o
    belief é binário: sem evidência ele AFIRMA "hora não confirmada — ofereça esta hora e espere o
    sim", e é essa ordem categórica que vira papagaio quando o cliente já aceitou de um jeito que o
    léxico não pega (medido: 131 de 131 turnos DEPOIS do aceite dele seguiam "não confirmada", com
    `<proximo_passo>` byte-idêntico por até 17 turnos). Aqui o falso positivo custa uma frase mais
    macia; o falso negativo custa a conversa. Quem consome escolhe a redação — este módulo não
    decide texto nem toca no estado.

    PURA e determinística, como as irmãs: lê a janela LIMPA, não persiste nada, não chama LLM.
    Inclui por construção todo turno em que `_horario_evidenciado_no_turno` é True (aceite
    confirmado é caso particular de aceite provável), então o consumidor pode testar só este sinal
    quando a pergunta é "posso parar de cobrar a confirmação ?"."""
    if _horario_evidenciado_no_turno(mensagens):
        return True
    leitura = _leitura_da_continuidade(mensagens, _burst_do_cliente(mensagens))
    return leitura is not None and leitura[0] >= 2


def _recuo_no_turno(mensagens: list[BaseMessage]) -> bool:
    """True se o burst ATUAL do cliente carrega um recuo (`classificar_recuo`, agente/_disciplina).

    Mesma mecânica de janela do horário evidenciado: o burst dele + as bolhas contíguas da IA
    imediatamente antes (o antecedente da negativa). EVENTO do turno, não estado — restrito ao
    burst atual porque um "hoje não consigo" de dez turnos atrás não rebaixa o aceite que veio
    DEPOIS dele.

    Por que NÃO é write-time como as flags A2 (agente/CLAUDE.md), pelo mesmo motivo do horário
    evidenciado: aquelas rastreiam o que a IA já fez (carimbáveis quando ela fala); esta lê a fala
    do CLIENTE e é consumida no MESMO turno, pelo `extrair`.

    Computado sobre a janela LIMPA, antes da anexação do contexto dinâmico — depois dela a cauda do
    último HumanMessage carrega o belief e a negativa curta deixaria de ser curta.
    """
    i = _burst_do_cliente(mensagens)
    burst = mensagens[i:]
    if not burst:  # último a falar não foi ele -> nada novo a retratar
        return False
    return (
        classificar_recuo(
            [_texto_msg(m) for m in burst],
            [_texto_msg(m) for m in _bolhas_ia_antes_do_burst(mensagens, i)],
        )
        is not None
    )


def _pediu_infos_no_burst(mensagens: list[BaseMessage]) -> bool:
    """True se o burst ATUAL do cliente pede a apresentação ("como funciona?", "me passa as
    infos" — `contem_pedido_de_infos`, agente/_disciplina).

    EVENTO do turno, não estado: restrito ao burst atual porque o pedido de infos de dez turnos
    atrás já foi respondido (ou cobrado) no turno em que saiu. Alimenta o ponteiro condicional de
    pitch no `<proximo_passo>` da cauda (rodada 3 do eval: "me passa as infos" respondido curto +
    pergunta devolvida foi padrão de derrota em apresentação) — só cauda, nunca guard: completude
    de pitch não se mede por regex.

    Computado sobre a janela LIMPA, antes da anexação do contexto dinâmico (mesmo motivo dos
    vizinhos)."""
    i = _burst_do_cliente(mensagens)
    return any(contem_pedido_de_infos(_texto_msg(m)) for m in mensagens[i:])


def _confirmou_dia_hoje(mensagens: list[BaseMessage]) -> bool:
    """True se a janela evidencia o abridor 'seria hoje?' (qualquer bolha da IA) respondido por uma
    afirmação curta do cliente — determinístico, sem LLM. Antes de varrer as bolhas da IA, pula a
    salva contígua do PRÓPRIO cliente: ele responde a pergunta composta 'tudo bem? seria hoje?' em
    duas bolhas ('tudobem' + 'sim'), e a afirmação fica precedida pela sua própria bolha anterior,
    não pela sondagem da IA (trace real 4837d789). Outro dia em qualquer bolha do burst → não assume
    hoje (deixa a extração capturar o dia explícito).

    Só o trecho DEPOIS da última marca de pausa conta: um par "seria hoje ?" + "sim" de seis dias
    atrás não fala do dia de HOJE (incidente 29/07, trace 06db4298), nem quando ele está inteiro no
    trecho antigo, nem quando a afirmação nova responderia a uma sondagem do trecho antigo."""
    inicio = next(
        (i + 1 for i in range(len(mensagens) - 1, -1, -1) if e_marca_pausa(mensagens[i])), 0
    )
    for i, msg in enumerate(mensagens[inicio:], start=inicio):
        if not (isinstance(msg, HumanMessage) and _e_afirmacao_curta(_texto_msg(msg))):
            continue
        j = i - 1
        # Pula a salva contígua do cliente (burst em bolhas separadas). Se alguma bolha do burst
        # cita outro dia, aborta este par — não confirma hoje.
        burst_cita_outro_dia = False
        while j >= 0 and isinstance(mensagens[j], HumanMessage):
            # A marca de pausa fecha o burst (mesma fronteira de `_burst_do_cliente`): ao parar
            # nela, a varredura das bolhas da IA abaixo também não a atravessa (a marca não é
            # AIMessage), então a sondagem do trecho antigo deixa de ser antecedente deste "sim".
            if e_marca_pausa(mensagens[j]):
                break
            if _TOKEN_OUTRO_DIA.search(_texto_msg(mensagens[j]).lower()):
                burst_cita_outro_dia = True
            j -= 1
        if burst_cita_outro_dia:
            continue
        # Varre as bolhas contíguas da IA que antecedem o burst, procurando a sondagem do dia.
        # Sonda DISJUNTIVA ("Seria hoje ou sábado ?") não conta: o "ok" do cliente responde à
        # escolha, não ao "hoje" — o veto de outro-dia vale também para a bolha da SONDA, senão
        # a disjunção da IA + afirmação curta fabricava <dia quando="hoje"> e armava a escada de
        # desconto no regime errado (loop-massa r1, eixo explorador_ambiguo).
        while j >= 0 and isinstance(mensagens[j], AIMessage):
            txt_ia = _texto_msg(mensagens[j])
            if _PROBE_DIA_HOJE.search(txt_ia) and not _TOKEN_OUTRO_DIA.search(txt_ia.lower()):
                return True
            j -= 1
    return False


def _ja_sondou_o_dia(mensagens: list[BaseMessage]) -> bool:
    """True se a IA já emitiu a sondagem do dia ("seria hoje?") em alguma AIMessage da janela.

    Guard anti-repetição (persona.md:18: a sondagem do "agora" é UMA vez). A re-pergunta vinha do
    LLM recolando a frase de sondagem mais saliente da persona sempre que o belief sinaliza
    agendamento em aberto — inclusive com o dia JÁ combinado (o A2 preenche `data_desejada`, mas o
    <antes_de_perguntar> só cobre itens de <ainda_falta>, e o dia não está lá; trace prod 9db632c7).
    Detectamos deterministicamente que a sondagem já foi feita (zero LLM, reusa `_PROBE_DIA_HOJE`)
    para o contexto dinâmico instruir a NÃO recolá-la. No turno de abertura a janela ainda não tem a
    sondagem (só a msg do cliente) → False, então não suprime o abridor social do primeiro turno.

    PARA na marca de pausa, como os detectores irmãos (`_conversa_em_andamento`,
    `_confirmou_dia_hoje`): a janela de 40 cruza atendimentos. Varrendo-a inteira, uma sondagem de
    seis dias atrás calava a sondagem no PRIMEIRO turno do atendimento novo — o oposto da conduta
    de retomada, e o mesmo modo de falha do incidente 29/07. O caso legítimo ("já sondei NESTE
    atendimento") continua coberto pelo OR com `dia_ja_sondado_hist`, que é por atendimento."""
    for msg in reversed(mensagens):
        if e_marca_pausa(msg):
            return False
        if isinstance(msg, AIMessage) and _PROBE_DIA_HOJE.search(_texto_msg(msg)):
            return True
    return False


def _conversa_em_andamento(mensagens: list[BaseMessage]) -> bool:
    """True se ELA já tem bolha nesta parte da conversa — varre de trás pra frente e PARA na marca
    de pausa (mesma fronteira dos outros detectores).

    Gate do "não recumprimente" da cauda (`contexto_dinamico.md.j2`, `<antes_de_perguntar>`). A
    frase afirmava, sem condição, que a conversa já estava no meio — e é a última instrução que o
    modelo lê antes da fala do cliente, então vencia a `<abertura>` do `regras.md.j2` no turno do
    "oi" seco: o cumprimento em 2 bolhas sumia. Condicionada aqui, ela some no primeiro contato e
    continua valendo assim que existe fala dela. A marca de pausa é a fronteira certa (e não
    "qualquer AIMessage da janela") porque a janela cruza atendimentos: bolha de seis dias atrás não
    faz o "oi" de agora ser meio de conversa — é abertura de novo (incidente 29/07).

    `modelo_manual` conta: já vem traduzida para AIMessage em `traduzir_mensagens`, e do lado do
    cliente uma bolha da modelo é fala dela igual.
    """
    for msg in reversed(mensagens):
        if e_marca_pausa(msg):
            return False
        if isinstance(msg, AIMessage):
            return True
    return False
