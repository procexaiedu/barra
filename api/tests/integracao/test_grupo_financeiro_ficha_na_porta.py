"""A Ficha do telefonista pela PORTA UNICA, com banco (spec 0006, ticket 06; ADR-0044/0046).

O que so o banco prova, e por isso vive aqui e nao no teste offline:

1. **A ficha e gravada CALADA** — nenhuma fala no grupo. Um "✅ Registrei" a cada card
   transformaria o grupo de fichas num eco, e o telefonista nao pediu confirmacao de nada.
2. **A ficha nao e receita**: nada nasce em `vendas_registradas` (ADR-0044 §2). O primeiro `WHERE`
   esquecido numa consulta de receita e exatamente o erro que a entidade separada existe para
   impedir.
3. **A modelo nao e coluna da ficha**: a festinha grava uma linha por participante em
   `ficha_participantes`, cada uma no `Valor de cada modelo`.
4. **O repost cai no dedup por conteudo** — o mesmo card postado de novo (ou postado tambem no
   grupo da outra participante) nao vira um segundo atendimento.
5. **O comunicado vincula, nunca cria uma segunda ficha.**
6. **A lista de fichas abertas e a da MODELO, nao a do grupo** (ADR-0046 §2).

⚠️ Exige as migrations da onda **20260820** aplicadas em `TEST_DATABASE_URL`
(`20260820120000` .. `20260820127000`), que por sua vez dependem da onda `20260814`. Sem elas
`barravips.fichas_de_agendamento` nao existe e todo teste deste arquivo falha na primeira escrita.

`needs_db` com ROLLBACK sempre, e pela porta unica: nenhum teste chama funcao interna do modulo
(licao do harness fiel).
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
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import fichas_abertas_da_modelo

pytestmark = pytest.mark.needs_db

NOITE_DE_20_08 = datetime(2026, 8, 20, 22, 0, tzinfo=UTC)

FICHA_DO_IGOR = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Igor
WhatsApp: 21 99999-8888

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: Barra Vips
Origem: (x) Próprio  ( ) Fake
Nome da modelo: {modelo}

🕒 *HORÁRIO*
Data: 22/08
Hora: 19:00
Duração: 1h

📍 *LOCAL*
(x) Local próprio  ( ) Saída
Tipo: ( ) Casa  (X) Hotel  ( ) Motel  ( ) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço: Rua Miguel y Canizares, 200
Número / bloco / complemento: Torre 2 Apt 2706

💰 *VALORES*
Valor total: R$ 700
Valor desta modelo: R$ 700
Valor do transporte: R$ 60
Valor antecipado: R$ 100
Forma do antecipado: (x) Pix  ( ) Link

💳 *PAGAMENTO*
( ) Dinheiro  ( ) Pix  ( ) Débito  (x) Crédito  ( ) Link

✏️ *OBSERVAÇÕES*
Não passar perfume.
"""

COMUNICADO_DO_IGOR = """👤 *CLIENTE*
Nome: Igor

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Origem: Próprio

🕒 *HORÁRIO*
Duração: 1h

📍 *LOCAL DO JOB*
Tipo: Hotel
Endereço: Rua Miguel y Canizares, 200

💰 *VALOR DO JOB*
Valor: R$ 700
Forma de pagamento: Crédito

✏️ *OBSERVAÇÕES*
Não passar perfume.
"""

FICHA_DA_FESTINHA = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Ramon

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: GSEX
Origem: ( ) Próprio  (x) Fake
Modelo 1: {uma}
Modelo 2: {outra}

🕒 *HORÁRIO*
Data: 23/08/2026
Hora: 22h

💰 *VALORES*
Valor total: R$ 1.600,00
Valor de cada modelo: R$ 800

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
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], Decimal("50")),
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


def _mensagem(jid: str, texto: str) -> MensagemDoGrupo:
    return MensagemDoGrupo(
        grupo_jid=jid,
        texto=texto,
        evolution_message_id=f"3EB0{uuid4().hex[:10]}",
        autor_nome="Lula",
        autor_jid="5521999999999@s.whatsapp.net",
        recebida_em=NOITE_DE_20_08,
    )


async def _contar(c: AsyncConnection[dict[str, Any]], tabela: str) -> int:
    cur = await c.execute(f"SELECT count(*) AS n FROM barravips.{tabela}")
    row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


class _Boca:
    """A boca do agente no grupo: guarda tudo que ele tentou falar."""

    def __init__(self) -> None:
        self.falas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.falas.append(texto)


# --- os casos -----------------------------------------------------------------------------------


async def test_ficha_individual_vira_ficha_aberta_sem_o_agente_falar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn, f"Yasmin {uuid4().hex[:6]}")
    _, jid = await _seed_grupo(conn, modelo_id)
    vendas_antes = await _contar(conn, "vendas_registradas")
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, FICHA_DO_IGOR.format(modelo="Yasmin")), enviar=boca
    )

    assert resultado.motivo == "ficha_registrada"
    assert resultado.ficha_id is not None
    assert boca.falas == []  # gravada CALADA (ADR-0044 §1)
    assert resultado.vendas == ()
    assert await _contar(conn, "vendas_registradas") == vendas_antes  # ficha nao e receita

    cur = await conn.execute(
        """
        SELECT estado, cliente_nome, nome_anuncio, site, origem, data, hora, duracao_minutos,
               tipo_atendimento, tipo_local, endereco, endereco_complemento, valor_total,
               valor_transporte, valor_antecipado, forma_antecipado, forma_pagamento
          FROM barravips.fichas_de_agendamento WHERE id = %s
        """,
        (resultado.ficha_id,),
    )
    ficha = await cur.fetchone()
    assert ficha is not None
    assert ficha["estado"] == "aberta"
    assert ficha["cliente_nome"] == "Igor"
    assert ficha["nome_anuncio"] == "Sofia"
    assert ficha["site"] == "Barra Vips"
    assert ficha["origem"] == "proprio"
    assert ficha["duracao_minutos"] == 60
    assert ficha["tipo_atendimento"] == "interno"
    assert ficha["tipo_local"] == "hotel"
    assert ficha["endereco_complemento"] == "Torre 2 Apt 2706"
    assert ficha["valor_total"] == Decimal("700.00")
    # Os dois numeros do deslocamento, distintos (ADR-0046 §6).
    assert ficha["valor_transporte"] == Decimal("60.00")
    assert ficha["valor_antecipado"] == Decimal("100.00")
    assert ficha["forma_antecipado"] == "pix"
    # Credito e forma propria: "cartao" nao existe mais (ADR-0046 §4).
    assert ficha["forma_pagamento"] == "credito"


async def test_ficha_de_festinha_grava_uma_participante_por_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    uma = f"Yasmin {uuid4().hex[:6]}"
    outra = f"Bianca {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, uma)
    outra_id = await _seed_modelo(conn, outra)
    _, jid = await _seed_grupo(conn, modelo_id)
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, FICHA_DA_FESTINHA.format(uma=uma, outra=outra)), enviar=boca
    )

    assert resultado.motivo == "ficha_registrada"
    assert boca.falas == []
    cur = await conn.execute(
        """
        SELECT modelo_id, valor, ordem FROM barravips.ficha_participantes
         WHERE ficha_id = %s ORDER BY ordem
        """,
        (resultado.ficha_id,),
    )
    participantes = list(await cur.fetchall())
    assert [p["modelo_id"] for p in participantes] == [modelo_id, outra_id]
    assert [p["valor"] for p in participantes] == [Decimal("800.00"), Decimal("800.00")]

    # O closed-world e por MODELO: cada uma ve a MESMA ficha, e ninguem ve ficha de terceiro.
    assert [f.id for f in await fichas_abertas_da_modelo(conn, modelo_id)] == [resultado.ficha_id]
    assert [f.id for f in await fichas_abertas_da_modelo(conn, outra_id)] == [resultado.ficha_id]


async def test_repost_do_mesmo_card_nao_cria_uma_segunda_ficha(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn, f"Yasmin {uuid4().hex[:6]}")
    _, jid = await _seed_grupo(conn, modelo_id)
    card = FICHA_DO_IGOR.format(modelo="Yasmin")
    boca = _Boca()

    primeira = await processar_evento_do_grupo(conn, _mensagem(jid, card), enviar=boca)
    segunda = await processar_evento_do_grupo(conn, _mensagem(jid, card), enviar=boca)

    assert primeira.motivo == "ficha_registrada"
    assert segunda.motivo == "ficha_duplicada"
    assert segunda.ficha_id == primeira.ficha_id
    assert boca.falas == []
    assert len(await fichas_abertas_da_modelo(conn, modelo_id)) == 1


async def test_comunicado_nao_cria_uma_segunda_ficha(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O arranjo com Grupo de fichas: a ficha completa la, o comunicado aqui, UM atendimento."""
    modelo_id = await _seed_modelo(conn, f"Yasmin {uuid4().hex[:6]}")
    _, jid = await _seed_grupo(conn, modelo_id)
    boca = _Boca()

    ficha = await processar_evento_do_grupo(
        conn, _mensagem(jid, FICHA_DO_IGOR.format(modelo="Yasmin")), enviar=boca
    )
    comunicado = await processar_evento_do_grupo(
        conn, _mensagem(jid, COMUNICADO_DO_IGOR), enviar=boca
    )

    assert comunicado.motivo == "comunicado_vinculado"
    assert comunicado.ficha_id == ficha.ficha_id
    assert boca.falas == []
    assert len(await fichas_abertas_da_modelo(conn, modelo_id)) == 1


async def test_comunicado_sem_ficha_correspondente_cria_a_ficha(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O arranjo SEM Grupo de fichas — e o que acontece quando o telefonista pula a ficha completa."""
    modelo_id = await _seed_modelo(conn, f"Yasmin {uuid4().hex[:6]}")
    _, jid = await _seed_grupo(conn, modelo_id)
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, COMUNICADO_DO_IGOR), enviar=boca
    )

    assert resultado.motivo == "ficha_registrada"
    assert resultado.ficha_id is not None
    assert boca.falas == []
    abertas = await fichas_abertas_da_modelo(conn, modelo_id)
    assert [f.id for f in abertas] == [resultado.ficha_id]
    assert abertas[0].valor_de(modelo_id) == Decimal("700.00")


async def test_nome_de_modelo_desconhecido_vira_pergunta_e_nao_grava(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn, f"Yasmin {uuid4().hex[:6]}")
    _, jid = await _seed_grupo(conn, modelo_id)
    fichas_antes = await _contar(conn, "fichas_de_agendamento")
    boca = _Boca()

    resultado = await processar_evento_do_grupo(
        conn, _mensagem(jid, FICHA_DO_IGOR.format(modelo="fran loira")), enviar=boca
    )

    assert resultado.motivo == "ficha_nome_desconhecido"
    assert resultado.ficha_id is None
    assert len(boca.falas) == 1
    assert "fran loira" in boca.falas[0]
    assert await _contar(conn, "fichas_de_agendamento") == fichas_antes


async def test_anuncio_livre_continua_virando_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A precedencia da ficha nao pode custar o caminho de hoje: o telefonista vai esquecer o card."""
    nome = f"Yasmin {uuid4().hex[:6]}"
    modelo_id = await _seed_modelo(conn, nome)
    _, jid = await _seed_grupo(conn, modelo_id)
    anuncio = f"Atendimento no nosso local \nCliente Gabriel \nPerfil {nome} \n700 1h"

    resultado = await processar_evento_do_grupo(conn, _mensagem(jid, anuncio), enviar=_Boca())

    assert len(resultado.vendas) == 1
    assert resultado.ficha_id is None
