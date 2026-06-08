"""F0.8 — atômico `Em_execucao → Fechado` pelo comando da modelo respondendo o card.

Critério (roadmap F0.8): `fechado [valor]` respondendo card → **Fechado** + **Valor final**
gravado + **bloqueio concluído**, provado no Postgres real. É o gatilho isolado da venda
fechada pela modelo no grupo de Coordenação (CONTEXT.md "Registro de resultado": comando da
modelo é efetivo imediatamente; "Bloqueio": Fechado → concluido). A costura webhook→estado
completa é F1.1; aqui exercitamos o núcleo de serviço (`aplicar_comando`) + o trigger
`sync_bloqueio_estado`, na mesma porta que o webhook chama ao resolver um card.

`needs_db` (Postgres via TEST_DATABASE_URL): o estado terminal vive no UPDATE do atendimento e
o bloqueio é sincronizado por **trigger** de banco (`sync_bloqueio_estado`); um `FakeConn` não
dispara trigger nem prova a transição. Padrão dos demais testes de integração: conn real
autocommit=False + ROLLBACK sempre.
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

from barra.core.errors import EntradaInvalida
from barra.dominio.escaladas.service import aplicar_comando


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


# --- seeds (espelham test_devolucao_correcao_em_execucao) ------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["interno", "externo"],
            Decimal("40"),
        ),
    )
    return modelo_id


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento_em_execucao(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    tipo: str = "interno",
) -> UUID:
    """Atendimento engajado: Em_execucao, IA pausada (modelo conduz), sem valor ainda."""
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, ia_pausada, ia_pausada_motivo, responsavel_atual)
        VALUES (%s, %s, %s, %s, 'Em_execucao'::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, true,
                'modelo_em_atendimento'::barravips.ia_pausada_motivo_enum, 'modelo')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, tipo),
    )
    return atendimento_id


async def _seed_bloqueio_em_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
) -> UUID:
    """Bloqueio vinculado em curso (em_atendimento), como num atendimento Em_execucao."""
    bloqueio_id = uuid4()
    inicio = datetime.now(UTC) - timedelta(minutes=30)
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'em_atendimento'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, inicio + timedelta(hours=1)),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return bloqueio_id


async def _ler_atendimento(c: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT estado::text AS estado, valor_final, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo,
               responsavel_atual::text AS responsavel_atual
          FROM barravips.atendimentos WHERE id = %s
        """,
        (aid,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _estado_bloqueio(c: AsyncConnection[dict[str, Any]], bid: UUID) -> str:
    res = await c.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bid,)
    )
    row = await res.fetchone()
    assert row is not None
    return str(row["estado"])


async def _tem_evento(c: AsyncConnection[dict[str, Any]], aid: UUID, tipo: str) -> bool:
    res = await c.execute(
        "SELECT 1 FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s LIMIT 1",
        (aid, tipo),
    )
    return await res.fetchone() is not None


# --- F0.8: o gatilho isolado -----------------------------------------------------------------


@pytest.mark.needs_db
async def test_fechado_card_em_execucao_fecha_grava_valor_e_conclui_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`fechado [valor]` respondendo card (modelo, grupo) → Fechado + Valor final + bloqueio
    concluido. Os 3 efeitos do critério F0.8 num único gatilho atômico."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_em_execucao(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    bloqueio_id = await _seed_bloqueio_em_atendimento(
        conn, modelo_id=modelo_id, atendimento_id=atendimento_id
    )
    # pre-condicao explicita: bloqueio em curso, atendimento ainda aberto.
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"

    # mesma porta que o webhook chama ao resolver um card de Coordenacao (autor=modelo).
    resultado = await aplicar_comando(
        conn,
        origem="grupo_coordenacao",
        autor="modelo",
        atendimento_id=atendimento_id,
        comando="registrar_fechado",
        payload={"valor_final": "1500"},
    )

    assert resultado.estado == "Fechado"

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Fechado"
    assert a["valor_final"] == Decimal("1500")
    # bloqueio vinculado concluido pelo trigger sync_bloqueio_estado.
    assert await _estado_bloqueio(conn, bloqueio_id) == "concluido"
    # despausa a IA no encerramento (CONTEXT.md "Registro de resultado").
    assert a["ia_pausada"] is False
    assert a["ia_pausada_motivo"] is None
    # auditoria do Financeiro + transicao.
    assert await _tem_evento(conn, atendimento_id, "fechado_registrado")
    assert await _tem_evento(conn, atendimento_id, "transicao_estado")


@pytest.mark.needs_db
async def test_fechado_sem_valor_nao_fecha_nem_conclui_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`fechado` sem valor não encerra (CONTEXT.md: fechamento exige Valor final): erro, nada
    muda — atendimento segue Em_execucao e o bloqueio segue em_atendimento. Tranca o "+ Valor
    final" como obrigatório, não cosmético."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento_em_execucao(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    bloqueio_id = await _seed_bloqueio_em_atendimento(
        conn, modelo_id=modelo_id, atendimento_id=atendimento_id
    )

    with pytest.raises(EntradaInvalida):
        await aplicar_comando(
            conn,
            origem="grupo_coordenacao",
            autor="modelo",
            atendimento_id=atendimento_id,
            comando="registrar_fechado",
            payload={},
        )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Em_execucao"
    assert a["valor_final"] is None
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"
