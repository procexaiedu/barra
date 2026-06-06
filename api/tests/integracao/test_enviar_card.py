"""M4d — `enviar_card(tipo="escalada")` envia o card no grupo e grava `escaladas.card_message_id`.

Idempotência por owner (06 §9): a 2ª execução não reenvia, pois `card_message_id` já está
preenchido. O Evolution é mockado, mas o mock NÃO pula `registrar_envio`: ele persiste em
`envios_evolution` com o `contexto`/`tipo` que o renderer passou, exatamente como o client real.
Isso é deliberado — a CHECK de `envios_evolution` (`contexto IN ('conversa_cliente',
'grupo_coordenacao')`, `tipo IN ('ia','card',...)`) só vale contra o banco real, e um fake que
devolve id sintético sem inserir deixaria passar um card com contexto/tipo inválido: em prod o
POST sai mas o INSERT estoura a CHECK, a transação reverte, `card_message_id` nunca grava e o
cron `reconciliar_cards_escalada` reenvia o card a cada minuto (duplicata no grupo).

Padrão needs_db de test_handoff_via_escalar.py: TEST_DATABASE_URL, autocommit=False, dict_row,
ROLLBACK SEMPRE no teardown — nada commita no banco prod self-hosted. Um `_FakePool` entrega a
MESMA conexão da fixture, então o `conn.transaction()` interno do card vira um SAVEPOINT dentro
da transação externa (revertida no fim).
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.evolution import registrar_envio
from barra.workers.envio import enviar_card


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


class _FakePool:
    """Pool que sempre devolve a conexão da fixture (mantém tudo numa transação revertida)."""

    def __init__(self, connection: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _FakeEvolution:
    """Mock do EvolutionClient: não toca a rede, mas persiste em `envios_evolution` via
    `registrar_envio` (como o client real) para que a CHECK de contexto/tipo seja exercida."""

    def __init__(self) -> None:
        self.envios: list[tuple[str, str]] = []

    async def enviar_texto(
        self,
        *,
        conn: AsyncConnection[dict[str, Any]],
        instance_id: str,
        remote_jid: str,
        contexto: str,
        tipo: str,
        **_: Any,
    ) -> str:
        mid = f"card-mid-{len(self.envios) + 1}"
        await registrar_envio(
            conn,
            evolution_message_id=mid,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=None,
            conversa_id=None,
            payload={},
        )
        self.envios.append((contexto, tipo))
        return mid


async def _seed_escalada(c: AsyncConnection[dict[str, Any]]) -> UUID:
    """Seede modelo (com grupo de coordenação) + cliente + conversa + atendimento + escalada."""
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             coordenacao_chat_id, evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["interno"],
            f"test-grp-{uuid4().hex}@g.us",
            f"inst-{uuid4().hex}",
        ),
    )
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Teste"),
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
        INSERT INTO barravips.atendimentos (id, cliente_id, modelo_id, conversa_id, estado)
        VALUES (%s, %s, %s, %s, 'Triagem')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    escalada_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.escaladas
            (id, atendimento_id, responsavel, tipo, motivo, resumo_operacional, acao_esperada)
        VALUES (%s, %s, 'Fernando', 'comportamento_atipico', 'disclosure_insistente', %s, %s)
        """,
        (
            escalada_id,
            atendimento_id,
            "Cliente insistindo em revelar a IA.",
            "Decidir se devolve para IA ou assume.",
        ),
    )
    return escalada_id


async def _ler_card_message_id(c: AsyncConnection[dict[str, Any]], escalada_id: UUID) -> str | None:
    res = await c.execute(
        "SELECT card_message_id FROM barravips.escaladas WHERE id = %s", (escalada_id,)
    )
    row = await res.fetchone()
    assert row is not None
    return row["card_message_id"]


@pytest.mark.needs_db
async def test_enviar_card_escalada_grava_id_e_idempotente(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    escalada_id = await _seed_escalada(conn)
    evolution = _FakeEvolution()
    ctx: dict[str, Any] = {"db_pool": _FakePool(conn), "evolution": evolution}

    await enviar_card(ctx, tipo="escalada", escalada_id=str(escalada_id))

    mid1 = await _ler_card_message_id(conn, escalada_id)
    assert mid1 is not None  # card_message_id gravado no owner
    assert len(evolution.envios) == 1
    # Contrato do card: contexto/tipo aceitos pela CHECK de envios_evolution. Com os antigos
    # ("coordenacao"/"card_escalada") o registrar_envio acima dispararia CheckViolation aqui.
    assert evolution.envios == [("grupo_coordenacao", "card")]

    # 2ª execução: card_message_id já preenchido → não reenvia (idempotência por owner).
    await enviar_card(ctx, tipo="escalada", escalada_id=str(escalada_id))

    mid2 = await _ler_card_message_id(conn, escalada_id)
    assert mid2 == mid1
    assert len(evolution.envios) == 1  # 2ª execução não reenviou
