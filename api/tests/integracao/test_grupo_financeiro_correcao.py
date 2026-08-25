"""Correcao pelo grupo: quote no recibo, delecao da mensagem-fonte e repost (spec 0005, ticket 05).

As tres portas de correcao que o grupo real usa, todas exercidas pelas PORTAS do modulo
(`processar_mensagem_do_grupo` e `processar_delecao_do_grupo`) — nenhum teste chama funcao
interna, pela mesma razao de sempre (licao do harness fiel: testar por dentro e testar um agente
que nao existe).

A sequencia de 08/08 do export e o roteiro central: a gestora posta o anuncio, ve o recibo,
**apaga** a mensagem e **reposta** a versao corrigida. O que o ticket exige e que isso termine com
UM registro vivo — o corrigido — e com rastro do que morreu.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: o dedup por chave viva, o UNIQUE parcial e o
append-only da auditoria sao garantias do BANCO. Um fake provaria o mock.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_delecao_do_grupo, processar_mensagem_do_grupo
from barra.agente_financeiro.porta import ResultadoDaPorta, delecao_de_evolution
from barra.dominio.grupo_financeiro.modelos import DelecaoNoGrupo, MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import eventos_da_venda
from barra.webhook.parser import extrair_delecao

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

ANUNCIO = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h"
ANUNCIO_CORRIGIDO = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n650 1h"
ANUNCIO_DE_DUAS = (
    "Atendimento externo bar\n"
    "Cliente Igor  e um amigo\n"
    "Perfil bianca/yasmin\n"
    "Perfil Sophia/Julia \n"
    "Atendimento de 2h \n"
    "1300 cada uma \n"
    "2600 no total"
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
    """A Yasmin (dona do grupo) e a Julia, para o recibo de duas linhas."""

    def __init__(self, yasmin: UUID, julia: UUID, jid: str, inicio: datetime) -> None:
        self.yasmin = yasmin
        self.julia = julia
        self.jid = jid
        self.relogio = inicio

    def avancar(self, quanto: timedelta) -> None:
        self.relogio += quanto


async def _montar_casa(c: AsyncConnection[dict[str, Any]]) -> _Casa:
    yasmin = await _seed_modelo(c, "Yasmin")
    await _seed_apelido(c, yasmin, f"bianca{uuid4().hex[:6]}")
    await _seed_apelido(c, yasmin, "bianca")
    julia = await _seed_modelo(c, "Julia")
    await _seed_apelido(c, julia, "sophia")
    return _Casa(yasmin, julia, await _seed_grupo(c, yasmin, "Yasmin/financeiro"), NOITE_DE_07_08)


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
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Alguem fala no grupo; a porta processa. O relogio anda ANTES de cada fala."""
    casa.avancar(depois)
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=casa.jid, texto=texto, recebida_em=casa.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _ecoar_recibo(
    c: AsyncConnection[dict[str, Any]],
    casa: _Casa,
    resultado: ResultadoDaPorta,
    *,
    falas: _Falas,
    citando: str,
) -> str:
    """O recibo volta pelo webhook como mensagem `de_mim` citando o anuncio — como em producao.

    Sem este eco o quote no RECIBO nao teria como ser resolvido: o segundo salto (recibo ->
    anuncio) so existe porque a mensagem do agente esta no log com o `quoted_message_id` dela.
    Devolve o id do recibo, que e o que a gestora cita ao corrigir.
    """
    assert resultado.resposta is not None
    recibo_id = f"3EB0{uuid4().hex[:12]}"
    await _dizer(
        c,
        casa,
        resultado.resposta,
        falas=falas,
        de_mim=True,
        evolution_message_id=recibo_id,
        quoted_message_id=citando,
        depois=timedelta(seconds=2),
    )
    return recibo_id


async def _anunciar(
    c: AsyncConnection[dict[str, Any]],
    casa: _Casa,
    texto: str,
    *,
    falas: _Falas,
) -> tuple[ResultadoDaPorta, str, str]:
    """O anuncio + o eco do recibo que a producao posta CITANDO ele.

    Devolve (resultado, id do anuncio, id do recibo) porque a correcao por quote pode chegar nas
    duas ancoras, e as duas precisam funcionar.
    """
    anuncio_id = f"3EB0{uuid4().hex[:12]}"
    resultado = await _dizer(c, casa, texto, falas=falas, evolution_message_id=anuncio_id)
    recibo_id = await _ecoar_recibo(c, casa, resultado, falas=falas, citando=anuncio_id)
    return resultado, anuncio_id, recibo_id


async def _apagar(
    c: AsyncConnection[dict[str, Any]], casa: _Casa, evolution_message_id: str
) -> ResultadoDaPorta:
    casa.avancar(timedelta(seconds=30))
    return await processar_delecao_do_grupo(
        c,
        DelecaoNoGrupo(
            grupo_jid=casa.jid,
            evolution_message_id=evolution_message_id,
            autor_jid="5521999999999@s.whatsapp.net",
            ocorrida_em=casa.relogio,
        ),
    )


async def _vendas(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, vivas: bool = True
) -> list[dict[str, Any]]:
    cur = await c.execute(
        f"""
        SELECT id, valor, data, cliente_nome, duracao_minutos, forma_pagamento, anulada_em,
               chave_conteudo
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s {"AND anulada_em IS NULL" if vivas else ""}
         ORDER BY created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


# --- 1. quote no recibo corrige a venda ---------------------------------------------------------


async def test_quote_no_recibo_com_valor_novo_corrige_a_venda_e_confirma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "foi 650" respondendo o recibo: a venda muda na hora e o agente ecoa o de→para.

    O eco tem que trazer o valor ANTIGO tambem — sem ele a gestora nao distingue "o agente
    corrigiu o que eu pedi" de "o agente entendeu outra coisa".
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)
    (venda,) = anuncio.vendas

    correcao = await _dizer(conn, casa, "foi 650", falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "correcao_aplicada"
    assert correcao.correcoes == (venda,)
    assert correcao.vendas == ()  # nao nasceu venda nova: a mesma linha mudou
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["id"] == venda
    assert viva["valor"] == Decimal("650.00")
    assert viva["anulada_em"] is None

    assert falas.ultima == correcao.resposta
    assert falas.ultima.startswith("✏️ Corrigi:")
    assert "R$ 700,00 → R$ 650,00" in falas.ultima


async def test_quote_no_anuncio_corrige_o_cliente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "o cliente era Ramon" citando o proprio anuncio — a outra ancora da mesma venda."""
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)

    correcao = await _dizer(
        conn, casa, "o cliente era Ramon", falas=falas, quoted_message_id=anuncio_id
    )

    assert correcao.correcoes == anuncio.vendas
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["cliente_nome"] == "Ramon"
    assert viva["valor"] == Decimal("700.00")  # o que nao foi dito nao muda
    assert "cliente Gabriel → Ramon" in falas.ultima


async def test_correcao_recalcula_a_chave_de_conteudo_e_o_repost_corrigido_nao_duplica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Corrigiu o valor, o dedup passa a vigiar o valor NOVO.

    Sem recalcular a chave, o anuncio ja corrigido repostado nasceria como segunda linha viva —
    o extrato dobraria justamente no gesto que a gestora usa para consertar as coisas.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    _, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)
    await _dizer(conn, casa, "foi 650", falas=falas, quoted_message_id=recibo_id)

    repost = await _dizer(conn, casa, ANUNCIO_CORRIGIDO, falas=falas, depois=timedelta(minutes=2))

    assert repost.vendas == ()
    assert repost.motivo == "venda_duplicada"
    assert len(await _vendas(conn, casa.yasmin)) == 1


async def test_correcao_que_nao_muda_nada_fica_calada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "foi 700" numa venda que ja esta em 700: nao houve evento, entao nao ha o que dizer."""
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)
    faladas = len(falas.enviadas)

    correcao = await _dizer(conn, casa, "foi 700", falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "correcao_sem_efeito"
    assert correcao.resposta is None
    assert len(falas.enviadas) == faladas
    assert await eventos_da_venda(conn, anuncio.vendas[0]) == []


async def test_valor_solto_sem_quote_nao_corrige_venda_nenhuma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O quote e o que diz DE QUAL venda se fala. Sem ele, "650" e so um numero no grupo.

    Este e o teste que impede a correcao de virar um sequestro do "600" que responde a pergunta
    minima do ticket 03 — e de reescrever a venda mais recente por acidente.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas)

    solta = await _dizer(conn, casa, "650", falas=falas)

    assert solta.correcoes == ()
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["valor"] == Decimal("700.00")
    assert await eventos_da_venda(conn, anuncio.vendas[0]) == []


async def test_correcao_de_valor_em_recibo_de_duas_modelos_vale_para_as_duas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "1300 cada uma" corrigido para "650": as duas linhas estavam iguais, as duas mudam.

    Uma so mudando deixaria o recibo dizendo uma coisa e o extrato outra, e ninguem olharia de
    novo — o recibo ja foi conferido.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO_DE_DUAS, falas=falas)
    assert len(anuncio.vendas) == 2

    correcao = await _dizer(conn, casa, "foi 650", falas=falas, quoted_message_id=recibo_id)

    assert len(correcao.correcoes) == 2
    (da_yasmin,) = await _vendas(conn, casa.yasmin)
    (da_julia,) = await _vendas(conn, casa.julia)
    assert da_yasmin["valor"] == Decimal("650.00")
    assert da_julia["valor"] == Decimal("650.00")
    assert da_yasmin["chave_conteudo"] != da_julia["chave_conteudo"]
    assert falas.ultima.startswith("✏️ Corrigi (2 linhas):")


async def test_forma_dita_pela_primeira_vez_e_absorcao_trocar_depois_e_correcao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A fronteira entre o ticket 03 e este: dizer "Pix" no recibo FECHA a Pendencia (nao e
    correcao — nada estava dito); dizer "foi dinheiro" DEPOIS troca o que ja estava dito, e isso
    e correcao, com eco e rastro.

    Sem essa distincao, ou a absorcao vira correcao (e a venda nasce "corrigida" de um campo
    vazio), ou a troca passa calada — e forma de pagamento errada e venda cobrada duas vezes no
    fechamento.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)
    (venda,) = anuncio.vendas

    absorvida = await _dizer(conn, casa, "Pix", falas=falas, quoted_message_id=recibo_id)
    assert absorvida.motivo == "pagamento_absorvido"
    assert absorvida.pagamentos == (venda,)
    assert absorvida.correcoes == ()
    assert await eventos_da_venda(conn, venda) == []

    trocada = await _dizer(conn, casa, "foi dinheiro", falas=falas, quoted_message_id=recibo_id)

    assert trocada.motivo == "correcao_aplicada"
    assert trocada.correcoes == (venda,)
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["forma_pagamento"] == "dinheiro"
    assert "forma de pagamento pix → dinheiro" in falas.ultima
    (evento,) = await eventos_da_venda(conn, venda)
    assert (evento.campo, evento.valor_anterior, evento.valor_novo) == (
        "forma_pagamento",
        "pix",
        "dinheiro",
    )


async def test_anuncio_novo_citando_o_recibo_nao_e_lido_como_correcao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A gestora responde o recibo postando o anuncio inteiro de novo (corrigido).

    Isso e repost, nao correcao: cada linha de uma correcao tem que render um campo, e "Perfil
    bianca/yasmin" nao rende nenhum. Sem essa regra, um anuncio novo reescreveria a venda velha e
    a venda nova nunca nasceria.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)

    repost = await _dizer(conn, casa, ANUNCIO_CORRIGIDO, falas=falas, quoted_message_id=recibo_id)

    assert repost.correcoes == ()
    assert len(repost.vendas) == 1
    valores = {v["valor"] for v in await _vendas(conn, casa.yasmin)}
    assert valores == {Decimal("700.00"), Decimal("650.00")}
    assert await eventos_da_venda(conn, anuncio.vendas[0]) == []


# --- 2. delecao da mensagem-fonte anula o registro ----------------------------------------------


async def test_delecao_do_anuncio_anula_a_venda_com_rastro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagou a mensagem, a venda deixa de valer — mas a linha continua la, marcada.

    Hard delete levaria junto a unica prova de que a venda existiu (e a `mensagem_id` que a
    ancora). Anulada, ela some de tudo que conta dinheiro e continua auditavel.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)
    (venda,) = anuncio.vendas

    delecao = await _apagar(conn, casa, anuncio_id)

    assert delecao.status == "delecao"
    assert delecao.motivo == "venda_anulada"
    assert delecao.anuladas == (venda,)
    assert await _vendas(conn, casa.yasmin) == []
    (linha,) = await _vendas(conn, casa.yasmin, vivas=False)
    assert linha["anulada_em"] is not None

    # O agente nao fala: a delecao e gesto deliberado e o repost fala por ele.
    assert delecao.resposta is None
    assert len(falas.enviadas) == 1  # so o recibo do anuncio


async def test_delecao_reentregue_nao_anula_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O router do numero ProceX entrega o mesmo evento duas vezes (medido no myEYE)."""
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)
    primeira = await _apagar(conn, casa, anuncio_id)
    de_novo = await _apagar(conn, casa, anuncio_id)

    assert primeira.anuladas == anuncio.vendas
    assert de_novo.anuladas == ()
    assert de_novo.motivo == "delecao_sem_venda"
    assert len(await eventos_da_venda(conn, anuncio.vendas[0])) == 1


async def test_delecao_de_mensagem_que_nunca_virou_venda_nao_quebra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagar uma conversa qualquer (ou uma mensagem que o modulo nem conhece) e rotina."""
    casa = await _montar_casa(conn)
    falas = _Falas()
    social_id = f"3EB0{uuid4().hex[:12]}"

    await _dizer(conn, casa, "bom dia gente", falas=falas, evolution_message_id=social_id)

    conhecida = await _apagar(conn, casa, social_id)
    desconhecida = await _apagar(conn, casa, f"3EB0{uuid4().hex[:12]}")

    assert conhecida.motivo == "delecao_sem_venda"
    assert desconhecida.motivo == "delecao_sem_venda"
    assert desconhecida.mensagem_id is None


async def test_delecao_em_grupo_nao_cadastrado_e_ignorada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O numero da ProceX e compartilhado com o myEYE: delecao alheia e o caso NORMAL."""
    resultado = await processar_delecao_do_grupo(
        conn,
        DelecaoNoGrupo(grupo_jid="120363999999999999@g.us", evolution_message_id="3EB0FORA"),
    )

    assert resultado.status == "grupo_nao_cadastrado"
    assert resultado.anuladas == ()


async def test_anuncio_incompleto_apagado_para_de_esperar_resposta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A pergunta minima morre com a mensagem que a motivou.

    Se o anuncio apagado continuasse no contexto, o proximo numero solto do grupo (um valor de
    cobranca, um numero de apartamento) completaria um registro que ninguem mais ve na tela.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    pediu = await _dizer(
        conn,
        casa,
        "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin",
        falas=falas,
        evolution_message_id=anuncio_id,
    )
    assert pediu.motivo == "sem_valor"

    await _apagar(conn, casa, anuncio_id)
    resposta = await _dizer(conn, casa, "700", falas=falas, depois=timedelta(minutes=2))

    assert resposta.vendas == ()
    assert await _vendas(conn, casa.yasmin) == []


# --- 3. apagar + repostar termina com UM registro vivo -------------------------------------------


async def test_apaga_e_reposta_corrigido_deixa_um_registro_vivo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A sequencia real de 08/08 — o gesto com que o grupo corrige hoje.

    Postou 700, apagou, repostou 650: sobra UMA venda viva (a de 650), a de 700 fica anulada com
    rastro, e o total da modelo e 650 — nao 1350, nem zero.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)
    await _apagar(conn, casa, anuncio_id)
    repost = await _dizer(conn, casa, ANUNCIO_CORRIGIDO, falas=falas, depois=timedelta(minutes=1))

    assert len(repost.vendas) == 1
    vivas = await _vendas(conn, casa.yasmin)
    assert len(vivas) == 1
    assert vivas[0]["valor"] == Decimal("650.00")
    assert len(await _vendas(conn, casa.yasmin, vivas=False)) == 2  # a anulada continua la
    assert repost.vendas[0] != anuncio.vendas[0]
    assert falas.ultima.startswith("✅ Registrei:")


async def test_apaga_e_reposta_identico_volta_a_registrar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """As vezes o repost e igualzinho (a gestora reposta por outro motivo).

    O dedup do ticket 04 vale entre linhas VIVAS: se a linha anulada segurasse a chave, a venda
    sumiria do sistema — apagar-e-repostar teria terminado em ZERO registros.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)
    await _apagar(conn, casa, anuncio_id)
    repost = await _dizer(conn, casa, ANUNCIO, falas=falas, depois=timedelta(minutes=1))

    assert len(repost.vendas) == 1
    assert len(await _vendas(conn, casa.yasmin)) == 1


async def test_repost_sem_delecao_continua_caindo_no_dedup(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O contrario do teste acima: sem apagar nada, repostar o mesmo anuncio nao duplica."""
    casa = await _montar_casa(conn)
    falas = _Falas()

    await _dizer(conn, casa, ANUNCIO, falas=falas)
    repost = await _dizer(conn, casa, ANUNCIO, falas=falas, depois=timedelta(minutes=1))

    assert repost.vendas == ()
    assert repost.motivo == "venda_duplicada"
    assert len(await _vendas(conn, casa.yasmin)) == 1


# --- 4. auditoria consultavel --------------------------------------------------------------------


async def test_correcao_e_anulacao_deixam_evento_de_auditoria(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Todo campo corrigido vira uma linha de rastro; a anulacao, uma linha propria.

    E o rastro que responde "por que o total de 07/08 mudou?" depois que a venda ja nao mostra
    mais nenhum dos numeros antigos.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"

    anuncio = await _dizer(conn, casa, ANUNCIO, falas=falas, evolution_message_id=anuncio_id)
    (venda,) = anuncio.vendas
    recibo_id = await _ecoar_recibo(conn, casa, anuncio, falas=falas, citando=anuncio_id)
    correcao = await _dizer(
        conn, casa, "foi 650\no cliente era Ramon", falas=falas, quoted_message_id=recibo_id
    )
    await _apagar(conn, casa, anuncio_id)

    eventos = await eventos_da_venda(conn, venda)

    assert [e.tipo for e in eventos].count("anulacao") == 1
    correcoes = {e.campo: (e.valor_anterior, e.valor_novo) for e in eventos if e.campo}
    assert correcoes["valor"] == ("R$ 700,00", "R$ 650,00")
    assert correcoes["cliente"] == ("Gabriel", "Ramon")
    assert all(e.mensagem_id is not None for e in eventos)
    # A mensagem que causou a correcao e a que o grupo mandou, nao o anuncio.
    assert next(e for e in eventos if e.campo == "valor").mensagem_id == correcao.mensagem_id


# --- 5. o envelope da plataforma ------------------------------------------------------------------


def test_revoke_da_evogo_vira_delecao_da_mensagem_alvo() -> None:
    """O revoke chega como `protocolMessage` dentro de um upsert (o formato da EvoGo em prod).

    O id que interessa e o do ALVO, nunca o do envelope: o envelope e uma mensagem de sistema
    nova, com id proprio, que nunca virou venda nenhuma. Ler o id errado anularia nada e deixaria
    a venda apagada viva no extrato.
    """
    payload = {
        "event": "messages.upsert",
        "instance": "procex",
        "data": {
            "key": {
                "id": "3EB0ENVELOPE",
                "remoteJid": "120363111111111111@g.us",
                "participant": "5521999999999@s.whatsapp.net",
            },
            "message": {"protocolMessage": {"type": "REVOKE", "key": {"id": "3EB0ALVO"}}},
        },
    }

    evento = extrair_delecao(payload)

    assert evento is not None
    assert evento.evolution_message_id == "3EB0ALVO"
    delecao = delecao_de_evolution(evento)
    assert delecao.grupo_jid == "120363111111111111@g.us"
    assert delecao.autor_jid == "5521999999999@s.whatsapp.net"


def test_evento_messages_delete_da_evolution_v2_vira_delecao() -> None:
    payload = {
        "event": "messages.delete",
        "instance": "procex",
        "data": {
            "id": "3EB0ALVO",
            "remoteJid": "120363111111111111@g.us",
            "participant": "5521999999999@s.whatsapp.net",
        },
    }

    evento = extrair_delecao(payload)

    assert evento is not None
    assert evento.evolution_message_id == "3EB0ALVO"


def test_mensagem_comum_e_protocolo_de_edicao_nao_sao_delecao() -> None:
    """Ler edicao de mensagem como delecao anularia venda que ninguem apagou."""
    comum = {
        "event": "messages.upsert",
        "data": {
            "key": {"id": "3EB0X", "remoteJid": "120363111111111111@g.us"},
            "message": {"conversation": "bom dia"},
        },
    }
    edicao = {
        "event": "messages.upsert",
        "data": {
            "key": {"id": "3EB0X", "remoteJid": "120363111111111111@g.us"},
            "message": {"protocolMessage": {"type": "MESSAGE_EDIT", "key": {"id": "3EB0ALVO"}}},
        },
    }

    assert extrair_delecao(comum) is None
    assert extrair_delecao(edicao) is None


# --- 5. a gramatica aberta (14/08): como o grupo escreve de verdade -----------------------------


@pytest.mark.parametrize(
    ("frase", "valor"),
    [
        ("na verdade foi 800", Decimal("800.00")),
        ("Na verdade, foi 800", Decimal("800.00")),
        ("corrigindo: 800", Decimal("800.00")),
        ("opa, foi 800", Decimal("800.00")),
        ("desculpa foi 800", Decimal("800.00")),
        ("foi 800 na verdade", Decimal("800.00")),
    ],
)
async def test_prefixo_de_retificacao_nao_derruba_a_correcao(
    conn: AsyncConnection[dict[str, Any]], frase: str, valor: Decimal
) -> None:
    """Quem corrige pede desculpa antes do dado. Isso nao pode custar a correcao inteira.

    Antes de 14/08 custava: "na verdade" nao rende campo, e uma linha que nao rende campo derruba
    a leitura toda — o agente ficava mudo e a venda seguia com o valor errado, que e o pior
    desfecho possivel para a porta que existe para consertar.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)

    correcao = await _dizer(conn, casa, frase, falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "correcao_aplicada"
    assert correcao.correcoes == anuncio.vendas
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["valor"] == valor
    assert falas.ultima is not None
    assert "R$ 700,00 → R$ 800,00" in falas.ultima


@pytest.mark.parametrize(
    ("frase", "nome"),
    [
        ("era o Caio Silva", "Caio Silva"),
        ("é a Duda", "Duda"),
        ("o nome dele é Ramon", "Ramon"),
        ("na verdade era o Ramon", "Ramon"),
    ],
)
async def test_cliente_sem_a_palavra_cliente_corrige_o_nome(
    conn: AsyncConnection[dict[str, Any]], frase: str, nome: str
) -> None:
    """ "era o Caio Silva" citando o anuncio: o artigo e o gatilho, e ele basta."""
    casa = await _montar_casa(conn)
    falas = _Falas()

    anuncio, _, recibo_id = await _anunciar(conn, casa, ANUNCIO, falas=falas)

    correcao = await _dizer(conn, casa, frase, falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "correcao_aplicada"
    assert correcao.correcoes == anuncio.vendas
    (viva,) = await _vendas(conn, casa.yasmin)
    assert viva["cliente_nome"] == nome
    assert viva["valor"] == Decimal("700.00")  # o que nao foi dito nao muda


@pytest.mark.parametrize(
    "frase",
    [
        "era 1h30",  # duracao, nao um cliente chamado "1h30"
        "era o pix",  # forma de pagamento, nao um cliente chamado "pix"
        "foi 650",  # valor
        "foi dia 07",  # data
        "era o combinado desde ontem amiga",  # conversa: passa do teto de palavras
        "era o combinado",  # conversa curta: tem a forma de "era o Caio", mas nao e nome proprio
        "na verdade",  # so o pedido de desculpa, sem dado nenhum
        "obrigada",
        "ta certo entao",
        "Perfil bianca/yasmin",
    ],
)
async def test_frase_que_nao_dita_nome_nao_vira_cliente(
    conn: AsyncConnection[dict[str, Any]], frase: str
) -> None:
    """O ultimo recurso da linha nao pode virar "tudo e nome de cliente".

    Cada uma destas ou tem leitura propria (que ganha antes) ou nao e correcao nenhuma — e uma
    frase de conversa que reescrevesse o cliente de uma venda seria invisivel: o nome errado nao
    quebra nada, so passa a estar errado.
    """
    casa = await _montar_casa(conn)
    falas = _Falas()

    await _anunciar(conn, casa, ANUNCIO, falas=falas)
    recibo_id = None
    anuncio_id = f"3EB0{uuid4().hex[:12]}"
    await _dizer(conn, casa, ANUNCIO_CORRIGIDO, falas=falas, evolution_message_id=anuncio_id)
    del recibo_id

    correcao = await _dizer(conn, casa, frase, falas=falas, quoted_message_id=anuncio_id)

    nomes = {v["cliente_nome"] for v in await _vendas(conn, casa.yasmin)}
    assert nomes == {"Gabriel"}
    assert frase not in str(correcao.resposta)
