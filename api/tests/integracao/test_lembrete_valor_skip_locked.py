"""`_buscar_alvos` do Lembrete de fechamento contra o Postgres real (REL-05).

`test_lembrete_valor.py` usa `FakeConn` (não executa SQL), então não pega o
`FeatureNotSupported: FOR UPDATE is not allowed with aggregate functions` que o
`CROSS JOIN LATERAL (count(*))` + `FOR UPDATE` dispara quando o lock não é escopado em `OF a`
(mesma armadilha do #67 em `workers/timeouts.py`). Este teste roda a query real:

  - prova que `FOR UPDATE OF a SKIP LOCKED` é aceito pelo Postgres (sem FeatureNotSupported);
  - prova que o alvo semeado (Em_execucao, bloqueio vencido além da tolerância) é elegível.

A garantia de não-duplicação sob concorrência vem da cláusula `SKIP LOCKED` (asserida presente
em `test_lembrete_valor.py::test_query_alvos_tem_guardas`) + da transação que segura o lock
(`test_roda_dentro_de_transacao`); aqui o foco é a validade do SQL no banco real.

`needs_db` (Postgres via TEST_DATABASE_URL); ROLLBACK sempre na fixture — nada commita.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.lembrete_valor import _buscar_alvos


class _Settings:
    """Stub com só o que `_buscar_alvos` lê (tolerância/intervalo/max_toques)."""

    lembrete_valor_ativo = True
    lembrete_valor_tolerancia_min = 15
    lembrete_valor_intervalo_min = 30
    lembrete_valor_max_toques = 3
    evolution_grupo_coordenacao_jid = "test@g.us"


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


async def _seed_alvo_vencido(c: AsyncConnection[dict[str, Any]], *, min_vencido: int) -> UUID:
    """Atendimento Em_execucao com bloqueio cujo `fim` está `min_vencido` minutos no passado."""
    modelo_id, cliente_id, conversa_id, atendimento_id, bloqueio_id = (uuid4() for _ in range(5))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s)
        """,
        (
            modelo_id,
            "Modelo Lembrete",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            f"test-inst-{uuid4().hex}",
        ),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Lembrete"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado)
        VALUES (%s, 1, %s, %s, %s, 'Em_execucao'::barravips.estado_atendimento_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    fim = datetime.now(UTC) - timedelta(minutes=min_vencido)
    inicio = fim - timedelta(hours=2)
    await c.execute(
        """
        INSERT INTO barravips.bloqueios
            (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'em_atendimento'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, fim),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return atendimento_id


@pytest.mark.needs_db
async def test_buscar_alvos_executa_for_update_of_a_skip_locked(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Regressão: sem `OF a` esta chamada levantaria FeatureNotSupported (FOR UPDATE + count()).
    # Banco compartilhado: a query pode apanhar outros alvos reais (desfeitos pelo ROLLBACK) ->
    # assertamos sobre o registro semeado, nunca sobre a contagem global.
    atendimento_id = await _seed_alvo_vencido(conn, min_vencido=60)

    alvos = await _buscar_alvos(conn, _Settings())  # type: ignore[arg-type]

    semeado = [a for a in alvos if a["id"] == atendimento_id]
    assert len(semeado) == 1
    assert semeado[0]["acao"] == "enviar"  # toques=0 -> primeiro card
    assert semeado[0]["toques"] == 0
    assert semeado[0]["cliente_nome"] == "Cliente Lembrete"


@pytest.mark.needs_db
async def test_buscar_alvos_ignora_bloqueio_dentro_da_tolerancia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Bloqueio terminou há 5 min < tolerância (15) -> ainda não é alvo. A query roda, o WHERE
    # descarta; garante que o seed semeado NÃO aparece (sem depender da contagem global).
    atendimento_id = await _seed_alvo_vencido(conn, min_vencido=5)

    alvos = await _buscar_alvos(conn, _Settings())  # type: ignore[arg-type]

    assert all(a["id"] != atendimento_id for a in alvos)
