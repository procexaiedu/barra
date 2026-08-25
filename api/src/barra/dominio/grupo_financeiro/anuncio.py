"""Triagem e leitura do anuncio de venda do Grupo financeiro (spec 0005, ticket 02).

Duas funcoes, nesta ordem, e a ordem importa:

1. `parece_anuncio_de_venda` — TRIAGEM barata. O grupo e social e vivo: sticker, "Bem buceta
   amei", "Foi pix ou din ?", cobranca da 3RJ, comprovante. Nada disso e anuncio de venda e nada
   disso pode custar uma chamada de extracao (spec 0005: "Mensagem social e descartada barato,
   classificacao antes de qualquer extracao cara"). A triagem e um casamento de marcador no
   INICIO de linha — `Atendimento` / `Cliente` / `Perfil`, a gramatica que a gestora repete no
   export inteiro. Ela e o portao que continua valendo quando o extrator for um LLM.
2. `extrair_anuncio` — LEITURA do anuncio. Deterministica de proposito: a grafia do grupo e
   fechada (uma linha por campo, valor em linha propria) e um extrator deterministico e o unico
   que da para PROVAR contra as mensagens reais do export — um extrator de LLM so poderia ser
   testado contra o proprio stub, e a licao do harness fiel e nao testar um agente que nao
   existe. Quando a grafia escapar (texto corrido, ditado por audio), o lugar de plugar o LLM e
   o parametro `extrair` da porta unica, sem mexer em quem chama.

O que esta funcao NAO decide: quem e a modelo (resolver closed-world em `nomes.py`), que dia foi
(a porta usa o dia BRT da mensagem) e se a venda ja existe (dedup). Aqui so se le o texto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

# Marcadores da gramatica do anuncio, no INICIO da linha. Sao as tres palavras que a gestora
# escreve em TODO anuncio do export ("Atendimento no nosso local" / "Cliente Gabriel" / "Perfil
# bianca/yasmin"). Casar no inicio da linha (e nao em qualquer lugar do texto) e o que mantem a
# cobranca da agencia ("*3RJ Suporte/Anuncio:* 3 DIAS | R$ 385,80", ticket 08) fora da triagem.
_MARCADOR = re.compile(r"^(atendimento|cliente|perfil)\b")

# Linha que E o valor (com duracao opcional colada): "700 1h", "600 1h", "1.300", "R$ 385,80".
# Ancorada no fim de proposito: linha com texto sobrando ("600 cada uma", "Torre 2 Apt 2706",
# "Rua Miguel y canizares - aleatorios bar") NAO e valor. Anuncio cujo valor nao esta em linha
# propria cai como "sem valor" e vira pergunta minima no ticket 03 — melhor perguntar do que
# registrar o numero de uma torre como dinheiro.
_VALOR = re.compile(
    r"^r?\$?\s*"
    r"(?P<inteiro>\d{1,3}(?:\.\d{3})+|\d+)"
    r"(?:,(?P<centavos>\d{2}))?"
    r"\s*(?:reais)?\s*"
    r"(?:(?P<horas>\d{1,2})\s*h(?:oras?)?\s*(?:(?P<h_min>\d{1,2})\s*(?:min\w*)?)?"
    r"|(?P<minutos>\d{1,3})\s*min\w*)?"
    r"\s*$"
)
# O "min" depois do `h` e OPCIONAL porque "1h30" e a grafia dominante da hora e meia — e o `$` no
# fim desta regex faz dela uma decisao tudo-ou-nada: com "min" obrigatorio, "900 1h30" nao casava
# NADA e o valor 900, escrito ali em letras garrafais, sumia. O agente entao perguntava "quanto
# foi o atendimento?" sobre um anuncio que dizia quanto foi — que e a pior forma de errar, porque
# parece que ele nao sabe ler.

# Duracao SOZINHA no resto da linha "Atendimento ..." ("Atendimento de 2h"): ali o que veio depois
# da palavra e a duracao, nao o local.
_DURACAO_SOLTA = re.compile(
    r"^(?:de\s+)?(?:(?P<horas>\d{1,2})\s*h(?:oras?)?\s*(?:(?P<h_min>\d{1,2})\s*(?:min\w*)?)?"
    r"|(?P<minutos>\d{1,3})\s*min\w*)$"
)

# Marcas de venda com DUAS modelos na grafia do grupo ("1300 cada uma / 2600 no total"). Quem
# parte isso em uma linha por modelo e `rateio.planejar` (ticket 04); aqui elas so precisam ser
# RECONHECIDAS para nao virarem uma venda unica com o valor de uma so.
_RATEIO = re.compile(r"\bcada\s+um[ao]\b|\bno\s+total\b")

# O sufixo que transforma uma linha de valor em valor POR MODELO: "1300 cada uma", "650 1h cada
# uma", "600 cada uma". Retirado o sufixo, o que sobra e lido pelo MESMO parser estrito do valor
# — e por isso "600 cada uma" so vale como rateio quando o resto da linha e exatamente um valor.
#
# "2600 no total" NAO e lido de proposito. O total e redundante quando o "cada uma" foi dito, e
# quando ele e a UNICA cifra do anuncio dividi-lo pelo numero de participantes seria palpite
# (nada garante rateio igual) — o certo ali e perguntar quanto foi de cada uma. Nao lendo o
# total, esse caso cai sozinho na pergunta minima.
_SUFIXO_DE_RATEIO = re.compile(r"\s+cada\s+um[ao]\s*$")

_ESPACOS = re.compile(r"\s+")

# "foi 600", "é 600", "era 600": o grupo responde a pergunta minima com o valor precedido de um
# verbo de ligacao. Nada alem disso — resposta com mais palavras nao e valor (ver
# `ler_valor_avulso`).
_PREFIXO_DE_RESPOSTA = re.compile(r"^(?:foi|e|eh|era|sao|deu)\s+")


@dataclass(frozen=True)
class AnuncioDeVenda:
    """O que o texto do anuncio diz — antes de qualquer resolucao contra o cadastro.

    `nomes` sao os tokens crus das linhas "Perfil ..." ("bianca", "yasmin", "fran loira"), na
    grafia do grupo: quem decide a quem pertencem e o resolver closed-world, nunca este modulo.

    `perfis` e o MESMO conteudo agrupado por linha — e a distincao que separa os dois sentidos da
    grafia do grupo (docs/dominio/grupo-financeiro.md): tokens na MESMA linha ("bianca/yasmin")
    sao apelido/nome verdadeiro de UMA mulher; linhas DIFERENTES sao participantes diferentes.
    Ler "X/Y" como duas mulheres somaria uma venda inexistente; ler duas linhas como uma so
    daria o dinheiro de uma para a outra.
    """

    nomes: tuple[str, ...] = ()
    valor: Decimal | None = None
    cliente: str | None = None
    local: str | None = None
    duracao_minutos: int | None = None
    varias_modelos: bool = False
    perfis: tuple[tuple[str, ...], ...] = ()
    """Um item por linha "Perfil …" — os tokens daquela participante."""
    valor_por_modelo: Decimal | None = None
    """O "cada uma": quanto cada participante recebeu. E o valor de CADA linha registrada quando
    o anuncio tem duas modelos — `valor` ali e o total do atendimento, que nao vai para lugar
    nenhum (a Venda registrada e por modelo, ADR-0043)."""


def normalizar(texto: str) -> str:
    """Minusculo, sem acento, espacos colapsados — a forma de casamento EXATO do modulo.

    E so isto: nao ha stemming, distancia de edicao nem prefixo. "yamin" (o typo real de 08/08)
    nao vira "yasmin" aqui, e e assim que tem que ser — o dominio proibe resolver nome por
    similaridade (o outro token da mesma linha e quem salva o anuncio).
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return _ESPACOS.sub(" ", sem_acento).strip().lower()


def parece_anuncio_de_venda(texto: str) -> bool:
    """Triagem barata: vale a pena gastar extracao com esta mensagem?

    `False` para tudo que o grupo posta e nao e venda — conversa, sticker (texto vazio),
    "Foi pix ou din ?", conferencia de fechamento, cobranca da agencia.

    **DUAS linhas da gramatica** (ou uma linha + o valor em linha propria), nunca uma so. Uma
    linha basta para a palavra cair no meio da conversa: "Cliente chato esse hein" comeca com
    marcador, e com o teste antigo virava um anuncio incompleto — o agente perguntava "quanto foi
    o atendimento do Cliente chato esse hein?" e, pior, deixava esse fantasma esperando um valor:
    o proximo "600" solto do grupo completaria uma venda que nunca existiu.

    Anuncio de verdade nunca vem em uma linha: no export inteiro sao tres ou quatro
    ("Atendimento no nosso local" / "Cliente Gabriel" / "Perfil bianca/yasmin" / "700 1h"), e a
    unica forma curta que a gestora usa ("Cliente Gabriel" + "700") ja traz o valor junto.
    """
    linhas = [normalizar(linha) for linha in texto.splitlines() if linha.strip()]
    marcadores = sum(1 for linha in linhas if _MARCADOR.match(linha))
    if marcadores >= 2:
        return True
    return marcadores == 1 and any(_VALOR.match(linha) for linha in linhas)


def ler_valor_avulso(texto: str) -> tuple[Decimal, int | None] | None:
    """O valor dito SOZINHO numa mensagem — a resposta a pergunta minima do ticket 03.

    "600", "600 1h", "R$ 1.300", "foi 600". Uma linha util e mais nada: o teto e o mesmo do
    anuncio ("o valor mora em linha propria"), so que aqui a linha e a mensagem inteira. Mensagem
    com texto em volta ("Torre 2 Apt 2706", "600 pix", "sao 3 dias") NAO e valor — o numero de um
    apartamento ou de um fechamento viraria dinheiro na conta de alguem.
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if len(linhas) != 1:
        return None
    return _valor_e_duracao(_PREFIXO_DE_RESPOSTA.sub("", normalizar(linhas[0])))


def extrair_anuncio(texto: str) -> AnuncioDeVenda:
    """Le o anuncio linha a linha. Nunca levanta: campo que nao apareceu volta `None`."""
    nomes: list[str] = []
    perfis: list[tuple[str, ...]] = []
    valor: Decimal | None = None
    valor_por_modelo: Decimal | None = None
    cliente: str | None = None
    local: str | None = None
    duracao: int | None = None

    for linha in texto.splitlines():
        crua = _ESPACOS.sub(" ", linha).strip()
        if not crua:
            continue
        n = normalizar(crua)
        if n.startswith("perfil"):
            tokens = _tokens_de_nome(crua)
            if tokens:
                perfis.append(tuple(tokens))
            nomes.extend(tokens)
        elif n.startswith("cliente"):
            cliente = cliente or _resto_depois_do_marcador(crua) or None
        elif n.startswith("atendimento"):
            resto = _resto_depois_do_marcador(crua)
            minutos = _duracao_solta(resto)
            if minutos is not None:
                duracao = duracao or minutos
            elif resto:
                local = local or resto
        else:
            rateio = _valor_de_rateio(n)
            if rateio is not None:
                por_modelo, minutos = rateio
                valor_por_modelo = valor_por_modelo or por_modelo
                duracao = duracao or minutos
            elif valor is None:
                achado = _valor_e_duracao(n)
                if achado is not None:
                    valor, minutos = achado
                    duracao = duracao or minutos

    return AnuncioDeVenda(
        nomes=tuple(nomes),
        valor=valor,
        cliente=cliente,
        local=local,
        duracao_minutos=duracao,
        varias_modelos=_tem_varias_modelos(texto, nomes_por_linha=len(perfis)),
        perfis=tuple(perfis),
        valor_por_modelo=valor_por_modelo,
    )


# --- interno ------------------------------------------------------------------------------------


def _resto_depois_do_marcador(linha: str) -> str:
    """O que vem depois de `Atendimento`/`Cliente`/`Perfil` na linha, ja limpo de pontuacao."""
    return re.sub(r"^\s*\w+\s*[:\-]?\s*", "", linha, count=1).strip(" -:")


def _tokens_de_nome(linha: str) -> list[str]:
    """ "Perfil bianca/yasmin" -> ["bianca", "yasmin"] — a MESMA mulher (anuncio / verdadeiro).

    A barra e a grafia de apelido do grupo, nunca separador de duas participantes: duas modelos
    aparecem como duas linhas "Perfil ..." com "cada uma" (docs/dominio/grupo-financeiro.md).

    A unica coisa que desmente isso e o CADASTRO (dois tokens = duas mulheres cadastradas), e
    quem olha o cadastro e `rateio.planejar` — aqui nao ha resolucao de nome nenhuma.
    """
    resto = _resto_depois_do_marcador(linha)
    return [parte.strip() for parte in resto.split("/") if parte.strip()]


def _tem_varias_modelos(texto: str, *, nomes_por_linha: int) -> bool:
    return nomes_por_linha > 1 or bool(_RATEIO.search(normalizar(texto)))


def _valor_de_rateio(linha_normalizada: str) -> tuple[Decimal, int | None] | None:
    """O valor POR MODELO dito na linha ("1300 cada uma", "650 1h cada uma"), ou `None`."""
    m = _SUFIXO_DE_RATEIO.search(linha_normalizada)
    if m is None:
        return None
    return _valor_e_duracao(linha_normalizada[: m.start()].strip())


def _duracao_solta(resto: str) -> int | None:
    m = _DURACAO_SOLTA.match(normalizar(resto))
    return _minutos(m.group("horas"), m.group("h_min"), m.group("minutos")) if m else None


def _valor_e_duracao(linha_normalizada: str) -> tuple[Decimal, int | None] | None:
    m = _VALOR.match(linha_normalizada)
    if m is None:
        return None
    inteiro = m.group("inteiro").replace(".", "")
    valor = Decimal(f"{inteiro}.{m.group('centavos') or '00'}")
    if valor <= 0:
        return None
    return valor, _minutos(m.group("horas"), m.group("h_min"), m.group("minutos"))


def _minutos(horas: str | None, horas_min: str | None, minutos: str | None) -> int | None:
    if horas:
        return int(horas) * 60 + int(horas_min or 0)
    if minutos:
        return int(minutos)
    return None
