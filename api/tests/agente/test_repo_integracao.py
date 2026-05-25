"""Integracao de repositorio contra o Postgres REAL — o que os fakes nao cobrem.

Valida duas coisas que `FakeConn` (resto da suite do agente) nao consegue provar:
  1. a query SQL de `carregar_mensagens` casa com o schema (`0001_schema_inicial.sql`) e
     devolve as colunas esperadas em ordem cronologica;
  2. o isolamento por par (cliente, modelo) e real no banco — a IA da modelo A nunca
     enxerga historico do mesmo cliente com a modelo B (CONTEXT.md "IA por modelo",
     agente/CLAUDE.md "Isolamento por par").

INEGOCIAVEIS (estes testes apontam pro Postgres de PROD self-hosted, vazio no piloto):
  - A conexao vem de TEST_DATABASE_URL (NAO DATABASE_URL, que o conftest forca ""). Sem ela,
    os testes PULAM via @pytest.mark.needs_db — a suite padrao e a CI nunca tocam o banco.
  - Cada teste roda numa transacao com ROLLBACK no teardown — NUNCA commit. Mesmo escrevendo,
    nada persiste: e isso que torna seguro apontar pro banco de prod.
  - O role da conexao precisa fazer BYPASS de RLS (service_role/superuser, como o backend ja
    faz): o schema tem FORCE ROW LEVEL SECURITY em tudo e a policy depende de auth.uid().
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.nos.prepare_context import carregar_mensagens


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    """Conexao psycopg3 numa transacao isolada; ROLLBACK sempre no teardown (nada persiste).

    Espelha a config de `core/db.py` no que importa para a leitura: `row_factory=dict_row`
    (sem ele `carregar_mensagens` quebra ao acessar `linha["direcao"]`) e
    `prepare_threshold=None` (Supavisor em transaction mode nao aceita prepared statements).
    """
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


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    """Modelo com o minimo de colunas NOT NULL/CHECK (0001 §5.2). Unicos via uuid p/ nao colidir."""
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


async def _seed_cliente(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    connection: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _inserir_mensagem(
    connection: AsyncConnection[dict[str, Any]],
    *,
    conversa_id: UUID,
    direcao: str,
    conteudo: str,
    created_at: datetime,
) -> UUID:
    """Mensagem de texto (sem media_object_key, ok pela CHECK mensagens_midia_exige_object_key)."""
    mensagem_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, %s, 'texto', %s, %s, %s)
        """,
        (mensagem_id, conversa_id, direcao, conteudo, f"test-evo-{uuid4().hex}", created_at),
    )
    return mensagem_id


@pytest.mark.needs_db
async def test_carregar_mensagens_cronologica(conn: AsyncConnection[dict[str, Any]]) -> None:
    """A query casa com o schema e devolve as 3 mensagens em ordem cronologica."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)

    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    await _inserir_mensagem(
        conn, conversa_id=conversa_id, direcao="cliente", conteudo="ola", created_at=base
    )
    await _inserir_mensagem(
        conn,
        conversa_id=conversa_id,
        direcao="ia",
        conteudo="oi amor, tudo bem?",
        created_at=base + timedelta(minutes=1),
    )
    await _inserir_mensagem(
        conn,
        conversa_id=conversa_id,
        direcao="modelo_manual",
        conteudo="deixa que eu respondo",
        created_at=base + timedelta(minutes=2),
    )

    linhas = await carregar_mensagens(conn, str(cliente_id), str(modelo_id))

    # 3 linhas, ordem cronologica (mais antiga primeiro), como prepare_context espera.
    assert [linha["direcao"] for linha in linhas] == ["cliente", "ia", "modelo_manual"]
    assert [linha["conteudo"] for linha in linhas] == [
        "ola",
        "oi amor, tudo bem?",
        "deixa que eu respondo",
    ]
    # created_at estritamente crescente confirma o reverse() sobre o ORDER BY DESC.
    assert linhas[0]["created_at"] < linhas[1]["created_at"] < linhas[2]["created_at"]
    # Colunas exatamente as que traduzir_mensagens consome — a query casa com o schema.
    assert set(linhas[0].keys()) == {
        "id",
        "direcao",
        "tipo",
        "conteudo",
        "media_object_key",
        "created_at",
    }


@pytest.mark.needs_db
async def test_isolamento_por_par(conn: AsyncConnection[dict[str, Any]]) -> None:
    """MESMO cliente, duas modelos: carregar pela modelo A nao traz nada da modelo B."""
    cliente_id = await _seed_cliente(conn)
    modelo_a = await _seed_modelo(conn)
    modelo_b = await _seed_modelo(conn)
    conversa_a = await _seed_conversa(conn, cliente_id, modelo_a)
    conversa_b = await _seed_conversa(conn, cliente_id, modelo_b)

    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    await _inserir_mensagem(
        conn, conversa_id=conversa_a, direcao="cliente", conteudo="ola modelo A", created_at=base
    )
    await _inserir_mensagem(
        conn, conversa_id=conversa_b, direcao="cliente", conteudo="ola modelo B", created_at=base
    )

    linhas_a = await carregar_mensagens(conn, str(cliente_id), str(modelo_a))

    assert [linha["conteudo"] for linha in linhas_a] == ["ola modelo A"]
    # Nenhuma mensagem do par (cliente, modelo B) vaza no contexto da modelo A.
    assert all("modelo B" not in linha["conteudo"] for linha in linhas_a)
