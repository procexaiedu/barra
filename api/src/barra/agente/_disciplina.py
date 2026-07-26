"""Detectores determinísticos de disciplina conversacional (padrão A2).

Regex compartilhados entre o WRITE-TIME (workers/envio.py, que carimba as flags em
barravips.atendimentos quando a IA fala) e o READ-TIME (agente/nos/prepare_context.py, que
ainda varre a JANELA deslizante p/ cobrir a fala do turno atual ainda não persistida). Manter
os dois lados na MESMA fonte evita drift entre o que é carimbado e o que é lido.

Fica em `agente/` (não em `dominio/`) porque depende de `normalizar` (agente/_normalizar.py) e
porque `dominio/` não pode importar `barra.agente` (dominio/CLAUDE.md). `workers/` pode importar
`agente/`; os writers de SQL puros (sem regex) é que vivem em dominio/atendimentos/service.py.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from ._normalizar import normalizar

# A2 (captura determinística do dia): o abridor social "seria hoje?" (persona.md:32). Detectar que
# a sondagem já foi feita (write-time carimba `dia_sondado_em`; read-time varre a janela) impede a
# IA de recolar a frase no turno do preço (persona.md:18, regras.md.j2:17 proíbem).
# Cobre a FAMÍLIA "hoje" E "agora": o prompt trata as duas como a MESMA sondagem ("«seria hoje?»,
# «seria agora?» é UMA vez na conversa inteira" — persona <voz>; regras.md.j2:35 e :44), mas o
# regex só via "hoje" e o gate ficava cego na variante de imediatismo. Atendimento #35 (24/07,
# 02:17-05:25): a IA sondou "Seria agora ?", nunca disse "hoje", `dia_sondado_em` ficou NULL, o
# <ja_sondou_o_dia> nunca entrou no contexto e ela recolou o empurrão 3x ("Vem agora ?") — o
# cliente lê como ansiedade. O verbo entra na alternância porque a paráfrase que o modelo produz é
# verbal ("Vem agora ?", "Pode vir agora ?"), não só o "seria". "vier" (da contraproposta "Consigo
# 500 se você vier hoje") NÃO casa: `\bvir\b` exige fronteira de palavra depois do "r".
_VERBOS_SONDAGEM = r"(?:seria|é pra|pra|é|vem|vir|vamos)"
_PROBE_DIA_HOJE = re.compile(rf"\b{_VERBOS_SONDAGEM}\s+(?:hoje|agora)\b", re.IGNORECASE)
# Só a variante de IMEDIATISMO ("seria agora ?"). Aceitá-la crava a HORA (é agora), enquanto o
# "seria hoje ?" crava só o DIA — a separação importa na proveniência do horário: um "sim" ao
# "seria hoje ?" não sustenta o horário que o fallback sintetizou.
_PROBE_AGORA = re.compile(rf"\b{_VERBOS_SONDAGEM}\s+agora\b", re.IGNORECASE)

# Contraproposta de desconto ("Consigo 500 se você vier hoje 😊") — a disciplina é ATÉ DUAS na
# conversa inteira (regras.md.j2 <desconto> 3/4, ADR-0031: degrau na 1ª, teto na 2ª e última).
# Forma canônica treinada pelo prompt: "consigo" + preço (3+ dígitos). Não colide com o resto do
# phrasebook: cotação é "600 1h no meu local" (sem "consigo"), hora é 1-2 dígitos + h (barrada pelo
# \d{3,}) e a recusa "não consigo" cai no lookbehind (texto já normalizado, sem acento).
_RE_CONTRAPROPOSTA = re.compile(r"(?<!nao )\bconsigo\s+(?:r\$\s*)?\d{3,}\b")


def contem_contraproposta(texto: str) -> bool:
    """True se a bolha carrega a contraproposta de desconto (ADR-0031). `normalizar` antes do
    match: tira acento/caixa p/ o lookbehind "não consigo" bater sem acento."""
    return _RE_CONTRAPROPOSTA.search(normalizar(texto)) is not None


def contem_sondagem_dia(texto: str) -> bool:
    """True se a bolha carrega a sondagem do dia ("seria hoje?", "seria agora?", "vem agora?").
    Sem `normalizar`: o regex já é case-insensitive e casa o "é" acentuado da forma canônica da
    persona."""
    return _PROBE_DIA_HOJE.search(texto) is not None


# Convite pra conhecer a amiga (regras.md.j2 <menage>): oferta de pós-venda que é UMA vez na
# negociação. O convite sai no FIM (com a venda já fechada), que é justamente onde ele desliza pra
# fora da janela de 20 msgs — sem a coluna materializada a IA reoferece.
#
# O corte é entre a oferta PROATIVA dela e a resposta de ESCALADA ("Deixa eu ver com ela e já te
# retorno amor"), que a IA dá quando é o CLIENTE quem pede a dupla: escalada não é convite, e
# carimbá-la calaria uma oferta que ela nunca fez. O possessivo é exigido nos verbos de trazer
# ("chamar/trazer minha amiga") porque "trazer sua amiga" é a segunda pessoa DELE, o outro ramo do
# <menage>. O determinante ("uma"/"minha") + o lookbehind mantêm a negativa do <fora_do_cardapio>
# ("não tenho uma amiga pra levar") fora da oferta.
_OFERTA_AMIGA = re.compile(
    r"(?<!nao )\btenho (?:uma|a minha|minha) amiga\b"
    r"|\bconhecer as duas\b"
    r"|\bconhecer (?:a )?(?:uma|minha) amiga\b"
    r"|\b(?:chamar|trazer|convidar) (?:a )?minha amiga\b"
)
# Escalada do pedido DELE — vence a oferta ("Tenho uma amiga sim amor" / "Deixa eu ver com ela"):
# quem abriu o assunto foi o cliente, o trilho é escalar, não convidar. Vive numa função à parte
# porque o veto é do TURNO, não da bolha: o chunker parte essa dupla em duas bolhas com facilidade,
# e a 1ª sozinha carimbaria a oferta que a 2ª desmente.
_ESCALADA_AMIGA = re.compile(
    r"\bdeixa eu (?:ver|falar|combinar|checar) com (?:a )?(?:ela|minha amiga)\b"
)


def contem_escalada_da_amiga(texto: str) -> bool:
    """True se o texto carrega a resposta de escalada do <menage> ("Deixa eu ver com ela amor").

    Recebe o TURNO inteiro no write-time (workers/envio.py): é o veto da oferta."""
    return _ESCALADA_AMIGA.search(normalizar(texto)) is not None


def contem_oferta_da_amiga(texto: str) -> bool:
    """True se a bolha CONVIDA o cliente pra conhecer a amiga (<menage>, oferta de pós-venda).

    `normalizar` antes do match: tira acento/caixa p/ o lookbehind "não tenho" bater sem acento.
    A escalada na MESMA bolha já veta aqui; partida entre bolhas, quem veta é o chamador com
    `contem_escalada_da_amiga` sobre o turno."""
    if contem_escalada_da_amiga(texto):
        return False
    return _OFERTA_AMIGA.search(normalizar(texto)) is not None


# Pedido do print da chegada (<tipos_de_encontro>: "Quando chegar me manda uma foto da portaria
# amor"). Sai UMA vez: pedido o print, a IA espera com presença curta e não recobra — "vai vir
# mesmo ?"/"chega em quanto tempo ?" repetidos são, pelo próprio prompt, o que mais afasta nessa
# fase. O pedido mora no FIM do combinado e desliza pra fora da janela justamente enquanto o
# cliente não chega, que é quando a regra vale.
#
# Duas famílias, porque o pedido aparece com e sem a palavra "portaria":
#  (a) foto/print PERTO de "portaria", nas duas ordens ("foto da portaria", "na portaria me manda
#      uma foto") — a forma da despedida do combinado;
#  (b) sem a palavra "portaria": pedido imperativo de foto E menção à chegada na MESMA bolha, em
#      qualquer ordem ("me manda uma foto quando chegar", "quando você chegou me manda a foto") —
#      é a forma que sai em resposta a "cheguei"/"to chegando", onde o contexto já está posto e o
#      modelo omite "portaria". A ordem é livre de propósito: exigi-la deixava cega justamente a
#      variante do turno em que a IA mais recobra.
# O imperativo (`manda`, não `mandar`) é o que separa o PEDIDO da promessa dela ("quando chegar vou
# te mandar uma foto", que é mídia do <midia>); a exigência de chegada/portaria mantém o book e o
# comprovante do Pix fora.
_FOTO = r"(?:foto|fotinha|print|imagem)\w*"
_PORTARIA_COM_FOTO = re.compile(
    rf"\b{_FOTO}\b[^\n]{{0,30}}\bportaria\b|\bportaria\b[^\n]{{0,30}}\b{_FOTO}\b"
)
_PEDIDO_DE_FOTO = re.compile(rf"\b(?:manda|mande|envia|envie)\b[^\n]{{0,20}}\b{_FOTO}\b")
_MENCAO_DE_CHEGADA = re.compile(r"\bcheg(?:ar|ando|ou|uei|a)\b")


def contem_pedido_da_foto_de_portaria(texto: str) -> bool:
    """True se a bolha PEDE o print da chegada ("Quando chegar me manda uma foto da portaria").

    `normalizar` antes do match: tira acento/caixa (o texto do modelo vem com "fotinha"/"imagem"
    acentuados em volta). Alimenta `foto_portaria_pedida_em` no write-time — pedir continua
    permitido (é o print, quando chega, que dispara o handoff implícito); o que a flag corta é a
    RECOBRANÇA enquanto ele não chega."""
    t = normalizar(texto)
    if _PORTARIA_COM_FOTO.search(t):
        return True
    return bool(_PEDIDO_DE_FOTO.search(t) and _MENCAO_DE_CHEGADA.search(t))


# Proveniência do horário (spec extracao-proveniencia-horario): a fala carrega uma HORA do relógio.
# Dois formatos, porque "2h" sozinho é AMBÍGUO no domínio — a duração do programa se escreve igual
# ao horário ("600 1h no meu local" é cotação; "quanto é 1h?" é duração):
#  (a) hora com MINUTO ("17:30", "18h15") ou o literal meio-dia/meia-noite: nunca é duração;
#  (b) hora cheia PRECEDIDA de marcador temporal ("às 18h", "umas 16 horas", "daqui 1h",
#      "tipo 18h", "pode ser 2h"). Sem o marcador não conta — falso positivo aqui carimba
#      evidência num horário que o cliente nunca pediu, que é justamente a falha do #25.
_HORA = r"(?:[01]?\d|2[0-3])"
_SUFIXO_HORA = r"(?:h|hs|hrs|horas?)\b"
_RE_HORA_COM_MINUTO = re.compile(rf"\b{_HORA}\s*[:h]\s*[0-5]\d\b|\bmeio\s?dia\b|\bmeia\s?noite\b")
_MARCADOR_TEMPORAL = (
    r"(?:as|umas?|pelas?|por volta d(?:as|a|e)|daqui(?:\s+a)?|tipo|pode ser|seria|ate|"
    r"depois d(?:as|e)|antes d(?:as|e))"
)
_RE_HORA_COM_MARCADOR = re.compile(rf"\b{_MARCADOR_TEMPORAL}\s+{_HORA}\s*{_SUFIXO_HORA}")


def contem_sondagem_imediatismo(texto: str) -> bool:
    """True se a bolha carrega a sondagem de IMEDIATISMO ("seria agora ?", "vem agora ?").

    Recorte de `contem_sondagem_dia` usado pela proveniência do horário: aceitar "seria agora ?"
    é o cliente dizendo QUE HORAS (agora); aceitar "seria hoje ?" só crava o dia."""
    return _PROBE_AGORA.search(texto) is not None


def contem_hora_explicita(texto: str) -> bool:
    """True se a fala carrega uma hora do relógio ("Umas 16 horas", "18h15", "às 17:30").

    `normalizar` antes do match: tira acento/caixa p/ "às"/"até" casarem sem acento. Usado nos
    dois primeiros gatilhos do horário evidenciado (fala do cliente com hora; bolha da IA com
    hora seguida de confirmação curta) — ver `_horario_evidenciado_no_turno` (nos/prepare_context).
    """
    t = normalizar(texto)
    return _RE_HORA_COM_MINUTO.search(t) is not None or _RE_HORA_COM_MARCADOR.search(t) is not None


# Pergunta de horário SEM proposta ("Seria que horas ?", "Qual horário amor ?") — o empurrão que o
# <conducao_da_venda> autoriza, e que vira loop quando o cliente desconversa (emoji, elogio, "que
# bom rs"). A disciplina tem DOIS degraus (por isso contador, como `n_contrapropostas`, e não
# timestamp): na 1ª repetição ela propõe um horário concreto; da 2ª em diante não pergunta mais.
#
# Dois cortes:
#  (a) a "?" é exigida, como no `_PEDE_FECHAMENTO`: o empurrão de horário sempre acaba nela, e sem
#      ela a bolha é outra coisa ("me avisa que horas você sai" é devolução do ônus, não pergunta);
#  (b) fala que já põe uma HORA na mesa é PROPOSTA, não pergunta ("Consigo às 21h ou prefere que
#      horas ?") — é exatamente o que a tag manda fazer no lugar da re-pergunta, e contá-la
#      gastaria a disciplina no turno em que a IA acertou (ver `contem_hora_na_mesa`).
# A sondagem do DIA ("seria hoje ?", "seria agora ?") não precisa de veto: ela tem flag própria
# (`dia_sondado_em`) e vocabulário disjunto deste — o teste de fronteira é que segura isso.
_PERGUNTA_DE_HORARIO = re.compile(r"\b(?:que|qual)\s+(?:hora|horas|horario|horarios)\b")

# Hora CRUA, sem marcador temporal: "Podemos combinar 21h amor ?", "consigo 14h". É o buraco que
# `contem_hora_explicita` deixa de propósito (lá o marcador é o que separa horário de DURAÇÃO,
# "quanto é 1h ?") — e "combinar 21h" é justamente a fala que o prompt manda usar no lugar da
# re-pergunta. Só é lida DENTRO do veto abaixo, onde errar para o lado largo custa um
# falso-negativo benigno (o contador não anda) em vez de queimar o degrau num turno certo.
_RE_HORA_CRUA = re.compile(rf"\b{_HORA}\s*{_SUFIXO_HORA}")


def contem_hora_na_mesa(texto: str) -> bool:
    """True se a fala põe uma HORA do relógio na mesa ("às 18h", "17:30", "combinar 21h").

    Veto da pergunta de horário, nos dois níveis: por BOLHA (a proposta que emenda a pergunta) e
    por TURNO em `workers/envio.py` — o chunker parte "Consigo às 21h amor" / "ou prefere que
    horas ?" em duas bolhas com facilidade, e a 2ª sozinha contaria a pergunta que a 1ª já
    respondeu com um horário."""
    return contem_hora_explicita(texto) or _RE_HORA_CRUA.search(normalizar(texto)) is not None


def contem_pergunta_de_horario(texto: str) -> bool:
    """True se a bolha PERGUNTA o horário sem propor nenhum ("Seria que horas amor ?").

    `normalizar` antes do match: tira acento/caixa p/ "horário" casar. Alimenta
    `n_perguntas_de_horario` no write-time — perguntar continua permitido (é a alavanca de
    fechamento do <conducao_da_venda>); o que o contador corta é a re-pergunta em loop."""
    t = normalizar(texto)
    if "?" not in t or contem_hora_na_mesa(t):
        return False
    return _PERGUNTA_DE_HORARIO.search(t) is not None


# Pergunta do MOTIVO no resgate da despedida (<desconto>: "obrigado, fica pra próxima" ainda não é
# perda — "Poxa, não gostou de mim ?"). Sai UMA vez: perguntar de novo deixa de ser resgate e vira
# cobrança, e é justamente quando ele volta depois de um silêncio — com a pergunta já fora da janela
# de 20 msgs — que a IA repete.
#
# Duas famílias, e o "?" é exigido nas duas (como no `_PERGUNTA_DE_HORARIO`): o resgate é pergunta,
# e sem ela a bolha é outra coisa.
#  (a) a NEGAÇÃO do gostar, ancorada NELA ("não gostou de mim ?", "não gostou mais de mim ?") — a
#      forma canônica. O "de mim" é o que segura os dois falsos-positivos do mesmo trecho: a
#      negação do OBJETO ("não curtiu as fotos ?" pós-book é venda, não resgate) e a negação
#      embutida na contraproposta ("se você não gostou do valor consigo 500, fecha ?"). Carimbar
#      qualquer uma calaria o resgate real da despedida, que é o que a flag existe pra proteger;
#  (b) o motivo pedido com todas as letras ("posso saber o motivo ?", "qual o motivo ?"), mais as
#      duas paráfrases que o modelo produz no lugar dela ("desistiu de mim ?", "foi alguma coisa
#      que eu falei ?") — "desistiu" também ancorado nela, senão a cobrança da espera ("desistiu de
#      vir ?") entra.
# As duas vizinhas de trecho ficam de fora por construção: a recusa de desconto ("Poxa amor não
# consigo") não é pergunta, e o empurrão de fechamento ("Podemos confirmar 21h ?") tem vocabulário
# disjunto deste.
_DE_MIM = r"[^\n]{0,10}\bde mim\b"
_PERGUNTA_DO_MOTIVO = re.compile(
    rf"\bnao (?:gostou|curtiu){_DE_MIM}"
    r"|\b(?:o|algum) motivo\b"
    rf"|\bdesistiu{_DE_MIM}"
    r"|\bfoi (?:algo|alguma coisa) que eu\b"
)


def contem_pergunta_do_motivo_do_resgate(texto: str) -> bool:
    """True se a bolha pergunta o MOTIVO da despedida ("Poxa, não gostou de mim ?").

    `normalizar` antes do match: tira acento/caixa p/ "não" casar sem acento. Alimenta
    `motivo_resgate_perguntado_em` no write-time — perguntar continua sendo o resgate do
    <desconto>; o que a flag corta é a re-pergunta, inclusive quando ele volta depois de sumir."""
    t = normalizar(texto)
    if "?" not in t:
        return False
    return _PERGUNTA_DO_MOTIVO.search(t) is not None


# Palavra de lugar que qualquer endereco tem: nao distingue o ponto de encontro DELA de nenhum
# outro, entao nao serve de evidencia de que ela entregou o endereco.
_GENERICOS_DE_LUGAR = frozenset(
    {"rua", "avenida", "av", "hotel", "residence", "apto", "apartamento", "predio", "casa"}
)
_SEPARADOR_TOKENS = re.compile(r"[^\wÀ-ÿ]+")


def tokens_de_lugar(*campos: str | None) -> set[str]:
    """Tokens normalizados dos campos de lugar do cadastro — o vocabulario de lugar da modelo.

    Descarta token de ate 2 letras e puro digito: o "SP"/"291"/"13024-020" do endereco formatado
    casaria com quase qualquer texto e furaria os detectores que dependem disto.
    """
    tokens: set[str] = set()
    for campo in campos:
        if campo:
            tokens |= {t for t in _SEPARADOR_TOKENS.split(normalizar(campo)) if len(t) > 2}
    return {t for t in tokens if not t.isdigit()}


def tokens_do_endereco(
    endereco: str | None, nome_local: str | None, regiao: str | None
) -> set[str]:
    """Tokens que so aparecem quando ela ENTREGA o ponto de encontro (nome do hotel, nome da rua).

    Tira a REGIAO de proposito: dizer o bairro e o degrau ANTERIOR do <tipos_de_encontro> ("no
    1o contato, so a regiao"), e a regiao esta contida no endereco formatado ("R. Santos Dumont,
    291 - Cambui, Campinas") — sem descontar, um simples "aqui no Cambui" contaria como endereco
    entregue. Tira tambem os genericos, que aparecem em qualquer endereco.
    """
    return tokens_de_lugar(endereco, nome_local) - tokens_de_lugar(regiao) - _GENERICOS_DE_LUGAR


def contem_endereco_de_encontro(texto: str, tokens_endereco: set[str]) -> bool:
    """True se a bolha ENTREGA o ponto de encontro (cita o nome do hotel ou o nome da rua).

    A2 do endereco (atendimento #41, 24/07 10:03): a IA disse "Vem aqui então / Já sabe onde é" —
    e so passou o endereco 7 minutos DEPOIS. "Ja passei o endereco" nao era fato rastreado em lugar
    nenhum, e a janela deslizante e curta demais pra servir de memoria. Sem `tokens_endereco`
    (cadastro sem endereco) nao ha o que detectar."""
    if not tokens_endereco:
        return False
    return bool(set(_SEPARADOR_TOKENS.split(normalizar(texto))) & tokens_endereco)


# Recuo do cliente (spec extracao-aceite-hibrido) — SITE CANÔNICO do porquê; os outros pontos da
# cadeia (estado.py, ferramentas/extracao.py, dominio/atendimentos/service.py) referenciam daqui.
#
# É a fala que REABRE a negociação de preço, e com ela a escada do <desconto>. O vocabulário é o do
# `regras.md.j2` <conducao_da_venda> ("Recuo pós-objeção": "Ainda não", "estou analisando", "vou
# ver", "te chamo antes"), inclusive a distinção que ele já faz do "vou te avisando" — quem diz
# isso JÁ quer, só não manda no relógio. O prompt é a fonte das formas: mudou a fala de lá, revise
# `_PEDE_FECHAMENTO`/`_NAO_E_RECUO` aqui, senão o detector fica cego em silêncio.
#
# Existe porque o único canal de retratação era o campo `limpar`, que o extrator usou 2 vezes em
# 531 extrações: na prática o aceite só subia. No #19 o cliente respondeu "Não" ao "Podemos
# confirmar 18h ?" e o atendimento seguiu com o preço marcado como aceito — o belief passa a
# mandar "não re-cote nem renegocie" e a venda morre sem nunca oferecer o degrau.

# Lista negativa — NUNCA é recuo: "vou te avisando", "te aviso quando sair", "me confirma". Age
# sobre a família CONDICIONAL abaixo, que é onde o vocabulário colide de fato ("te aviso quando eu
# puder" é aviso, não recuo). Recuo EXPLÍCITO na mesma bolha vence o veto: quem escreve "hoje não
# consigo, te aviso quando der" recuou, e no WhatsApp as duas coisas cabem numa bolha só.
_NAO_E_RECUO = re.compile(r"\b(?:te avis|vou avisando|me confirma|te confirmo)")

# Recuo AUTÔNOMO explícito: a fala se basta, não precisa de correferência nem sobrevive a veto.
_RECUO_AUTONOMO = re.compile(
    # deliberação ("vou ver", "estou analisando", "depois eu vejo")
    r"\bvou (?:ver|pensar|analisar|dar uma olhada)\b"
    # "vendo" fica de FORA desta família: "to vendo" é o cliente olhando as fotos tanto quanto
    # deliberando, e o par "deixa eu ver"/"vou ver" já cobre a deliberação sem essa ambiguidade.
    r"|\b(?:estou|to) (?:analisando|pensando)\b"
    r"|\bdeixa eu (?:ver|pensar)\b"
    r"|\bdepois eu (?:vejo|penso|falo)\b"
    # impossibilidade agora ("hoje não consigo" — #27)
    r"|\b(?:hoje|agora) nao (?:consigo|posso|da|vai dar|rola)\b"
    r"|\bnao (?:consigo|posso|vou conseguir|vai dar|da) (?:hoje|agora)\b"
    # adiamento para um futuro indefinido ("esperar começo do mês" — #20)
    r"|\b(?:mes|semana) que vem\b|\bprox(?:imo mes|ima semana)\b"
    r"|\b(?:comeco|inicio) do mes\b"
    r"|\bmais (?:pra|para) frente\b"
    r"|\boutro dia\b|\boutra hora\b"
    # retorno diferido — só as formas do prompt ("te chamo antes"). "te chamo/te ligo" solto NÃO
    # entra: "te chamo quando sair de casa" é a mesma coisa que "te aviso quando sair", que a lista
    # negativa protege (o #34 com outro verbo).
    r"|\bte (?:chamo|ligo) (?:antes|depois)\b"
)

# Recuo CONDICIONAL ("quando eu tiver"): mesma classe, mas derrotável pela lista negativa. O sujeito
# "eu" é exigido porque sem ele a forma é pedido, não recuo — "me manda quando puder" é o cliente
# pedindo mídia, e rebaixaria o aceite à toa.
_RECUO_CONDICIONAL = re.compile(
    r"\bquando eu (?:tiver|puder|der|conseguir)\b|\bassim que eu (?:puder|der|conseguir)\b"
)

# Negativa CURTA do cliente — conjunto fechado, como as afirmações do detector de horário. Fechado
# de propósito: "Não conheço" (#24, respondendo a "Campinas ?") começa igual e não é recuo, então
# um prefixo genérico de "não" rebaixaria o aceite por qualquer negativa de conversa. "ainda não"
# mora AQUI, e não no recuo autônomo, pelo mesmo motivo: o prompt o cita como resposta À proposta
# ("Ainda não" depois da sua proposta), e solto ele reabre o #24 ("ainda não conheço, mas topo").
_NEGATIVAS_CURTAS = frozenset(
    {
        "nao",
        "nao nao",
        "agora nao",
        "hoje nao",
        "ainda nao",
        "acho que nao",
        "melhor nao",
        "nao posso",
        "nao consigo",
        "nao da",
        "nao vai dar",
        "nao obrigado",
        "nao por enquanto",
    }
)
_SO_LETRAS = re.compile(r"[^a-z ]+")

# Bolha da IA que PEDE o fechamento — o antecedente que dá sentido ao "não" isolado. Formas
# canônicas do prompt ("Posso confirmar às 18h ?", "Consigo às 22h, fecha ?", "Confirmado ?",
# "Fechamos 15h então ?"). O "?" é exigido porque o empurrão de fechamento sempre acaba em "?"
# (<conducao_da_venda>) — sem ele a bolha é promessa, não proposta.
_PEDE_FECHAMENTO = re.compile(
    r"\b(?:confirmar|confirmado|confirmamos|fecha|fechamos|fechado|marcado|marcamos|reservo)\b"
    r"[^?]*\?"  # o empurrão de fechamento SEMPRE acaba em "?"; sem ele a bolha é promessa
)


def _e_negativa_curta(texto_normalizado: str) -> bool:
    """True se a bolha é uma negativa curta do conjunto fechado ("não", "agora não", "acho que
    não"). Reduz a alpha+espaço antes de comparar: descarta emoji e pontuação ("Não 😕" → "nao")."""
    return " ".join(_SO_LETRAS.sub(" ", texto_normalizado).split()) in _NEGATIVAS_CURTAS


def classificar_recuo(
    falas_cliente: Iterable[str], bolhas_ia: Iterable[str]
) -> Literal["autonomo", "correferenciado"] | None:
    """Classifica o recuo do cliente no turno; `None` = não recuou.

    `falas_cliente` são as bolhas do burst ATUAL dele; `bolhas_ia` as bolhas contíguas da IA
    imediatamente antes — o antecedente ao qual a negativa se refere.

    Duas classes, porque o "não" isolado é ambíguo demais para valer sozinho (#24: "Não conheço"
    respondendo a "Campinas ?"): o recuo AUTÔNOMO se basta na fala dele; a negativa
    CORREFERENCIADA só conta colada num pedido de fechamento da IA.
    """
    falas = [normalizar(t) for t in falas_cliente]
    for fala in falas:
        if _RECUO_AUTONOMO.search(fala):
            return "autonomo"
        if _RECUO_CONDICIONAL.search(fala) and not _NAO_E_RECUO.search(fala):
            return "autonomo"
    pediu_fechamento = any(_PEDE_FECHAMENTO.search(normalizar(b)) for b in bolhas_ia)
    if pediu_fechamento and any(_e_negativa_curta(t) for t in falas):
        return "correferenciado"
    return None


def contar_contrapropostas(textos: Iterable[str]) -> int:
    """Nº de linhas de `mensagens` (bolha/chunk enviado, não turno lógico) que carregam a
    contraproposta de desconto (ADR-0031: até 2 por atendimento — degrau na 1ª, teto na 2ª e
    última). Conta por linha (`search`, não `findall`): a frase canônica é curta e o chunker do
    envio não a parte nem a repete dentro do mesmo turno, então bolha ≈ oferta na prática."""
    return sum(1 for t in textos if contem_contraproposta(t))
