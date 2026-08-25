"""Painel P0 da segunda fonte de receita (spec 0005, ticket 11; ADR-0043) — pela API real.

O que este arquivo prova, sempre do jeito que o operador ve (HTTP autenticado do painel):

1. A receita do Modulo Financeiro soma as **duas fontes** — projecao de atendimentos `Fechado`
   (ADR-0011) + Vendas registradas — sem dobrar nada; e com `atendimentos` vazio, que e o mundo de
   producao hoje, o total e exatamente o que a operacao anunciou nos Grupos financeiros.
2. A lista de Vendas registradas filtra por modelo e mostra estado de conciliacao, Pendencias e
   anuladas (estas so quando pedidas — o default e a operacao viva).
3. Flag de **chave Pix desconhecida** (da venda) e **divergencia de fechamento** (da modelo) sao
   duas coisas distintas e aparecem em lugares distintos da resposta.
4. Nada da lista carrega Dado cadastral da modelo (endereco operacional, chave Pix dela), e a
   rota inteira e do painel: sem token nao ha lista, e papel != fernando tambem nao ve.

**O dado deste arquivo nasce sempre pela PORTA UNICA** (`processar_mensagem_do_grupo`): o painel so
e prova de alguma coisa se o que ele mostra veio do mesmo caminho que a producao percorre. Nenhum
INSERT direto em `vendas_registradas` — o unico SQL de fixture aqui e o cadastro (modelo, apelido,
vinculo do grupo) e o Atendimento `Fechado` da PRIMEIRA fonte, que nasce em outro modulo.

O leitor de comprovante e stubado (nenhum teste desta casa exige chave de provider). `needs_db`
com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import (
    ResultadoDaPorta,
    processar_delecao_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.api.deps import get_conn
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.modelos import (
    DelecaoNoGrupo,
    ImagemDoGrupo,
    MensagemDoGrupo,
)
from barra.main import app

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
"""Destino da Cobranca da agencia: fora da lista da casa."""

APARTAMENTO = "Torre 2 Apt 2706"
"""Dado cadastral real do export (09/08). Painel-only por outro caminho (ticket 12): a linha de
uma venda nunca pode carrega-lo."""

# 13/08 01:00 UTC = 12/08 22:00 em Brasilia — a noite em que o grupo conferiu e pediu o Pix.
NOITE_DE_12_08 = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
DIA_DAS_VENDAS = date(2026, 8, 12)


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


# --- o painel (HTTP real, na transacao do teste) ------------------------------------------------


def _token(papel: str = "fernando") -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:{papel}:true"}


@asynccontextmanager
async def _painel(c: AsyncConnection[dict[str, Any]]) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP do painel amarrado a TRANSACAO do teste.

    Sem lifespan de proposito: `app.state.settings` ja existe no build e `db_pool` ausente faz a
    autenticacao cair no token de teste. O `get_conn` sobreposto entrega a mesma conexao onde a
    porta acabou de escrever — e o ROLLBACK no fim leva tudo junto.
    """

    async def _mesma_conexao() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield c

    app.dependency_overrides[get_conn] = _mesma_conexao
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://painel") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_conn, None)


def _periodo_das_vendas(**extra: Any) -> dict[str, Any]:
    """Janela custom fechada em cima do dia do export — imune a residuo de outra data no banco."""
    return {
        "periodo": "custom",
        "de": DIA_DAS_VENDAS.isoformat(),
        "ate": DIA_DAS_VENDAS.isoformat(),
        **extra,
    }


# --- o grupo (identico ao dos tickets 09/12: nada fala com a Evolution) -------------------------


class _Falas:
    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)


class _Olho:
    """Leitor de comprovante stubado: devolve o combinado, sem tocar em provider nenhum."""

    def __init__(self, *leituras: LeituraDoComprovante) -> None:
        self.leituras = list(leituras)

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        return self.leituras.pop(0) if self.leituras else None


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, numero: str) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.numero = numero
        self.jid_da_modelo = f"{numero}@s.whatsapp.net"
        self.relogio = NOITE_DE_12_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]]) -> _Grupo:
    """Uma modelo nova, o Nome de anuncio dela e o vinculo closed-world do Grupo financeiro."""
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    numero = f"5511{uuid4().int % 1_000_000_000:09d}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, f"Yasmin {uuid4().hex[:6]}", 25, numero, 600, ["interno"], Decimal("40")),
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
    return _Grupo(modelo_id, jid, apelido, numero)


async def _cadastrar_a_chave_da_casa(c: AsyncConnection[dict[str, Any]]) -> None:
    """A lista de destinos legitimos da casa, com a chave ficticia deste arquivo.

    Em producao essa linha entra a mao pelo runbook — chave viva nao mora no repositorio. Aqui ela
    nasce dentro da transacao que o teste desfaz, para que a flag `chave_pix_desconhecida` do
    painel tenha contra o que comparar sem depender de seed aplicado no banco.
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


async def _vender(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    *,
    cliente: str,
    valor: str,
    forma: str | None,
    falas: _Falas,
    depois: timedelta = timedelta(minutes=20),
) -> UUID:
    """Um anuncio de venda e, quando dita, a forma de pagamento — na grafia do grupo."""
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


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    leitura: LeituraDoComprovante,
    *,
    falas: _Falas,
) -> ResultadoDaPorta:
    """A modelo posta a foto do comprovante.

    Os bytes variam com o que a foto MOSTRA: dois Pix diferentes sao duas fotos diferentes, e o
    dedup de conteudo do ticket 07 (mesma imagem nao conta duas vezes) recusaria a segunda se
    todos os comprovantes do teste compartilhassem a mesma fixture.
    """
    grupo.relogio += timedelta(minutes=5)
    foto = f"jpeg-do-export|{leitura.valor}|{leitura.chave_destino}".encode()
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(b"\xff\xd8\xff\xe0" + foto, mimetype="image/jpeg"),
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid=grupo.jid_da_modelo,
        recebida_em=grupo.relogio,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


def _comprovante(valor: str, *, chave: str = CHAVE_DA_CASA) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal(valor),
        data=DIA_DAS_VENDAS,
        pagador="YASMIN NASCIMENTO DE ALBUQUERQUE",
        chave_destino=chave,
        titular_destino=TITULAR_DA_CASA,
    )


# --- a PRIMEIRA fonte: um Atendimento `Fechado` de verdade --------------------------------------


async def _atendimento_fechado(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, valor: Decimal
) -> None:
    """A receita do ADR-0011: `Fechado` + evento `fechado_registrado` (a ancora do regime caixa).

    SQL direto porque esta fonte nasce no ciclo comercial da IA de venda, que e outro modulo — o
    ponto do teste e que as duas fontes somam, nao como a primeira e escrita.
    """
    cliente_id, conversa_id, atendimento_id = (uuid4() for _ in range(3))
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, ia_pausada,
             fonte_decisao_ultima_transicao, valor_final)
        VALUES (%s, %s, %s, %s, 'Fechado'::barravips.estado_atendimento_enum, false,
                'extracao_ia', %s)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, valor),
    )
    await c.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, created_at)
        VALUES (%s, 'fechado_registrado', 'agente', 'IA', %s)
        """,
        (atendimento_id, NOITE_DE_12_08),
    )


# --- 1. receita de duas fontes ------------------------------------------------------------------


async def test_receita_soma_as_duas_fontes_sem_dobrar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesma modelo, mesmo dia, duas fontes: cada uma conta UMA vez e o total e a soma.

    As duas sao disjuntas por construcao — o Grupo financeiro nunca fabrica Atendimento nem
    Cliente (ADR-0043) — entao nao ha o que deduplicar hoje. A projecao de atendimentos continua
    intacta no bloco `resumo`: e ela que sustenta repasse e liquido, e a Venda registrada nao tem
    snapshot de repasse nenhum para entrar la.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _atendimento_fechado(conn, grupo.modelo_id, valor=Decimal("500.00"))
    await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    await _vender(conn, grupo, cliente="Lucas", valor="700", forma="dinheiro", falas=falas)

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    assert resp.status_code == 200, resp.text
    fontes = resp.json()["receita_das_duas_fontes"]
    assert fontes["atendimentos_fechados_brl"] == 500.0
    assert fontes["atendimentos_fechados_total"] == 1
    assert fontes["vendas_registradas_brl"] == 1300.0
    assert fontes["vendas_registradas_total"] == 2
    assert fontes["total_brl"] == 1800.0
    # A projecao de sempre nao foi contaminada pela segunda fonte.
    assert resp.json()["resumo"]["valor_bruto_brl"] == 500.0


async def test_com_atendimentos_vazio_a_receita_e_so_a_venda_registrada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O mundo de producao hoje: a IA de venda nao estreou, `atendimentos` esta vazio.

    Sem a segunda fonte o painel mostraria R$ 0,00 com o grupo faturando todo dia — que e
    literalmente o problema que o ADR-0043 existe para resolver.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Igor", valor="1300", forma=None, falas=falas)

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    fontes = resp.json()["receita_das_duas_fontes"]
    assert fontes["atendimentos_fechados_brl"] == 0.0
    assert fontes["atendimentos_fechados_total"] == 0
    assert fontes["total_brl"] == 1300.0 == fontes["vendas_registradas_brl"]


async def test_repost_e_anulacao_nao_inflam_a_receita(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Os dois jeitos de o mesmo dinheiro aparecer duas vezes — e nenhum aparece.

    O repost identico cai no dedup de conteudo (ticket 04) e a venda anulada some da receita
    (ticket 05), continuando visivel so para quem pede o rastro.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    texto = ANUNCIO.format(cliente="Gabriel", apelido=grupo.apelido, valor="700")
    primeiro = await _dizer(conn, grupo, texto, falas=falas)
    (venda_id,) = primeiro.vendas
    repost = await _dizer(conn, grupo, texto, falas=falas, depois=timedelta(minutes=1))
    assert repost.vendas == ()  # dedup por conteudo: o mesmo anuncio nao vira duas linhas

    async with _painel(conn) as client:
        antes = await client.get(
            "/v1/financeiro",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )
        assert antes.json()["receita_das_duas_fontes"]["vendas_registradas_brl"] == 700.0
        assert antes.json()["receita_das_duas_fontes"]["vendas_registradas_total"] == 1

    # O gesto real de correcao do grupo: apagar a mensagem que anunciou.
    apagou = await _apagar_anuncio(conn, grupo, texto)
    assert apagou.anuladas == (venda_id,)

    async with _painel(conn) as client:
        depois = await client.get(
            "/v1/financeiro",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )
        lista = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )
        com_rastro = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id), incluir_anuladas="true"),
            headers=_token(),
        )

    assert depois.json()["receita_das_duas_fontes"]["vendas_registradas_brl"] == 0.0
    assert lista.json()["items"] == []
    (anulada,) = com_rastro.json()["items"]
    assert anulada["id"] == str(venda_id)
    assert anulada["conciliacao"] == "anulada"
    assert anulada["anulada_em"] is not None
    assert anulada["pendencias"] == []  # venda apagada nao cobra nada de ninguem


async def _apagar_anuncio(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, texto: str
) -> ResultadoDaPorta:
    """Apaga a mensagem-fonte do anuncio (o gesto real de correcao do grupo)."""
    cur = await c.execute(
        """
        SELECT m.evolution_message_id
          FROM barravips.grupo_financeiro_mensagens m
          JOIN barravips.grupos_financeiros g ON g.id = m.grupo_id
         WHERE g.jid = %s AND m.texto = %s
         ORDER BY m.recebida_em
         LIMIT 1
        """,
        (grupo.jid, texto),
    )
    row = await cur.fetchone()
    assert row is not None
    return await processar_delecao_do_grupo(
        c,
        DelecaoNoGrupo(grupo_jid=grupo.jid, evolution_message_id=row["evolution_message_id"]),
    )


# --- 2. a lista: filtro por modelo, estado de conciliacao e pendencias --------------------------


async def test_lista_mostra_conciliacao_e_pendencias_e_filtra_por_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Uma linha por venda, com o pe em que ela esta — e so as da modelo pedida.

    Os quatro pes possiveis aparecem juntos porque e assim que o grupo vive: o anuncio precede o
    pagamento, o dinheiro fica em especie e o pix espera comprovante.
    """
    grupo = await _montar_grupo(conn)
    outra = await _montar_grupo(conn)
    falas = _Falas()
    sem_forma = await _vender(conn, grupo, cliente="Igor", valor="900", forma=None, falas=falas)
    especie = await _vender(
        conn, grupo, cliente="Gabriel", valor="700", forma="dinheiro", falas=falas
    )
    pix_aberta = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    await _vender(conn, outra, cliente="Cliente da outra", valor="500", forma="pix", falas=falas)

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    assert resp.status_code == 200, resp.text
    itens = {UUID(i["id"]): i for i in resp.json()["items"]}
    assert set(itens) == {sem_forma, especie, pix_aberta}  # a venda da outra modelo ficou fora
    assert itens[sem_forma]["conciliacao"] == "aguardando_forma"
    assert itens[sem_forma]["pendencias"] == ["forma_pagamento"]
    assert itens[sem_forma]["forma_pagamento"] is None
    assert itens[especie]["conciliacao"] == "em_especie"
    assert itens[especie]["pendencias"] == []  # dinheiro vivo nao espera comprovante
    assert itens[pix_aberta]["conciliacao"] == "aguardando_comprovante"
    assert itens[pix_aberta]["pendencias"] == ["comprovante"]
    # O que a linha mostra do fato: cliente e TEXTO LIVRE, nunca um `clientes.id` (ADR-0043).
    assert itens[especie]["cliente_nome"].lower() == "gabriel"
    assert itens[especie]["modelo_nome"]
    assert float(itens[especie]["valor"]) == 700.0
    assert "cliente_id" not in itens[especie]


async def test_venda_com_comprovante_aparece_conciliada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O lote real de 12/08: 600 + 600 em pix, comprovante de 1.200 — as duas fecham."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    lucas = await _vender(conn, grupo, cliente="Lucas", valor="600", forma="pix", falas=falas)
    conferiu = await _postar_comprovante(conn, grupo, _comprovante("1200.00"), falas=falas)
    assert set(conferiu.abatidas) == {ramon, lucas}

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    corpo = resp.json()
    assert [i["conciliacao"] for i in corpo["items"]] == ["conciliada", "conciliada"]
    assert all(i["pendencias"] == [] for i in corpo["items"])
    assert all(i["comprovante_id"] == str(conferiu.comprovante_id) for i in corpo["items"])
    assert all(i["chave_pix_desconhecida"] is False for i in corpo["items"])
    assert corpo["divergencias"] == []


# --- 3. as duas flags, em lugares distintos -----------------------------------------------------


async def test_chave_desconhecida_e_divergencia_sao_flags_distintas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Chave desconhecida e da VENDA (que Pix a fechou); divergencia e da MODELO (a conferencia).

    Aqui as duas coexistem: o comprovante de R$ 600,00 fecha a venda do Ramon mas foi para a chave
    da 3RJ, e o de R$ 385,80 nao fecha venda nenhuma. Nenhuma das duas trava a lista — e uma nao
    pode se disfarcar da outra, senao o operador iria conferir o destino errado.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    await _postar_comprovante(conn, grupo, _comprovante("600.00", chave=CHAVE_3RJ), falas=falas)
    retido = await _postar_comprovante(
        conn, grupo, _comprovante("385.80", chave=CHAVE_3RJ), falas=falas
    )
    assert retido.motivo == "comprovante_nao_classificado"

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    corpo = resp.json()
    (linha,) = corpo["items"]
    assert linha["id"] == str(ramon)
    assert linha["conciliacao"] == "conciliada"  # chave desconhecida sinaliza, nunca trava
    assert linha["chave_pix_desconhecida"] is True
    assert linha["chave_pix_destino"] == CHAVE_3RJ  # a vista, para o humano comparar
    # UMA divergencia, com o valor a vista: o comprovante que nao fechou venda nenhuma. Ele NAO
    # aparece tambem como "comprovado acima do vendido" — o retido fica fora do total transferido
    # (fechamento.py::_divergencias), senao o mesmo R$ 385,80 divergiria duas vezes e o painel
    # faria duas perguntas sobre um Pix so, a segunda sem resposta possivel.
    por_tipo = {d["tipo"]: d for d in corpo["divergencias"]}
    assert set(por_tipo) == {"comprovante_sem_par"}
    sem_par = por_tipo["comprovante_sem_par"]
    assert float(sem_par["valor"]) == 385.80
    assert sem_par["modelo_id"] == str(grupo.modelo_id)
    assert sem_par["modelo_nome"]
    assert sem_par["comprovante_id"] == str(retido.comprovante_id)
    # As duas moram em lugares diferentes da resposta: a flag na linha, a divergencia no bloco.
    assert "tipo" not in linha and "chave_pix_desconhecida" not in sem_par


# --- 4. painel-only -----------------------------------------------------------------------------


async def test_a_lista_nao_carrega_dado_cadastral_da_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A modelo dita o apartamento e a chave Pix dela no grupo (ticket 12) e a lista nao os ve.

    Aquele dado e painel-only pelo contexto DA MODELO, nao pela linha de uma venda: vaza-lo aqui
    o colocaria numa resposta que existe para auditar dinheiro, e é a resposta que a interface
    espalha por tela, export e URL.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    anotou = await _dizer(
        conn, grupo, APARTAMENTO, falas=falas, autor_jid=grupo.jid_da_modelo, autor_nome="Yasmin"
    )
    assert anotou.cadastro is not None  # o dado FOI aprendido — o teste nao e sobre nao aprender

    async with _painel(conn) as client:
        resp = await client.get(
            "/v1/financeiro/vendas-registradas",
            params=_periodo_das_vendas(modelo_id=str(grupo.modelo_id)),
            headers=_token(),
        )

    assert APARTAMENTO not in resp.text
    assert "endereco_operacional" not in resp.text
    assert 'chave_pix"' not in resp.text  # `chave_pix_destino`/`_desconhecida` sim; a dela nao


async def test_a_lista_e_do_painel_e_de_mais_ninguem(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem token nao ha lista; com papel que nao e o do operador, tambem nao."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)

    async with _painel(conn) as client:
        anonimo = await client.get("/v1/financeiro/vendas-registradas")
        outro_papel = await client.get(
            "/v1/financeiro/vendas-registradas", headers=_token(papel="vendedor")
        )

    assert anonimo.status_code == 401
    assert outro_papel.status_code == 403
