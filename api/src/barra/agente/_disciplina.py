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


def contar_contrapropostas(textos: Iterable[str]) -> int:
    """Nº de linhas de `mensagens` (bolha/chunk enviado, não turno lógico) que carregam a
    contraproposta de desconto (ADR-0031: até 2 por atendimento — degrau na 1ª, teto na 2ª e
    última). Conta por linha (`search`, não `findall`): a frase canônica é curta e o chunker do
    envio não a parte nem a repete dentro do mesmo turno, então bolha ≈ oferta na prática."""
    return sum(1 for t in textos if contem_contraproposta(t))
