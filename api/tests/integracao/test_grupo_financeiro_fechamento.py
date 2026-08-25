"""Fechamento sob comando (spec 0005, ticket 09) — pela PORTA UNICA.

O gesto real e o de 12/08: duas vendas de R$ 600,00 em pix, a gestora confere de cabeca ("confere:
600 pix, 600 pix"), a modelo transfere R$ 1.200,00 e a conta zera. Aqui esse "de cabeca" vira
comando: alguem escreve "fechamento" no grupo e o agente posta o extrato de tres colunas —
vendido, comprovado (pix), em especie — com a diferenca que falta comprovar, as pendencias e as
divergencias.

Tudo entra pela mesma porta que a producao usa (`processar_mensagem_do_grupo`): o comando e uma
mensagem de texto como qualquer outra, e o extrato e o que o grupo LE. Nenhum teste chama o motor
de fechamento por dentro — o que se afirma aqui e o que a gestora veria no WhatsApp.

O leitor de comprovante e stubado (nenhum teste desta casa exige chave); os valores stubados sao
os dos comprovantes reais do export.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
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

from barra.agente_financeiro import (
    ResultadoDaPorta,
    processar_delecao_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.fechamento import TUDO_CONCILIADO
from barra.dominio.grupo_financeiro.modelos import DelecaoNoGrupo, ImagemDoGrupo, MensagemDoGrupo

pytestmark = pytest.mark.needs_db

ANUNCIO = "Atendimento no nosso local \nCliente {cliente} \nPerfil {apelido} \n{valor} 1h"

CHAVE_DA_CASA = "00000000-0000-0000-0000-000000000000"
"""O destino de fechamento da casa, com valor FICTICIO.

A chave viva e o nome civil do titular sao dado operacional e nao moram no repositorio: em prod
a linha entra por INSERT manual do runbook (`infra/runbooks/aplicar-migrations-prod.md`). Aqui o
proprio teste a cadastra (`_cadastrar_a_chave_da_casa`), dentro da transacao que o rollback desfaz.
"""
TITULAR_DA_CASA = "Fulano de Tal"
"""Titular ficticio: o que o OCR le no comprovante de fechamento."""
CHAVE_3RJ = "+55 71 99984 0879"
"""Destino da Cobranca da agencia: comprovante que NAO fecha venda nenhuma (ticket 08)."""

# 13/08 01:00 UTC = 12/08 22:00 em Brasilia — o dia em que o grupo conferiu e pediu o Pix.
NOITE_DE_12_08 = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)


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


# --- o grupo -------------------------------------------------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.enviadas[-1] if self.enviadas else None


class _Olho:
    """Leitor de comprovante stubado: devolve o combinado, sem tocar em provider nenhum."""

    def __init__(self, *leituras: LeituraDoComprovante) -> None:
        self.leituras = list(leituras)

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        return self.leituras.pop(0) if self.leituras else None


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, inicio: datetime) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = inicio


async def _montar_grupo(
    c: AsyncConnection[dict[str, Any]], *, inicio: datetime = NOITE_DE_12_08
) -> _Grupo:
    """Um Grupo financeiro novo (modelo + Nome de anuncio + vinculo closed-world)."""
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (
            modelo_id,
            f"Yasmin {uuid4().hex[:6]}",
            25,
            f"test-wpp-{uuid4().hex}",
            600,
            ["interno"],
            Decimal("40"),
        ),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, apelido, apelido),
    )
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (uuid4(), modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    await _cadastrar_a_chave_da_casa(c)
    return _Grupo(modelo_id, jid, apelido, inicio)


async def _cadastrar_a_chave_da_casa(c: AsyncConnection[dict[str, Any]]) -> None:
    """A lista de destinos legitimos da casa, com a chave ficticia deste arquivo.

    Em producao essa linha entra a mao pelo runbook — chave viva nao mora no repositorio. Aqui ela
    nasce dentro da transacao que o teste desfaz, para que o comprovante do fechamento caia no
    caminho normal (destino conhecido, sem aviso) sem depender de seed aplicado no banco.
    """
    await c.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, titular, descricao)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (chave_normalizada) DO NOTHING
        """,
        (
            CHAVE_DA_CASA,
            normalizar_chave(CHAVE_DA_CASA),
            TITULAR_DA_CASA,
            "Chave de fechamento ficticia, cadastrada pelo teste.",
        ),
    )


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    leitura: LeituraDoComprovante,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(minutes=5),
) -> ResultadoDaPorta:
    """A modelo posta a foto do comprovante (mensagem `imagem`, texto vazio).

    Os bytes variam com o que a foto MOSTRA: dois Pix diferentes sao duas fotos diferentes, e o
    dedup de conteudo (ticket 07) recusaria a segunda se a fixture fosse a mesma para todos.
    """
    grupo.relogio += depois
    foto = f"jpeg-do-export|{leitura.valor}|{leitura.data}".encode()
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(b"\xff\xd8\xff\xe0" + foto, mimetype="image/jpeg"),
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid="5571988887777@s.whatsapp.net",
        recebida_em=grupo.relogio,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


async def _vender(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    *,
    cliente: str,
    valor: str,
    forma: str | None,
    falas: _Falas,
    depois: timedelta = timedelta(hours=2),
) -> UUID:
    """Um anuncio de venda e, quando dita, a forma de pagamento — do jeito que o grupo escreve."""
    lancou = await _dizer(
        c,
        grupo,
        ANUNCIO.format(cliente=cliente, apelido=grupo.apelido, valor=valor),
        falas=falas,
        depois=depois,
    )
    (venda_id,) = lancou.vendas
    if forma is not None:
        pago = await _dizer(
            c,
            grupo,
            "Pix" if forma == "pix" else "Dinheiro",
            falas=falas,
            depois=timedelta(minutes=5),
        )
        assert pago.pagamentos == (venda_id,)
    return venda_id


def _comprovante(valor: str, *, dia: date, chave: str = CHAVE_DA_CASA) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal(valor),
        data=dia,
        pagador="YASMIN NASCIMENTO DE ALBUQUERQUE",
        chave_destino=chave,
        titular_destino=TITULAR_DA_CASA,
    )


# --- 1. o lote real de 12/08: 2x600 pix -> comprovante 1.200 -> extrato zerado --------------------


async def test_lote_de_12_08_fecha_e_o_extrato_zera(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A conta que a Parcerias faz de cabeca, agora sob comando — antes e depois do comprovante."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    lucas = await _vender(conn, grupo, cliente="Lucas", valor="600", forma="pix", falas=falas)

    antes = await _dizer(conn, grupo, "fechamento", falas=falas)

    assert antes.motivo == "fechamento_postado"
    assert antes.extrato is not None
    assert (antes.extrato.vendido, antes.extrato.comprovado) == (
        Decimal("1200.00"),
        Decimal("0.00"),
    )
    assert antes.extrato.em_especie == Decimal("0.00")
    assert antes.extrato.a_comprovar == Decimal("1200.00")
    assert {p.venda_id for p in antes.extrato.pendencias} == {ramon, lucas}
    assert antes.extrato.divergencias == ()
    assert falas.ultima is not None
    assert "Falta comprovar: R$ 1.200,00" in falas.ultima
    assert "Comprovado (pix): R$ 0,00" in falas.ultima

    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("1200.00", dia=date(2026, 8, 12)), falas=falas
    )
    assert set(conferiu.abatidas) == {ramon, lucas}

    depois = await _dizer(conn, grupo, "fechamento", falas=falas)

    # Extrato zerado nao vira relatorio de zeros: vira a frase curta.
    assert depois.extrato is not None
    assert depois.extrato.comprovado == Decimal("1200.00")
    assert depois.extrato.a_comprovar == Decimal("0.00")
    assert depois.extrato.pendencias == ()
    assert depois.extrato.divergencias == ()
    assert depois.extrato.conciliado
    assert falas.ultima == TUDO_CONCILIADO


# --- 2. as tres colunas: pix comprovado, dinheiro em especie, venda sem forma --------------------


async def test_extrato_separa_comprovado_em_especie_e_sem_forma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Venda em dinheiro conta no vendido e NAO e cobrada de comprovante; sem forma e coluna a
    parte — e as tres somam o vendido, senao algum dinheiro sumiu entre as colunas."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    await _postar_comprovante(
        conn, grupo, _comprovante("600.00", dia=date(2026, 8, 12)), falas=falas
    )
    await _vender(conn, grupo, cliente="Gabriel", valor="700", forma="dinheiro", falas=falas)
    sem_forma = await _vender(conn, grupo, cliente="Igor", valor="900", forma=None, falas=falas)

    pediu = await _dizer(conn, grupo, "confere aí", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("2200.00")
    assert extrato.comprovado == Decimal("600.00")
    assert extrato.em_especie == Decimal("700.00")
    assert extrato.a_comprovar == Decimal("0.00")
    assert extrato.sem_forma == Decimal("900.00")
    assert (
        extrato.comprovado + extrato.em_especie + extrato.a_comprovar + extrato.sem_forma
        == extrato.vendido
    )
    # A unica pendencia e a forma de pagamento da venda do Igor: dinheiro nao espera comprovante.
    assert [(p.venda_id, p.tipo) for p in extrato.pendencias] == [(sem_forma, "forma_pagamento")]
    assert falas.ultima is not None
    assert "Em espécie com a modelo: R$ 700,00" in falas.ultima
    # A identidade das quatro parcelas tem que estar VISIVEL no bloco de numeros — e o gestor que
    # confere de cabeca somando as linhas. Enquanto "sem forma" so aparecia la embaixo na linha de
    # pendencia, o bloco nao fechava: R$ 2.200,00 vendidos com R$ 1.300,00 explicados.
    for linha in (
        "Vendido: R$ 2.200,00 (3 vendas)",
        "Comprovado (pix): R$ 600,00",
        "Em espécie com a modelo: R$ 700,00",
        "Falta comprovar: R$ 0,00",
        "Sem forma dita: R$ 900,00",
    ):
        assert linha in falas.ultima
    # E o valor NAO se repete na linha de pendencia (o mesmo numero duas vezes faz procurar
    # diferenca onde nao ha): ali a informacao e quantas vendas esperam resposta.
    assert "⏳ Falta a forma de pagamento de 1 venda." in falas.ultima
    assert falas.ultima.count("R$ 900,00") == 1


# --- 3. o contínuo: comprovante atrasado de dias entra sem nada ter fechado periodo --------------


async def test_comprovante_atrasado_entra_no_saldo_corrente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Nada "fecha" — a venda de semanas atras segue na fila e o Pix de hoje a abate normalmente.

    Entre as duas ha um fechamento pedido no meio: pedir o extrato nao pode carimbar corte
    nenhum, senao o comprovante que chega depois nao teria mais o que abater.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_12_08 - timedelta(days=21))
    falas = _Falas()
    antiga = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)

    meio = await _dizer(conn, grupo, "fechamento", falas=falas, depois=timedelta(days=7))
    assert meio.extrato is not None
    assert meio.extrato.a_comprovar == Decimal("600.00")

    nova = await _vender(
        conn,
        grupo,
        cliente="Lucas",
        valor="600",
        forma="pix",
        falas=falas,
        depois=timedelta(days=14),
    )
    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("600.00", dia=date(2026, 8, 12)), falas=falas
    )

    # FIFO sobre o saldo corrente: quem baixa e a mais ANTIGA, mesmo tendo atravessado um pedido
    # de fechamento e tres semanas.
    assert conferiu.abatidas == (antiga,)

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)
    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("1200.00")
    assert extrato.comprovado == Decimal("600.00")
    assert extrato.a_comprovar == Decimal("600.00")
    assert [p.venda_id for p in extrato.pendencias] == [nova]


# --- 4. sem movimento aberto: resposta curta, nunca extrato vazio --------------------------------


async def test_sem_movimento_a_resposta_e_curta(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Grupo novo, nada registrado: o agente responde uma linha e nao um relatorio de zeros."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    pediu = await _dizer(conn, grupo, "Fechamento?", falas=falas)

    assert pediu.motivo == "fechamento_postado"
    assert pediu.extrato is not None
    assert pediu.extrato.vendas == 0
    assert pediu.extrato.conciliado
    assert falas.enviadas == [TUDO_CONCILIADO]
    assert "Vendido" not in TUDO_CONCILIADO


# --- 5. divergencia: vira pergunta, nunca erro que interrompe ------------------------------------


async def test_comprovante_sem_par_vira_pergunta_no_extrato(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O R$ 385,80 da 3RJ (13/08) nao fecha venda nenhuma: fica retido e o extrato PERGUNTA.

    O extrato sai inteiro do mesmo jeito — as tres colunas continuam corretas com a divergencia
    do lado. Divergencia nao trava.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)

    retido = await _postar_comprovante(
        conn,
        grupo,
        _comprovante("385.80", dia=date(2026, 8, 13), chave=CHAVE_3RJ),
        falas=falas,
    )
    assert retido.motivo == "comprovante_nao_classificado"
    assert retido.abatidas == ()

    pediu = await _dizer(conn, grupo, "extrato", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("600.00")
    assert extrato.a_comprovar == Decimal("600.00")
    assert [p.venda_id for p in extrato.pendencias] == [ramon]
    assert [(d.tipo, d.valor) for d in extrato.divergencias] == [
        ("comprovante_sem_par", Decimal("385.80"))
    ]
    assert falas.ultima is not None
    assert "Falta comprovar: R$ 600,00" in falas.ultima
    assert "❓ Tem um comprovante de R$ 385,80 · 13/08 que não fechou venda nenhuma" in falas.ultima


async def test_comprovante_maior_que_a_fila_pergunta_UMA_vez(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Comprovante maior que a fila: a sobra vira credito da modelo, e SO isso.

    E o gesto mais comum do grupo — a modelo manda um Pix redondo maior que a venda. Ate 14/08 ele
    rendia duas linhas de pergunta sobre os MESMOS R$ 400,00 ("sobrou 400" e "passa o vendido em
    400"), porque a segunda conta comparava o transferido com o vendido total sem descontar a
    sobra que a primeira ja tinha reportado. A segunda pergunta nao tinha resposta possivel: quem
    respondesse a primeira nao mudaria nada nela.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)

    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("1000.00", dia=date(2026, 8, 12)), falas=falas
    )
    assert conferiu.abatidas == (ramon,)

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("600.00")
    assert extrato.comprovado == Decimal("600.00")
    assert extrato.a_comprovar == Decimal("0.00")
    assert extrato.pendencias == ()
    assert [(d.tipo, d.valor) for d in extrato.divergencias] == [
        ("credito_da_modelo", Decimal("400.00"))
    ]
    assert falas.ultima is not None
    assert "Sobrou R$ 400,00 do comprovante" in falas.ultima
    assert falas.ultima.count("R$ 400,00") == 1


async def test_venda_paga_que_vira_dinheiro_deixa_o_pix_orfao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Foi dinheiro, nao pix" DEPOIS do comprovante: o Pix perde o par e o extrato tem que falar.

    O gesto e banal — alguem se confunde na hora de responder "pix ou dinheiro?" e corrige depois.
    Mas o estado que ele deixa e o pior do modulo: a venda sai da coluna `comprovado` e entra em
    "em especie com a modelo", e o R$ 500,00 do Pix, que ja esta na conta da casa, passa a ser
    contado TAMBEM como dinheiro vivo na mao dela. Ate 14/08 o extrato respondia "tudo conciliado"
    ali, porque a unica conta que olhava o transferido o comparava com o vendido — e o vendido nao
    muda quando a forma muda.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"
    lancou = await _dizer(
        conn,
        grupo,
        ANUNCIO.format(cliente="Rafael", apelido=grupo.apelido, valor="500"),
        falas=falas,
        evolution_message_id=anuncio_id,
    )
    (rafael,) = lancou.vendas
    pago = await _dizer(conn, grupo, "Pix", falas=falas)
    assert pago.pagamentos == (rafael,)

    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("500.00", dia=date(2026, 8, 12)), falas=falas
    )
    assert conferiu.abatidas == (rafael,)

    antes = await _dizer(conn, grupo, "fechamento", falas=falas)
    assert antes.extrato is not None
    assert antes.extrato.conciliado is True  # o Pix cobre a venda inteira

    corrigiu = await _dizer(conn, grupo, "foi dinheiro", falas=falas, quoted_message_id=anuncio_id)
    assert corrigiu.correcoes == (rafael,)

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal(
        "500.00"
    )  # o vendido NAO muda — por isso a conta velha nao via
    assert extrato.em_especie == Decimal("500.00")
    assert extrato.comprovado == Decimal("0.00")
    assert extrato.conciliado is False
    assert [(d.tipo, d.valor) for d in extrato.divergencias] == [
        ("pix_sem_venda_em_pix", Decimal("500.00"))
    ]
    assert falas.ultima is not None
    assert "Chegou R$ 500,00 de Pix que nenhuma venda em pix explica" in falas.ultima


async def test_anular_a_venda_ja_paga_deixa_o_pix_orfao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O outro caminho para o mesmo buraco: apagam o anuncio de uma venda que o Pix ja fechou.

    Aqui o extrato zera inteiro — vendido, comprovado, tudo. Sem a pergunta, a modelo teria
    transferido R$ 500,00 que sumiriam da conferencia junto com a venda.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"
    lancou = await _dizer(
        conn,
        grupo,
        ANUNCIO.format(cliente="Rafael", apelido=grupo.apelido, valor="500"),
        falas=falas,
        evolution_message_id=anuncio_id,
    )
    (rafael,) = lancou.vendas
    await _dizer(conn, grupo, "Pix", falas=falas)
    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("500.00", dia=date(2026, 8, 12)), falas=falas
    )
    assert conferiu.abatidas == (rafael,)

    grupo.relogio += timedelta(minutes=1)
    apagou = await processar_delecao_do_grupo(
        conn,
        DelecaoNoGrupo(
            grupo_jid=grupo.jid,
            evolution_message_id=anuncio_id,
            autor_jid="5521999999999@s.whatsapp.net",
            ocorrida_em=grupo.relogio,
        ),
    )
    assert apagou.motivo == "venda_anulada"

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("0.00")
    assert extrato.conciliado is False
    assert [(d.tipo, d.valor) for d in extrato.divergencias] == [
        ("pix_sem_venda_em_pix", Decimal("500.00"))
    ]


async def test_valor_corrigido_para_cima_depois_do_pix_vira_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A venda ja estava conciliada quando alguem corrigiu o valor dela para cima.

    O Pix foi de R$ 600,00 e a venda virou R$ 800,00: a identidade das quatro colunas continua
    fechando (o `comprovado` sobe junto com o `vendido`) e, ate 14/08, o extrato respondia "tudo
    conciliado" com R$ 200,00 que nunca entraram. E a divergencia mais perigosa do modulo porque
    ela se esconde no unico estado que ninguem confere: o que bate.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    anuncio_id = f"3EB0{uuid4().hex[:12]}"
    lancou = await _dizer(
        conn,
        grupo,
        ANUNCIO.format(cliente="Marcos", apelido=grupo.apelido, valor="600"),
        falas=falas,
        evolution_message_id=anuncio_id,
    )
    (marcos,) = lancou.vendas
    pago = await _dizer(conn, grupo, "Pix", falas=falas)
    assert pago.pagamentos == (marcos,)

    conferiu = await _postar_comprovante(
        conn, grupo, _comprovante("600.00", dia=date(2026, 8, 12)), falas=falas
    )
    assert conferiu.abatidas == (marcos,)

    antes = await _dizer(conn, grupo, "fechamento", falas=falas)
    assert antes.extrato is not None
    assert antes.extrato.divergencias == ()  # nada a explicar: o Pix cobre a venda inteira

    corrigiu = await _dizer(
        conn, grupo, "na verdade foi 800", falas=falas, quoted_message_id=anuncio_id
    )
    assert corrigiu.correcoes == (marcos,)

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("800.00")
    assert extrato.comprovado == Decimal("800.00")  # a venda segue com comprovante amarrado
    assert extrato.conciliado is False  # <- o que mudou: o extrato para de mentir
    assert [(d.tipo, d.valor) for d in extrato.divergencias] == [
        ("venda_comprovada_a_menor", Decimal("200.00"))
    ]
    assert falas.ultima is not None
    assert "faltam R$ 200,00 de comprovante" in falas.ultima


# --- 6. o comando nao rouba mensagem que fala de dinheiro ----------------------------------------


async def test_a_conta_feita_na_mao_nao_e_pedido_de_fechamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "confere: 600 pix, 600 pix" e a gestora conferindo, nao um comando — numero desqualifica.

    Se essa mensagem virasse pedido, o agente responderia extrato em cima de uma fala que pode ser
    correcao ou resposta de pergunta minima, e o "600" nunca chegaria a quem esperava por ele.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    antes = len(falas.enviadas)

    conferindo = await _dizer(conn, grupo, "confere: 600 pix, 600 pix", falas=falas)

    assert conferindo.motivo != "fechamento_postado"
    assert conferindo.extrato is None
    assert len(falas.enviadas) == antes  # o agente nao falou


async def test_conversa_com_a_palavra_fechamento_nao_dispara_extrato(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Frase comprida com "fechamento" dentro e conversa sobre fechamento, nao pedido dele."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    falando = await _dizer(
        conn,
        grupo,
        "amanhã eu vejo o fechamento com a menina do financeiro pra bater tudo",
        falas=falas,
    )

    assert falando.motivo == "nao_e_anuncio"
    assert falando.extrato is None
    assert falas.enviadas == []
