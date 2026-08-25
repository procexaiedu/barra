"""Dados cadastrais oportunistas da modelo (spec 0005, ticket 12).

O grupo dita dado operacional no meio da conversa, sem nunca falar com o sistema (09/08/2026):

    [12:55:16] ~ Dani:            Passa o novo apartamento amiga
    [12:55:20] ~ Dani:            Torre e apartamento
    [12:55:39] +55 11 96854-4493: Torre 2 Apt 2706

O agente guarda o "Torre 2 Apt 2706" e **nao responde nada** — nem "anotei". Ele tambem nunca
inicia a pergunta: quem perguntou pelo apartamento foi a gestora, e e assim que tem que ser
(docs/dominio, "Agente financeiro": _Avoid_ perguntar cadastro proativamente; o fetiche
cadastro-first ja mordeu o agente de venda). A unica pergunta que este modulo faz continua sendo
a **pergunta minima** de uma venda (tickets 03/04) — aquilo e venda, nao cadastro.

## Por que a leitura e uma gramatica fechada, e nao "achou um numero de apto"

Dado cadastral escrito errado nao da erro: ele fica la, certo o suficiente para ninguem
desconfiar. Entao a leitura e **fail-closed** — a mensagem INTEIRA tem que ser o dado, palavra por
palavra:

* "Torre 2 Apt 2706" -> endereco. Todas as palavras sao lugar+numero, nada sobra.
* "Torre e apartamento" -> nada (a pergunta da gestora: lugar sem numero).
* "Passa o novo apartamento amiga" -> nada (palavra fora da gramatica).
* "O cliente ta na torre 3 apt 101" -> nada. E o caso do **terceiro**: dado de outra pessoa vem
  com as palavras que dizem de quem ele e, e sao elas que derrubam a leitura. Nao ha aqui um
  classificador de "e dela?" — ha uma gramatica tao estreita que so o dado dela passa.

## A chave Pix tem uma tranca a mais: quem falou

"Minha Chave Pix para transferência: +5571…" e uma mensagem REAL do grupo — e ela e de um GESTOR
passando a chave da casa, nao da modelo. Primeira pessoa nao prova posse num grupo com quatro
pessoas dentro. Por isso a chave so vira cadastro quando **quem escreveu e a modelo do grupo**
(numero dela, `@s.whatsapp.net`); qualquer outro autor cai em `de_terceiro`, que o agente ignora
em silencio. Chave errada atribuida a ela nao seria so um campo torto: ela entra no contexto de
classificacao de comprovante, e passaria a explicar dinheiro que foi para a conta de outra pessoa.

A chave dela **nao** entra em `chaves_pix_conhecidas` (o destino legitimo da casa, ticket 07) —
ver o comentario da migration. Aqui ela serve para RECONHECER a parte: um comprovante que aponta
para a chave da propria modelo deixa de ser "chave fora da lista, confere ai" e passa a ser
"esse Pix foi pra chave dela", que e outra conversa.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.comprovante import normalizar_chave

CampoCadastral = Literal["endereco_operacional", "chave_pix"]
"""O que este modulo aprende de graca no grupo. Fechado de proposito: cada campo novo aqui e uma
gramatica nova, e gramatica frouxa escreve cadastro errado em silencio."""

VereditoDaLeitura = Literal["dado", "de_terceiro", "nada"]


@dataclass(frozen=True)
class DadoCadastral:
    """Um dado cadastral lido de uma mensagem, ainda nao persistido."""

    campo: CampoCadastral
    valor: str


@dataclass(frozen=True)
class LeituraCadastral:
    """O que a mensagem rendeu de cadastro.

    `de_terceiro` existe separado de `nada` porque as duas condutas sao iguais (silencio) e as
    duas causas nao sao: uma e o grupo conversando, a outra e alguem ditando a chave Pix de
    outra pessoa. A segunda tem que aparecer no log e na metrica — e o unico sinal de que o
    agente RECUSOU aprender algo.
    """

    veredito: VereditoDaLeitura
    dado: DadoCadastral | None = None


@dataclass(frozen=True)
class DadoCadastralRegistrado:
    """Uma observacao ja persistida: o que passou a valer, o que valia antes, por causa de que.

    Append-only — nao existe "atualizar" um dado cadastral neste modulo, existe observar de novo.
    """

    id: UUID
    modelo_id: UUID
    campo: CampoCadastral
    valor: str
    valor_anterior: str | None
    mensagem_id: UUID | None
    observado_em: datetime


# --- endereco operacional (torre/apto) ----------------------------------------------------------

# Palavra de lugar que, seguida de numero, e o dado. `_NUCLEO` e o que basta sozinho; `andar` e
# `sala` so acompanham (uma mensagem "Andar 5" nao e o apartamento de ninguem).
_NUCLEO = frozenset({"ap", "apt", "apto", "apartamento", "torre", "bloco", "unidade"})
_ACOMPANHAMENTO = frozenset({"andar", "sala"})
_LUGAR = _NUCLEO | _ACOMPANHAMENTO

_NUMERO_DO_LUGAR = re.compile(r"^\d{1,5}[a-z]?$")
_PONTUACAO = re.compile(r"[,;:./#\-º°ª]+")

MAX_PARES_DO_ENDERECO = 4
"""Teto de "lugar + numero" numa mensagem. Endereco de grupo e "Torre 2 Apt 2706"; quatro pares
ja cobrem bloco/torre/andar/apto e mantem a leitura longe de texto corrido."""


def _ler_endereco(texto: str) -> str | None:
    """A mensagem inteira e um endereco de torre/apto? Devolve como foi dito. `None` = nao e.

    Exige que TODA palavra seja lugar-seguido-de-numero. E essa exigencia (e nao uma lista de
    frases proibidas) que faz "Passa o novo apartamento amiga" e "O cliente ta na torre 3 apt 101"
    cairem fora: sobra palavra.
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if len(linhas) != 1:
        return None
    tokens = _forma_do_endereco(linhas[0]).split()
    if not tokens or len(tokens) > 2 * MAX_PARES_DO_ENDERECO:
        return None

    lugares: list[str] = []
    for i in range(0, len(tokens), 2):
        lugar = tokens[i]
        if lugar not in _LUGAR:
            return None
        if i + 1 >= len(tokens) or not _NUMERO_DO_LUGAR.match(tokens[i + 1]):
            return None
        lugares.append(lugar)
    if not any(lugar in _NUCLEO for lugar in lugares):
        return None
    return " ".join(linhas[0].split())


# --- chave Pix da propria modelo ----------------------------------------------------------------

# Allowlist fechada do que pode acompanhar a declaracao, no mesmo espirito de `pagamento.py`:
# palavra fora daqui (um nome proprio, um imperativo) e sinal de que a mensagem NAO e "esta e a
# minha chave" — e o que separa "Minha chave pix e X" de "Pode enviar nesse pix X".
_RECHEIO_DA_DECLARACAO = frozenset(
    {
        "a",
        "amiga",
        "amigo",
        "aqui",
        "chave",
        "conta",
        "de",
        "do",
        "e",
        "eh",
        "esta",
        "meu",
        "minha",
        "nova",
        "novo",
        "para",
        "pix",
        "pra",
        "receber",
        "segue",
        "transferencia",
        "transferencias",
    }
)
_POSSE = frozenset({"minha", "meu"})
_NOMEIA_A_CHAVE = frozenset({"chave", "pix"})

MAX_PALAVRAS_DA_DECLARACAO = 7
"""Teto do que vem ANTES da chave. Declaracao de chave e curta; paragrafo com uma chave no meio e
outra coisa (instrucao de transferencia, conversa) e nao se cadastra."""

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _parece_chave_pix(bruta: str) -> bool:
    """Formato de chave Pix: telefone, CPF/CNPJ, e-mail ou chave aleatoria.

    Fechado de proposito. Sem isso, "Minha chave e a mesma" cadastraria a palavra "mesma" como
    chave da modelo — e um cadastro errado que so aparece quando alguem tentar pagar.
    """
    if _EMAIL.match(bruta.strip()):
        return True
    limpa = normalizar_chave(bruta)
    if _HEX32.match(limpa):
        return True
    return limpa.isdigit() and 10 <= len(limpa) <= 14


def _ler_chave_pix(texto: str) -> str | None:
    """A mensagem inteira e "minha chave pix e X"? Devolve X como foi dito. `None` = nao e.

    NAO decide de quem e a chave — isso e do autor da mensagem (`autor_e_a_modelo`), porque
    primeira pessoa num grupo de quatro pessoas nao prova posse.
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if len(linhas) != 1:
        return None
    bruto = " ".join(linhas[0].split())

    if ":" in bruto:
        cabeca, _, chave = bruto.partition(":")
    else:
        palavras = bruto.split()
        if len(palavras) < 2:
            return None
        cabeca, chave = " ".join(palavras[:-1]), palavras[-1]

    chave = chave.strip()
    if not _parece_chave_pix(chave):
        return None

    declaracao = normalizar(_PONTUACAO.sub(" ", cabeca)).split()
    if not declaracao or len(declaracao) > MAX_PALAVRAS_DA_DECLARACAO:
        return None
    if declaracao[0] not in _POSSE:
        return None
    if not _NOMEIA_A_CHAVE.intersection(declaracao):
        return None
    if any(palavra not in _RECHEIO_DA_DECLARACAO for palavra in declaracao):
        return None
    return " ".join(chave.split())


# --- quem falou ---------------------------------------------------------------------------------

_SO_DIGITOS = re.compile(r"\D")
DIGITOS_COMPARADOS = 8
"""Quantos digitos finais decidem se dois numeros sao o mesmo. Oito porque o nono digito e a
divergencia classica do WhatsApp brasileiro ("11 96854-4493" x "11 6854-4493") e o DDD nao muda o
assinante — comparar a cauda e o que o resto do sistema tambem faz com telefone."""


def autor_e_a_modelo(autor_jid: str | None, numero_da_modelo: str | None) -> bool:
    """Quem escreveu esta mensagem e a modelo dona do grupo?

    Fail-closed em tres pontos, e os tres importam: sem autor, sem numero cadastrado ou com autor
    em `@lid` a resposta e NAO. O `@lid` e o identificador opaco que o WhatsApp entrega no lugar
    do telefone (ja gravado como telefone por engano neste projeto) — comparar digito de `@lid`
    com telefone e comparar duas coisas diferentes que as vezes se parecem.
    """
    if not autor_jid or not numero_da_modelo:
        return False
    usuario, _, dominio = autor_jid.partition("@")
    if dominio.startswith("lid"):
        return False
    dela = _SO_DIGITOS.sub("", numero_da_modelo)
    autor = _SO_DIGITOS.sub("", usuario.partition(":")[0])
    if len(dela) < 10 or len(autor) < 10:
        return False
    return dela[-DIGITOS_COMPARADOS:] == autor[-DIGITOS_COMPARADOS:]


# --- a leitura --------------------------------------------------------------------------------


def ler_dado_cadastral(texto: str, *, autor_e_a_modelo: bool) -> LeituraCadastral:
    """O que esta mensagem ensina sobre o cadastro da modelo do grupo.

    Endereco nao depende de quem falou: no grupo DELA, "Torre 2 Apt 2706" e o local dela — a
    gestora que responde pela modelo diz a mesma coisa que ela. Chave Pix depende, e muito
    (`de_terceiro`).
    """
    endereco = _ler_endereco(texto)
    if endereco is not None:
        return LeituraCadastral("dado", DadoCadastral("endereco_operacional", endereco))

    chave = _ler_chave_pix(texto)
    if chave is None:
        return LeituraCadastral("nada")
    if not autor_e_a_modelo:
        return LeituraCadastral("de_terceiro")
    return LeituraCadastral("dado", DadoCadastral("chave_pix", chave))


def mesmo_valor(campo: CampoCadastral, atual: str | None, novo: str) -> bool:
    """O dado dito agora e o que ja esta guardado? Entao nao ha o que registrar.

    A comparacao e por campo porque "igual" e por campo: "Torre 2, apt 2706" e o mesmo endereco
    que "Torre 2 Apt 2706" (a virgula e a caixa sao digitacao — a mesma forma que a LEITURA do
    endereco usa), e "+55 71 99984-0879" e a mesma chave que "5571999840879" (a mesma normalizacao
    do comprovante — comparar chave Pix e o mesmo problema nos dois lugares).
    """
    if atual is None:
        return False
    if campo == "chave_pix":
        return normalizar_chave(atual) == normalizar_chave(novo)
    return _forma_do_endereco(atual) == _forma_do_endereco(novo)


def _forma_do_endereco(endereco: str) -> str:
    return normalizar(_PONTUACAO.sub(" ", endereco))


def e_a_chave_da_modelo(chave_lida: str | None, chave_cadastrada: str | None) -> bool:
    """O destino deste comprovante e a chave da propria modelo?"""
    if not chave_lida or not chave_cadastrada:
        return False
    return normalizar_chave(chave_lida) == normalizar_chave(chave_cadastrada)


def nome_e_da_modelo(nome_lido: str | None, nomes_dela: Collection[str]) -> bool:
    """O nome que o comprovante mostra (pagador ou titular) e o dela?

    Decide pelo **primeiro nome dos dois lados**, e so por ele: o comprovante traz o nome civil
    inteiro ("YASMIN NASCIMENTO DE ALBUQUERQUE") e o cadastro guarda ora o apelido ("bianca"), ora
    o nome com sobrenome ("Yasmin Ruiva"). Sobrenome nao serve de chave — o do cadastro quase nunca
    e o civil — e casar por "contem qualquer token" faria "Erick de Melo Souza" bater com uma
    modelo chamada Melo.

    Um homonimo (cliente Yasmin pagando a casa) da falso positivo aqui, e e por isso que quem
    chama isto nao decide so com o titular: quem PAGOU tambem tem que nao ser ela.
    """
    if not nome_lido:
        return False
    palavras = normalizar(nome_lido).split()
    if not palavras:
        return False
    dela = {partes[0] for nome in nomes_dela if (partes := normalizar(nome).split())}
    return palavras[0] in dela


def montar_aviso_de_chave_da_modelo(*, chave: str | None, titular: str | None = None) -> str:
    """ "⚠️ Esse Pix foi pra chave da própria modelo (…) — não é a conta da casa, confere aí."

    Substitui o aviso generico de chave desconhecida quando o destino e a chave DELA: as duas
    situacoes pedem o mesmo olho humano, mas dizem coisas diferentes — uma pode ser golpe ou erro
    de digitacao, a outra e dinheiro que ficou com a modelo (cliente que pagou direto a ela). Sem
    esta linha, o cadastro que o agente aprendeu de graca nao mudaria nada no que ele enxerga.
    """
    alvo = " · ".join(p for p in (titular, chave) if p) or "chave que o comprovante não mostrou"
    return (
        f"⚠️ Esse Pix foi pra chave da própria modelo ({alvo}) — não é a conta da casa, confere aí."
    )
