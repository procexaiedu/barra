"""A volta do freio manual (issue #98): reativar a modelo não pode deixar cliente no vácuo.

Enquanto a modelo está pausada, atendimento novo nasce `ia_pausada=true` (motivo `modelo_pausada`)
— correto, é o freio. O que faltava era a metade de volta: `POST /v1/modelos/{id}/ativar` só CONTAVA
os presos, então a IA nunca voltava a responder e ninguém era avisado. Agora cada preso vira um
Handoff normal (escalada `responsavel='modelo'` → card no grupo pelo cron de reconciliação) e a IA
retorna pela Devolução de sempre (`IA assume`).

`needs_db` contra o Postgres real (TEST_DATABASE_URL), sempre com ROLLBACK: o que está sob teste é
a query que separa os baldes de pausa — enums e todos.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.modelos.routes import ativar_modelo
from barra.workers import reconciliacao
from barra.workers.coordenador import resolver_atendimento

pytestmark = pytest.mark.needs_db


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


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], status: str) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[],
                %s::barravips.modelo_status_enum)
        """,
        (modelo_id, "Modelo Volta", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"], status),
    )
    return modelo_id


async def _seed_conversa(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> UUID:
    cliente_id, conversa_id = uuid4(), uuid4()
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
    return conversa_id


async def _atendimento(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT ia_pausada, ia_pausada_motivo::text AS motivo
          FROM barravips.atendimentos WHERE id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def test_ativar_abre_handoff_por_preso(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id = await _seed_modelo(conn, "pausada")
    preso = await resolver_atendimento(conn, await _seed_conversa(conn, modelo_id))
    assert preso["ia_pausada_motivo"] == "modelo_pausada"

    resposta = await ativar_modelo(modelo_id, conn)

    assert resposta["status"] == "ativa"
    assert resposta["conversas_pausadas_pendentes"] == 1

    res = await conn.execute(
        """
        SELECT responsavel, tipo::text AS tipo, card_message_id
          FROM barravips.escaladas
         WHERE atendimento_id = %s AND fechada_em IS NULL
        """,
        (preso["id"],),
    )
    escaladas = await res.fetchall()
    assert len(escaladas) == 1
    # `responsavel='modelo'` + card_message_id NULL é exatamente o que a varredura
    # `reconciliar_cards_escalada` pesca para entregar o card no grupo de Coordenação.
    assert escaladas[0]["responsavel"] == "modelo"
    assert escaladas[0]["tipo"] == "modelo_pausada"
    assert escaladas[0]["card_message_id"] is None

    # A IA NÃO volta sozinha: segue pausada, agora como handoff comum, à espera do `IA assume`.
    depois = await _atendimento(conn, preso["id"])
    assert depois["ia_pausada"] is True
    assert depois["motivo"] == "handoff_ia"


async def test_ativar_nao_toca_modelo_em_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`modelo_em_atendimento` é a modelo COM o cliente agora (pós-Pix/pós-Foto de portaria) —
    reativar a modelo não pode abrir card nem mexer nesse atendimento."""
    modelo_id = await _seed_modelo(conn, "pausada")
    em_curso = await resolver_atendimento(conn, await _seed_conversa(conn, modelo_id))
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Confirmado', ia_pausada_motivo = 'modelo_em_atendimento'
         WHERE id = %s
        """,
        (em_curso["id"],),
    )

    resposta = await ativar_modelo(modelo_id, conn)

    assert resposta["conversas_pausadas_pendentes"] == 0
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (em_curso["id"],),
    )
    row = await res.fetchone()
    assert row is not None and row["n"] == 0
    intacto = await _atendimento(conn, em_curso["id"])
    assert intacto["ia_pausada"] is True
    assert intacto["motivo"] == "modelo_em_atendimento"


async def test_reconciliacao_pesca_a_escalada_da_reativacao(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O card só chega porque `reconciliar_cards_escalada` (cron de 1 min) varre escalada aberta
    sem `card_message_id` com `responsavel='modelo'`. Este teste roda a varredura REAL contra o
    banco — se a escalada da reativação sair de fora dessa query, o card nunca sai e o issue #98
    volta silenciosamente."""
    modelo_id = await _seed_modelo(conn, "pausada")
    preso = await resolver_atendimento(conn, await _seed_conversa(conn, modelo_id))
    await ativar_modelo(modelo_id, conn)
    # A varredura tem folga de 30s antes de agir (evita corrida com o envio inline).
    await conn.execute(
        "UPDATE barravips.escaladas SET aberta_em = now() - interval '5 minutes' WHERE "
        "atendimento_id = %s",
        (preso["id"],),
    )

    enviados: list[dict[str, Any]] = []

    async def _fake_enviar_card(ctx: dict[str, Any], **kwargs: Any) -> None:
        enviados.append(kwargs)

    monkeypatch.setattr(reconciliacao, "enviar_card", _fake_enviar_card)

    @asynccontextmanager
    async def _connection() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield conn

    class _Pool:
        connection = staticmethod(_connection)

    await reconciliacao.reconciliar_cards_escalada({"db_pool": _Pool(), "evolution": object()})

    assert [e["atendimento_id"] for e in enviados] == [str(preso["id"])]
    assert enviados[0]["tipo"] == "escalada"  # 🔔 Handoff genérico: "…ou responda *IA assume*"
