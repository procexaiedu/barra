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
from datetime import time
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
# conversa inteira (regras.md.j2 <desconto> 5/6, ADR-0031: degrau na 1ª, teto na 2ª e última).
# Forma canônica treinada pelo prompt: "consigo" + preço (3+ dígitos). Não colide com o resto do
# phrasebook: cotação é "600 1h no meu local" (sem "consigo"), hora é 1-2 dígitos + h (barrada pelo
# \d{3,}) e a recusa "não consigo" cai no lookbehind (texto já normalizado, sem acento).
#
# Ramo de ACEITE (ADR-0040): a rodada também é consumida quando quem nomeia o número é o CLIENTE e
# ela só diz sim — e a fala natural desse sim ("Fechado 700 amor", "Tabom, 700 então") não tem
# "consigo". Sem este ramo o contador não anda, a escada não esgota e a mesma conversa vira leilão
# (700 → 650 → 620): o orçamento de rodadas é a ÚNICA coisa que segura isso. Prescrever a frase
# "Consigo 700 sim amor" no prompt faria o contador andar de graça — foi recusado pelo dono do
# produto (conduta prescrita como frase vira tique), então quem alarga é o detector.
#
# A fronteira que este ramo NÃO pode cruzar é a COTAÇÃO: "400 1h no meu local" não é contraproposta
# nenhuma. Por isso (a) nenhum ramo casa número solto — o token de fechamento é obrigatório e vem
# COLADO nele —, e (b) número seguido de duração está barrado por lookahead, que é o que separa o
# aceite ("Fechado 700 amor") da cotação com muleta na frente ("Fechado, 400 1h no meu local").
_TOKENS_DE_ACEITE = r"fechado|fechados|fechamos|combinado|tabom|ta bom|fecho|faco|topo"
_SEM_DURACAO_COLADA = r"(?!\s*(?:\d{1,2}\s*h|h\b|hora|hr\b|min))"
# O ELO entre "consigo" e o numero. Ate 11/08/2026 o ramo exigia o numero COLADO em "consigo", e a
# fala que o dono do produto ditou para a oferta condicionada ao dia (ADR-0041) — "se vier hoje
# consigo FAZER 600 uma hora" — nao casava: o contador nao andava, a escada nunca esgotava e a IA
# repetia a mesma oferta para sempre. Medido em 11/08 no regex antigo: "consigo te fazer por 600",
# "consigo deixar em 600" e "consigo fazer 600" davam False; so "consigo 600" dava True.
#
# O elo e OPCIONAL e fechado: verbo de concessao (com "te" opcional) e/ou preposicao. Nao afrouxa
# nenhuma das duas fronteiras que o ramo tem de segurar:
#  - a RECUSA ("nao consigo fazer 600") continua barrada pelo mesmo lookbehind, que morde antes do
#    elo, no "consigo" — texto ja normalizado, sem acento;
#  - a COTACAO ("400 1h no meu local", "Podemos combinar 2h 1000") nao tem "consigo" e nunca casou;
#    e o upsell da conduta de subir o tempo ("consigo fazer 2h por 800") tambem nao casa, porque
#    entre o elo e o numero de 3+ digitos entra a DURACAO — subir o ticket nao e desconto e nao
#    pode consumir rodada da escada.
_ELO_DO_CONSIGO = (
    r"(?:(?:te\s+)?(?:fazer|deixar|colocar|baixar)(?:\s+(?:por|em|pra|para|a))?|por|em)\s+"
)
_RE_CONTRAPROPOSTA = re.compile(
    rf"(?<!nao )\bconsigo\s+(?:{_ELO_DO_CONSIGO})?(?:r\$\s*)?\d{{3,}}\b"
    rf"|(?<!nao )\b(?:{_TOKENS_DE_ACEITE})[,!]?\s+(?:por\s+|em\s+|r\$\s*)?\d{{3,}}\b"
    + _SEM_DURACAO_COLADA
    + r"|\b\d{3,}\b\s+(?:entao|fechado|fechamos|combinado)\b"
)


def contem_contraproposta(texto: str) -> bool:
    """True se a bolha carrega a contraproposta de desconto (ADR-0031). `normalizar` antes do
    match: tira acento/caixa p/ o lookbehind "não consigo" bater sem acento."""
    return _RE_CONTRAPROPOSTA.search(normalizar(texto)) is not None


def contem_sondagem_dia(texto: str) -> bool:
    """True se a bolha carrega a sondagem do dia ("seria hoje?", "seria agora?", "vem agora?").
    Sem `normalizar`: o regex já é case-insensitive e casa o "é" acentuado da forma canônica da
    persona."""
    return _PROBE_DIA_HOJE.search(texto) is not None


# Convite pra conhecer a amiga (regras.md.j2 <composicoes>): oferta de pós-venda que é UMA vez na
# negociação. O convite sai no FIM (com a venda já fechada), que é justamente onde ele desliza pra
# fora da janela de 20 msgs — sem a coluna materializada a IA reoferece.
#
# O corte é entre a oferta PROATIVA dela e a resposta de ESCALADA ("Deixa eu ver com ela e já te
# retorno amor"), que a IA dá quando é o CLIENTE quem pede a dupla: escalada não é convite, e
# carimbá-la calaria uma oferta que ela nunca fez. O possessivo é exigido nos verbos de trazer
# ("chamar/trazer minha amiga") porque "trazer sua amiga" é a segunda pessoa DELE, o outro ramo do
# <composicoes>. O determinante ("uma"/"minha") + o lookbehind mantêm a negativa do <fora_do_cardapio>
# ("não tenho uma amiga pra levar") fora da oferta.
_OFERTA_AMIGA = re.compile(
    r"(?<!nao )\btenho (?:uma|a minha|minha) amiga\b"
    r"|\bconhecer as duas\b"
    r"|\bconhecer (?:a )?(?:uma|minha) amiga\b"
    r"|\b(?:chamar|trazer|convidar) (?:a )?minha amiga\b"
)
# "Deixa eu ver com ela" — a fala da ESCALADA, que o `<composicoes>` prescrevia quando era o
# CLIENTE quem pedia a dupla. O ADR-0042 REVOGOU essa escalada: hoje a modelo do canal fecha o
# encontro das duas sozinha, e essa bolha não é mais conduta nenhuma — é regressão de prompt
# (ilustrada no par de `<armadilhas_de_voz>` da persona), e o judge/telemetria a lê como tal.
#
# O detector CONTINUA vetando o carimbo de `amiga_ofertada_em`, e por um motivo que sobreviveu à
# revogação: "Deixa eu ver com ela" promete um retorno, não CONVIDA. Carimbar a oferta ali marcaria
# como aceito um convite que ela nunca fez — e é justamente `amiga_ofertada_em` que a tool
# `envolver_parceira` exige para liberar o contato da parceira (o "aceite dele"). Sem o veto, um
# turno de promessa vazia destravaria o encaminhamento do telefone.
#
# Vive numa função à parte porque o veto é do TURNO, não da bolha: o chunker parte essa dupla em
# duas bolhas com facilidade, e a 1ª sozinha carimbaria a oferta que a 2ª desmente.
_ESCALADA_AMIGA = re.compile(
    r"\bdeixa eu (?:ver|falar|combinar|checar) com (?:a )?(?:ela|minha amiga)\b"
)


def contem_escalada_da_amiga(texto: str) -> bool:
    """True se o texto carrega a promessa de retorno sobre a amiga ("Deixa eu ver com ela amor").

    Conduta REVOGADA pelo ADR-0042 (a modelo fecha a dupla sozinha); o detector sobrevive como veto
    da oferta — promessa de retorno não é convite, e carimbar `amiga_ofertada_em` ali destravaria o
    encaminhamento do contato sem que ele tivesse topado coisa nenhuma.

    Recebe o TURNO inteiro no write-time (workers/envio.py)."""
    return _ESCALADA_AMIGA.search(normalizar(texto)) is not None


def contem_oferta_da_amiga(texto: str) -> bool:
    """True se a bolha CONVIDA o cliente pra conhecer a amiga (<composicoes>, oferta de pós-venda).

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
# Recorte INEQUÍVOCO da hora (13-23): nenhum pacote da tabela usa essas durações (o mais longo é o
# pernoite de 12h), então neste intervalo "Nh" não pode ser lida como duração de programa. Definido
# aqui, junto do `_HORA`, porque TRÊS gerações do detector dependem dele — a agenda dele ("consigo
# só 22h"), o imperativo "fecha 20h" e o espelho hora→dia ("21h hj"). Cada uma dessas famílias
# dispensa o marcador temporal, e é só o recorte que as mantém seguras.
_HORA_INEQUIVOCA = r"(?:1[3-9]|2[0-3])"
_SUFIXO_HORA = r"(?:h|hs|hrs|horas?)\b"
_RE_HORA_COM_MINUTO = re.compile(rf"\b{_HORA}\s*[:h]\s*[0-5]\d\b|\bmeio\s?dia\b|\bmeia\s?noite\b")
_MARCADOR_TEMPORAL = (
    r"(?:as|umas?|pelas?|por volta d(?:as|a|e)|daqui(?:\s+a)?|tipo|pode ser|seria|ate|"
    r"depois d(?:as|e)|antes d(?:as|e))"
)
_RE_HORA_COM_MARCADOR = re.compile(rf"\b{_MARCADOR_TEMPORAL}\s+{_HORA}\s*{_SUFIXO_HORA}")
# Offset relativo em MINUTOS ("daqui 30 min", "daqui uns 40 minutos", "daqui meia hora"): mesma
# família do "daqui 1h" que o marcador acima já cobre — o extrator converte os dois em hora do
# relógio (DESC do horario_desejado), então vetar só o de minutos gravava `horario_evidenciado=
# false` num encontro que o cliente cravou (loop-massa r1, eixo decidido_rapido). "daqui" torna
# a leitura de DURAÇÃO impossível por construção — duração de pacote não usa offset de chegada.
# "daqui uma hora"/"daqui duas horas" entram pelo MESMO argumento que já grafou "meia hora" por
# extenso — o fix parou no meio (loop-massa r3): a forma por extenso é tão comum quanto o "daqui 1h"
# e ficava fora sem recorte que a justificasse. Colisão zero por construção: o "daqui" torna a
# leitura de duração impossível ("quanto e uma hora?" e "uma hora 400" seguem falsos, medidos).
_RE_OFFSET_MINUTOS = re.compile(
    r"\bdaqui(?:\s+a)?(?:\s+u(?:ns|mas?))?\s+"
    r"(?:\d{1,3}\s*(?:min|mins|minutos?)|meia\s+hora|(?:uma|duas|tres)\s+horas?)\b"
)

# Segunda geração do marcador (diagnóstico 11/08, P0-2): a lista fechada acima perdeu 5 das 9 falas
# com hora dos traces ("hoje 21h", "pras 22h de hoje", "21h então rola", "fechou, 21h to ai", "hoje
# 21h com a inversao entao") — e o belief então AFIRMA ao modelo "palpite seu, ele não confirmou"
# sobre uma hora que o cliente cravou três vezes, mandando re-ofertar em plena fase de fechamento.
# Duas famílias novas, ambas em contexto onde a leitura de DURAÇÃO não cabe:
#  (c) marcador de DIA colado na hora ("hoje 21h", "sexta 22h", "dia 12 19h") — duração de programa
#      não se prende a um dia;
#  (d) hora colada a verbo de FECHAMENTO, nas duas ordens ("fechou, 21h to ai", "21h então rola") —
#      quem fecha está cravando o relógio, não comprando N horas.
# "pra/pras" entra junto porque é como se marca hora na fala real ("pras 22h de hoje").
# As três são vetadas por CONTEXTO DE PREÇO na mesma bolha (`_RE_CONTEXTO_DE_PRECO`): é lá que o
# empate hora-vs-duração vive ("600 1h no meu local", "quanto é 1h ?") e é o falso positivo que o
# marcador fechado existia para evitar (#25 — carimbar evidência num horário que ninguém pediu).
# O marcador ORIGINAL não passa por esse veto: "consigo 600 as 21h" é cotação COM hora do relógio.
_MARCADOR_DE_DIA = (
    r"(?:hoje|hj|amanha|dia \d{1,2}|segunda|terca|quarta|quinta|sexta|sabado|domingo)"
)
# O irmão NEGATIVO do marcador acima: a fala cita um dia que NÃO é hoje. Veio de
# `nos/_janela_do_turno` (campanha 13/08, c7), onde nasceu para o A2 do dia não assumir "hoje" com
# outro dia na mesa; a pauta de horas (`horas_em_pauta_da_conversa`) usa a MESMA fronteira para não
# materializar a hora de amanhã na data de hoje. Um regex, dois leitores.
_TOKEN_OUTRO_DIA = re.compile(
    r"\b(amanh[ãa]|depois de amanh[ãa]|segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|"
    r"semana|m[êe]s|dia \d+)\b",
    re.IGNORECASE,
)
_RE_HORA_COM_DIA = re.compile(rf"\b{_MARCADOR_DE_DIA}[\s,]+(?:as\s+)?{_HORA}\s*{_SUFIXO_HORA}")
# Espelho hora→dia ("21h hj", "21h hoje", "20h amanha"): no WhatsApp a hora vem antes do dia com a
# mesma naturalidade, e o ramo acima só lia dia→hora — a fala do cliente E a bolha da IA do mesmo
# turno usavam a ordem espelhada, e o "Blz" do turno seguinte caiu no vazio pelos dois lados
# (loop-massa r3, eixo externo_a t5/t6).
# Restrito a `_HORA_INEQUIVOCA` DE PROPÓSITO, e a assimetria com o ramo acima é medida: com o dia
# ANTES, "hoje 2h" já lê como relógio; com o dia DEPOIS, "2h hoje"/"1h hoje"/"3h sexta"/"faz 2h
# hoje?" leem como DURAÇÃO — no espelho largo os quatro acendiam.
_RE_DIA_DEPOIS_DA_HORA = re.compile(
    rf"\b{_HORA_INEQUIVOCA}\s*{_SUFIXO_HORA}[\s,]*(?:de\s+)?{_MARCADOR_DE_DIA}\b"
)
_RE_HORA_COM_PRA = re.compile(rf"\bpras?\s+(?:as\s+)?{_HORA}\s*{_SUFIXO_HORA}")
_VERBO_DE_FECHAMENTO = (
    r"(?:fech(?:o|ou|ado|amos)|confirmad[oa]|marcad[oa]|combinado|to ai|tou ai|estou ai|"
    r"rola|rolou|bora)"
)
_RE_HORA_COM_FECHAMENTO = re.compile(
    rf"\b{_VERBO_DE_FECHAMENTO}\b[^\n]{{0,20}}\b{_HORA}\s*{_SUFIXO_HORA}"
    rf"|\b{_HORA}\s*{_SUFIXO_HORA}[^\n]{{0,20}}\b{_VERBO_DE_FECHAMENTO}\b"
)
# O imperativo "fecha 20h" — eco literal do empurrão que o prompt manda a IA usar ("Consigo às 20h,
# fecha ?" → "Fecha 20h"). Ele NÃO entra na alternância de `_VERBO_DE_FECHAMENTO` com as irmãs
# porque lá a hora é o `_HORA` largo, e as irmãs já herdam a colisão com duração que existe hoje
# ("fechamos 2h", "combinado 1h", "bora 2h" acendem em HEAD). Ramo próprio em 13-23 fecha o caso
# (loop-massa r3, `remarcacao` t4) sem alargar a exposição: "fecha 2h"/"fecha 1h" seguem duração e
# "fecha a porta" nunca teve hora para casar.
_RE_HORA_COM_FECHA = re.compile(
    rf"\bfecha\b[^\n]{{0,20}}\b{_HORA_INEQUIVOCA}\s*{_SUFIXO_HORA}"
    rf"|\b{_HORA_INEQUIVOCA}\s*{_SUFIXO_HORA}[^\n]{{0,20}}\bfecha\b"
)
_RE_CONTEXTO_DE_PRECO = re.compile(
    r"\b\d{3,4}\b|\bquanto\b|\bvalor(?:es)?\b|\bpreco\b|\bcusta\b|\bcobra\b|r\$"
)

# Terceira geração (12/08, roteiro `remarcou`): o cliente REMARCANDO fala pela agenda dele, não
# pela do relógio dela — "amor, deu ruim aqui, consigo só 22h. pode?" não tem marcador, não tem
# dia, não tem verbo de fechamento, e por isso a remarcação era lida como hora NÃO evidenciada: a
# hora nova não entrava e a conversa morria numa escalada (5 de 5 conversas do roteiro).
# A ambiguidade hora-vs-duração some por CONSTRUÇÃO aqui: só conta hora de 13 a 23, que nenhum
# pacote da tabela usa (o mais longo é o pernoite de 12h) — "consigo 2h" segue sendo duração.
_VERBO_DE_POSSIBILIDADE = (
    r"(?:consigo|so consigo|posso|da pra mim|chego|vou chegar|to livre|estou livre|me libero|"
    r"pode|serve|da certo)"
)
_RE_HORA_DA_AGENDA_DELE = re.compile(
    rf"\b{_VERBO_DE_POSSIBILIDADE}\b[^\n]{{0,14}}\b{_HORA_INEQUIVOCA}\s*{_SUFIXO_HORA}"
    rf"|\b{_HORA_INEQUIVOCA}\s*{_SUFIXO_HORA}[^\n]{{0,14}}\b{_VERBO_DE_POSSIBILIDADE}\b"
)

# Quarta geração (loop-massa r3): a hora NUA depois do marcador ("as 8 da noite", "mais tarde,
# umas 8"). O sufixo-h obrigatório do `_RE_HORA_COM_MARCADOR` é DESENHO e é load-bearing — com ele
# opcional entram "umas 3 fotos", "me manda umas 10 fotos", "tenho umas 9 amigas". A extensão
# segura tem DUAS condições, medidas contra essa família:
#   (i) a hora fica em posição TERMINAL na bolha (o lookahead `(?!\s*[\wÀ-ÿ:])` é o que mata
#       "umas 8 fotos" — e o `:` mantém "as 8:30" com o ramo de minuto, que é mais específico);
#  (ii) há período do dia COLADO ("as 8 da noite") ou moldura temporal na MESMA bolha ("Tinha q ser
#       mais tarde, umas 8", "hoje umas 8").
# "umas 8" solto, sem moldura, segue de FORA: ali o desenho do módulo continua valendo, e é ele que
# separa hora de quantidade ("me manda umas 20").
_PERIODO_DO_DIA = r"d[ao]\s+(?:manha|tarde|noite|madrugada)"
_RE_HORA_NUA_COM_PERIODO = re.compile(rf"\b{_MARCADOR_TEMPORAL}\s+{_HORA}\s+{_PERIODO_DO_DIA}\b")
_RE_HORA_NUA_TERMINAL = re.compile(rf"\b{_MARCADOR_TEMPORAL}\s+{_HORA}(?!\s*[\wÀ-ÿ:])")
_RE_MOLDURA_TEMPORAL = re.compile(
    r"\b(?:hoje|hj|amanha|mais\s+tarde|mais\s+cedo|de\s+(?:manha|tarde|noite|madrugada)|"
    r"a\s+(?:tarde|noite)|de\s+madrugada|que\s+horas|horario)\b"
)

# Duração escrita como hora DENTRO da cotação ("400 1h no meu local"): o mesmo recorte que o
# `extrair_precos_citados` do output_guard usa p/ separar preço de duração, replicado aqui porque
# `agente/nos/output_guard.py` importa ESTE módulo (importá-lo de volta fecharia o ciclo).
_RE_DURACAO_COTADA = re.compile(rf"\b\d{{3,4}}\s+{_HORA}\s*{_SUFIXO_HORA}")


def contem_sondagem_imediatismo(texto: str) -> bool:
    """True se a bolha carrega a sondagem de IMEDIATISMO ("seria agora ?", "vem agora ?").

    Recorte de `contem_sondagem_dia` usado pela proveniência do horário: aceitar "seria agora ?"
    é o cliente dizendo QUE HORAS (agora); aceitar "seria hoje ?" só crava o dia."""
    return _PROBE_AGORA.search(texto) is not None


def contem_hora_explicita(texto: str) -> bool:
    """True se a fala carrega uma hora do relógio ("Umas 16 horas", "18h15", "às 17:30", "hoje
    21h", "21h hj", "pras 22h de hoje", "fechou, 21h to ai", "fecha 20h", "as 8 da noite").

    `normalizar` antes do match: tira acento/caixa p/ "às"/"até"/"amanhã" casarem sem acento. Usado
    nos dois primeiros gatilhos do horário evidenciado (fala do cliente com hora; bolha da IA com
    hora seguida de confirmação curta) — ver `_horario_evidenciado_no_turno` (nos/_janela_do_turno).

    As famílias LARGAS (dia nas duas ordens, "pra/pras", verbo de fechamento, agenda dele, hora nua
    terminal) só valem fora de contexto de preço, onde "1h" é duração e não relógio — ver o
    comentário dos regex. As que dispensam marcador temporal são ainda restritas a
    `_HORA_INEQUIVOCA`, onde a leitura de duração não cabe.
    """
    t = normalizar(texto)
    if (
        _RE_HORA_COM_MINUTO.search(t) is not None
        or _RE_HORA_COM_MARCADOR.search(t) is not None
        or _RE_OFFSET_MINUTOS.search(t) is not None
    ):
        return True
    if _RE_CONTEXTO_DE_PRECO.search(t) is not None:
        return False
    return (
        _RE_HORA_COM_DIA.search(t) is not None
        or _RE_DIA_DEPOIS_DA_HORA.search(t) is not None
        or _RE_HORA_COM_PRA.search(t) is not None
        or _RE_HORA_COM_FECHAMENTO.search(t) is not None
        or _RE_HORA_COM_FECHA.search(t) is not None
        or _RE_HORA_DA_AGENDA_DELE.search(t) is not None
        or _RE_HORA_NUA_COM_PERIODO.search(t) is not None
        or (
            _RE_HORA_NUA_TERMINAL.search(t) is not None
            and _RE_MOLDURA_TEMPORAL.search(t) is not None
        )
    )


# Faixa ABERTA ("estou livre hoje a partir das 19:30", "atendo das 14h as 23h"): é a
# DISPONIBILIDADE dela, não uma proposta de horário. Mora aqui, com o resto da gramática de hora,
# porque DOIS leitores da fala dela precisam da mesma fronteira: o `_bolha_da_ia_propoe_hora`
# (nos/_janela_do_turno, proveniência do horário evidenciado) e as horas em pauta abaixo. "a partir
# das" é PISO, não ponto — creditá-lo como oferta carimba compromisso sobre hora que ninguém propôs.
#
# O que desqualifica é o PISO/INTERVALO, não o verbo: "Estou livre às 20h, fecha ?" segue oferta.
_RE_FAIXA_ABERTA = re.compile(
    r"\ba partir d(?:as|a|e|o)\b|\bdepois d(?:as|e)\b|\bdas\b[^\n]{0,12}\b[àa]s\b",
    re.IGNORECASE,
)

# --- A hora que a fala DELA põe em pauta (campanha 13/08, ciclo 7 — eb01:210917388210413) --------
# O <horario_minimo> é recalculado a cada turno (agora + antecedência) e por isso ANDA enquanto o
# cliente pensa: a IA ofertou "Consigo às 10h" quatro vezes, o cliente aceitou às 09:32 com o piso
# já em 10:30 e ela negou a própria oferta ("às 10h não consigo não") no turno do fechamento. Para
# o piso poder respeitar o que ela mesma pôs na mesa, é preciso o NÚMERO da hora ofertada, e não só
# o booleano de "propôs hora" que a proveniência do horário já tem.
#
# A gramática é a da fala DELA, que o persona.md prescreve ("Hora é «16h», «20:30»"; proposta sai
# com "às"): hora com MINUTO é inequívoca sozinha ("10:30", "10h30"); hora CHEIA só conta atrás do
# marcador de relógio ("às 10h", "pras 22h") — sem ele "400 1h no meu local" é DURAÇÃO, o mesmo
# empate hora-vs-duração que o `contem_hora_explicita` documenta.
#
# O `(?<!ate )` é o LIMITE: "atendo até as 2h", "consigo hoje 14h até as 2h" fecham a jornada, não
# ofertam as 02:00 (refutação 13/08). É a mesma fronteira do `_RE_FAIXA_ABERTA` — piso/teto não é
# ponto —, só que colada no marcador, para não mexer no regex que a proveniência do horário divide.
_RE_HORA_OFERTADA = re.compile(
    rf"(?<!ate )\b(?:as|pras?|para as)\s+({_HORA})\s*(?:[:h]\s*([0-5]\d)\b|{_SUFIXO_HORA})"
)
_RE_HORA_DITA_COM_MINUTO = re.compile(rf"\b({_HORA})\s*[:h]\s*([0-5]\d)\b")
# A mesma hora com o marcador OPCIONAL, para a leitura de RETIRADA: a recusa é fala livre ("10h não
# dá pra mim", "9h não consigo") e exigir o "às" ali deixava a hora recusada viva na pauta
# (refutação 13/08). É a régua de `horas_recusadas_na_fala` (dominio/atendimentos/service.py), que
# lê a recusa com o mesmo marcador opcional — e o erro dela é sempre para o lado seguro: uma hora a
# menos na pauta só devolve o piso ao valor conservador.
_RE_HORA_CITADA = re.compile(rf"\b(?:as\s+)?({_HORA})\s*(?:[:h]\s*([0-5]\d)\b|{_SUFIXO_HORA})")
# LINHA DE TABELA, não relógio: "400 a 1h amor", "700 as 2h", "2500 as 12h" — falas REAIS do corpus
# (eb03:180316434104536 t6, eb01:160219460010212 t7) em que o preço vem colado na DURAÇÃO com o
# mesmo marcador que a oferta de hora usa. Sem este corte a tabela de preços injeta 02:00/12:00 na
# pauta e rebaixa o piso da madrugada (refutação 13/08, achado GRAVE).
# O recorte é o `_HORA_INEQUIVOCA` lido ao contrário: só 0-12 empata com duração de pacote (o mais
# longo é o pernoite de 12h), então "consigo 600 as 21h" continua sendo cotação COM hora do relógio
# — a MESMA fronteira que `contem_hora_explicita` documenta no veto de contexto de preço.
_HORA_AMBIGUA_COM_DURACAO = r"(?:0?\d|1[0-2])"
_RE_LINHA_DE_TABELA = re.compile(
    rf"\b\d{{3,4}}\s*(?:a|as|pras?|para as|na|no|em|por|de)?\s*"
    rf"{_HORA_AMBIGUA_COM_DURACAO}\s*{_SUFIXO_HORA}"
)
# Cláusula em que a hora é RETIRADA ("às 10h não consigo não", "10h não dá pra mim", "10h é
# impossível"): a mesma hora aparece na fala, mas para negar. Sem este corte a recusa realimentaria
# a oferta.
_RE_RETIRADA_DE_HORA = re.compile(r"\b(?:nao|nunca|nem|jamais|impossivel)\b")
# Fim de cláusula: a MESMA régua de `precos_ofertados_na_fala` (dominio/atendimentos/service.py,
# `_RE_FIM_DE_CLAUSULA`) com UMA emenda obrigatória aqui — lá o ":" fecha cláusula, e aqui ele
# parte ao meio o número que estamos lendo ("10:30" viraria "10" e "30"). O guard `(?<!\d)`/`(?!\d)`
# que lá protege "1.500"/"500,00" passa a proteger também a hora. O grupo externo é de CAPTURA: o
# `split` devolve os terminadores junto, e o "?" é o que separa a recusa dele ("10h não dá pra mim")
# da pergunta dele ("não dá 10h ?"), que não retira nada.
_RE_FIM_DE_CLAUSULA_DE_HORA = re.compile(r"((?<!\d)[.,:]|[.,:](?!\d)|[;!?\n])")


def _clausulas_com_terminador(texto: str) -> list[tuple[str, str]]:
    """`[(cláusula normalizada, terminador)]` — o terminador da última cláusula é "" (fim da fala).

    A normalização vem DEPOIS do corte de propósito: `normalizar` colapsa o \\n em espaço e fundiria
    "às 10h não consigo não" com o "Consigo às 10:30" da bolha seguinte.
    """
    partes = _RE_FIM_DE_CLAUSULA_DE_HORA.split(texto)
    return [
        (normalizar(partes[i]), partes[i + 1] if i + 1 < len(partes) else "")
        for i in range(0, len(partes), 2)
    ]


def _horas_da_clausula(clausula: str, *, exige_marcador: bool) -> set[time]:
    """Horas do relógio que a cláusula (já normalizada) nomeia — ver os regex acima.

    `exige_marcador=True` é a leitura de OFERTA (o que ela põe na mesa: hora com minuto, ou hora
    cheia atrás de "às/pras"); `False` é a leitura de MENÇÃO, usada só para RETIRAR. A assimetria é
    o ponto: errar para mais na oferta injeta hora que ninguém propôs, errar para mais na retirada
    só devolve o piso ao conservador.
    """
    limpa = _RE_LINHA_DE_TABELA.sub(" ", clausula)
    horas = {
        time(int(h), int(m)) for h, m in _RE_HORA_DITA_COM_MINUTO.findall(limpa) if int(h) <= 23
    }
    padrao = _RE_HORA_OFERTADA if exige_marcador else _RE_HORA_CITADA
    for h, m in padrao.findall(limpa):
        horas.add(time(int(h), int(m) if m else 0))
    return horas


def horas_em_pauta_da_conversa(bolhas: Iterable[tuple[bool, str]]) -> set[time]:
    """As horas do relógio de HOJE que a fala DELA pôs na mesa e que ninguém retirou.

    `bolhas` = `(é_fala_dela, texto)` em ordem CRONOLÓGICA. A assimetria é o desenho: só a fala
    DELA (IA ou modelo no manual) ACRESCENTA — o cliente propor 11h não compromete a agenda dela —,
    mas a retirada vale dos DOIS lados: "às 10h não consigo não" (ela) e "10h não dá pra mim, só
    consigo 11h" (ele) tiram 10:00 da pauta do mesmo jeito (refutação 13/08). Como o cliente só
    consegue REMOVER, o pior que uma fala hostil faz é devolver o piso ao valor conservador.

    Não entram na pauta, todas por baixo (fail-closed):
      - faixa aberta / limite de jornada (`_RE_FAIXA_ABERTA`, "até as 2h"): disponibilidade e teto
        não são proposta;
      - linha de tabela (`_RE_LINHA_DE_TABELA`, "700 as 2h"): é preço por duração, não relógio;
      - cláusula que fala de OUTRO DIA (`_TOKEN_OUTRO_DIA`, "amanhã consigo às 10h"): a pauta é a
        de HOJE, e quem a consome materializa a hora na data de hoje;
      - pergunta DELE ("não dá 10h ?"): pergunta não retira, do mesmo jeito que `_aceite_de_
        fechamento` não lê pergunta como aceite.

    PURA e determinística, como todo detector deste módulo: quem decide o que fazer com a pauta é o
    chamador (hoje só o piso do `<horario_minimo>`, em `nos/prepare_context`).
    """
    em_pauta: set[time] = set()
    for dela, bolha in bolhas:
        for clausula, terminador in _clausulas_com_terminador(bolha):
            if _RE_FAIXA_ABERTA.search(clausula) or _TOKEN_OUTRO_DIA.search(clausula):
                continue
            if _RE_RETIRADA_DE_HORA.search(clausula) is not None:
                # Pergunta DELE não retira ("não dá 10h ?" é sondagem, não recusa) — o mesmo veto
                # que `_aceite_de_fechamento` aplica ao ler aceite.
                if dela or terminador != "?":
                    em_pauta -= _horas_da_clausula(clausula, exige_marcador=False)
            elif dela:
                em_pauta |= _horas_da_clausula(clausula, exige_marcador=True)
    return em_pauta


# --- FECHAMENTO de agenda na bolha dela (guard de HORA FANTASMA, 14/08) -------------------------
#
# A fala que COMPROMETE a agenda ("fechado", "te espero"), separada da que só OFERECE ("consigo às
# 22h, fecha ?"). A distinção é load-bearing para o `bolhas_hora_fantasma` (nos/output_guard):
# reofertar uma hora diferente da gravada é conduta CERTA (é assim que a reancoragem funciona);
# CONFIRMAR uma hora diferente da gravada é a mentira que compromete a modelo com um encontro que
# não existe. Medido nos 445 turnos com hora gravada dos ciclos da campanha: exigindo o token de
# fechamento, 2 bolhas divergem (as duas, defeito real); sem ele, 20 — e as 18 extras são ofertas
# legítimas ("Consigo às 11h, fecha ?").
#
# Vocabulário FECHADO e sem convite ("pode vir ?", "pode chegar ?"): convite é oferta com ponto de
# interrogação, e creditá-lo como fechamento reprovaria a reancoragem. O verbo de fechamento do
# `_RE_HORA_COM_FECHAMENTO` acima não serve aqui — lá ele lê a fala DELE (aceite), e inclui "rola"/
# "bora", que na boca dela ainda é proposta.
_RE_CONFIRMA_AGENDA = re.compile(
    r"\bfechad[oa]\b|\bfechou\b|\bfechamos\b|\bcombinad[oa]\b|\bmarcad[oa]\b|\bconfirmad[oa]\b"
    r"|\bagendad[oa]\b|\banotad[oa]\b|te espero|te aguardo|te esperando|nos vemos"
)


def confirma_agenda(texto: str) -> bool:
    """True se a fala FECHA o encontro ("fechado", "combinado", "te espero") — não se só oferece."""
    return _RE_CONFIRMA_AGENDA.search(normalizar(texto)) is not None


def horas_afirmadas_na_fala(texto: str) -> set[time]:
    """As horas do relógio que a fala AFIRMA para hoje (a leitura de OFERTA, cláusula a cláusula).

    Mesma régua de `horas_em_pauta_da_conversa` — e de propósito a MESMA função de gramática
    (`_horas_da_clausula`, `exige_marcador=True`): uma segunda cópia do regex divergiria e uma
    legitimaria o que a outra derruba (a lição do `extrair_precos_citados`). Ficam de fora, todas
    por baixo: faixa aberta/teto de jornada ("a partir das 10:30", "até as 2h"), linha de tabela
    ("400 1h no meu local" é duração), outro dia ("amanhã às 15h") e a cláusula que RETIRA a hora
    ("23h já não consigo") — nenhuma delas afirma hora de hoje.
    """
    horas: set[time] = set()
    for clausula, _terminador in _clausulas_com_terminador(texto):
        if _RE_FAIXA_ABERTA.search(clausula) or _TOKEN_OUTRO_DIA.search(clausula):
            continue
        if _RE_RETIRADA_DE_HORA.search(clausula) is not None:
            continue
        horas |= _horas_da_clausula(clausula, exige_marcador=True)
    return horas


# --- O DIA que o cliente já tirou da mesa (campanha 13/08, ciclo 7 — eb04:79981032001710) --------
# Erro capital nº 3 do playbook (atropelar restrição declarada), medido no caso real: o cliente
# disse "Não hoje não" (t4), "Tô lotado hoje, sem chance" (t13) e "Hoje eu realmente não consigo"
# (t14) — e a IA ofertou 11h (t12) e 14h (t13) do MESMO dia. O contexto do t13 não tinha carimbo
# nenhum da recusa: o `<escada_travada_sem_o_dia>` afirmava "você ainda NÃO sabe que dia ele quer"
# e o `<agenda>` abria a `janela_livre` em HOJE, então o único dia concreto à vista era o recusado.
#
# O que já existia e NÃO cobria: `_TOKEN_OUTRO_DIA` só VETA (impede assumir hoje, não registra a
# recusa); `classificar_recuo` é evento do burst, vai para a extração e nem casa estas três falas
# ("to lotado hoje" e "hoje eu realmente nao consigo" ficam fora do `_RECUO_AUTONOMO`); e a família
# `<oferta_condicionada_ao_dia>`/`estado_da_escada` condiciona o DESCONTO ao dia, não a oferta.
#
# Aqui o dia recusado vira DADO do turno, pela mesma régua de contiguidade das horas em pauta
# (`_falas_da_conversa_contigua`): depois de 6h de silêncio a recusa de "hoje" já é de outro dia e
# some sozinha, sem relógio nenhum dentro do detector.
# "depois de amanha" ANTES de "amanha" na alternância: o regex é lido da esquerda e a ordem
# invertida rotularia "depois de amanhã" como "amanhã" — o dia errado no bloco é pior que nenhum.
_DIA_NOMEADO = (
    r"(?:hoje|hj|depois de amanha|amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo)"
)
_ROTULO_DO_DIA = {
    "hj": "hoje",
    "amanha": "amanhã",
    "depois de amanha": "depois de amanhã",
    "terca": "terça",
    "sabado": "sábado",
}
# Impossibilidade NO DIA — a fala que tira o dia da mesa. Vocabulário fechado e medido contra o
# caso real: as três formas dele ("não hoje não", "tô lotado hoje", "hoje eu realmente não
# consigo") mais as vizinhas do corpus. Lido por CO-OCORRÊNCIA na mesma cláusula (dia + token),
# não por ordem: no WhatsApp o dia vem antes e depois com a mesma naturalidade.
# "dar conta"/"poder" entraram com o t8 do c8 ("hoje acho que não vou dar conta não"): a forma é
# tão comum quanto "não consigo" e ficava fora sem recorte que a justificasse.
_TOKEN_DE_IMPOSSIBILIDADE = re.compile(
    r"\bnao\s+(?:consigo|vou conseguir|posso|vou poder|vou dar conta|dou conta|da|vai dar|rola"
    r"|tenho como|to podendo)\b"
    r"|\bimpossivel\b|\bsem chance\b|\bsem condicoes\b|\bsem tempo\b"
    r"|\b(?:lotado|atolado|enrolado|ocupadao)\b"
)
# Hedge que o cliente intercala entre o dia e a negação ("hoje ACHO QUE não vou dar conta", "hoje
# REALMENTE não"). Lista curta e FECHADA de advérbio de atenuação, nunca `.*`: o que separa a
# recusa hedgeada do "hoje eu não te falei o endereço" é justamente não aceitar qualquer palavra no
# meio. "eu"/"já"/"mesmo" ficam de FORA por isso — e a fala que os usa ("hoje eu realmente não
# consigo") já entra pelo token de impossibilidade.
_HEDGE_DA_RECUSA = r"(?:eu acho que|acho que|acho|realmente|infelizmente|sinceramente|na verdade)"
# A negação NUA colada no dia ("não hoje não", "hoje não", "hoje acho que não"): sozinha ela não
# diz o verbo, mas a adjacência ao dia já é a recusa inteira — é a forma mais comum das três do
# caso real. INCERTEZA não é recusa e o lookahead a corta: "hoje não sei" é o cliente pensando, e
# tratá-lo como veto do dia empurraria pra amanhã quem ainda pode vir hoje.
_RE_NEGACAO_COLADA_NO_DIA = re.compile(
    rf"\bnao\s+{_DIA_NOMEADO}\b"
    rf"|\b{_DIA_NOMEADO}\s+(?:{_HEDGE_DA_RECUSA}\s+){{0,2}}nao\b(?!\s+(?:sei|tenho certeza))"
)
# O mesmo veto por OUTRA porta: "só amanhã", "fica pra sexta", "melhor segunda" recusam HOJE sem
# nunca dizer "hoje". Captura o dia CITADO; quem recusa é o hoje (ver a função).
_RE_SO_OUTRO_DIA = re.compile(
    rf"\b(?:so|fica pra|fica para|melhor|prefiro|vai ter que ser|tem que ser)\s+"
    rf"(?:na\s+|no\s+|de\s+)?({_DIA_NOMEADO})\b"
)
# Reabertura pelo PRÓPRIO cliente ("hoje agora deu certo", "consigo hoje sim", "hoje pode ser"):
# quem fechou o dia é quem o reabre. Cláusula com "nao" não reabre nada (o veto está na função).
_RE_REABERTURA_DO_DIA = re.compile(
    rf"\b(?:consigo|posso|da|deu|deu certo|rola|pode ser|topo|bora|vamos|vou|serve|libero|liberou)"
    rf"\b[^\n]{{0,24}}?\b{_DIA_NOMEADO}\b"
    rf"|\b{_DIA_NOMEADO}\b[^\n]{{0,24}}?"
    rf"\b(?:consigo|posso|da|deu|deu certo|rola|pode ser|topo|bora|vamos|vou|serve|ta bom|sim)\b"
)


def dia_recusado_pelo_cliente(bolhas: Iterable[tuple[bool, str]]) -> str | None:
    """O dia que o CLIENTE tirou da mesa e não reabriu ("hoje", "amanhã", "sexta"...); None = nenhum.

    `bolhas` = `(é_fala_dela, texto)` em ordem CRONOLÓGICA, o mesmo par de
    `horas_em_pauta_da_conversa` — e a MESMA fonte contígua (`_falas_da_conversa_contigua`, que já
    esquece o que veio antes de uma pausa de 6h). Só a fala DELE conta, nos dois sentidos: ele é
    quem fecha o dia e é quem o reabre; a fala dela nunca recusa o próprio dia.

    A unidade de leitura é o BURST dele (as bolhas seguidas, até ela falar): no WhatsApp o dia e o
    motivo saem em bolhas separadas ("Hmm hoje acho que não vou dar conta não" / "Tô lotado de
    coisa pra resolver"), e ler cláusula a cláusula perdia a recusa inteira. Ver
    `_dia_recusado_no_burst`.

    Três vetos, todos medidos contra o que o bloco NÃO pode fazer:
      - pergunta DELE ("você está livre hoje ?"): terminador "?" não recusa nada — o mesmo veto que
        `horas_em_pauta_da_conversa` e `_aceite_de_fechamento` aplicam;
      - recusa de HORÁRIO ("hoje às 10h não dá"): cláusula com hora do relógio fala do relógio, não
        do dia — quem trata a hora é a pauta de horas, e vetar aqui é o que separa as duas;
      - objeção de PREÇO ("hoje não consigo pagar isso", "hoje tá caro"): `_RE_CONTEXTO_DE_PRECO`
        (o mesmo corte que `contem_hora_explicita` usa) somado ao `_OBJECAO_DE_PRECO` que
        `classificar_recuo` já lê — recusar o valor não é recusar o dia, e quem trata a objeção de
        preço é a escada do desconto.
    A cláusula vetada sai da leitura inteira, inclusive da regra de burst abaixo.

    PURA e determinística: quem decide o que fazer com o carimbo é o chamador (hoje só o bloco
    `<dia_recusado>` do `<agenda>`, em `nos/prepare_context`).
    """
    recusado: str | None = None
    for clausulas in _bursts_dele(bolhas):
        recusado = _dia_recusado_no_burst(clausulas, recusado)
    return recusado


def _bursts_dele(bolhas: Iterable[tuple[bool, str]]) -> list[list[str]]:
    """As cláusulas VÁLIDAS de cada burst do cliente, na ordem — uma lista por burst.

    Burst = bolhas seguidas dele, cortadas por qualquer fala dela. Cláusula vetada (pergunta,
    hora do relógio, contexto/objeção de preço) nem entra: o veto vale para as duas leituras, a
    da cláusula e a do burst.
    """
    bursts: list[list[str]] = []
    dela_antes = True
    for dela, bolha in bolhas:
        if dela:
            dela_antes = True
            continue
        if dela_antes:
            bursts.append([])
        dela_antes = False
        for clausula, terminador in _clausulas_com_terminador(bolha):
            if (
                terminador == "?"
                or _RE_CONTEXTO_DE_PRECO.search(clausula)
                or _OBJECAO_DE_PRECO.search(clausula)
                or _RE_HORA_CITADA.search(_RE_LINHA_DE_TABELA.sub(" ", clausula))
            ):
                continue
            bursts[-1].append(clausula)
    return bursts


def _dia_recusado_no_burst(clausulas: list[str], recusado: str | None) -> str | None:
    """Aplica UM burst dele sobre o dia recusado que vinha de antes.

    Duas leituras, nesta ordem. A da CLÁUSULA decide sozinha quando o dia e o motivo cabem na mesma
    (`_dia_recusado_na_clausula`), e é ela também que reabre o dia. Só quando o burst inteiro não
    disse nada entra a leitura do BURST: o dia numa cláusula e a impossibilidade em OUTRA ("Hmm
    hoje acho que não vou dar conta não" / "Tô lotado de coisa pra resolver", t8 do c8).

    A leitura de burst é a mais larga das duas e por isso tem trava própria: não vale se alguma
    cláusula do MESMO burst REABRE o dia citado ("hoje eu consigo" / "tô atolado mas dou um jeito")
    — ali o motivo não está vetando dia nenhum.
    """
    mudou = False
    for clausula in clausulas:
        dia = _dia_recusado_na_clausula(clausula)
        if dia is not None:
            recusado, mudou = dia, True
        elif recusado is not None and _reabre_o_dia(clausula, recusado):
            recusado, mudou = None, True
    if mudou or not any(_TOKEN_DE_IMPOSSIBILIDADE.search(c) for c in clausulas):
        return recusado
    for clausula in clausulas:
        primeiro = re.search(rf"\b{_DIA_NOMEADO}\b", clausula)
        if primeiro is None:
            continue
        dia = _ROTULO_DO_DIA.get(primeiro.group(0), primeiro.group(0))
        if any(_reabre_o_dia(c, dia) for c in clausulas):
            continue
        return dia
    return recusado


def _reabre_o_dia(clausula: str, dia: str) -> bool:
    """True se ESTA cláusula do cliente devolve `dia` para a mesa ("hoje agora deu certo").

    Cláusula com "não" não reabre nada — é o mesmo fail-closed do resto do módulo: errar aqui para
    o lado largo apaga um veto que ele declarou, que é o defeito que o carimbo existe para corrigir.
    """
    return (
        "nao" not in clausula.split()
        and _RE_REABERTURA_DO_DIA.search(clausula) is not None
        and dia in _dias_citados(clausula)
    )


def _dias_citados(clausula: str) -> set[str]:
    """Os dias que a cláusula nomeia, já com o rótulo humano ("hj" -> "hoje", "terca" -> "terça")."""
    return {_ROTULO_DO_DIA.get(d, d) for d in re.findall(rf"\b{_DIA_NOMEADO}\b", clausula)}


def _dia_recusado_na_clausula(clausula: str) -> str | None:
    """O dia que ESTA cláusula (já normalizada, já vetada) tira da mesa; None = nenhum.

    Duas portas. A direta nomeia o dia e a impossibilidade na mesma cláusula ("tô lotado hoje",
    "hoje eu realmente não consigo", "não hoje não") — o dia recusado é o citado. A indireta é o
    "só amanhã"/"fica pra sexta": ele não diz "hoje" em lugar nenhum, mas empurrar o encontro para
    OUTRO dia é recusar o de hoje, e é esse que volta.
    """
    citados = _dias_citados(clausula)
    if citados and (
        _TOKEN_DE_IMPOSSIBILIDADE.search(clausula) or _RE_NEGACAO_COLADA_NO_DIA.search(clausula)
    ):
        # Um só dia por cláusula na fala real; com mais de um, o primeiro citado é o recusado.
        primeiro = re.search(rf"\b{_DIA_NOMEADO}\b", clausula)
        return _ROTULO_DO_DIA.get(primeiro.group(0), primeiro.group(0)) if primeiro else None
    outro = _RE_SO_OUTRO_DIA.search(clausula)
    if outro is not None and _ROTULO_DO_DIA.get(outro.group(1), outro.group(1)) != "hoje":
        return "hoje"
    return None


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


def contem_hora_na_mesa_no_turno(bolhas: Iterable[str]) -> bool:
    """`contem_hora_na_mesa` sobre o TURNO (lista de bolhas), IGNORANDO a duração da cotação.

    O veto por turno existe porque o chunker parte "Consigo às 21h amor" / "ou prefere que horas ?"
    em duas bolhas. Medido sobre o turno CONCATENADO, porém, a duração da cotação ("400 1h no meu
    local") casava a hora crua e vetava o contador de todo turno que tem cotação — e como toda
    cotação carrega duração, `n_perguntas_de_horario` deu 0 em 21 turnos medidos (diagnóstico
    11/08, P1-4c): a disciplina anti-loop de horário nunca existiu em produção.

    Duas correções na mesma função: avalia POR BOLHA (o contexto de preço de uma bolha não
    contamina a vizinha) e tira a duração colada ao preço antes de olhar a hora crua.
    """
    return any(contem_hora_na_mesa(_RE_DURACAO_COTADA.sub(" ", normalizar(b))) for b in bolhas)


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


# Pedido de LOCALIZAÇÃO na fala do cliente (rodada 3 do eval, fase 1-E): "Manda a localização" /
# "onde fica?" respondidos com "é bem discreto, você vai gostar" foram a pior célula persistente
# do shadow (logística 57%). O detector alimenta o gatilho `endereco` do output_guard: cliente
# pediu o ponto E o estágio já libera o <local_de_encontro> E a resposta não entregou nenhum token
# do endereço → regenera pedindo a entrega. Fechado de propósito — só as formas inequívocas de
# pedir o PONTO DE ENCONTRO: o imperativo de envio ("manda a localização/o endereço/a loc") e a
# pergunta direta ("onde fica?", "onde você atende?", "qual o endereço?"). "seu local" solto NÃO
# entra ("no meu local" é fala de cotação dos dois lados), nem "onde você mora" (residência ≠
# ponto de encontro; PII que a IA nunca entrega).
_RE_PEDIDO_DE_ENDERECO = re.compile(
    r"\b(?:manda|mande|passa|passe|envia|envie|me da|me de)\b[^\n?]{0,24}"
    r"\b(?:localizacao|endereco|loc)\b"
    r"|\bonde (?:voce |vc )?(?:fica|atende|esta|e)\b"
    r"|\bqual (?:e )?(?:o )?(?:endereco|local exato)\b"
    r"|\bendereco\s*\?"
    # Formas coloquiais medidas na triagem da rodada 4 (derrotas de logistica que o detector nao
    # via): "proximo onde?", "qual rua/que rua (do seu local)", "nao conheco esse hotel" — todas
    # inequivocas de quem quer o PONTO. "fica longe"/"e casa ou apartamento" ficam de fora AQUI de
    # proposito (sao objecao de distancia/pergunta de acesso; a resposta boa pode nao ter token de
    # endereco e o regen pressionaria a fala errada) — no foco (_foco_do_turno) elas entram, la o
    # efeito e so injetar o dado.
    r"|\bproximo\s+(?:de\s+|a\s+)?onde\b"
    r"|\b(?:qual|que)\s+rua\b"
    r"|\bnao\s+conhec[oe]\b[^\n?]{0,20}\b(?:hotel|lugar|local|rua|endereco)\b"
    # Campanha 13/08: "Tem local?" e "onde (a gente pode se) encontrar" sao pedidos inequivocos do
    # PONTO e ficavam fora — com eles fora, o gatilho `endereco` do guard ficava desarmado no turno
    # em que o cliente pede o ponto com a forma mais comum do corpus (eb02:91564424585333). Modelo
    # sem endereco no cadastro nao arma o gatilho de qualquer forma (tokens_endereco vazio).
    r"|\b(?:vc\s+|voce\s+)?tem\s+(?:local|lugar)\b"
    r"|\bonde\b[^\n?]{0,30}\b(?:encontr(?:o|ar|amos)|nos\s+vemos|te\s+vejo)\b"
)


def contem_pedido_de_endereco(texto: str) -> bool:
    """True se a fala do cliente PEDE o ponto de encontro ("manda a localização", "onde fica?").

    `normalizar` antes do match: tira acento/caixa ("localização", "endereço"). Usado pelo
    gatilho `endereco` do output_guard — o pedido é do burst ATUAL do cliente; pedido antigo já
    foi respondido (ou cobrado) no turno em que saiu."""
    return _RE_PEDIDO_DE_ENDERECO.search(normalizar(texto)) is not None


# Pergunta-aberta-de-infos ("como funciona?", "me passa as infos") — a porta que o vendedor bom
# responde com o pacote completo de uma vez (playbook do corpus) e a IA respondia curto + devolvia
# pergunta (pitch 65% no shadow v2). O detector NÃO vira guard de completude (medir "pitch
# completo" por regex é frágil): ele só acende o ponteiro condicional no <proximo_passo> da cauda
# apontando o molde do <exemplo> de apresentação. Fechado: as formas de pedir a apresentação, sem
# o vocabulário de preço ("quanto custa/qual o valor" é <cotacao>, tem trilho próprio).
_RE_PEDIDO_DE_INFOS = re.compile(
    r"\bcomo (?:funciona|que funciona|voce trabalha|vc trabalha)\b"
    r"|\bcomo (?:esta|ta) funcionando\b"
    # "gostaria de" e o MESMO verbo dos ramos `quero|queria` em outro modo — e a forma mais comum
    # do lead que chega pelo site ("Gostaria de informações sobre seu atendimento"), que ficava de
    # fora por inconsistencia interna do proprio conjunto (loop-massa r2, eixos pre_cotacao/ghost).
    r"|\b(?:manda|me passa|passa|me da|me de|me fala|quero|queria|gostaria de) "
    r"(?:as |os |mais |umas )?(?:infos|informacao|informacoes|detalhes)\b"
    r"|\b(?:quero|queria|gostaria de) saber (?:mais|tudo|como)\b"
    r"|\bmais detalhes\b"
    r"|\bo que (?:esta|ta) inclu[si]"
    r"|\bquais (?:sao )?(?:seus|os seus|teus) servicos\b"
)


# Âncora do texto AUTOMÁTICO que o site gera na primeira mensagem do lead ("Peguei seu contato no
# site X. Gostaria de informações sobre seu atendimento."). A <abertura> (regras.md.j2) manda SÓ
# cumprimentar nessa âncora — mas o ramo "gostaria de informações" do _RE_PEDIDO_DE_INFOS casava o
# mesmo template e o <proximo_passo> injetava "apresente completo de uma vez": duas instruções
# opostas no MESMO prompt, em praticamente todo lead de site (campanha 13/08, eb02:26311003246742).
# A bolha com a âncora não conta como pedido de infos; o que ele DIGITOU depois conta normalmente.
_RE_ANCORA_DO_SITE = re.compile(
    r"\b(?:peguei\s+(?:seu|o|teu)\s+(?:contato|numero)\s+no\s+site"
    r"|vi\s+(?:seu|o|teu)\s+anuncio\s+no\s+site)\b"
)


def contem_ancora_do_site(texto: str) -> bool:
    """True se a fala carrega a âncora do template automático do site (ver `_RE_ANCORA_DO_SITE`)."""
    return _RE_ANCORA_DO_SITE.search(normalizar(texto)) is not None


def contem_pedido_de_infos(texto: str) -> bool:
    """True se a fala do cliente pede a APRESENTAÇÃO ("como funciona?", "me passa as infos").

    `normalizar` antes do match: tira acento/caixa ("informações"). Alimenta o ponteiro
    condicional de pitch no <proximo_passo> (prepare_context) — só cauda, nunca guard. A bolha
    que carrega a âncora do site é template, não pedido dele (`contem_ancora_do_site`)."""
    normalizado = normalizar(texto)
    if _RE_ANCORA_DO_SITE.search(normalizado):
        return False
    return _RE_PEDIDO_DE_INFOS.search(normalizado) is not None


# Saudação de PERÍODO ("bom dia"/"boa tarde"/"boa noite") — rodada 4 do eval: a IA respondia "Boa
# noite" ao cliente que abriu com "boa tarde" (~5 derrotas). O espelhamento é determinístico: o
# período correto a responder é O DELE, sem relógio nem LLM — quem detecta é o sistema, a IA só
# fraseia. Alimenta o <foco_do_turno> (injeta a saudação dele como dado) e o gatilho `saudacao`
# do output_guard (resposta com período CONFLITANTE regenera; pass-through se persistir).
_RE_SAUDACAO_PERIODO = re.compile(r"\b(bom dia|boa tarde|boa noite)\b")


def periodo_da_saudacao(texto: str) -> str | None:
    """A saudação de período da fala ("bom dia"/"boa tarde"/"boa noite"), normalizada, ou None.

    Primeira ocorrência vence ("boa tarde... boa noite pra você" é raro e a primeira é a saudação
    de abertura). `normalizar` tira acento/caixa ("Bom Dia!!")."""
    m = _RE_SAUDACAO_PERIODO.search(normalizar(texto))
    return m.group(1) if m else None


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

# OBJEÇÃO DE PREÇO — a família que faltava (loop-massa r3, achado 1 da refutação de extração:
# `'Ta um pouco caro'`, `'faz 300'`, `'400 ta fora pra mim'`, `'250 e o maximo'` e
# `'Nao consigo pagar isso'` devolviam TODOS `None`). Achar caro, dar lowball ou cravar um teto é o
# CONTRÁRIO de aceite, e o rebaixamento do `aceita_valor` já tem caminho testado
# (`recuo_detectado` → `_sinais_qualificacao_do_turno`): o que faltava era a fala chegar até ele.
# Alargar aqui é o conserto barato — reescrever a DESC do extrator não teria evitado 4 dos 7
# payloads falsos do corpus (o produtor ignorou cláusula que já existia).
#
# O efeito de um falso positivo é o MESMO benigno da família inteira: reabre a escada do desconto.
# Ainda assim, todo ramo com número exige 3-4 dígitos (preço de programa; "faz 2 horas" não entra)
# e o vocabulário de ACEITE fica fora por construção — "fechado 300", "300 as 20h ta fechado" e
# "so pra confirmar: 300 na 1 hr" não têm token de objeção nenhum.
_OBJECAO_DE_PRECO = re.compile(
    # achar caro ("ta caro", "ta um pouco caro", "achei caro", "muito caro", "caro demais")
    r"\b(?:ta|esta|e|eh|achei|ficou)\s+(?:um pouco |meio |muito |bem )?(?:caro|salgado)\b"
    r"|\b(?:muito|meio|bem) (?:caro|salgado)\b"
    r"|\bcaro (?:demais|pra mim)\b"
    # lowball ("faz 300", "faz por 300")
    r"|\bfa(?:z|co) (?:por )?\d{3,4}\b"
    # teto ("250 e o maximo", "meu maximo e 250", "so tenho 300", "so consigo 300")
    r"|\b\d{3,4} (?:e|eh) o (?:maximo|limite)\b"
    r"|\b(?:meu )?(?:maximo|limite) (?:e|eh) (?:r\$ ?)?\d{3,4}\b"
    r"|\bso (?:tenho|consigo pagar) (?:r\$ ?)?\d{3,4}\b"
    # fora do orçamento / não pode pagar
    r"|\b(?:ta|esta) fora (?:pra mim|do meu)\b|\bfora do meu orcamento\b"
    r"|\bnao (?:consigo|posso|da pra) pagar\b"
    r"|\bacima do (?:meu|que eu)\b"
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
    CORREFERENCIADA só conta colada num pedido de fechamento da IA. A OBJEÇÃO DE PREÇO entra como
    autônoma (a fala se basta) — ver `_OBJECAO_DE_PRECO`.
    """
    falas = [normalizar(t) for t in falas_cliente]
    for fala in falas:
        if _RECUO_AUTONOMO.search(fala) or _OBJECAO_DE_PRECO.search(fala):
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
