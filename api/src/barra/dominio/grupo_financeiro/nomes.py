"""Resolver de Nome de anuncio — closed-world (spec 0005, ticket 02).

"Perfil bianca/yasmin" tem que virar UMA modelo. O cadastro que responde isso e a uniao de dois
conjuntos: o **nome verdadeiro** (`modelos.nome`) e os **nomes de anuncio**
(`modelo_nomes_anuncio`). Fora dessa uniao nao existe resposta: nome desconhecido NAO vira venda
por palpite — o ticket 04 pergunta no grupo ("'fran loira' e quem?") e grava a resposta.

Tres motivos para o casamento ser EXATO (sobre a forma normalizada) e nunca por similaridade:

* nomes de anuncio sao curtos e parecidos entre si por profissao ("bianca", "bruna", "bia");
* errar a mulher e errar o dinheiro dela — o registro vai para o extrato de outra pessoa;
* o grupo ja escreve com typo ("Perfil bianca/yamin", 08/08). O typo nao pode "quase casar":
  quem salva o anuncio e o OUTRO token da mesma linha, que casa exato. Se nenhum casar, a
  resposta certa e perguntar, nao adivinhar.

Homonimo tambem nao adivinha: dois cadastros para o mesmo nome devolvem `ambiguo` (o `barra_test`
tem varias "Yasmin" de residuo de teste — em producao isso seria erro de cadastro, e o agente
pergunta em vez de sortear).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar

VereditoDoNome = Literal["resolvido", "sem_nome", "desconhecido", "ambiguo"]

OrigemDoAnuncio = Literal["proprio", "fake"]
"""De qual anuncio o cliente veio: o **proprio** (com as fotos dela) ou o **fake** (o generico).

E atributo da VENDA, nunca do Nome de anuncio (docs/dominio/grupo-financeiro.md): a mesma "Bianca"
vende pelos dois, e criar um apelido "fake bianca" no cadastro so funcionaria se o telefonista
sempre escrevesse a palavra — no export real ele nao escreve. Mora aqui, e nao em `ficha.py`,
porque em texto livre a marca vem **colada ao nome** e quem a separa do nome e este resolver;
`ficha.py` reimporta o tipo para o card, que e a outra porta do mesmo fato.
"""

_MARCAS_DE_ORIGEM: dict[str, OrigemDoAnuncio] = {
    "fake": "fake",
    "perfil": "proprio",
    "proprio": "proprio",
    "propria": "proprio",
    "original": "proprio",
}
"""As palavras que, coladas ao nome, DIZEM a origem — allowlist fechada, como todo vocabulario
deste modulo.

"perfil" conta como `proprio` porque e assim que o grupo escreve o anuncio dela ("Perfil
bianca/yasmin") e e o contraste que o telefonista usa quando muda ("fake Bianca"). E o que faz o
backfill de agosto ja render a metrica em vez de um campo nulo em toda linha.

O que NAO esta aqui nao vira origem: "modelo bianca", "a Duda" e o card com `Origem` em branco
ficam com origem NULA. Nulo e resposta legitima — a metrica do dono compara fake contra proprio, e
um palpite carimbado em cima do que ninguem disse contamina exatamente a decisao de investimento
que ela existe para informar. Pelo mesmo motivo o **site** nao deduz a origem: o dono disse que "o
fake so vai ser sites especificos", mas quais sites sao esses nao esta escrito em lugar nenhum, e
inventar a lista aqui seria fabricar a metrica.
"""


PALAVRAS_DE_ATRIBUICAO = frozenset(
    {
        "e",  # "é" e "e" colapsam na forma normalizada (sem acento)
        "eh",
        "a",
        "o",
        "as",
        "os",
        "da",
        "do",
        "de",
        "na",
        "no",
        "com",
        "essa",
        "esse",
        "esta",
        "este",
        "era",
        "foi",
        "ela",
        "sim",
        "aquela",
        "mesma",
        "amiga",
        "amigas",
        "modelo",
        "perfil",
        "nome",
    }
)
"""O que pode sobrar numa frase que ATRIBUI a venda a alguem ("é a Duda", "essa é da Yasmin").

Allowlist fechada, nao blocklist: o conjunto de frases em que um nome aparece de passagem e
infinito, e errar para o lado de nao entender custa uma pergunta repetida — errar para o outro
lado poe a venda no extrato da mulher errada e grava um apelido falso no cadastro.
"""


def separar_origem(texto: str) -> tuple[OrigemDoAnuncio | None, str]:
    """Separa a marca de origem do NOME: `"fake Bianca"` -> `("fake", "Bianca")`.

    Pura e sem cadastro: aqui nao se pergunta quem e Bianca, so se tira do token o que nao e nome
    dela. As duas saidas viram coisas diferentes e irreversiveis — a origem vai para a coluna da
    venda (a metrica do dono) e o resto vai para o resolver closed-world, que pode ensina-lo ao
    cadastro como Nome de anuncio.

    Tres decisoes:

    * **`fake` vence `proprio`.** "perfil fake bianca" tem as duas palavras, e a que o telefonista
      digitou de proposito e "fake" — "perfil" ali e so o rotulo do campo.
    * **A grafia do nome e preservada** (nao devolvemos a forma normalizada): quem grava o Nome de
      anuncio no cadastro grava o que o grupo escreveu, e o recibo fala como a casa fala.
    * **Marca sozinha devolve nome VAZIO** ("Perfil fake" sem nome nenhum). Devolver o texto
      original ali faria "fake" virar um token desconhecido, o agente perguntaria "'fake' e quem?"
      e a resposta cadastraria a palavra como apelido de alguem — exatamente o que o dominio
      proibe (docs/dominio/grupo-financeiro.md, _Avoid_).
    """
    marcas: list[OrigemDoAnuncio] = []
    restantes: list[str] = []
    for palavra in texto.split():
        marca = _MARCAS_DE_ORIGEM.get(normalizar(palavra).strip(".,;:!?()[]-/"))
        if marca is None:
            restantes.append(palavra)
        else:
            marcas.append(marca)
    if not marcas:
        return None, texto
    origem: OrigemDoAnuncio = "fake" if "fake" in marcas else "proprio"
    return origem, " ".join(restantes)


@dataclass(frozen=True)
class ResolucaoDeNome:
    """Quem o anuncio nomeou — e, quando ninguem, por que."""

    veredito: VereditoDoNome
    modelo_id: UUID | None = None
    nome: str | None = None
    """Nome VERDADEIRO da modelo (o do cadastro), para o recibo falar como a casa fala."""
    nomes_nao_resolvidos: tuple[str, ...] = ()
    """Tokens que o cadastro nao conhece — o texto da pergunta do ticket 04 sai daqui.

    Vem **sem** a marca de origem: e o nome que o grupo vai ensinar ("fran loira"), nunca "fake
    fran loira". Gravar a marca junto criaria um Nome de anuncio que so casa quando o telefonista
    repetir a palavra, e a mesma mulher passaria a ter dois apelidos concorrentes no cadastro.
    """
    origem: OrigemDoAnuncio | None = None
    """A marca que veio colada ao nome ("fake Bianca" -> `fake`). `None` = ninguem disse."""


@dataclass(frozen=True)
class CadastroDeNomes:
    """Indice em memoria do cadastro (nome verdadeiro + nomes de anuncio).

    Vive por mensagem: e um punhado de linhas (dezenas de modelos) e ler o cadastro fresco a cada
    anuncio e o que faz um apelido recem-cadastrado pelo grupo valer no anuncio seguinte, sem
    invalidacao de cache nenhuma.
    """

    por_nome: dict[str, frozenset[UUID]] = field(default_factory=dict)
    nome_verdadeiro: dict[UUID, str] = field(default_factory=dict)

    @classmethod
    def de_linhas(
        cls, *, modelos: list[tuple[UUID, str]], apelidos: list[tuple[UUID, str]]
    ) -> CadastroDeNomes:
        indice: defaultdict[str, set[UUID]] = defaultdict(set)
        verdadeiros: dict[UUID, str] = {}
        for modelo_id, nome in modelos:
            verdadeiros[modelo_id] = nome
            chave = normalizar(nome)
            if chave:
                indice[chave].add(modelo_id)
        for modelo_id, apelido in apelidos:
            chave = normalizar(apelido)
            if chave:
                indice[chave].add(modelo_id)
        return cls(
            por_nome={chave: frozenset(ids) for chave, ids in indice.items()},
            nome_verdadeiro=verdadeiros,
        )

    def nomes_de(self, modelo_id: UUID) -> frozenset[str]:
        """Todas as formas normalizadas por que ESTA modelo e conhecida (verdadeiro + anuncio).

        O indice e por nome porque o resolver pergunta "de quem e este nome?"; aqui a pergunta e a
        inversa — "este nome e dela?" —, e a resposta tem que incluir os apelidos: o comprovante
        traz o nome civil ("Yasmin Nascimento De Albuquerque") e o cadastro guarda "yasmin".
        """
        return frozenset(nome for nome, ids in self.por_nome.items() if modelo_id in ids)

    def nomeia(self, texto: str, modelo_id: UUID) -> bool:
        """Este texto nomeia ESTA modelo? — verificacao contra UMA pessoa, nunca uma busca.

        E a outra pergunta do modulo sobre nome, e ela e de natureza diferente da que `resolver`
        responde. `resolver` escolhe UMA mulher dentro do cadastro inteiro, e por isso casa
        EXATO: "Alicia" nao pode virar "Alicia Prado" porque a prefixo pode corresponder a
        varias, e errar a mulher e errar o dinheiro dela. Aqui a candidata ja e uma so — ela veio
        do vinculo grupo<->modelo, que e closed-world e nao e palpite — e a unica coisa em jogo e
        se o que o card escreveu **e ela** ou **e outra conversa**. Nao ha ninguem para quem
        errar.

        Por isso a forma curta conta: o telefonista escreve "Yasmin" no card do grupo da "Yasmin
        Nascimento", e esse card CASA com a dona (ticket 19: "o campo, se presente, tem que casar
        com a modelo do grupo"). O criterio e conter: toda palavra do texto tem que ser uma
        palavra de algum nome dela (verdadeiro ou de anuncio). "fran loira" no grupo da Yasmin
        nao tem nenhuma, entao nao a nomeia — e continua sendo a pergunta ensinavel de sempre.

        A direcao e deliberadamente so essa. Um card que diz MAIS do que o cadastro sabe ("Yasmin
        Prado" onde o cadastro tem "Yasmin") nao casa por aqui: a palavra sobrando pode ser o
        sobrenome dela ou o nome de outra mulher, e este metodo nao tem como saber a diferenca.
        """
        alvo = normalizar(separar_origem(texto)[1])
        palavras = alvo.split()
        if not palavras:
            return False
        conhecidas = {palavra for nome in self.nomes_de(modelo_id) for palavra in nome.split()}
        return all(palavra in conhecidas for palavra in palavras)

    def resolver(self, nomes: tuple[str, ...]) -> ResolucaoDeNome:
        """Resolve os tokens de UMA venda (que, neste ticket, e de uma modelo so).

        Os tokens de "X/Y" sao a MESMA mulher, entao a resposta e a INTERSECAO dos candidatos —
        nao a uniao. E o que faz "Perfil bianca/yasmin" continuar resolvendo mesmo quando um dos
        lados e homonimo: "bianca" aponta para uma, "yasmin" para varias, e so uma esta nas duas
        listas. Token que o cadastro nao conhece nao entra na conta (o typo "yamin" nao pode
        zerar a intersecao que "bianca" ja fechou); ele volta em `nomes_nao_resolvidos` para o
        ticket 04 perguntar/cadastrar — sempre SEM a marca de origem (ticket 16), que sai de cada
        token antes da busca e volta em `origem`. E o que faz "fake Bianca" achar a Bianca do
        cadastro em vez de virar um apelido novo com a palavra dentro.
        """
        if not nomes:
            return ResolucaoDeNome(veredito="sem_nome")

        candidatos: set[UUID] | None = None
        desconhecidos: list[str] = []
        limpos: list[str] = []
        origem: OrigemDoAnuncio | None = None
        for token in nomes:
            marca, limpo = separar_origem(token)
            origem = _origem_mais_forte(origem, marca)
            if not limpo:
                # O token era so a marca ("Perfil fake"): a origem foi dita, o nome nao.
                continue
            limpos.append(limpo)
            ids = self.por_nome.get(normalizar(limpo))
            if not ids:
                desconhecidos.append(limpo)
                continue
            candidatos = set(ids) if candidatos is None else candidatos & set(ids)

        if candidatos is None:
            veredito: VereditoDoNome = "desconhecido" if desconhecidos else "sem_nome"
            return ResolucaoDeNome(
                veredito=veredito, nomes_nao_resolvidos=tuple(desconhecidos), origem=origem
            )
        if len(candidatos) != 1:
            # Intersecao vazia = os tokens apontam para mulheres DIFERENTES (grafia "X/Y" usada
            # para duas participantes, ou cadastro errado). Intersecao com varias = homonimo que
            # nenhum token desempata. Nos dois casos a resposta e perguntar, nunca sortear.
            return ResolucaoDeNome(
                veredito="ambiguo", nomes_nao_resolvidos=tuple(limpos), origem=origem
            )

        modelo_id = next(iter(candidatos))
        return ResolucaoDeNome(
            veredito="resolvido",
            modelo_id=modelo_id,
            nome=self.nome_verdadeiro.get(modelo_id),
            nomes_nao_resolvidos=tuple(desconhecidos),
            origem=origem,
        )

    def atribuicao_em_texto(self, texto: str) -> ResolucaoDeNome:
        """A quem esta frase solta ATRIBUI a venda ("é a Duda", "a Yasmin")?

        E o resolver de novo, so que sobre texto livre em vez dos tokens de "Perfil …": e o que
        le a resposta do grupo a pergunta "'fran loira' e quem?". Continua CLOSED-WORLD e
        continua sem palpite — casa nome inteiro do cadastro, e se a frase reconhecer duas
        mulheres o veredito e `ambiguo`.

        Reconhecer o nome nao basta: a frase inteira precisa ser uma ATRIBUICAO. Tirado o nome, o
        que sobra tem que caber em `PALAVRAS_DE_ATRIBUICAO` — "é a Duda" passa, "a Duda tá on"
        nao. A diferenca importa porque desta leitura saem DUAS escritas irreversiveis: a venda
        vai para o extrato de alguem e os nomes perguntados viram Nome de anuncio dela no
        cadastro. Uma modelo citada de passagem no meio de outro assunto nao pode disparar isso —
        e a mesma disciplina de allowlist fechada que `pagamento.py` usa para nao ler "Pix erick"
        como forma de pagamento.
        """
        origem, alvo = separar_origem(normalizar(texto))
        if not alvo:
            return ResolucaoDeNome(veredito="sem_nome", origem=origem)
        encontrados: set[UUID] = set()
        sobra = alvo
        for chave, ids in self.por_nome.items():
            padrao = rf"(?<![a-z0-9]){re.escape(chave)}(?![a-z0-9])"
            if re.search(padrao, alvo):
                encontrados |= set(ids)
                sobra = re.sub(padrao, " ", sobra)
        if not encontrados:
            return ResolucaoDeNome(veredito="sem_nome", origem=origem)
        if len(encontrados) > 1:
            return ResolucaoDeNome(veredito="ambiguo", origem=origem)
        if any(palavra not in PALAVRAS_DE_ATRIBUICAO for palavra in sobra.split()):
            return ResolucaoDeNome(veredito="sem_nome", origem=origem)
        modelo_id = next(iter(encontrados))
        return ResolucaoDeNome(
            veredito="resolvido",
            modelo_id=modelo_id,
            nome=self.nome_verdadeiro.get(modelo_id),
            origem=origem,
        )


def _origem_mais_forte(
    ja_vista: OrigemDoAnuncio | None, nova: OrigemDoAnuncio | None
) -> OrigemDoAnuncio | None:
    """`fake` > `proprio` > nada, na leitura de varios tokens da mesma venda.

    "Perfil fake bianca/yasmin" e um anuncio so: se um dos lados diz `fake`, a venda e do fake —
    somar as duas marcas como se fossem duas vendas e o erro que a metrica nao perdoa.
    """
    if "fake" in (ja_vista, nova):
        return "fake"
    return ja_vista or nova
