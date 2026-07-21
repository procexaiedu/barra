"""Handoff manual por operador (ADR-0032, spec 0003-handoff-manual-operador.md).

`needs_db` (Postgres via TEST_DATABASE_URL), mesmo padrao de
`test_devolucao_correcao_em_execucao.py`: conn real autocommit=False + ROLLBACK sempre.
Cobre `aplicar_comando(comando="pausar_ia")` — o comando novo que pausa a IA por decisao
livre do operador, sem depender de um gatilho automatico do state machine.
"""

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.errors import ConflitoEstado
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
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
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


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    estado: str,
    ia_pausada: bool = False,
    valor_final: Decimal | None = None,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, ia_pausada, valor_final)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, %s, %s)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, ia_pausada, valor_final),
    )
    return atendimento_id


async def _ler_atendimento(c: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT estado::text AS estado, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo,
               responsavel_atual::text AS responsavel_atual
          FROM barravips.atendimentos WHERE id = %s
        """,
        (aid,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _escaladas_abertas(c: AsyncConnection[dict[str, Any]], aid: UUID) -> list[dict[str, Any]]:
    res = await c.execute(
        "SELECT id, tipo::text AS tipo, responsavel::text AS responsavel "
        "FROM barravips.escaladas WHERE atendimento_id = %s AND fechada_em IS NULL",
        (aid,),
    )
    return list(await res.fetchall())


async def _tem_evento(c: AsyncConnection[dict[str, Any]], aid: UUID, tipo: str) -> bool:
    res = await c.execute(
        "SELECT 1 FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s LIMIT 1",
        (aid, tipo),
    )
    return await res.fetchone() is not None


# --- pausar_ia -----------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_pausar_ia_pausa_com_motivo_e_tipo_proprios(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Pausa manual seta ia_pausada=true com motivo distinto dos gatilhos automaticos, abre
    escalada tipo pausa_manual_operador e registra evento."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Qualificado",
    )

    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="pausar_ia",
        payload={"observacao": "resposta ruim, assumindo"},
    )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["ia_pausada"] is True
    assert a["ia_pausada_motivo"] == "pausa_manual_operador"
    assert a["estado"] == "Qualificado"  # pausa manual nao mexe no estado comercial

    escaladas = await _escaladas_abertas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["tipo"] == "pausa_manual_operador"
    assert await _tem_evento(conn, atendimento_id, "handoff_aberto")


@pytest.mark.needs_db
async def test_pausar_ia_idempotente_quando_ja_pausado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Pausar um atendimento ja pausado nao quebra nem duplica a escalada aberta."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Qualificado",
    )

    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="pausar_ia",
        payload={"observacao": "primeira pausa"},
    )
    # Segunda chamada, atendimento ja pausado: nao deve lancar nem abrir 2a escalada.
    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="pausar_ia",
        payload={"observacao": "segunda pausa"},
    )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["ia_pausada"] is True
    assert a["ia_pausada_motivo"] == "pausa_manual_operador"
    escaladas = await _escaladas_abertas(conn, atendimento_id)
    assert len(escaladas) == 1  # nao duplicou


@pytest.mark.needs_db
async def test_pausar_ia_rejeita_atendimento_finalizado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Fechado",
        valor_final=Decimal("1000"),
    )
    with pytest.raises(ConflitoEstado):
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=atendimento_id,
            comando="pausar_ia",
            payload={},
        )


@pytest.mark.needs_db
async def test_pausar_depois_devolucao_reativa_normalmente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Devolucao (ja existente) fecha a escalada de pausa manual e despausa a IA."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Qualificado",
    )

    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="pausar_ia",
        payload={},
    )
    await aplicar_comando(
        conn,
        origem="grupo_coordenacao",
        autor="modelo",
        atendimento_id=atendimento_id,
        comando="devolver_para_ia",
        payload={},
    )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["ia_pausada"] is False
    assert a["ia_pausada_motivo"] is None
    assert a["responsavel_atual"] == "IA"
    assert len(await _escaladas_abertas(conn, atendimento_id)) == 0


@pytest.mark.needs_db
async def test_recorrencia_nasce_com_ia_ativa_apos_pausa_manual(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A pausa manual e escopada ao Atendimento (ADR-0032): um atendimento novo do mesmo par
    (recorrencia) nasce com ia_pausada=false, independente da pausa do atendimento anterior."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_anterior_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Qualificado",
    )
    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_anterior_id,
        comando="pausar_ia",
        payload={},
    )
    assert (await _ler_atendimento(conn, atendimento_anterior_id))["ia_pausada"] is True

    # Atendimento novo do mesmo par (cliente, modelo) — nasce com o default da coluna.
    novo_atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Novo",
    )

    assert (await _ler_atendimento(conn, novo_atendimento_id))["ia_pausada"] is False
