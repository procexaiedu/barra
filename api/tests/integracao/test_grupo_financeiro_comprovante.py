"""Comprovante de fechamento por OCR (spec 0005, ticket 07) — pela PORTA UNICA.

O gesto real: em 12/08 a gestora confere de cabeca ("600 pix / 600 pix"), pede a transferencia
("Pode enviar nesse pix") e a modelo posta a foto do comprovante de R$ 1.200,00. No dia seguinte
ela posta outro, de R$ 385,80, que **nao e** fechamento de venda nenhuma (e o pagamento da
Cobranca da agencia — ticket 08). Os dois entram por aqui como imagem e saem como efeito
observavel: vendas abatidas, comprovante retido, aviso ao gestor.

As duas imagens sao JPEGs **sinteticos** (`tests/fixtures/grupo_financeiro/`, ver o README de la:
comprovante real do export carrega PII de terceiro e nao entra no repo). O que e stubado e so a
ida ao provider — nenhum teste desta casa pode exigir chave —, e o stub devolve a leitura que o
roteiro pede. Os bytes atravessam a porta assim mesmo: e por eles que passa o transporte e a
deteccao de mime, e a contagem do stub e o que prova quantas vezes a casa pagaria OCR.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import (
    ResultadoDaPorta,
    processar_delecao_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.dominio.grupo_financeiro.comprovante import (
    PEDIDO_DE_REENVIO,
    LeituraDoComprovante,
    normalizar_chave,
)
from barra.dominio.grupo_financeiro.modelos import (
    DelecaoNoGrupo,
    ImagemDoGrupo,
    MensagemDoGrupo,
)
from barra.dominio.grupo_financeiro.pendencia import Pendencia

pytestmark = pytest.mark.needs_db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "grupo_financeiro"

# Os dois comprovantes Bradesco do export, com o que o OCR le neles.
IMAGEM_1200 = (FIXTURES / "comprovante_1200_fechamento.jpg").read_bytes()
IMAGEM_385 = (FIXTURES / "comprovante_385_80_cobranca_3rj.jpg").read_bytes()

CHAVE_DA_CASA = "00000000-0000-0000-0000-000000000000"
"""O destino de fechamento da casa, com valor FICTICIO.

A chave viva e o nome civil do titular sao dado operacional e nao moram no repositorio: em prod
essa linha entra por INSERT manual do runbook (`infra/runbooks/aplicar-migrations-prod.md`). Aqui
o proprio teste cadastra a chave que ele mesmo inventou (`_cadastrar_a_chave_da_casa`), dentro da
transacao que o rollback desfaz — o comportamento coberto e o mesmo, e nao ha seed a depender.
"""
TITULAR_DA_CASA = "Fulano de Tal"
"""Titular ficticio: o que o OCR le no comprovante e o que a lista da casa guarda."""
CHAVE_3RJ = "+55 71 99984 0879"
"""Destino da Cobranca da agencia. NAO e chave de fechamento: quem a cadastra e o ticket 08."""

LEITURA_1200 = LeituraDoComprovante(
    e_comprovante=True,
    legivel=True,
    valor=Decimal("1200.00"),
    data=date(2026, 8, 12),
    pagador="YASMIN NASCIMENTO DE ALBUQUERQUE",
    chave_destino=CHAVE_DA_CASA,
    titular_destino=TITULAR_DA_CASA,
)
LEITURA_385 = LeituraDoComprovante(
    e_comprovante=True,
    legivel=True,
    valor=Decimal("385.80"),
    data=date(2026, 8, 13),
    pagador="YASMIN NASCIMENTO DE ALBUQUERQUE",
    chave_destino=CHAVE_3RJ,
    titular_destino="3RJ PRODUCAO E SERVICOS ADMINISTRATIVOS",
)

ANUNCIO = "Atendimento no nosso local \nCliente {cliente} \nPerfil {apelido} \n600 1h"

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
    """Leitor de comprovante stubado: devolve o combinado e conta o que leu.

    A contagem e metade do teste — ela prova o que NAO custa OCR (eco do proprio agente, segunda
    entrega do router), que e onde o dinheiro de vision escaparia sem ninguem ver.
    """

    def __init__(self, *leituras: LeituraDoComprovante | None, erro: Exception | None = None):
        self.leituras = list(leituras)
        self.erro = erro
        self.lidas: list[bytes] = []

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        self.lidas.append(imagem.conteudo)
        if self.erro is not None:
            raise self.erro
        return self.leituras.pop(0) if self.leituras else None

    @property
    def vezes(self) -> int:
        return len(self.lidas)


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
    nasce dentro da transacao que o teste desfaz, para que `chave_conhecida` tenha o que comparar
    sem que nenhum teste dependa de seed aplicado no banco.
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
    olho: _Olho | None = None,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=olho)


async def _postar_imagem(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    conteudo: bytes,
    *,
    falas: _Falas,
    olho: _Olho | None,
    depois: timedelta = timedelta(minutes=5),
    sem_bytes: bool = False,
    **kw: Any,
) -> ResultadoDaPorta:
    """A modelo posta a foto do comprovante (mensagem `imagem`, texto vazio — e assim que chega).

    `sem_bytes` encena a midia que o webhook nao conseguiu (MinIO fora, download barrado): a
    mensagem existe, a imagem nao.
    """
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Yasmin")
    kw.setdefault("autor_jid", "5571988887777@s.whatsapp.net")
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=None if sem_bytes else ImagemDoGrupo(conteudo, mimetype="image/jpeg"),
        recebida_em=grupo.relogio,
        **kw,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=olho)


async def _duas_vendas_em_pix(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, *, falas: _Falas
) -> list[UUID]:
    """A conversa de 12/08 ate o "600 pix / 600 pix": duas vendas de R$ 600,00 abertas em pix."""
    vendas: list[UUID] = []
    for cliente in ("Ramon", "Lucas"):
        lancou = await _dizer(
            c,
            grupo,
            ANUNCIO.format(cliente=cliente, apelido=grupo.apelido),
            falas=falas,
            depois=timedelta(hours=2),
        )
        (venda_id,) = lancou.vendas
        pago = await _dizer(c, grupo, "Pix", falas=falas, depois=timedelta(minutes=5))
        assert pago.pagamentos == (venda_id,)
        vendas.append(venda_id)
    return vendas


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, valor, data, cliente_nome, forma_pagamento, comprovante_id
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _comprovantes(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT co.id, co.classificacao, co.valor, co.data_transferencia, co.pagador,
               co.chave_destino, co.titular_destino, co.chave_conhecida, co.valor_abatido
          FROM barravips.comprovantes_do_grupo co
          JOIN barravips.grupos_financeiros g ON g.id = co.grupo_id
         WHERE g.jid = %s
         ORDER BY co.created_at
        """,
        (grupo.jid,),
    )
    return list(await cur.fetchall())


async def _esquecer_a_chave_da_casa(c: AsyncConnection[dict[str, Any]]) -> None:
    """O cadastro de chaves SEM a chave deste comprovante — o estado real do dia 1 do piloto.

    Apagar aqui (dentro da transacao que o teste desfaz) e o jeito honesto de encenar "destino
    fora da lista": a alternativa seria inventar um comprovante com outra chave, e o comprovante
    e a evidencia real do export.
    """
    await c.execute("DELETE FROM barravips.chaves_pix_conhecidas")


def _contador(resultado: str) -> float:
    # Gotcha da casa: `get_sample_value` NAO duplica o sufixo `_total`.
    return (
        REGISTRY.get_sample_value(
            "barra_grupo_financeiro_comprovantes_total", {"resultado": resultado}
        )
        or 0.0
    )


# --- 1. o comprovante de R$ 1.200,00 fecha as duas vendas de R$ 600,00 (FIFO) --------------------


async def test_comprovante_de_1200_abate_as_duas_vendas_pix_em_fifo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """12/08 as 19:12: a conta que o gestor fazia de cabeca vira duas linhas comprovadas."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    olho = _Olho(LEITURA_1200)

    conferiu = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    assert olho.vezes == 1
    assert olho.lidas == [IMAGEM_1200]  # os bytes reais chegaram inteiros ao leitor
    assert conferiu.motivo == "comprovante_conciliado"
    assert set(conferiu.abatidas) == {ramon, lucas}
    # FIFO: a mais antiga primeiro — e as duas sairam da fila.
    assert conferiu.abatidas[0] == ramon
    assert [v["comprovante_id"] for v in await _vendas(conn, grupo.modelo_id)] == [
        conferiu.comprovante_id,
        conferiu.comprovante_id,
    ]

    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "fechamento"
    assert comprovante["valor"] == Decimal("1200.00")
    assert comprovante["data_transferencia"] == date(2026, 8, 12)
    assert comprovante["valor_abatido"] == Decimal("1200.00")
    assert comprovante["chave_conhecida"] is True
    assert comprovante["titular_destino"] == TITULAR_DA_CASA

    # A confirmacao e CURTA e diz o que ainda falta — o Fechamento aparecendo uma linha por vez.
    assert falas.ultima is not None
    assert falas.ultima.startswith("✅ Comprovante conferido: R$ 1.200,00 · 12/08")
    assert "baixei 2 vendas em pix" in falas.ultima
    assert "Falta comprovar: R$ 0,00" in falas.ultima
    assert "⚠️" not in falas.ultima  # chave conhecida: nada a sinalizar


async def test_venda_abatida_perde_a_pendencia_de_comprovante(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A Pendencia de comprovante e derivada da coluna: ela nasce com o pix e morre com o abate."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    lancou = await _dizer(
        conn, grupo, ANUNCIO.format(cliente="Ramon", apelido=grupo.apelido), falas=falas
    )
    (venda_id,) = lancou.vendas
    assert lancou.pendencias == (Pendencia(venda_id, "forma_pagamento"),)

    pago = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(minutes=5))
    # Descoberto o pix, a pendencia TROCA: agora falta o comprovante (nunca as duas juntas).
    assert pago.pendencias == (Pendencia(venda_id, "comprovante"),)

    olho = _Olho(
        LeituraDoComprovante(
            e_comprovante=True,
            legivel=True,
            valor=Decimal("600.00"),
            data=date(2026, 8, 12),
            chave_destino=CHAVE_DA_CASA,
        )
    )
    conferiu = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    assert conferiu.abatidas == (venda_id,)
    assert conferiu.pendencias == ()


# --- 2. chave fora do cadastro: sinaliza, nunca trava --------------------------------------------


async def test_chave_fora_do_cadastro_sinaliza_ao_gestor_sem_travar_o_abate(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Dinheiro indo para chave desconhecida e erro ou golpe — mas travar seria pior que avisar."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    await _esquecer_a_chave_da_casa(conn)
    olho = _Olho(LEITURA_1200)
    antes = _contador("chave_desconhecida")

    conferiu = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    # O abate aconteceu do mesmo jeito: a operacao nunca para por comprovante duvidoso.
    assert conferiu.motivo == "comprovante_conciliado"
    assert set(conferiu.abatidas) == {ramon, lucas}
    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "fechamento"
    assert comprovante["chave_conhecida"] is False  # a flag que o painel mostra

    assert falas.ultima is not None
    assert falas.ultima.startswith("✅ Comprovante conferido")
    aviso = falas.ultima.splitlines()[-1]
    assert aviso.startswith("⚠️ Esse Pix foi pra uma chave fora da lista da casa")
    # O aviso mostra a chave COMO FOI LIDA: sem o dado, ninguem consegue conferir nada.
    assert CHAVE_DA_CASA in aviso
    assert _contador("chave_desconhecida") == antes + 1


# --- 3. o que nao casa fica retido, com pergunta -------------------------------------------------


async def test_comprovante_que_nao_casa_com_venda_fica_retido_com_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """13/08: R$ 385,80 para a 3RJ. Nao fecha venda nenhuma — e nao pode sumir (ticket 08)."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    (venda_id,) = (await _duas_vendas_em_pix(conn, grupo, falas=falas))[:1]
    olho = _Olho(LEITURA_385)

    retido = await _postar_imagem(
        conn, grupo, IMAGEM_385, falas=falas, olho=olho, depois=timedelta(days=1)
    )

    assert retido.motivo == "comprovante_nao_classificado"
    assert retido.abatidas == ()
    assert retido.comprovante_id is not None  # existe: e a prova de que dinheiro saiu

    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "nao_classificado"
    assert comprovante["valor"] == Decimal("385.80")
    assert comprovante["valor_abatido"] == Decimal("0.00")
    assert comprovante["chave_conhecida"] is False  # a chave da 3RJ so entra no ticket 08

    # As vendas em pix continuam abertas: R$ 385,80 nao cobre uma venda de R$ 600,00, e abater
    # meia venda seria inventar um terceiro estado que conversa nenhuma do grupo produz.
    assert [v["comprovante_id"] for v in await _vendas(conn, grupo.modelo_id)] == [None, None]
    assert venda_id is not None

    assert falas.ultima is not None
    pergunta = falas.ultima.splitlines()[0]
    assert pergunta.startswith("❓ Recebi um comprovante de R$ 385,80 · 13/08")
    assert pergunta.endswith("É de quê?")


# --- 4. dinheiro nunca entra na expectativa de abate ---------------------------------------------


async def test_venda_em_dinheiro_nunca_entra_na_fila_do_abate(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """08/08: "Foi pix ou din ?" -> "Dinheiro". O cash fica com a modelo, fora do comprovante."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    lancou = await _dizer(
        conn, grupo, ANUNCIO.format(cliente="Gabriel", apelido=grupo.apelido), falas=falas
    )
    (venda_id,) = lancou.vendas
    pago = await _dizer(conn, grupo, "Dinheiro", falas=falas, depois=timedelta(hours=2))
    assert pago.pendencias == ()  # dinheiro nao espera comprovante nenhum

    olho = _Olho(
        LeituraDoComprovante(
            e_comprovante=True,
            legivel=True,
            valor=Decimal("600.00"),
            data=date(2026, 8, 12),
            chave_destino=CHAVE_DA_CASA,
        )
    )
    veio = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    # Um comprovante do valor EXATO da venda em dinheiro nao a abate: ela nunca esteve na fila.
    assert veio.abatidas == ()
    assert veio.motivo == "comprovante_nao_classificado"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["id"] == venda_id
    assert venda["comprovante_id"] is None


# --- 5. OCR ilegivel pede reenvio; falha nossa cala ----------------------------------------------


async def test_comprovante_ilegivel_pede_reenvio_sem_crash(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Foto cortada/desfocada: o agente pede a imagem de novo, uma vez, e nao abate nada."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _duas_vendas_em_pix(conn, grupo, falas=falas)
    olho = _Olho(LeituraDoComprovante(e_comprovante=True, legivel=False))

    borrado = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    assert borrado.status == "registrada"  # nao levantou: o webhook e sincrono
    assert borrado.motivo == "comprovante_ilegivel"
    assert borrado.abatidas == ()
    assert falas.ultima == PEDIDO_DE_REENVIO
    # A linha existe mesmo sem valor: senao "eu mandei" da modelo nao teria nada no sistema.
    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "ilegivel"
    assert comprovante["valor"] is None
    assert [v["comprovante_id"] for v in await _vendas(conn, grupo.modelo_id)] == [None, None]


async def test_falha_do_provider_e_ambiente_sem_leitor_terminam_calados(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Falha NOSSA nao vira pedido de reenvio: seria um loop que a modelo paga com paciencia."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    quebrado = await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(erro=RuntimeError("openrouter fora"))
    )
    sem_leitor = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=None)
    sem_bytes = await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(LEITURA_1200), sem_bytes=True
    )

    for resultado in (quebrado, sem_leitor, sem_bytes):
        assert resultado.status == "registrada"
        assert resultado.motivo == "imagem_sem_leitura"
        assert resultado.comprovante_id is None
    assert falas.enviadas == []
    assert await _comprovantes(conn, grupo) == []


async def test_foto_que_nao_e_comprovante_morre_calada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O grupo posta foto do site, print de perfil, sticker. O agente nao comenta imagem.

    Os bytes aqui sao sinteticos de proposito: as fotos do export sao todas comprovantes, e o que
    esta sob teste e a conduta quando o OCR diz "isto nao e comprovante" — nao a imagem.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    olho = _Olho(LeituraDoComprovante(e_comprovante=False))
    antes = _contador("nao_e_comprovante")

    foto = await _postar_imagem(
        conn, grupo, b"\x89PNG\r\n\x1a\nqualquer-foto", falas=falas, olho=olho
    )

    assert foto.motivo == "nao_e_comprovante"
    assert foto.resposta is None
    assert falas.enviadas == []
    assert await _comprovantes(conn, grupo) == []
    assert _contador("nao_e_comprovante") == antes + 1


async def test_anuncio_na_legenda_da_foto_continua_virando_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A foto nao apaga o que um humano escreveu: legenda que e anuncio segue para o caminho dele.

    E o que impede este ticket de engolir uma venda que os anteriores registravam — a imagem passa
    pelo OCR primeiro, e so quando ela nao rende comprovante a legenda e lida.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    olho = _Olho(LeituraDoComprovante(e_comprovante=False))

    lancou = await _postar_imagem(
        conn,
        grupo,
        b"\x89PNG\r\n\x1a\nfoto-do-quarto",
        falas=falas,
        olho=olho,
        caption=ANUNCIO.format(cliente="Antônio", apelido=grupo.apelido),
    )

    assert len(lancou.vendas) == 1
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["cliente_nome"] == "Antônio"
    assert falas.ultima is not None and falas.ultima.startswith("✅ Registrei:")


# --- 6. custo: OCR uma vez por imagem de gente ---------------------------------------------------


async def test_eco_do_agente_e_reentrega_nao_custam_ocr(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Vision so para imagem de gente, uma vez por mensagem — e o abate nunca acontece duas vezes."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    olho = _Olho(LEITURA_1200, LEITURA_1200)

    eco = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho, de_mim=True)
    assert eco.motivo == "eco_do_agente"
    assert olho.vezes == 0

    evo = f"3EB0{uuid4().hex[:12]}"
    primeira = await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=olho, evolution_message_id=evo
    )
    repetida = await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=olho, evolution_message_id=evo
    )

    assert set(primeira.abatidas) == {ramon, lucas}
    assert repetida.status == "duplicada"  # a segunda entrega do router morre ANTES do provider
    assert olho.vezes == 1
    assert len(await _comprovantes(conn, grupo)) == 1


async def test_a_mesma_foto_reenviada_nao_abate_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O reenvio da MESMA imagem — mensagem nova, message_id novo — nao conta o dinheiro de novo.

    Medido em 14/08 antes do dedup de conteudo: com duas vendas em pix de R$ 600,00 abertas e UM
    comprovante de R$ 1.200,00 reenviado, o agente abatia as duas na primeira e ainda achava o que
    abater na segunda. O Fechamento fechava — e essa e a parte cara: o extrato so mente quando
    fecha, porque ninguem confere o que ja bate.

    A fala e obrigatoria: quem reenvia acha que a primeira nao chegou e mandaria uma terceira.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    olho = _Olho(LEITURA_1200, LEITURA_1200)

    primeira = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)
    repetida = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    assert set(primeira.abatidas) == {ramon, lucas}
    assert repetida.motivo == "comprovante_duplicado"
    assert repetida.abatidas == ()
    assert len(await _comprovantes(conn, grupo)) == 1  # nem linha nova de comprovante

    assert repetida.resposta is not None
    assert falas.enviadas[-1] == repetida.resposta
    assert "já tinha conferido" in repetida.resposta
    assert "R$ 1.200,00" in repetida.resposta


async def test_reenvio_da_imagem_ilegivel_continua_sendo_lido(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O dedup de conteudo nao pode engolir a unica coisa que o agente PEDE de volta.

    Ele acabou de dizer "reenvia a imagem inteira"; se a modelo reenviar a mesma foto (e o OCR
    conseguir agora, com outra passada), tem que valer. Por isso o ilegivel nao grava hash.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    olho = _Olho(LeituraDoComprovante(e_comprovante=True, legivel=False), LEITURA_1200)

    pediu = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)
    assert pediu.motivo == "comprovante_ilegivel"

    de_novo = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=olho)

    assert de_novo.motivo == "comprovante_conciliado"
    assert set(de_novo.abatidas) == {ramon, lucas}


async def test_apagar_a_foto_do_comprovante_desfaz_o_abate(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mandou a foto errada e apagou: as vendas voltam para "falta comprovar".

    Apagar-e-repostar e como o grupo corrige, e ate 14/08 esse gesto so funcionava metade: apagar
    o ANUNCIO anulava a venda, apagar o COMPROVANTE nao fazia nada. A venda seguia dada como paga
    por uma prova que nao existe mais no grupo — e, como o extrato continuava fechando, ninguem ia
    procurar.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    evo = f"3EB0{uuid4().hex[:12]}"

    conferiu = await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(LEITURA_1200), evolution_message_id=evo
    )
    assert set(conferiu.abatidas) == {ramon, lucas}

    apagou = await processar_delecao_do_grupo(
        conn,
        DelecaoNoGrupo(
            grupo_jid=grupo.jid,
            evolution_message_id=evo,
            autor_jid="5571988887777@s.whatsapp.net",
            ocorrida_em=grupo.relogio + timedelta(minutes=1),
        ),
    )

    assert apagou.motivo == "comprovante_anulado"
    # As duas voltaram para a fila, com a pendencia que elas tinham antes da foto.
    assert {p.venda_id for p in apagou.pendencias} == {ramon, lucas}
    assert all(p.tipo == "comprovante" for p in apagou.pendencias)
    assert [v["comprovante_id"] for v in await _vendas(conn, grupo.modelo_id)] == [None, None]

    # A linha do comprovante continua no banco (o que aconteceu nao deixa de ter acontecido), mas
    # sai da conferencia: o extrato volta a dizer que falta comprovar.
    assert len(await _comprovantes(conn, grupo)) == 1
    assert falas.enviadas[-1].startswith("✅ Comprovante conferido:")  # a delecao nao fala


async def test_reenviar_a_foto_depois_de_apagar_por_engano_volta_a_valer(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagou sem querer e mandou a MESMA foto de novo: o dedup de conteudo tem que soltar.

    Sem isto o agente responderia "já tinha conferido" sobre um comprovante que ele mesmo acabou
    de anular — e as vendas ficariam presas na fila para sempre, sem foto que as tire de la.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    evo = f"3EB0{uuid4().hex[:12]}"
    await _postar_imagem(
        conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(LEITURA_1200), evolution_message_id=evo
    )
    await processar_delecao_do_grupo(
        conn,
        DelecaoNoGrupo(
            grupo_jid=grupo.jid,
            evolution_message_id=evo,
            autor_jid="5571988887777@s.whatsapp.net",
            ocorrida_em=grupo.relogio + timedelta(minutes=1),
        ),
    )

    de_novo = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(LEITURA_1200))

    assert de_novo.motivo == "comprovante_conciliado"
    assert set(de_novo.abatidas) == {ramon, lucas}


# --- 9. o comprovante que aponta para o lado contrario --------------------------------------------


async def test_comprovante_do_cliente_para_a_modelo_nao_abate_nem_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """06/08 do export: a gestora postou o Pix que a CLIENTE fez PARA a modelo.

    Ate este ticket o agente lia aquilo como transferencia dela: perguntava "é de quê?", disparava
    o alarme de chave fora da lista apontando o nome da propria modelo e — com venda em pix aberta
    na fila, que e o estado normal do grupo — teria ABATIDO. Dinheiro que a casa nao recebeu
    viraria venda comprovada, e a cobranca da manha pararia de pedir o que ainda falta.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _duas_vendas_em_pix(conn, grupo, falas=falas)  # R$ 1.200,00 em pix esperando comprovante
    entrada = LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("1200.00"),
        data=date(2026, 8, 6),
        pagador="VANESSA MELO DE OLIVEIRA",
        chave_destino=None,  # o comprovante do Neon nao mostra chave nenhuma: so os nomes
        titular_destino=f"{grupo.apelido} Nascimento De Albuquerque",
    )

    lido = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(entrada))

    assert lido.motivo == "comprovante_entrada_da_modelo"
    assert lido.abatidas == ()
    assert [v["comprovante_id"] for v in await _vendas(conn, grupo.modelo_id)] == [None, None]

    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "entrada_da_modelo"
    assert comprovante["valor"] == Decimal("1200.00")  # fica de prova de que a venda foi paga
    assert comprovante["valor_abatido"] == Decimal("0.00")

    assert falas.ultima is not None
    assert falas.ultima.startswith("📥 Esse comprovante de R$ 1.200,00 · 06/08")
    assert "VANESSA MELO DE OLIVEIRA" in falas.ultima
    # As duas falas erradas do estado anterior: nenhuma pode voltar.
    assert "É de quê?" not in falas.ultima
    assert "fora da lista da casa" not in falas.ultima


async def test_fechamento_para_destino_homonimo_da_modelo_continua_abatendo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A tranca da tranca: quem PAGOU foi ela, entao o destino parecido nao muda nada.

    Sem esta condicao, uma casa cujo titular divida o primeiro nome com a modelo faria o agente
    parar de abater todos os fechamentos dela — em silencio, e para sempre.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ramon, lucas = await _duas_vendas_em_pix(conn, grupo, falas=falas)
    await _esquecer_a_chave_da_casa(conn)
    homonimo = LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("1200.00"),
        data=date(2026, 8, 12),
        pagador=f"{grupo.apelido} Nascimento De Albuquerque",
        chave_destino=CHAVE_DA_CASA,
        titular_destino=f"{grupo.apelido} de Melo Souza",
    )

    conferiu = await _postar_imagem(conn, grupo, IMAGEM_1200, falas=falas, olho=_Olho(homonimo))

    assert conferiu.motivo == "comprovante_conciliado"
    assert set(conferiu.abatidas) == {ramon, lucas}
