"""Duas modelos, dedup cross-grupo e Nome de anuncio desconhecido (spec 0005, ticket 04).

Os anuncios aqui sao os DE VERDADE, copiados do export "Modelo Yasmin Ruiva/financeiro" com a
grafia intacta (espaco sobrando, barra com espaco, "cada uma" em linha propria):

* **07/08** — "Perfil bianca/yasmin" + "Perfil Sophia/Julia" / "1300 cada uma" / "2600 no total":
  duas mulheres, uma Venda registrada para cada, no valor de cada uma (ADR-0043, decisao 3).
* **10/08** — "Perfil Alicia/ fran loira" + "Perfil bianca/ yasmin amiga" / "1200 1h" / "600 cada
  uma": duas mulheres, e uma delas o cadastro nao conhece. A conhecida registra na hora; pela
  outra o agente pergunta, e a resposta do grupo vira CADASTRO.

Os tres comportamentos do ticket compartilham a mesma engrenagem e por isso vivem no mesmo
arquivo: o plano do anuncio (quem recebe quanto), a chave de conteudo (o mesmo fato nao entra
duas vezes) e o resolver closed-world (que agora aprende).

Tudo entra por `processar_mensagem_do_grupo` — a porta unica. Nenhum teste chama funcao interna:
o desenho contrario induziu 4 bugs falsos no agente de venda (licao do harness fiel, spec 0005
"Testing Decisions"). `needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: dedup e cadastro sao
UNIQUE no banco, e um fake provaria o mock.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_mensagem_do_grupo
from barra.agente_financeiro.porta import ResultadoDaPorta
from barra.agente_financeiro.rotina import cobrar_pendencias_do_grupo
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA
from barra.dominio.grupo_financeiro.repo import buscar_grupo_por_jid

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

ANUNCIO_07_08 = (
    "Atendimento externo bar\n"
    "Rua Miguel y canizares - aleatórios bar \n"
    "Cliente Igor  e um amigo\n"
    "Perfil bianca/yasmin\n"
    "Perfil Sophia/Julia \n"
    "Atendimento de 2h \n"
    "1300 cada uma \n"
    "2600 no total\n"
    "1h no bar \n"
    "1h no hotel"
)
ANUNCIO_10_08 = (
    "Atendimento no nosso local \n"
    "Cliente Tiago \n"
    "Perfil Alicia/ fran loira \n"
    "Perfil bianca/ yasmin amiga \n"
    "1200 1h \n"
    "600 cada uma"
)
ANUNCIO_08_08_SO_O_TOTAL = (
    "Atendimento no nosso local \n"
    "Cliente Gustavo e Diego \n"
    "Perfil sophia/julia \n"
    "Perfil bianca/yamin \n"
    "1300 no total"
)
ANUNCIO_DE_UMA_SO = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h"
ANUNCIO_DUAS_NA_MESMA_LINHA = (
    # 16/08: as duas participantes escritas na MESMA linha "Perfil". A grafia e a de apelido, mas
    # "bianca" e "sophia" sao duas mulheres CADASTRADAS — e o cadastro que desmente a grafia.
    "Atendimento no nosso local \nCliente Denis \nPerfil bianca/ sophia \n1200 1h \n600 cada uma"
)
ANUNCIO_DE_DUAS_COM_UMA_NOMEADA = (
    # Mesma forma, outra substancia: "bianca/yasmin" fecha intersecao numa mulher so. O anuncio
    # afirma duas ("cada uma") e nomeia uma — ninguem registra.
    "Atendimento no nosso local \nCliente Denis \nPerfil bianca/yasmin \n1200 1h \n600 cada uma"
)
ANUNCIO_08_08 = (
    # A PARCEIRA vem primeiro na grafia real de 08/08 — e e isso que faz a venda dela ser a mais
    # antiga da fila (o rateio registra na ordem em que os perfis aparecem). Sem esta ordem, o
    # teste de escopo abaixo passaria mesmo com o bug.
    "Atendimento no nosso local \n"
    "Cliente Gustavo e Diego \n"
    "Perfil sophia/julia \n"
    "Perfil bianca/yamin \n"
    "650 1h cada uma \n"
    "1300 no total"
)

# 08/08 01:09 UTC = 07/08 22:09 em Brasilia: a venda e do dia 07, como a gestora conta.
NOITE_DE_07_08 = datetime(2026, 8, 8, 1, 9, tzinfo=UTC)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


# --- seeds --------------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], nome: str) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], Decimal("40")),
    )
    return modelo_id


async def _seed_apelido(c: AsyncConnection[dict[str, Any]], modelo_id: UUID, nome: str) -> None:
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, nome, nome.strip().lower()),
    )


async def _seed_grupo(c: AsyncConnection[dict[str, Any]], modelo_id: UUID, nome: str) -> str:
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        "INSERT INTO barravips.grupos_financeiros (modelo_id, jid, nome) VALUES (%s, %s, %s)",
        (modelo_id, jid, nome),
    )
    return jid


class _Casa:
    """As duas modelos do anuncio de 07/08, cada uma com o SEU Grupo financeiro.

    Dois grupos e o que torna o dedup cross-grupo testavel de verdade: a mesma venda anunciada no
    grupo da Yasmin e no grupo da Julia e o caso que infla o total quando ninguem deduplica.

    NB: o `barra_test` tem varias "Yasmin" de residuo. E proposital deixar assim — "yasmin"
    sozinho e homonimo e quem desempata e o "bianca" da mesma linha (intersecao dos candidatos),
    nunca um palpite.
    """

    def __init__(
        self, yasmin: UUID, julia: UUID, jid_yasmin: str, jid_julia: str, inicio: datetime
    ) -> None:
        self.yasmin = yasmin
        self.julia = julia
        self.jid_yasmin = jid_yasmin
        self.jid_julia = jid_julia
        self.relogio = inicio

    def avancar(self, quanto: timedelta) -> None:
        self.relogio += quanto


async def _montar_casa(
    c: AsyncConnection[dict[str, Any]], *, inicio: datetime = NOITE_DE_07_08
) -> _Casa:
    yasmin = await _seed_modelo(c, "Yasmin")
    await _seed_apelido(c, yasmin, "bianca")
    julia = await _seed_modelo(c, "Julia")
    await _seed_apelido(c, julia, "sophia")
    return _Casa(
        yasmin,
        julia,
        await _seed_grupo(c, yasmin, "Modelo Yasmin Ruiva/financeiro"),
        await _seed_grupo(c, julia, "Modelo Julia/financeiro"),
        inicio,
    )


# --- a conversa ----------------------------------------------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str:
        assert self.enviadas, "o agente nao falou nada"
        return self.enviadas[-1]


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    casa: _Casa,
    texto: str,
    *,
    falas: _Falas,
    jid: str | None = None,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Alguem fala no grupo; a porta processa. O relogio anda ANTES de cada fala."""
    casa.avancar(depois)
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(
        grupo_jid=jid or casa.jid_yasmin, texto=texto, recebida_em=casa.relogio, **kw
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, valor, data, cliente_nome, local_atendimento, duracao_minutos, mensagem_id,
               chave_conteudo
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s
         ORDER BY created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _apelidos(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> set[str]:
    cur = await c.execute(
        "SELECT nome_normalizado FROM barravips.modelo_nomes_anuncio WHERE modelo_id = %s",
        (modelo_id,),
    )
    return {linha["nome_normalizado"] for linha in await cur.fetchall()}


# --- 1. duas modelos: uma linha por modelo, cada uma no valor dela ------------------------------


async def test_anuncio_de_duas_modelos_vira_uma_venda_para_cada_uma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """07/08: "1300 cada uma / 2600 no total" -> duas linhas de 1300, nao uma de 2600.

    O recibo sai UM so (foi um atendimento so) e diz nome + valor de cada uma: e exatamente o par
    que pode estar trocado, e o recibo e a porta de correcao.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    resultado = await _dizer(conn, casa, ANUNCIO_07_08, falas=falas)

    assert resultado.motivo is None
    assert len(resultado.vendas) == 2

    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    (da_julia,) = await _vendas(conn, casa.julia)
    for venda in (da_yasmin, da_julia):
        assert venda["valor"] == Decimal("1300.00")  # o "cada uma", nunca o total
        assert venda["data"] == date(2026, 8, 7)  # dia BRT da mensagem
        assert venda["cliente_nome"] == "Igor e um amigo"
        assert venda["duracao_minutos"] == 120  # "Atendimento de 2h"
        assert venda["local_atendimento"] == "externo bar"
        assert venda["mensagem_id"] == resultado.mensagem_id
    # Chaves de conteudo distintas: as duas linhas do MESMO anuncio nao podem deduplicar entre si.
    assert da_yasmin["chave_conteudo"] != da_julia["chave_conteudo"]

    assert falas.enviadas == [resultado.resposta]
    recibo = falas.ultima
    assert recibo.startswith("✅ Registrei:")
    assert "Yasmin R$ 1.300,00" in recibo
    assert "Julia R$ 1.300,00" in recibo
    assert "R$ 2.600,00" not in recibo
    assert "Cliente Igor e um amigo" in recibo


async def test_x_barra_y_continua_sendo_uma_modelo_so(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A grafia "bianca/yasmin" e apelido/nome verdadeiro da MESMA mulher.

    Duas participantes aparecem como duas LINHAS "Perfil …" — e a distincao que separa uma venda
    de 700 de duas vendas de 700 que ninguem fez.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    resultado = await _dizer(conn, casa, ANUNCIO_DE_UMA_SO, falas=falas)

    assert len(resultado.vendas) == 1
    assert len(await _vendas(conn, casa.yasmin)) == 1
    assert await _vendas(conn, casa.julia) == []


async def test_duas_cadastradas_na_mesma_linha_registram_as_duas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Perfil bianca/ sophia" + "600 cada uma": a barra aqui separa DUAS mulheres, e nao apelido.

    Quem decide nao e a grafia (o grupo escreve dos dois jeitos) e sim o CADASTRO: "bianca" e
    "sophia" resolvem sozinhas para mulheres diferentes, entao a intersecao vazia nao e duvida —
    e a resposta. Antes disto o anuncio inteiro sumia calado e a casa ficava sem as duas vendas.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    resultado = await _dizer(conn, casa, ANUNCIO_DUAS_NA_MESMA_LINHA, falas=falas)

    assert resultado.motivo is None
    assert len(resultado.vendas) == 2

    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    (da_julia,) = await _vendas(conn, casa.julia)
    for venda in (da_yasmin, da_julia):
        assert venda["valor"] == Decimal("600.00")  # o "cada uma", nunca os 1200 do total
        assert venda["cliente_nome"] == "Denis"
    assert "Yasmin R$ 600,00" in falas.ultima
    assert "Julia R$ 600,00" in falas.ultima


async def test_uma_participante_nomeada_com_cada_uma_nao_registra_ninguem(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A contrapartida: "Perfil bianca/yasmin" + "600 cada uma" e UMA mulher nomeada de duas.

    Registrar a nomeada daria a ela o valor de outra que nunca aparece no sistema. O silencio tem
    motivo visivel (`varias_modelos`) — e o que separa "o agente calou porque nao dava" de "o
    agente calou e ninguem sabe por que".
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    resultado = await _dizer(conn, casa, ANUNCIO_DE_DUAS_COM_UMA_NOMEADA, falas=falas)

    assert resultado.motivo == "varias_modelos"
    assert resultado.vendas == ()
    assert await _vendas(conn, casa.yasmin) == []
    assert await _vendas(conn, casa.julia) == []
    assert falas.enviadas == []


async def test_so_o_total_dito_pergunta_quanto_foi_de_cada_uma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem o "cada uma", dividir o total por duas seria supor rateio igual — e supor e proibido.

    O agente pergunta, e a resposta ("650") registra as duas linhas de uma vez.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    pediu = await _dizer(conn, casa, ANUNCIO_08_08_SO_O_TOTAL, falas=falas)

    assert pediu.motivo == "sem_valor"
    assert pediu.vendas == ()
    assert await _vendas(conn, casa.yasmin) == []
    assert falas.ultima.startswith(PREFIXO_DA_PERGUNTA)
    assert "cada uma" in falas.ultima  # senao a resposta volta como total

    respondeu = await _dizer(conn, casa, "650", falas=falas, depois=timedelta(minutes=3))

    assert len(respondeu.vendas) == 2
    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    (da_julia,) = await _vendas(conn, casa.julia)
    assert da_yasmin["valor"] == Decimal("650.00")
    assert da_julia["valor"] == Decimal("650.00")
    assert da_yasmin["mensagem_id"] == pediu.mensagem_id  # origem = onde o fato foi afirmado


# --- 2. dedup cross-grupo por conteudo ----------------------------------------------------------


async def test_mesmo_anuncio_no_grupo_da_outra_modelo_nao_duplica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A venda casada e anunciada nos DOIS grupos. O total nao pode dobrar por causa disso.

    A mensagem e nova (outro grupo, outro id): quem reconhece o fato repetido e a chave de
    conteudo (data+valor+modelo+cliente), nao o dedup de entrega do ticket 01.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    primeiro = await _dizer(conn, casa, ANUNCIO_07_08, falas=falas)
    assert len(primeiro.vendas) == 2

    repetido = await _dizer(
        conn, casa, ANUNCIO_07_08, falas=falas, jid=casa.jid_julia, depois=timedelta(minutes=4)
    )

    assert repetido.status == "registrada"  # a MENSAGEM entrou no log do outro grupo...
    assert repetido.vendas == ()  # ...e nenhuma linha nova nasceu
    assert repetido.motivo == "venda_duplicada"
    assert len(await _vendas(conn, casa.yasmin)) == 1
    assert len(await _vendas(conn, casa.julia)) == 1

    # E o agente AVISA: quem postou precisa saber que a venda ja esta no sistema (senao reposta
    # de novo) e qual venda foi reconhecida.
    assert falas.ultima == repetido.resposta
    assert falas.ultima.startswith("♻️")
    assert "Yasmin R$ 1.300,00" in falas.ultima
    assert "Julia R$ 1.300,00" in falas.ultima


async def test_repost_do_mesmo_anuncio_no_mesmo_grupo_nao_duplica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagar e repostar e como o grupo corrige hoje (08/08: "Mensagem apagada" + repost).

    O repost tem id novo e passa reto pelo dedup de entrega — quem o segura e o conteudo.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    await _dizer(conn, casa, ANUNCIO_DE_UMA_SO, falas=falas)
    repost = await _dizer(conn, casa, ANUNCIO_DE_UMA_SO, falas=falas, depois=timedelta(minutes=1))

    assert repost.vendas == ()
    assert repost.motivo == "venda_duplicada"
    assert len(await _vendas(conn, casa.yasmin)) == 1


async def test_venda_de_outro_cliente_no_mesmo_dia_e_pelo_mesmo_valor_registra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O dedup e por FATO, nao por semelhanca: cliente diferente e outra venda."""
    casa = await _montar_casa(conn)
    falas = _Falas()

    await _dizer(conn, casa, ANUNCIO_DE_UMA_SO, falas=falas)
    outra = await _dizer(
        conn,
        casa,
        "Atendimento no nosso local \nCliente Ramon \nPerfil bianca/yasmin \n700 1h",
        falas=falas,
        depois=timedelta(hours=2),
    )

    assert len(outra.vendas) == 1
    assert len(await _vendas(conn, casa.yasmin)) == 2


# --- 3. Nome de anuncio desconhecido: perguntar, aprender, nunca perguntar duas vezes -----------


async def test_participante_desconhecida_nao_segura_a_venda_da_conhecida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """10/08: "Perfil Alicia/ fran loira" o cadastro nao conhece; "Perfil bianca/ yasmin amiga",
    sim. A conhecida registra na hora e a pergunta e so pela outra — Pendencia bloqueia a
    conciliacao daquela venda, nunca o registro das demais."""
    casa = await _montar_casa(conn)
    falas = _Falas()

    resultado = await _dizer(conn, casa, ANUNCIO_10_08, falas=falas)

    assert resultado.motivo == "nome_desconhecido"
    assert len(resultado.vendas) == 1
    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    assert da_yasmin["valor"] == Decimal("600.00")  # o "cada uma", nao os 1200 do atendimento
    assert await _vendas(conn, casa.julia) == []  # nem cai numa modelo qualquer

    # UMA mensagem com as duas coisas: o que foi registrado e o unico buraco que sobrou.
    assert falas.enviadas == [resultado.resposta]
    assert "✅ Registrei:" in falas.ultima
    assert "Alicia / fran loira" in falas.ultima
    assert "é quem?" in falas.ultima


async def test_resposta_do_grupo_vira_cadastro_e_destrava_a_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "'Alicia / fran loira' é quem?" -> "é a Duda": a resposta grava os apelidos NOVOS no
    cadastro e a venda que faltava nasce, datada do anuncio.

    E o que mantem o resolver closed-world sem obrigar Fernando a cadastrar apelido por apelido.
    """
    casa = await _montar_casa(conn)
    duda_nome = f"Duda{uuid4().hex[:6]}"
    duda = await _seed_modelo(conn, duda_nome)
    falas = _Falas()

    pediu = await _dizer(conn, casa, ANUNCIO_10_08, falas=falas)
    respondeu = await _dizer(
        conn, casa, f"é a {duda_nome}", falas=falas, depois=timedelta(minutes=2)
    )

    assert len(respondeu.vendas) == 1
    assert respondeu.modelo_id == duda
    (da_duda,) = await _vendas(conn, duda)
    assert da_duda["valor"] == Decimal("600.00")
    assert da_duda["cliente_nome"] == "Tiago"
    assert da_duda["data"] == date(2026, 8, 7)  # dia do ANUNCIO, nao o da resposta
    assert da_duda["mensagem_id"] == pediu.mensagem_id
    # A venda da Yasmin, ja registrada no anuncio, nao e registrada de novo.
    assert len(await _vendas(conn, casa.yasmin)) == 1

    assert await _apelidos(conn, duda) == {"alicia", "fran loira"}
    assert falas.ultima.startswith("✅ Registrei:")
    assert f"{duda_nome} R$ 600,00" in falas.ultima


async def test_nome_aprendido_resolve_sozinho_no_anuncio_seguinte(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Aprender e o que faz a pergunta NAO se repetir: o proximo "fran loira" registra calado."""
    casa = await _montar_casa(conn)
    duda_nome = f"Duda{uuid4().hex[:6]}"
    duda = await _seed_modelo(conn, duda_nome)
    falas = _Falas()

    await _dizer(conn, casa, ANUNCIO_10_08, falas=falas)
    await _dizer(conn, casa, f"é a {duda_nome}", falas=falas, depois=timedelta(minutes=2))

    seguinte = await _dizer(
        conn,
        casa,
        "Atendimento no nosso local \nCliente Ramon \nPerfil fran loira \n800 1h",
        falas=falas,
        depois=timedelta(days=1),
    )

    assert seguinte.motivo is None
    assert len(seguinte.vendas) == 1
    assert "é quem?" not in falas.ultima
    valores = {v["valor"] for v in await _vendas(conn, duda)}
    assert valores == {Decimal("600.00"), Decimal("800.00")}


async def test_nome_desconhecido_nao_e_perguntado_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ninguem respondeu a primeira pergunta e outro anuncio com o mesmo nome chega.

    Perguntar de novo e a metralhadora que o dominio proibe. O agente sabe que ja perguntou
    porque a propria pergunta volta pelo webhook como mensagem `de_mim` e fica no log do grupo —
    estado derivado, como todo o resto do modulo.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    primeiro = await _dizer(conn, casa, ANUNCIO_10_08, falas=falas)
    assert primeiro.resposta is not None
    # O eco `fromMe` da propria pergunta, como a EvoGo entrega em producao.
    await _dizer(
        conn, casa, primeiro.resposta, falas=falas, de_mim=True, depois=timedelta(seconds=5)
    )

    de_novo = await _dizer(
        conn,
        casa,
        "Atendimento no nosso local \nCliente Ramon \nPerfil Alicia/ fran loira \n900 1h",
        falas=falas,
        depois=timedelta(hours=3),
    )

    assert de_novo.motivo == "nome_desconhecido"
    assert de_novo.vendas == ()
    assert de_novo.resposta is None  # calado: a pergunta ja esta no grupo
    assert len(falas.enviadas) == 1  # so a primeira pergunta


async def test_nome_citado_de_passagem_nao_vira_apelido_nem_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "a Duda tá on" nao e uma atribuicao — e conversa com um nome dentro.

    Se bastasse reconhecer o nome, uma modelo citada no meio de outro assunto ganharia a venda de
    outra pessoa E os apelidos perguntados no cadastro dela. Duas escritas irreversiveis por uma
    frase ambigua.
    """
    casa = await _montar_casa(conn)
    duda_nome = f"Duda{uuid4().hex[:6]}"
    duda = await _seed_modelo(conn, duda_nome)
    falas = _Falas()

    await _dizer(conn, casa, ANUNCIO_10_08, falas=falas)
    solta = await _dizer(
        conn, casa, f"a {duda_nome} tá on", falas=falas, depois=timedelta(minutes=5)
    )

    assert solta.vendas == ()
    assert await _vendas(conn, duda) == []
    assert await _apelidos(conn, duda) == set()


async def test_resposta_de_pagamento_nao_atinge_a_venda_da_parceira(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """No grupo da Yasmin, "Pix" so pode escrever forma em venda DA YASMIN.

    Regressao do replay do export (14/08): o anuncio de duas modelos e postado no grupo de UMA
    delas, entao a venda da parceira nasce ancorada aqui. Enquanto a fila de vendas abertas era do
    GRUPO, a venda mais antiga da fila era a da Julia — e a resposta da Yasmin escrevia a forma na
    venda da outra, o erro que nunca mais e descoberto (a venda sai da fila e ninguem a cobra de
    novo).
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    await _dizer(conn, casa, ANUNCIO_08_08, falas=falas)

    pago = await _dizer(conn, casa, "Pix", falas=falas, depois=timedelta(hours=2))

    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    (da_julia,) = await _vendas(conn, casa.julia)
    assert pago.pagamentos == (da_yasmin["id"],)
    assert da_julia["id"] not in pago.pagamentos
    cur = await conn.execute(
        "SELECT forma_pagamento FROM barravips.vendas_registradas WHERE id = %s", (da_julia["id"],)
    )
    linha = await cur.fetchone()
    assert linha is not None and linha["forma_pagamento"] is None


async def test_cobranca_da_manha_no_grupo_da_modelo_nao_cobra_a_venda_da_parceira(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A cobranca consolidada e a fala inteira do agente naquela manha — e ela e sobre UMA modelo.

    Sem isto, a Yasmin recebia duas linhas identicas ("Cliente Gustavo e Diego · R$ 650,00"),
    uma delas sobre a venda da Julia, enquanto o saldo logo abaixo so contava as dela. Duas
    metades da mesma mensagem discordando sobre de quem e a conta.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    await _dizer(conn, casa, ANUNCIO_08_08, falas=falas)
    grupo = await buscar_grupo_por_jid(conn, casa.jid_yasmin)
    assert grupo is not None

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo, agora=casa.relogio + timedelta(days=1), enviar=falas
    )

    assert rotina.fala is not None
    assert rotina.fala.count("Cliente Gustavo e Diego") == 1
    assert {p.venda_id for p in rotina.pendencias} == {
        v["id"] for v in await _vendas(conn, casa.yasmin)
    }
