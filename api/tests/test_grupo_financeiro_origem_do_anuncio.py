"""Origem do anuncio (proprio x fake) e o Site — a metrica de onde investir (ticket 16).

O dono pediu *"quanto que o anuncio fake esta fazendo e quanto que o anuncio original esta
fazendo"* (spec 0006 §45) e, desde 20/08, tambem por qual **site** a venda entrou (§68). Sao DOIS
campos e nao um: o site e mais fino e "em geral determina" a origem, mas quais sites sao fake nao
esta escrito em lugar nenhum — deduzir um do outro seria fabricar a metrica.

O que estes testes prendem:

* a marca de origem vem **colada ao nome** no texto livre ("fake Bianca" x "perfil Bianca"), e quem
  a separa do nome e o resolver closed-world — e o que faz o backfill de agosto render a metrica;
* separar nao pode virar **cadastrar**: "fake fran loira" ensina "fran loira", e "fake" sozinho nao
  ensina nada. Um Nome de anuncio com a palavra dentro so casaria quando o telefonista a
  repetisse, e a mesma mulher passaria a ter dois apelidos concorrentes (docs/dominio/
  grupo-financeiro.md, _Avoid_);
* origem nao dita fica **nula** — nem o site, nem o rotulo do campo a preenchem por palpite;
* o site em branco nao bloqueia nada, e o site escrito de dois jeitos agrupa num so.

Sem banco de proposito: as migrations da v2 (`origem` e `site` em `vendas_registradas`) ainda nao
foram aplicadas em lugar nenhum. O que as consultas precisam provar aqui e que carregam as guardas
certas (anulada fora, a fatia "nao dito" preservada), nao que o Postgres aceita o comando.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from barra.dominio.grupo_financeiro import repo
from barra.dominio.grupo_financeiro.ficha import (
    FichaLida,
    ler_ficha,
    normalizar_site,
    planejar_ficha,
)
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes, separar_origem

BIANCA = UUID("b1a11ca0-0000-0000-0000-000000000001")
YASMIN = UUID("11a51111-0000-0000-0000-000000000002")
DUDA = UUID("d0da0000-0000-0000-0000-000000000003")
MENSAGEM = UUID("dddddddd-0000-0000-0000-000000000001")
HOJE = date(2026, 8, 20)

CADASTRO = CadastroDeNomes.de_linhas(
    modelos=[(BIANCA, "Bianca"), (YASMIN, "Yasmin"), (DUDA, "Duda")],
    apelidos=[(BIANCA, "bibi"), (YASMIN, "sofia")],
)


# --- a marca colada ao nome ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "origem", "nome"),
    [
        ("fake Bianca", "fake", "Bianca"),
        ("perfil Bianca", "proprio", "Bianca"),
        ("Perfil fake bianca", "fake", "bianca"),  # as duas palavras: `fake` e a deliberada
        ("Bianca", None, "Bianca"),
        ("FAKE Sofia Ruiva", "fake", "Sofia Ruiva"),  # a grafia do nome sobrevive
        ("fake", "fake", ""),  # a marca sozinha nao deixa nome nenhum
        ("", None, ""),
    ],
)
def test_separar_origem_tira_a_marca_e_preserva_o_nome(
    texto: str, origem: str | None, nome: str
) -> None:
    assert separar_origem(texto) == (origem, nome)


def test_resolver_le_a_origem_e_ainda_acha_a_modelo() -> None:
    """ "fake Bianca" e a Bianca do cadastro — a palavra e origem, nao parte do nome."""
    resolvido = CADASTRO.resolver(("fake Bianca",))

    assert resolvido.veredito == "resolvido"
    assert resolvido.modelo_id == BIANCA
    assert resolvido.origem == "fake"


def test_perfil_colado_ao_nome_e_o_anuncio_proprio() -> None:
    resolvido = CADASTRO.resolver(("perfil Bianca",))

    assert resolvido.veredito == "resolvido"
    assert resolvido.modelo_id == BIANCA
    assert resolvido.origem == "proprio"


def test_nome_sem_marca_nenhuma_fica_com_origem_nula() -> None:
    """Origem nao dita nao vira palpite: nulo e resposta legitima."""
    assert CADASTRO.resolver(("Bianca",)).origem is None


def test_marca_num_token_vale_para_a_venda_inteira() -> None:
    """ "Perfil fake bianca/bibi" e UM anuncio: a origem e da venda, nao de cada token."""
    resolvido = CADASTRO.resolver(("fake bianca", "bibi"))

    assert resolvido.veredito == "resolvido"
    assert resolvido.modelo_id == BIANCA
    assert resolvido.origem == "fake"


def test_nome_desconhecido_volta_sem_a_marca() -> None:
    """A pergunta do grupo e "'fran loira' e quem?" — e o que ela ensinar sera "fran loira"."""
    resolvido = CADASTRO.resolver(("fake fran loira",))

    assert resolvido.veredito == "desconhecido"
    assert resolvido.nomes_nao_resolvidos == ("fran loira",)
    assert resolvido.origem == "fake"


def test_marca_sozinha_nao_e_nome_desconhecido() -> None:
    """ "Perfil fake" sem nome nenhum: origem dita, nome nao.

    Se "fake" voltasse como nome nao resolvido, o agente perguntaria "'fake' e quem?" e a resposta
    cadastraria a palavra como apelido de alguem — o Nome de anuncio que o dominio proibe.
    """
    resolvido = CADASTRO.resolver(("fake",))

    assert resolvido.veredito == "sem_nome"
    assert resolvido.nomes_nao_resolvidos == ()
    assert resolvido.origem == "fake"


def test_frase_de_atribuicao_carrega_a_origem() -> None:
    """A resposta do grupo a pergunta minima tambem diz de qual anuncio o cliente veio."""
    assert CADASTRO.atribuicao_em_texto("fake Bianca").modelo_id == BIANCA
    assert CADASTRO.atribuicao_em_texto("fake Bianca").origem == "fake"
    assert CADASTRO.atribuicao_em_texto("perfil Bianca").origem == "proprio"
    assert CADASTRO.atribuicao_em_texto("é a Duda").modelo_id == DUDA
    assert CADASTRO.atribuicao_em_texto("é a Duda").origem is None


def test_marca_de_origem_nao_afrouxa_a_allowlist_de_atribuicao() -> None:
    """Tirar "fake" da frase nao pode transformar conversa em atribuicao (a licao de nomes.py)."""
    assert CADASTRO.atribuicao_em_texto("fake a Duda tá on").veredito == "sem_nome"


# --- o card: dois campos, nunca um ---------------------------------------------------------------

FICHA = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Igor

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: barravips
Origem: ( ) Próprio  (x) Fake
Nome da modelo: Yasmin

🕒 *HORÁRIO*
Data: 22/08
Hora: 19:00
Duração: 1h

💰 *VALORES*
Valor total: R$ 700
Valor desta modelo: R$ 700
"""


def _lida(texto: str) -> FichaLida:
    ficha = ler_ficha(texto, hoje=HOJE)
    assert ficha is not None
    return ficha


def test_card_grava_site_e_origem_como_dois_campos() -> None:
    ficha = _lida(FICHA)

    assert ficha.origem == "fake"
    assert ficha.site == "Barra Vips"


def test_site_em_branco_nao_bloqueia_a_ficha() -> None:
    ficha = _lida(FICHA.replace("Site: barravips", "Site:"))

    assert ficha.site is None
    assert ficha.origem == "fake"
    assert ficha.tem_conteudo


def test_site_nao_deduz_a_origem() -> None:
    """ "o fake so vai ser sites especificos" — mas QUAIS nao esta escrito em lugar nenhum."""
    ficha = _lida(FICHA.replace("Origem: ( ) Próprio  (x) Fake", "Origem: ( ) Próprio  ( ) Fake"))

    assert ficha.site == "Barra Vips"
    assert ficha.origem is None


def test_marca_no_nome_do_anuncio_vale_quando_o_campo_ficou_em_branco() -> None:
    """O card degradado ainda rende a metrica — e o nome guardado sai limpo."""
    ficha = _lida(
        FICHA.replace("Origem: ( ) Próprio  (x) Fake", "Origem: ( ) Próprio  ( ) Fake").replace(
            "Nome do perfil/anúncio: Sofia", "Nome do perfil/anúncio: fake Sofia"
        )
    )

    assert ficha.origem == "fake"
    assert ficha.nome_anuncio == "Sofia"


def test_campo_marcado_vence_a_marca_colada_ao_nome() -> None:
    """O campo e a resposta que o telefonista deu a uma pergunta; a marca e o jeito antigo."""
    ficha = _lida(
        FICHA.replace("Origem: ( ) Próprio  (x) Fake", "Origem: (x) Próprio  ( ) Fake").replace(
            "Nome do perfil/anúncio: Sofia", "Nome do perfil/anúncio: fake Sofia"
        )
    )

    assert ficha.origem == "proprio"


def test_perfil_com_fake_ainda_encontra_a_modelo_no_cadastro() -> None:
    """ "fake Sofia" e a Yasmin (apelido "sofia") — a palavra nao vira nome desconhecido."""
    ficha = _lida(
        FICHA.replace(
            "Nome do perfil/anúncio: Sofia", "Nome do perfil/anúncio: fake Sofia"
        ).replace("Nome da modelo: Yasmin\n", "")
    )
    plano = planejar_ficha(ficha, cadastro=CADASTRO, dona_do_grupo=None)

    assert [p.modelo_id for p in plano.participantes] == [YASMIN]
    assert plano.nomes_desconhecidos == ()


@pytest.mark.parametrize(
    ("escrito", "canonico"),
    [
        ("barravips", "Barra Vips"),
        ("  Barra   Vips  ", "Barra Vips"),
        ("GSEX", "GSEX"),
        ("g sex", "GSEX"),
        ("Viva Local", "Viva Local"),
        ("garota com local", "Garota com Local"),
        ("insta", "Instagram"),
        ("Sexy Vip Girls", "Sexy Vip Girls"),  # site novo entra como veio, sem migration
        ("", None),
        (None, None),
    ],
)
def test_normalizar_site_agrupa_o_conhecido_e_preserva_o_novo(
    escrito: str | None, canonico: str | None
) -> None:
    assert normalizar_site(escrito) == canonico


# --- o SQL: o que a metrica escreve e o que ela le ------------------------------------------------


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Grava (query, params) e devolve as linhas que o teste mandou. Nenhum banco envolvido."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.binds: list[tuple[str, Any]] = []
        self._rows = rows or []

    async def execute(self, query: str, params: Any = None) -> _Cursor:
        self.binds.append((query, params))
        return _Cursor(self._rows)


@pytest.mark.asyncio
async def test_venda_de_texto_livre_grava_origem_e_site_normalizado() -> None:
    conn = FakeConn()

    await repo.registrar_venda(
        conn,  # type: ignore[arg-type]
        modelo_id=BIANCA,
        valor=Decimal("700.00"),
        data=HOJE,
        mensagem_id=MENSAGEM,
        chave_conteudo="chave",
        origem="fake",
        site="barravips",
    )

    query, params = conn.binds[0]
    assert "origem, site" in query
    assert "origem_anuncio_enum" in query
    assert params[-2:] == ("fake", "Barra Vips")


@pytest.mark.asyncio
async def test_venda_sem_origem_dita_grava_nulo() -> None:
    conn = FakeConn()

    await repo.registrar_venda(
        conn,  # type: ignore[arg-type]
        modelo_id=BIANCA,
        valor=Decimal("700.00"),
        data=HOJE,
        mensagem_id=MENSAGEM,
        chave_conteudo="chave",
    )

    _, params = conn.binds[0]
    assert params[-2:] == (None, None)


@pytest.mark.asyncio
async def test_cadastro_aprende_o_nome_sem_a_marca() -> None:
    """A ultima porta antes do INSERT: nenhum caminho cadastra "fake fran loira"."""
    conn = FakeConn([{"nome": "fran loira"}])

    gravados = await repo.gravar_nomes_de_anuncio(conn, BIANCA, ["fake fran loira"])  # type: ignore[arg-type]

    assert gravados == ("fran loira",)
    _, params = conn.binds[0]
    assert params == (BIANCA, "fran loira", "fran loira")


@pytest.mark.asyncio
async def test_a_marca_sozinha_nunca_vira_nome_de_anuncio() -> None:
    conn = FakeConn([{"nome": "fake"}])

    gravados = await repo.gravar_nomes_de_anuncio(conn, BIANCA, ["fake"])  # type: ignore[arg-type]

    assert gravados == ()
    assert conn.binds == []  # nem chegou a tentar o INSERT


@pytest.mark.asyncio
async def test_faturamento_por_origem_mantem_a_fatia_nao_dita() -> None:
    """Esconder o "nao dito" faria o eixo mais preenchido parecer o mais rentavel."""
    conn = FakeConn(
        [
            {"origem": "fake", "vendas": 3, "total": Decimal("2100.00")},
            {"origem": "proprio", "vendas": 2, "total": Decimal("1300.00")},
            {"origem": None, "vendas": 1, "total": Decimal("600.00")},
        ]
    )

    linhas = await repo.faturamento_por_origem(  # type: ignore[arg-type]
        conn, de=date(2026, 8, 1), ate=date(2026, 8, 31)
    )

    assert [(linha.origem, linha.vendas, linha.total) for linha in linhas] == [
        ("fake", 3, Decimal("2100.00")),
        ("proprio", 2, Decimal("1300.00")),
        (None, 1, Decimal("600.00")),
    ]
    query, params = conn.binds[0]
    assert "anulada_em IS NULL" in query
    assert "GROUP BY origem" in query
    assert params == [date(2026, 8, 1), date(2026, 8, 31)]


@pytest.mark.asyncio
async def test_faturamento_por_site_recorta_por_modelo_quando_pedido() -> None:
    conn = FakeConn([{"site": "Barra Vips", "vendas": 4, "total": Decimal("2800.00")}])

    linhas = await repo.faturamento_por_site(  # type: ignore[arg-type]
        conn, de=date(2026, 8, 1), ate=date(2026, 8, 31), modelo_ids=[BIANCA]
    )

    assert [(linha.site, linha.vendas, linha.total) for linha in linhas] == [
        ("Barra Vips", 4, Decimal("2800.00"))
    ]
    query, params = conn.binds[0]
    assert "anulada_em IS NULL" in query
    assert "GROUP BY site" in query
    assert params == [date(2026, 8, 1), date(2026, 8, 31), [BIANCA]]
