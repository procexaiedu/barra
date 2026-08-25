"""O pagamento promovendo a Ficha a Venda registrada, com banco (spec 0006, ticket 07; ADR-0044).

O caso do ticket, ponta a ponta: o card do Igor (R$ 700, 1h, local próprio) entra às 19h e às 22h
a modelo escreve só **"recebi, foi dinheiro"**. A venda nasce ali com tudo que o telefonista já
digitou, a ficha passa a `realizada`, e ninguém pergunta nada a ela.

O que só o banco prova, e por isso vive aqui e não no arquivo offline:

1. A venda **nasce da ficha** com valor, cliente, duração, local, site, origem e `ficha_id` — e
   com o `percentual_repasse_snapshot` copiado do cadastro (ADR-0045 §3).
2. O **bolso é fato da venda** (ADR-0047): dinheiro é `dela`; pix sem prova é `nao_dito`.
3. A ficha vira `realizada` e sai da lista de abertas — e o rastro `realizacao` fica em
   `ficha_de_agendamento_eventos` (append-only).
4. **Idempotência entre as duas portas** (ADR-0046 §5): a mesma promoção duas vezes não produz
   duas vendas, pela chave de conteúdo que o módulo já tem. É o que o ticket 20 vai reusar.
5. O **comprovante Pix de valor exato** promove a ficha e a fecha na mesma passada: uma venda, um
   comprovante amarrado, uma fala só no grupo.
6. **Comprovante sem ficha nenhuma** continua retido com uma pergunta — não vira venda anônima.
7. Três fichas abertas e nada que aponte viram **uma** pergunta de desempate, não um palpite.
8. **Áudio vale o mesmo que texto**: a transcrição entra antes de qualquer conduta.
9. O recibo é **corrigível por quote** e o de→para aparece.

⚠️ Exige as migrations da onda **20260820** aplicadas em `TEST_DATABASE_URL`
(`20260820120000` .. `20260820127000`), que dependem da onda `20260814`. Sem elas
`barravips.fichas_de_agendamento` e `vendas_registradas.bolso` não existem e todo teste deste
arquivo falha na primeira escrita.

`needs_db` com ROLLBACK sempre, e pela porta única: nenhum teste chama função interna do módulo
(lição do harness fiel).
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_evento_do_grupo
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo
from barra.dominio.grupo_financeiro.pagamento import PREFIXO_DO_DESEMPATE
from barra.dominio.grupo_financeiro.repo import fichas_abertas_da_modelo

pytestmark = pytest.mark.needs_db

# 22/08 22:00 BRT — a modelo avisa que recebeu, três horas depois do atendimento das 19h.
NOITE_DE_22_08 = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)

CHAVE_DA_CASA = "00000000-0000-0000-0000-000000000000"
TITULAR_DA_CASA = "Fulano de Tal"

FICHA = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: {cliente}

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: Barra Vips
Origem: (x) Próprio  ( ) Fake
Nome da modelo: {modelo}

🕒 *HORÁRIO*
Data: 22/08/2026
Hora: {hora}
Duração: 1h

📍 *LOCAL*
( ) Saída  (x) Local próprio
Tipo: (x) Casa

💰 *VALORES*
Valor total: R$ {valor}
Valor desta modelo: R$ {valor}

💳 *PAGAMENTO*
( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link
"""


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


# --- seeds ----------------------------------------------------------------------------------------


async def _seed_modelo(
    c: AsyncConnection[dict[str, Any]], nome: str, *, percentual: Decimal | None = Decimal("50")
) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], percentual),
    )
    return modelo_id


async def _seed_grupo(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> tuple[UUID, str]:
    grupo_id = uuid4()
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (grupo_id, modelo_id, jid, "financeiro de teste"),
    )
    return grupo_id, jid


async def _cadastrar_a_chave_da_casa(c: AsyncConnection[dict[str, Any]]) -> None:
    await c.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, titular)
        VALUES (%s, %s, %s)
        ON CONFLICT (chave_normalizada) DO NOTHING
        """,
        (CHAVE_DA_CASA, CHAVE_DA_CASA, TITULAR_DA_CASA),
    )


def _mensagem(jid: str, texto: str, **extra: Any) -> MensagemDoGrupo:
    return MensagemDoGrupo(
        grupo_jid=jid,
        texto=texto,
        evolution_message_id=f"3EB0{uuid4().hex[:10]}",
        autor_nome="Lula",
        autor_jid="5521999999999@s.whatsapp.net",
        recebida_em=NOITE_DE_22_08,
        **extra,
    )


class _Boca:
    def __init__(self) -> None:
        self.falas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.falas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.falas[-1] if self.falas else None


class _Olho:
    def __init__(self, *leituras: LeituraDoComprovante | None) -> None:
        self.leituras = list(leituras)

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        return self.leituras.pop(0) if self.leituras else None


class _Ouvido:
    def __init__(self, texto: str) -> None:
        self.texto = texto

    async def __call__(self, audio: Any) -> str:
        return self.texto


async def _postar_ficha(
    c: AsyncConnection[dict[str, Any]],
    jid: str,
    *,
    modelo: str,
    cliente: str = "Igor",
    valor: str = "700",
    hora: str = "19:00",
) -> UUID:
    resultado = await processar_evento_do_grupo(
        c,
        _mensagem(jid, FICHA.format(modelo=modelo, cliente=cliente, valor=valor, hora=hora)),
    )
    assert resultado.ficha_id is not None, resultado.motivo
    return resultado.ficha_id


async def _venda(c: AsyncConnection[dict[str, Any]], venda_id: UUID) -> dict[str, Any]:
    cur = await c.execute(
        """
        SELECT valor, data, cliente_nome, duracao_minutos, local_atendimento, forma_pagamento,
               bolso, ficha_id, site, origem, percentual_repasse_snapshot, comprovante_id,
               pagamento_mensagem_id, bolso_mensagem_id
          FROM barravips.vendas_registradas WHERE id = %s
        """,
        (venda_id,),
    )
    row = await cur.fetchone()
    assert row is not None
    return dict(row)


async def _estado_da_ficha(c: AsyncConnection[dict[str, Any]], ficha_id: UUID) -> str:
    cur = await c.execute(
        "SELECT estado FROM barravips.fichas_de_agendamento WHERE id = %s", (ficha_id,)
    )
    row = await cur.fetchone()
    assert row is not None
    return str(row["estado"])


async def _eventos_da_ficha(c: AsyncConnection[dict[str, Any]], ficha_id: UUID) -> list[str]:
    cur = await c.execute(
        "SELECT tipo FROM barravips.ficha_de_agendamento_eventos WHERE ficha_id = %s", (ficha_id,)
    )
    return [str(row["tipo"]) for row in await cur.fetchall()]


async def _contar_vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> int:
    cur = await c.execute(
        "SELECT count(*) AS n FROM barravips.vendas_registradas WHERE modelo_id = %s", (modelo_id,)
    )
    row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


# --- a fala da modelo -----------------------------------------------------------------------------


async def test_recebi_foi_dinheiro_com_uma_ficha_aberta_cria_a_venda_inteira(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    ficha_id = await _postar_ficha(conn, jid, modelo=nome)
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, "recebi, foi dinheiro"), enviar=boca
    )

    assert resultado.motivo == "ficha_promovida"
    assert resultado.ficha_id == ficha_id
    assert len(resultado.vendas) == 1

    venda = await _venda(conn, resultado.vendas[0])
    assert venda["valor"] == Decimal("700.00")
    assert venda["cliente_nome"] == "Igor"
    assert venda["duracao_minutos"] == 60
    assert venda["local_atendimento"] == "no nosso local"
    assert venda["site"] == "Barra Vips"
    assert venda["origem"] == "proprio"
    assert venda["ficha_id"] == ficha_id
    assert venda["forma_pagamento"] == "dinheiro"
    # A venda nasce com o percentual do cadastro CONGELADO (ADR-0045 §3).
    assert venda["percentual_repasse_snapshot"] == Decimal("50.00")
    # Dinheiro e sempre dela — especie nao tem outro bolso (ADR-0047 §2).
    assert venda["bolso"] == "dela"

    # Recibo curto, com o que o telefonista digitou, e UMA fala so.
    assert len(boca.falas) == 1
    assert boca.ultima is not None
    assert "R$ 700,00" in boca.ultima and "Igor" in boca.ultima and "1h" in boca.ultima

    # A ficha cumpriu o desfecho e saiu da lista de abertas.
    assert await _estado_da_ficha(conn, ficha_id) == "realizada"
    assert await _eventos_da_ficha(conn, ficha_id) == ["realizacao"]
    assert await fichas_abertas_da_modelo(conn, modelo_id) == []


async def test_a_venda_e_datada_pelo_combinado_e_nao_pelo_dia_do_aviso(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O aviso pode chegar no dia seguinte; o dinheiro pertence ao dia do atendimento."""
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _postar_ficha(conn, jid, modelo=nome)

    resultado = await processar_evento_do_grupo(
        conn,
        MensagemDoGrupo(
            grupo_jid=jid,
            texto="recebi, foi dinheiro",
            evolution_message_id=f"3EB0{uuid4().hex[:10]}",
            autor_jid="5521999999999@s.whatsapp.net",
            recebida_em=datetime(2026, 8, 24, 14, 0, tzinfo=UTC),
        ),
    )

    assert len(resultado.vendas) == 1
    venda = await _venda(conn, resultado.vendas[0])
    assert str(venda["data"]) == "2026-08-22"


async def test_a_segunda_porta_nao_cria_uma_segunda_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O ✅ do telefonista (ticket 20) vem depois da fala dela. Um fato, uma venda.

    Aqui a segunda passagem e a MESMA fala reentregue com outro id de mensagem — o que o webhook
    faz quando o router duplica fora da janela de dedup. A tranca e a chave de conteudo, e e ela
    que o ticket 20 herda.
    """
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    ficha_id = await _postar_ficha(conn, jid, modelo=nome)

    primeira = await processar_evento_do_grupo(conn, _mensagem(jid, "recebi, foi dinheiro"))
    assert primeira.motivo == "ficha_promovida"

    # A ficha ja esta realizada: a segunda fala nao encontra alvo aberto e nao escreve nada.
    segunda = await processar_evento_do_grupo(conn, _mensagem(jid, "recebi, foi dinheiro"))

    assert segunda.vendas == ()
    assert await _contar_vendas(conn, modelo_id) == 1
    assert await _eventos_da_ficha(conn, ficha_id) == ["realizacao"]


async def test_tres_fichas_abertas_viram_uma_pergunta_e_nenhuma_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    for cliente, valor, hora in (("Igor", "700", "19:00"), ("Ramon", "900", "21:00")):
        await _postar_ficha(conn, jid, modelo=nome, cliente=cliente, valor=valor, hora=hora)
    await _postar_ficha(conn, jid, modelo=nome, cliente="Denis", valor="500", hora="23:00")
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, "recebi, foi dinheiro"), enviar=boca
    )

    assert resultado.motivo == "promocao_ambigua"
    assert resultado.vendas == ()
    assert await _contar_vendas(conn, modelo_id) == 0
    assert boca.ultima is not None and boca.ultima.startswith(PREFIXO_DO_DESEMPATE)
    assert len(await fichas_abertas_da_modelo(conn, modelo_id)) == 3

    # E UMA pergunta: repetir a fala nao repergunta (a metralhadora que o dominio proibe).
    await processar_evento_do_grupo(conn, _mensagem(jid, "recebi, foi dinheiro"), enviar=boca)
    assert len(boca.falas) == 1


async def test_o_nome_do_cliente_desempata_entre_as_fichas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _postar_ficha(conn, jid, modelo=nome, cliente="Igor", valor="700", hora="19:00")
    do_ramon = await _postar_ficha(
        conn, jid, modelo=nome, cliente="Ramon", valor="900", hora="21:00"
    )

    resultado = await processar_evento_do_grupo(conn, _mensagem(jid, "o do Ramon foi pix"))

    assert resultado.motivo == "ficha_promovida"
    assert resultado.ficha_id == do_ramon
    venda = await _venda(conn, resultado.vendas[0])
    assert venda["cliente_nome"] == "Ramon"
    assert venda["valor"] == Decimal("900.00")
    # Pix sem prova nao decide bolso nenhum: "nao dito" e estado legitimo (ADR-0047 §3).
    assert venda["bolso"] == "nao_dito"
    assert venda["bolso_mensagem_id"] is None


async def test_audio_dizendo_a_forma_vale_o_mesmo_que_texto(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _postar_ficha(conn, jid, modelo=nome)

    resultado = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "", tipo="audio", audio=None),
        transcrever=_Ouvido("recebi, foi dinheiro"),
    )

    # Sem bytes nao ha o que ouvir; o teste do audio de verdade e o proximo.
    assert resultado.motivo == "audio_sem_transcricao"

    from barra.dominio.grupo_financeiro.modelos import AudioDoGrupo

    resultado = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "", tipo="audio", audio=AudioDoGrupo(conteudo=b"ogg", mimetype="audio/ogg")),
        transcrever=_Ouvido("recebi, foi dinheiro"),
    )

    assert resultado.motivo == "ficha_promovida"
    venda = await _venda(conn, resultado.vendas[0])
    assert venda["forma_pagamento"] == "dinheiro"
    assert await _contar_vendas(conn, modelo_id) == 1


async def test_o_recibo_da_promocao_e_corrigivel_por_quote(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _postar_ficha(conn, jid, modelo=nome)
    boca = _Boca()
    aviso = _mensagem(jid, "recebi, foi dinheiro")

    promovida = await processar_evento_do_grupo(conn, aviso, enviar=boca)
    assert promovida.motivo == "ficha_promovida"

    correcao = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "foi 650 na verdade", quoted_message_id=aviso.evolution_message_id),
        enviar=boca,
    )

    assert correcao.motivo == "correcao_aplicada"
    assert correcao.correcoes == promovida.vendas
    venda = await _venda(conn, promovida.vendas[0])
    assert venda["valor"] == Decimal("650.00")
    assert boca.ultima is not None
    assert "700" in boca.ultima and "650" in boca.ultima  # o de->para aparece


async def test_ficha_sem_valor_nao_vira_venda_de_zero(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    comunicado = (
        "📣 Atendimento confirmado\n"
        f"Cliente: Igor\nPerfil: Sofia\nNome da modelo: {nome}\n"
        "Duração: 1h\nTipo: Casa\nEndereço: aqui\nForma: Dinheiro\nObservações: -\n"
    )
    aberta = await processar_evento_do_grupo(conn, _mensagem(jid, comunicado))
    assert aberta.ficha_id is not None

    resultado = await processar_evento_do_grupo(conn, _mensagem(jid, "recebi, foi dinheiro"))

    assert resultado.motivo == "promocao_sem_valor"
    assert await _contar_vendas(conn, modelo_id) == 0
    assert await _estado_da_ficha(conn, aberta.ficha_id) == "aberta"


# --- o comprovante ---------------------------------------------------------------------------------


async def test_comprovante_pix_com_ficha_aberta_fecha_a_venda_na_mesma_passada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _cadastrar_a_chave_da_casa(conn)
    ficha_id = await _postar_ficha(conn, jid, modelo=nome)
    boca = _Boca()
    olho = _Olho(
        LeituraDoComprovante(
            e_comprovante=True,
            legivel=True,
            valor=Decimal("700.00"),
            data=NOITE_DE_22_08.date(),
            pagador=nome.upper(),
            chave_destino=CHAVE_DA_CASA,
            titular_destino=TITULAR_DA_CASA,
        )
    )

    resultado = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "", tipo="imagem", imagem=ImagemDoGrupo(conteudo=b"jpeg-700")),
        enviar=boca,
        ler_comprovante=olho,
    )

    assert resultado.motivo == "comprovante_conciliado"
    assert len(resultado.abatidas) == 1
    assert await _contar_vendas(conn, modelo_id) == 1
    assert await _estado_da_ficha(conn, ficha_id) == "realizada"

    venda = await _venda(conn, resultado.abatidas[0])
    assert venda["ficha_id"] == ficha_id
    assert venda["forma_pagamento"] == "pix"
    assert venda["comprovante_id"] == resultado.comprovante_id
    # Comprovante dela -> casa: o dinheiro passou pela conta dela (ADR-0047 §2, primeira linha).
    assert venda["bolso"] == "dela"
    # UMA fala: a confirmacao do abate. A promocao e calada.
    assert len(boca.falas) == 1


async def test_comprovante_sem_ficha_aberta_nenhuma_fica_retido_com_uma_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _cadastrar_a_chave_da_casa(conn)
    boca = _Boca()
    olho = _Olho(
        LeituraDoComprovante(
            e_comprovante=True,
            legivel=True,
            valor=Decimal("700.00"),
            data=NOITE_DE_22_08.date(),
            pagador=nome.upper(),
            chave_destino=CHAVE_DA_CASA,
            titular_destino=TITULAR_DA_CASA,
        )
    )

    resultado = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "", tipo="imagem", imagem=ImagemDoGrupo(conteudo=b"jpeg-orfao")),
        enviar=boca,
        ler_comprovante=olho,
    )

    assert resultado.motivo == "comprovante_nao_classificado"
    assert resultado.comprovante_id is not None  # nao some: e dinheiro que saiu
    assert await _contar_vendas(conn, modelo_id) == 0
    assert len(boca.falas) == 1


async def test_comprovante_que_nao_bate_o_valor_de_ficha_nenhuma_nao_promove_por_aproximacao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Casar por aproximacao criaria uma venda com o valor de outro atendimento."""
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _cadastrar_a_chave_da_casa(conn)
    ficha_id = await _postar_ficha(conn, jid, modelo=nome, valor="700")
    olho = _Olho(
        LeituraDoComprovante(
            e_comprovante=True,
            legivel=True,
            valor=Decimal("650.00"),
            data=NOITE_DE_22_08.date(),
            pagador=nome.upper(),
            chave_destino=CHAVE_DA_CASA,
            titular_destino=TITULAR_DA_CASA,
        )
    )

    resultado = await processar_evento_do_grupo(
        conn,
        _mensagem(jid, "", tipo="imagem", imagem=ImagemDoGrupo(conteudo=b"jpeg-650")),
        ler_comprovante=olho,
    )

    assert resultado.motivo == "comprovante_nao_classificado"
    assert await _contar_vendas(conn, modelo_id) == 0
    assert await _estado_da_ficha(conn, ficha_id) == "aberta"


async def test_modelo_sem_percentual_cadastrado_nao_ganha_50_por_cento_chutado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """50% e default de CADASTRO, nunca constante de codigo (ADR-0045 §3)."""
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome, percentual=None)
    _, jid = await _seed_grupo(conn, modelo_id)
    await _postar_ficha(conn, jid, modelo=nome)

    resultado = await processar_evento_do_grupo(conn, _mensagem(jid, "recebi, foi dinheiro"))

    venda = await _venda(conn, resultado.vendas[0])
    assert venda["percentual_repasse_snapshot"] is None
