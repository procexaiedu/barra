"""Flags de disciplina (padrão A2) carimbadas no write-time (workers/envio.py).

Prova, contra o Postgres real, que:
- os writers de dominio/atendimentos/service.py materializam corretamente (`incrementar_contrapropostas`
  soma; `marcar_dia_sondado`/`marcar_book_enviado` são first-write-wins / idempotentes);
- o CONTRATO de idempotência do contador vale sob retry de envio: o INSERT da bolha usa
  `ON CONFLICT (evolution_message_id) DO NOTHING RETURNING 1`, e o incremento só acontece quando a
  linha foi de fato inserida — reprocessar o mesmo `evolution_message_id` NÃO dobra `n_contrapropostas`.

needs_db: lê/escreve o Postgres real numa transação com ROLLBACK sempre (espelha test_contexto_dinamico).
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.atendimentos.service import (
    incrementar_contrapropostas,
    marcar_book_enviado,
    marcar_dia_sondado,
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


async def _seed_atendimento(c: AsyncConnection[dict[str, Any]]) -> tuple[UUID, UUID]:
    """Semeia modelo/cliente/conversa/atendimento e devolve (atendimento_id, conversa_id)."""
    modelo_id, cliente_id, conversa_id, atendimento_id = uuid4(), uuid4(), uuid4(), uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["externo"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente"),
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
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento)
        VALUES (%s, 7, %s, %s, %s, 'Qualificado', 'externo')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id, conversa_id


async def _flags(c: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await c.execute(
        "SELECT n_contrapropostas, dia_sondado_em, book_enviado_em "
        "FROM barravips.atendimentos WHERE id = %s",
        (aid,),
    )
    return await res.fetchone() or {}


async def test_writers_materializam_e_sao_idempotentes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    aid, _ = await _seed_atendimento(conn)

    # Contador: soma a cada chamada.
    await incrementar_contrapropostas(conn, aid)
    await incrementar_contrapropostas(conn, aid)
    # Timestamps first-write-wins: 2ª chamada é no-op, preserva o 1º instante.
    await marcar_dia_sondado(conn, aid)
    await marcar_book_enviado(conn, aid)
    f1 = await _flags(conn, aid)
    await marcar_dia_sondado(conn, aid)
    await marcar_book_enviado(conn, aid)
    f2 = await _flags(conn, aid)

    assert f1["n_contrapropostas"] == 2
    assert f1["dia_sondado_em"] is not None
    assert f1["book_enviado_em"] is not None
    assert f2["dia_sondado_em"] == f1["dia_sondado_em"]  # não recarimbou
    assert f2["book_enviado_em"] == f1["book_enviado_em"]


async def _inserir_bolha_e_talvez_contar(
    c: AsyncConnection[dict[str, Any]], *, conversa_id: UUID, aid: UUID, evo_id: str, conteudo: str
) -> None:
    """Replica o padrão de workers/envio.py: INSERT idempotente + incremento SÓ se inseriu."""
    cur = await c.execute(
        """
        INSERT INTO barravips.mensagens
            (conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, 'ia', 'texto', %s, %s)
        ON CONFLICT (evolution_message_id) DO NOTHING
        RETURNING 1
        """,
        (conversa_id, aid, conteudo, evo_id),
    )
    inseriu = await cur.fetchone() is not None
    if inseriu:
        await incrementar_contrapropostas(conn=c, atendimento_id=aid)


async def test_retry_do_envio_nao_dobra_o_contador(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    aid, conversa_id = await _seed_atendimento(conn)
    evo_id = f"test-evo-{uuid4().hex}"  # mesma bolha reprocessada

    await _inserir_bolha_e_talvez_contar(
        conn, conversa_id=conversa_id, aid=aid, evo_id=evo_id, conteudo="Consigo 500 amor"
    )
    # Retry: mesmo evolution_message_id -> ON CONFLICT DO NOTHING -> RETURNING vazio -> não conta.
    await _inserir_bolha_e_talvez_contar(
        conn, conversa_id=conversa_id, aid=aid, evo_id=evo_id, conteudo="Consigo 500 amor"
    )

    assert (await _flags(conn, aid))["n_contrapropostas"] == 1
