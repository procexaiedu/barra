"""REL-02 — `abrir_handoff` idempotente no nivel do banco (roadmap §3.5).

Defesa em profundidade: mesmo fora do `_executar_idempotente` (que dedupa por turno_id),
`abrir_handoff` chamado 2x para o mesmo atendimento NAO abre escalada duplicada. Cobre o
re-drain do ARQ (sem checkpointer) e o caminho direto de `intercept_disclosure`.

Padrao needs_db de test_handoff_via_escalar.py: TEST_DATABASE_URL, autocommit=False, dict_row,
prepare_threshold=None, ROLLBACK SEMPRE no teardown (nada commita no banco prod self-hosted).
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff


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


async def _seed_atendimento(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado)
        VALUES (%s, %s, %s, %s, 'Triagem')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _contar_escaladas(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> int:
    res = await c.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return int(row["n"])


async def _abrir(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID, obs: str) -> None:
    await abrir_handoff(
        c,
        atendimento_id=atendimento_id,
        responsavel="Fernando",
        tipo=TipoEscalada.comportamento_atipico,
        resumo_operacional="Cenario REL-02.",
        acao_esperada="Assumir a conversa.",
        origem="agente",
        autor="sistema",
        observacao=obs,
    )


@pytest.mark.needs_db
async def test_abrir_handoff_duplicado_nao_abre_segunda_escalada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id = await _seed_atendimento(conn)

    await _abrir(conn, atendimento_id, "jailbreak_attempt")
    # Reprocessamento (re-drain): mesma chamada, ate com observacao diferente, nao duplica
    # enquanto a primeira escalada continua aberta.
    await _abrir(conn, atendimento_id, "disclosure_insistente")

    assert await _contar_escaladas(conn, atendimento_id) == 1

    # IA segue pausada pela 1a escalada.
    res = await conn.execute(
        "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None and row["ia_pausada"] is True


@pytest.mark.needs_db
async def test_abrir_handoff_apos_fechada_reabre(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fechada a escalada anterior, um novo handoff legitimo volta a abrir (guard so olha abertas)."""
    atendimento_id = await _seed_atendimento(conn)

    await _abrir(conn, atendimento_id, "jailbreak_attempt")
    await conn.execute(
        "UPDATE barravips.escaladas SET fechada_em = now() WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    await _abrir(conn, atendimento_id, "disclosure_insistente")

    assert await _contar_escaladas(conn, atendimento_id) == 2
