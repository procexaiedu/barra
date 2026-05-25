"""M3f — `escalar` abre handoff via mapping motivo->(tipo,responsavel) (04 §3.4, 09 §4.3).

Exercita o caminho de DB da tool `escalar`: `_executar_idempotente(...escalar...) ->
_executar_handoff -> abrir_handoff`. O `enqueue_job("enviar_card")` da tool e side-effect
POS-commit (ArqRedis) e fica fora do escopo deste teste de DB — coberto por outros testes.

Padrao needs_db de test_tools_idempotencia.py: TEST_DATABASE_URL, autocommit=False, dict_row,
prepare_threshold=None, ROLLBACK SEMPRE no teardown (nada commita no banco prod self-hosted).
Os seeds abrem a transacao externa, entao os `conn.transaction()` internos viram SAVEPOINTs.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas._idempotencia import _executar_idempotente
from barra.agente.ferramentas.escalada import _executar_handoff


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
    """Seede modelo + cliente + conversa + atendimento (estado Triagem, ia_pausada default)."""
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


async def _escalar(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID, motivo: str, turno_id: str
) -> dict[str, Any]:
    """Replica o caminho de DB da tool `escalar` (idempotente)."""
    payload = {
        "motivo": motivo,
        "resumo_operacional": f"Cenario de teste para motivo={motivo}.",
        "acao_esperada": "Decidir se devolve para IA ou assume.",
    }
    return await _executar_idempotente(
        c,
        turno_id,
        "escalar",
        0,
        payload,
        executor=lambda cc, p: _executar_handoff(cc, str(atendimento_id), p),
    )


async def _ler_atendimento(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await c.execute(
        "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _ler_escaladas(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> list[dict[str, Any]]:
    res = await c.execute(
        "SELECT responsavel::text AS responsavel, tipo::text AS tipo, observacao"
        " FROM barravips.escaladas WHERE atendimento_id = %s ORDER BY aberta_em",
        (atendimento_id,),
    )
    return await res.fetchall()


@pytest.mark.needs_db
async def test_escalar_aup_vai_para_fernando(conn: AsyncConnection[dict[str, Any]]) -> None:
    from barra.dominio.escaladas.service import mapear_bucket

    atendimento_id = await _seed_atendimento(conn)

    resultado = await _escalar(conn, atendimento_id, "disclosure_insistente", str(uuid4()))

    assert resultado["responsavel"] == "Fernando"
    assert (await _ler_atendimento(conn, atendimento_id))["ia_pausada"] is True

    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["responsavel"] == "Fernando"
    assert escaladas[0]["tipo"] == "comportamento_atipico"
    assert escaladas[0]["observacao"] == "disclosure_insistente"  # motivo literal preservado
    assert mapear_bucket("disclosure_insistente") == "defesa"


@pytest.mark.needs_db
async def test_escalar_fora_de_oferta_vai_para_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id = await _seed_atendimento(conn)

    resultado = await _escalar(conn, atendimento_id, "fora_de_oferta", str(uuid4()))

    assert resultado["responsavel"] == "modelo"
    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["responsavel"] == "modelo"
    assert escaladas[0]["tipo"] == "fora_de_oferta"


@pytest.mark.needs_db
async def test_escalar_outro_default_fernando(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id = await _seed_atendimento(conn)

    resultado = await _escalar(conn, atendimento_id, "outro", str(uuid4()))

    assert resultado["responsavel"] == "Fernando"
    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1
    assert escaladas[0]["responsavel"] == "Fernando"
    assert escaladas[0]["tipo"] == "outro"


@pytest.mark.needs_db
async def test_escalar_idempotente_nao_duplica(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id = await _seed_atendimento(conn)
    turno_id = str(uuid4())

    r1 = await _escalar(conn, atendimento_id, "jailbreak_attempt", turno_id)
    r2 = await _escalar(conn, atendimento_id, "jailbreak_attempt", turno_id)

    # 2a chamada (mesmo turno_id) devolve o resultado da 1a, sem reexecutar o handoff.
    assert r2 == r1
    escaladas = await _ler_escaladas(conn, atendimento_id)
    assert len(escaladas) == 1  # nao duplicou
