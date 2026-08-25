"""Do anuncio para as LINHAS que vao ser registradas (spec 0005, ticket 04).

Uma venda com duas modelos ("Perfil Alicia/fran loira + Perfil bianca/yasmin / 1200 1h / 600 cada
uma") vira **uma Venda registrada por modelo, cada uma no valor dela** (ADR-0043, decisao 3).
Somar as duas numa linha inventaria uma venda que ninguem fez, e dar o total a uma so daria o
dinheiro de uma para a outra — os dois erros passariam despercebidos no extrato.

Este modulo e a unica peca que sabe transformar `AnuncioDeVenda` + `CadastroDeNomes` no
**plano** do que registrar. Ele e puro (nao toca banco, nao fala no grupo) e serve aos DOIS
momentos em que o plano e montado: quando o anuncio chega e quando a resposta a uma pergunta
minima destrava o que faltava — a porta simplesmente ajusta a entrada (o valor dito, o apelido
recem-aprendido) e replaneja. Uma verdade so sobre "quem recebe quanto".

Regras que ele carrega, todas do dominio:

* **Uma linha "Perfil …" = uma participante**; tokens da mesma linha ("bianca/yasmin") sao a
  mesma mulher (o resolver closed-world de `nomes.py` fecha a intersecao).
* **Ninguem nomeado = a dona do grupo** — o vinculo grupo<->modelo e closed-world, entao nao ha
  palpite ("Cliente Antônio / Seu nome é bianca / 600 1h", 10/08). Vale so para anuncio de UMA
  participante: com duas, cair na dona do grupo registraria a venda da outra na mulher errada.
* **Falta parcial nao trava o resto**: no anuncio de 10/08 uma participante e conhecida e a outra
  nao. A conhecida e registrada na hora e o agente pergunta so pela outra — Pendencia bloqueia a
  conciliacao daquela venda, nunca o registro das demais (docs/dominio/grupo-financeiro.md).
* **Sem valor por modelo, ninguem registra.** Com duas participantes, o unico numero que serve e
  o "cada uma"; dividir o total pelo numero de mulheres seria supor rateio igual, e supor e o
  que o dominio proibe. Sem ele o plano volta com a falta e a porta pergunta.
* **Quem trabalhou e quem RECEBEU sao perguntas diferentes** (ticket 13, ADR-0045 §6). Na
  festinha, uma modelo costuma receber o valor de todas e repassar depois. Isso NAO muda o
  rateio — continuam sendo N linhas, cada uma no valor da sua modelo, senao o faturamento
  individual some —, muda de quem e o debito do bruto. Por isso `recebido_por` e campo da LINHA
  e chega de fora (`ler_recebedor_unico`), em vez de virar mais um jeito de dividir dinheiro.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import AnuncioDeVenda, normalizar
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes
from barra.dominio.grupo_financeiro.pergunta import Falta


@dataclass(frozen=True)
class LinhaDoAnuncio:
    """Uma Venda registrada a nascer: a modelo, o nome dela na fala da casa e o valor DELA."""

    modelo_id: UUID
    nome: str
    valor: Decimal
    recebido_por: UUID | None = None
    """Quem ficou com o dinheiro desta linha, quando nao foi a propria modelo (ticket 13).

    `None` = ela mesma. Preenchido so na festinha em que **uma recebeu por todas**: as N linhas
    continuam existindo, cada uma no valor da sua modelo (ADR-0043 — o faturamento individual e o
    que nao pode sumir), e o que muda e de quem e o DEBITO do bruto (ADR-0045 §6).

    Fica na linha, e nao no plano, porque e fato de cada venda: a coluna que ele alimenta e
    `vendas_registradas.recebido_por_modelo_id`, uma por linha. Guardar no plano obrigaria quem
    grava a lembrar de copia-lo N vezes — e esquecer numa delas e a festinha em que tres modelos
    aparecem devendo e a quarta nao."""


@dataclass(frozen=True)
class PlanoDoAnuncio:
    """O que o anuncio rende — o que da para registrar agora e o que precisa ser perguntado."""

    linhas: tuple[LinhaDoAnuncio, ...] = ()
    faltas: tuple[Falta, ...] = ()
    nomes_desconhecidos: tuple[str, ...] = ()
    """Tokens que o cadastro nao conhece — o texto da pergunta sai daqui e, quando o grupo
    responder quem e, sao ELES que viram Nome de anuncio da mulher nomeada."""
    ambiguo: bool = False
    """Algum "Perfil …" bateu em mais de um cadastro. Nao vira pergunta: repetir o nome nao
    desempata homonimo — isso e erro de cadastro e se resolve no painel."""
    por_modelo: bool = False
    """O anuncio e de duas ou mais participantes: a pergunta pelo valor fala "cada uma"."""
    participante_oculta: bool = False
    """O anuncio AFIRMA duas participantes ("cada uma", "no total") e so identifica uma.

    Registrar a nomeada daria a ela o valor de uma mulher que nunca aparece no sistema, e
    perguntar "quem mais?" seria interrogatorio sobre um anuncio escrito pela metade. O plano
    volta vazio e a porta cala com motivo visivel."""


def planejar(
    anuncio: AnuncioDeVenda,
    *,
    cadastro: CadastroDeNomes,
    dona_do_grupo: UUID | None,
    recebido_por: UUID | None = None,
) -> PlanoDoAnuncio:
    """Quem recebe quanto neste anuncio. Nunca levanta: o que falta volta em `faltas`.

    `recebido_por` e a festinha em que **uma modelo recebeu o dinheiro de todas** (ticket 13),
    lida do texto por `ler_recebedor_unico` — parametro, e nao coisa que este modulo va inferir:
    o plano sabe quem trabalhou, nunca quem ficou com a nota na mao.

    Ele so vale se a mulher apontada estiver ENTRE as participantes planejadas. Uma festinha nao
    e um nome solto na frase: apontar para quem nao esta na venda mandaria o debito de R$ 4.000
    para o extrato de alguem que nao esteve la, e as quatro que estiveram ficariam limpas. Fora
    dessa condicao ele e simplesmente ignorado — nao vira falta nem pergunta, porque a venda esta
    completa sem ele (o default `None` ja significa "cada uma recebeu a sua", que e o caso comum).
    """
    perfis = _participantes(anuncio, cadastro=cadastro)
    if len(perfis) > 1:
        plano = _plano_de_varias(anuncio, perfis=perfis, cadastro=cadastro)
    elif anuncio.varias_modelos:
        plano = PlanoDoAnuncio(participante_oculta=True)
    else:
        plano = _plano_de_uma(anuncio, cadastro=cadastro, dona_do_grupo=dona_do_grupo)
    return _com_recebedor(plano, recebido_por)


def _com_recebedor(plano: PlanoDoAnuncio, recebido_por: UUID | None) -> PlanoDoAnuncio:
    """Carimba o recebedor unico em TODAS as linhas — ou em nenhuma.

    Todas, inclusive na linha da propria recebedora: `recebido_por == modelo_id` e a mesma coisa
    que `None` para quem le (o razao usa `COALESCE(recebido_por_modelo_id, modelo_id)`), e
    carimbar so as outras deixaria a festinha com quatro linhas de dois formatos diferentes para
    o mesmo fato. Uma verdade so por venda.
    """
    if recebido_por is None or not plano.linhas:
        return plano
    if not any(linha.modelo_id == recebido_por for linha in plano.linhas):
        return plano
    return replace(
        plano, linhas=tuple(replace(linha, recebido_por=recebido_por) for linha in plano.linhas)
    )


# --- "uma recebeu o dinheiro de todas" (ticket 13) -----------------------------------------------
#
# Na festinha, uma modelo costuma receber o valor das outras e repassar depois ("essa fechinha, uma
# modelo so recebeu o valor de todas"). Sem ler isso, tres mulheres aparecem devendo o bruto que
# nunca viram e a IA cobra comprovante de quem nao recebeu nada.
#
# A leitura e uma ALLOWLIST FECHADA, como todo leitor deste modulo: verbo de recebimento + palavra
# de totalidade + UM nome do cadastro, e nada mais na frase. E deliberadamente estreita porque a
# escrita que ela dispara e cara e silenciosa — o debito do bruto INTEIRO muda de dona, e ninguem
# revisa uma coluna que o sistema preencheu sozinho. Frase que nao casa nao vira palpite: o default
# ("cada uma recebeu a sua") continua valendo, que e o que acontece na maioria das vendas.

MAX_PALAVRAS_DO_RECEBEDOR = 12
"""Teto da frase que declara o recebedor unico. A declaracao real e telegrafica ("a Yasmin recebeu
tudo"); o teto derruba de graca o paragrafo que MENCIONA a Yasmin falando de outra coisa."""

_VERBOS_DE_RECEBIMENTO = frozenset({"recebeu", "recebi", "pegou", "levou", "ficou", "embolsou"})
"""O verbo e obrigatorio: sem ele, "tudo da Yasmin" e uma frase sobre posse que pode ser sobre
qualquer coisa. Com ele, a frase e sobre dinheiro que trocou de mao."""

_ESCOPO_TOTAL = frozenset({"tudo", "todas", "todos", "td", "tds", "total", "geral", "inteiro"})
"""A palavra de totalidade e obrigatoria pelo mesmo motivo, do outro lado: "a Yasmin recebeu" (sem
"tudo") e a resposta de pagamento de UMA venda — a mais comum do grupo — e le-la como festinha
mandaria o dinheiro das colegas para o extrato dela."""

_RECHEIO_DO_RECEBEDOR = frozenset(
    {
        "a",
        "as",
        "o",
        "os",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "com",
        "em",
        "na",
        "nas",
        "no",
        "nos",
        "por",
        "pra",
        "para",
        "e",
        "eh",
        "foi",
        "ela",
        "elas",
        "dela",
        "delas",
        "amiga",
        "amigas",
        "meninas",
        "gente",
        "dinheiro",
        "valor",
        "grana",
        "pagamento",
        "programa",
        "ja",
        "so",
        "sozinha",
        "entao",
        "todo",
        "sim",
    }
)


def ler_recebedor_unico(
    texto: str, *, cadastro: CadastroDeNomes, candidatas: Sequence[UUID]
) -> UUID | None:
    """Quem recebeu o dinheiro de TODAS nesta venda? `None` quando a frase nao declara isso.

    `candidatas` sao as modelos da venda. O alvo tem que estar entre elas — e quem trabalhou que
    pode ter recebido pelas outras — e a frase nao pode nomear nenhuma mulher de FORA: nomear
    duas pessoas e um fato sobre duas pessoas, e este modulo nunca escolhe uma delas.

    Nao confundir com a resposta de pagamento (`pagamento.ler_fala_de_pagamento`): la a pergunta e
    "COMO foi pago", aqui e "COM QUEM ficou o dinheiro". As duas podem estar na mesma mensagem
    ("foi pix, a Yasmin recebeu tudo") e sao lidas por leitores diferentes, cada um pelo seu lado.
    """
    if not candidatas:
        return None
    normalizado = normalizar(texto)
    if not normalizado or "?" in normalizado:
        # Pergunta nao declara nada. "quem recebeu tudo?" e o telefonista perguntando — e a
        # resposta dele, mais adiante, e que sera a declaracao.
        return None
    palavras = _PALAVRA_DO_RECEBEDOR.findall(normalizado)
    if not palavras or len(palavras) > MAX_PALAVRAS_DO_RECEBEDOR:
        return None
    if not any(p in _VERBOS_DE_RECEBIMENTO for p in palavras):
        return None
    if not any(p in _ESCOPO_TOTAL for p in palavras):
        return None

    encontradas: set[UUID] = set()
    sobra = normalizado
    for chave, ids in cadastro.por_nome.items():
        padrao = rf"(?<![a-z0-9]){re.escape(chave)}(?![a-z0-9])"
        if re.search(padrao, normalizado):
            encontradas |= set(ids)
            sobra = re.sub(padrao, " ", sobra)
    # Homonimo cadastrado faz `encontradas` crescer sem que a frase cite duas mulheres; a
    # intersecao com as participantes desempata, e so ela — se sobrar mais de uma, a frase e
    # ambigua de verdade e o silencio e a resposta certa.
    alvos = encontradas & set(candidatas)
    if len(alvos) != 1 or encontradas - set(candidatas):
        return None
    if any(p not in _PERMITIDAS_NO_RECEBEDOR for p in _PALAVRA_DO_RECEBEDOR.findall(sobra)):
        return None
    return next(iter(alvos))


_PALAVRA_DO_RECEBEDOR = re.compile(r"[a-z0-9]+")

_PERMITIDAS_NO_RECEBEDOR = _RECHEIO_DO_RECEBEDOR | _VERBOS_DE_RECEBIMENTO | _ESCOPO_TOTAL


def _participantes(
    anuncio: AnuncioDeVenda, *, cadastro: CadastroDeNomes
) -> tuple[tuple[str, ...], ...]:
    """As linhas "Perfil …" ja partidas em participantes — normalmente uma linha, uma mulher.

    A excecao e a linha unica que o CADASTRO desmente. "Perfil lari/ juju" com "600 cada uma"
    (16/08) tem a grafia de apelido, mas "lari" e "juju" sao duas mulheres cadastradas: a
    intersecao do resolver da vazia e o anuncio inteiro sumia calado, com a casa sem registrar
    duas vendas que aconteceram.

    So partimos quando o cadastro nao deixa duvida: cada token resolve SOZINHO para uma mulher e
    as mulheres sao diferentes. Typo ("bianca/yamin"), homonimo e apelido que resolve para a
    mesma pessoa continuam sendo uma participante so — nesses a intersecao e a resposta certa.
    """
    if len(anuncio.perfis) != 1 or not anuncio.varias_modelos:
        return anuncio.perfis
    tokens = anuncio.perfis[0]
    if len(tokens) < 2 or cadastro.resolver(tokens).veredito != "ambiguo":
        return anuncio.perfis
    sozinhas = [cadastro.resolver((token,)) for token in tokens]
    if any(r.veredito != "resolvido" or r.modelo_id is None for r in sozinhas):
        return anuncio.perfis
    if len({r.modelo_id for r in sozinhas}) != len(sozinhas):
        return anuncio.perfis
    return tuple((token,) for token in tokens)


def _plano_de_uma(
    anuncio: AnuncioDeVenda,
    *,
    cadastro: CadastroDeNomes,
    dona_do_grupo: UUID | None,
) -> PlanoDoAnuncio:
    resolucao = cadastro.resolver(anuncio.nomes)
    if resolucao.veredito == "ambiguo":
        return PlanoDoAnuncio(ambiguo=True, nomes_desconhecidos=resolucao.nomes_nao_resolvidos)

    faltas: list[Falta] = []
    if anuncio.valor is None:
        faltas.append("valor")
    if resolucao.veredito == "desconhecido":
        faltas.append("modelo")
    if faltas:
        return PlanoDoAnuncio(
            faltas=tuple(faltas), nomes_desconhecidos=resolucao.nomes_nao_resolvidos
        )

    # `sem_nome` = o anuncio nao nomeou ninguem; a dona do grupo e a resposta (ver docstring).
    modelo_id = resolucao.modelo_id or dona_do_grupo
    if modelo_id is None or anuncio.valor is None:  # pragma: no cover - grupo sempre tem modelo
        return PlanoDoAnuncio(faltas=("modelo",))
    nome = resolucao.nome or cadastro.nome_verdadeiro.get(modelo_id) or "modelo"
    return PlanoDoAnuncio(linhas=(LinhaDoAnuncio(modelo_id, nome, anuncio.valor),))


def _plano_de_varias(
    anuncio: AnuncioDeVenda,
    *,
    perfis: tuple[tuple[str, ...], ...],
    cadastro: CadastroDeNomes,
) -> PlanoDoAnuncio:
    valor = anuncio.valor_por_modelo
    linhas: list[LinhaDoAnuncio] = []
    desconhecidos: list[str] = []
    ambiguo = False
    ja_planejadas: set[UUID] = set()

    for tokens in perfis:
        resolucao = cadastro.resolver(tokens)
        if resolucao.veredito == "ambiguo":
            ambiguo = True
            continue
        if resolucao.veredito != "resolvido" or resolucao.modelo_id is None:
            desconhecidos.extend(resolucao.nomes_nao_resolvidos or tokens)
            continue
        if resolucao.modelo_id in ja_planejadas:
            # As duas linhas resolveram para a MESMA mulher (o grupo repetiu o perfil dela em
            # duas linhas). Uma mulher recebe uma vez: registrar duas seria dobrar a venda.
            continue
        ja_planejadas.add(resolucao.modelo_id)
        if valor is not None:
            nome = resolucao.nome or cadastro.nome_verdadeiro.get(resolucao.modelo_id) or "modelo"
            linhas.append(LinhaDoAnuncio(resolucao.modelo_id, nome, valor))

    faltas: list[Falta] = []
    if valor is None:
        faltas.append("valor")
    if desconhecidos:
        faltas.append("modelo")
    return PlanoDoAnuncio(
        linhas=tuple(linhas),
        faltas=tuple(faltas),
        nomes_desconhecidos=tuple(desconhecidos),
        ambiguo=ambiguo,
        por_modelo=True,
    )
