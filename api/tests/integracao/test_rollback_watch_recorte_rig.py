"""Os gatilhos de rollback contam CLIENTE REAL, não o rig de teste.

O grupo Playground (`...@g.us`) está no JID permitido e vira conversa/mensagem como qualquer
outra; provocação adversarial ali ("vc é robô?", jailbreak de teste) inflava os gatilhos e podia
disparar rollback de um piloto saudável. `needs_db` de propósito: o que está sob teste são os
JOINs até `conversas.evolution_chat_id`, que só o Postgres sabe executar — e SQL quebrado num cron
diário só apareceria em produção. ROLLBACK sempre (banco compartilhado).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.rollback_watch import (
    _SQL_MSGS_CLIENTE,
    contar_conversas_com_acusacao,
)

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


async def _seed_acusacao(c: AsyncConnection[dict[str, Any]], chat_id: str) -> UUID:
    """Uma conversa com UMA mensagem de cliente acusando — o `chat_id` decide se é rig ou real."""
    modelo_id, cliente_id, conversa_id = (uuid4() for _ in range(3))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Rig", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, chat_id),
    )
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, 'cliente', 'texto', %s, %s)
        """,
        (conversa_id, "vc é robô?", f"test-evo-{uuid4().hex}"),
    )
    return conversa_id


async def _acusacoes_da_janela(c: AsyncConnection[dict[str, Any]]) -> set[UUID]:
    res = await c.execute(_SQL_MSGS_CLIENTE, (7,))
    linhas = list(await res.fetchall())
    assert contar_conversas_com_acusacao(linhas) == len({m["conversa_id"] for m in linhas}), (
        "toda mensagem semeada acusa — o detector puro é coberto no teste unit"
    )
    return {m["conversa_id"] for m in linhas}


async def test_acusacao_de_cliente_real_conta(conn: AsyncConnection[dict[str, Any]]) -> None:
    conversa_id = await _seed_acusacao(conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net")

    assert conversa_id in await _acusacoes_da_janela(conn)


async def test_acusacao_no_grupo_de_rig_nao_conta(conn: AsyncConnection[dict[str, Any]]) -> None:
    conversa_id = await _seed_acusacao(conn, f"120363{uuid4().hex[:12]}@g.us")

    assert conversa_id not in await _acusacoes_da_janela(conn)
