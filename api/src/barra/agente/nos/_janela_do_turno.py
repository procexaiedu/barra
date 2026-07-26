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
    _PROBE_DIA_HOJE,
    classificar_recuo,
    contem_hora_explicita,
    contem_sondagem_imediatismo,
)

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
# Cliente citou OUTRO dia → não assume hoje (deixa a extração capturar o dia explícito).
_TOKEN_OUTRO_DIA = re.compile(
    r"\b(amanh[ãa]|depois de amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|"
    r"semana|m[êe]s|dia \d+)\b",
    re.IGNORECASE,
)
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
    }
)
# Primeira palavra forte o bastante p/ valer mesmo seguida de vocativo ("sim amor", "claro vida").
_AFIRMACOES_FORTES = frozenset({"sim", "isso", "claro", "aham", "uhum", "ahan", "perfeito"})


def _texto_msg(msg: BaseMessage) -> str:
    return msg.content if isinstance(msg.content, str) else ""


def _normalizar_afirmacao(texto: str) -> str:
    """Reduz a alpha+espaço minúsculo (descarta emoji/pontuação): 'Sim 😊' → 'sim'."""
    limpo = "".join(c for c in texto.lower() if c.isalpha() or c.isspace())
    return " ".join(limpo.split())


def _e_afirmacao_curta(texto: str) -> bool:
    """True se a msg do cliente é uma afirmação curta de 'sim' SEM citar outro dia."""
    if _TOKEN_OUTRO_DIA.search(texto.lower()):
        return False
    norm = _normalizar_afirmacao(texto)
    if not norm:
        return False
    return norm in _AFIRMACOES or norm.split()[0] in _AFIRMACOES_FORTES


def _burst_do_cliente(mensagens: list[BaseMessage]) -> int:
    """Índice onde começa o burst ATUAL do cliente (HumanMessages contíguas no fim da janela);
    `len(mensagens)` quando o último a falar não foi ele."""
    i = len(mensagens)
    while i > 0 and isinstance(mensagens[i - 1], HumanMessage):
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


def _horario_evidenciado_no_turno(mensagens: list[BaseMessage]) -> bool:
    """True se a janela do turno EVIDENCIA o horário: existe fala do cliente que o sustenta.

    Os três gatilhos da spec (extracao-proveniencia-horario), todos no corpus de produção:
      1. hora explícita numa bolha do burst atual do cliente ("Umas 16 horas" — #24);
      2. confirmação curta do cliente logo após bolha da IA que contém hora ("Posso confirmar às
         18h" → "Perfeito" — #34); mesma mecânica de correferência já usada para o dia;
      3. o mesmo par, com a bolha da IA sendo a sondagem de IMEDIATISMO ("Seria agora ?" → "sim"
         — #35): o número vem do fallback, mas a intenção é dele.

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
    if not any(_e_afirmacao_curta(_texto_msg(m)) for m in burst):
        return False
    return any(
        contem_hora_explicita(_texto_msg(m)) or contem_sondagem_imediatismo(_texto_msg(m))
        for m in _bolhas_ia_antes_do_burst(mensagens, i)
    )


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


def _confirmou_dia_hoje(mensagens: list[BaseMessage]) -> bool:
    """True se a janela evidencia o abridor 'seria hoje?' (qualquer bolha da IA) respondido por uma
    afirmação curta do cliente — determinístico, sem LLM. Antes de varrer as bolhas da IA, pula a
    salva contígua do PRÓPRIO cliente: ele responde a pergunta composta 'tudo bem? seria hoje?' em
    duas bolhas ('tudobem' + 'sim'), e a afirmação fica precedida pela sua própria bolha anterior,
    não pela sondagem da IA (trace real 4837d789). Outro dia em qualquer bolha do burst → não assume
    hoje (deixa a extração capturar o dia explícito)."""
    for i, msg in enumerate(mensagens):
        if not (isinstance(msg, HumanMessage) and _e_afirmacao_curta(_texto_msg(msg))):
            continue
        j = i - 1
        # Pula a salva contígua do cliente (burst em bolhas separadas). Se alguma bolha do burst
        # cita outro dia, aborta este par — não confirma hoje.
        burst_cita_outro_dia = False
        while j >= 0 and isinstance(mensagens[j], HumanMessage):
            if _TOKEN_OUTRO_DIA.search(_texto_msg(mensagens[j]).lower()):
                burst_cita_outro_dia = True
            j -= 1
        if burst_cita_outro_dia:
            continue
        # Varre as bolhas contíguas da IA que antecedem o burst, procurando a sondagem do dia.
        while j >= 0 and isinstance(mensagens[j], AIMessage):
            if _PROBE_DIA_HOJE.search(_texto_msg(mensagens[j])):
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
    sondagem (só a msg do cliente) → False, então não suprime o abridor social do primeiro turno."""
    return any(
        isinstance(m, AIMessage) and _PROBE_DIA_HOJE.search(_texto_msg(m)) for m in mensagens
    )
