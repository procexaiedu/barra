"""ADR-0030 / spec 0001-fetiche-calculado — POST /{atendimento_id}/fetiches calcula o preço do
extra a partir do(s) programa(s) vendidos no atendimento, em vez de ler um valor cadastrado.

`needs_db` (Postgres via TEST_DATABASE_URL), mesmo padrão de test_pausar_ia.py /
test_registrar_extracao.py: conn real autocommit=False + ROLLBACK sempre. Chama a rota
`adicionar_fetiche` diretamente (mesmo padrão de test_pausar_ia.py chamando `aplicar_comando`).
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
from barra.dominio.atendimentos.routes import adicionar_fetiche
from barra.dominio.atendimentos.schemas import AdicionarFeticheRequest


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


# --- seeds (espelham test_pausar_ia / test_registrar_extracao) -------------------------------


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
    c: AsyncConnection[dict[str, Any]], *, cliente_id: UUID, modelo_id: UUID, conversa_id: UUID
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, 'Qualificado'::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _seed_fetiche(c: AsyncConnection[dict[str, Any]]) -> UUID:
    fetiche_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.fetiches (id, nome) VALUES (%s, %s)",
        (fetiche_id, f"Fetiche Teste {uuid4().hex[:8]}"),
    )
    return fetiche_id


async def _seed_modelo_fetiche(
    c: AsyncConnection[dict[str, Any]], *, modelo_id: UUID, fetiche_id: UUID, pago: bool
) -> None:
    # Semântica atual (ADR-0030, ticket 02 pendente): NULL = incluso; NOT NULL = pago, valor
    # ignorado pelo cálculo. Usamos um valor deliberadamente "errado" (R$1) para provar que o
    # cálculo NUNCA lê esta coluna quando pago=True.
    await c.execute(
        "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) VALUES (%s, %s, %s)",
        (modelo_id, fetiche_id, Decimal("1") if pago else None),
    )


async def _duracao_id_por_horas(c: AsyncConnection[dict[str, Any]], horas: str) -> UUID:
    res = await c.execute(
        "SELECT id FROM barravips.duracoes WHERE horas = %s LIMIT 1", (Decimal(horas),)
    )
    row = await res.fetchone()
    assert row is not None, f"nenhuma duracao com horas={horas} (seed 0010/20260525181816)"
    return row["id"]


async def _programa_id_qualquer(c: AsyncConnection[dict[str, Any]]) -> UUID:
    res = await c.execute("SELECT id FROM barravips.programas LIMIT 1")
    row = await res.fetchone()
    assert row is not None, "nenhum programa no catalogo global (seed 0010)"
    return row["id"]


async def _seed_atendimento_servico(
    c: AsyncConnection[dict[str, Any]],
    *,
    atendimento_id: UUID,
    programa_id: UUID,
    duracao_id: UUID,
    preco_snapshot: Decimal,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.atendimento_servicos
            (atendimento_id, programa_id, duracao_id, preco_snapshot)
        VALUES (%s, %s, %s, %s)
        """,
        (atendimento_id, programa_id, duracao_id, preco_snapshot),
    )


async def _preco_snapshot_gravado(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> Any:
    res = await c.execute(
        "SELECT preco_snapshot FROM barravips.atendimento_fetiches WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row["preco_snapshot"]


async def _setup_atendimento(c: AsyncConnection[dict[str, Any]]) -> tuple[UUID, UUID]:
    """Modelo + cliente + conversa + atendimento Qualificado. Retorna (atendimento_id, modelo_id)."""
    modelo_id = await _seed_modelo(c)
    cliente_id = await _seed_cliente(c)
    conversa_id = await _seed_conversa(c, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        c, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    return atendimento_id, modelo_id


# --- adicionar_fetiche -------------------------------------------------------------------


@pytest.mark.needs_db
async def test_fetiche_incluso_grava_preco_snapshot_null(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=False)

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    assert row["preco_snapshot"] is None
    assert await _preco_snapshot_gravado(conn, atendimento_id) is None


@pytest.mark.needs_db
async def test_fetiche_pago_servico_unico_usa_preco_hora_do_pacote(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    programa_id = await _programa_id_qualquer(conn)
    duracao_id = await _duracao_id_por_horas(conn, "1")
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=duracao_id,
        preco_snapshot=Decimal("400"),
    )

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    assert row["preco_snapshot"] == Decimal("400.00")
    assert await _preco_snapshot_gravado(conn, atendimento_id) == Decimal("400.00")


@pytest.mark.needs_db
async def test_fetiche_pago_multiplos_servicos_soma_dividido_por_max_horas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Dois serviços no mesmo atendimento: soma dos preços de tabela / MAX(duracao) — mesma
    convenção de "duração sugerida = MAX" (CONTEXT.md, Programa e duração)."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    programa_id = await _programa_id_qualquer(conn)
    duracao_1h = await _duracao_id_por_horas(conn, "1")
    duracao_2h = await _duracao_id_por_horas(conn, "2")
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=duracao_1h,
        preco_snapshot=Decimal("400"),
    )
    outro_programa_id = await _programa_id_qualquer(conn)
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=outro_programa_id,
        duracao_id=duracao_2h,
        preco_snapshot=Decimal("800"),
    )

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    # soma = 400 + 800 = 1200; MAX(horas) = 2 -> 600.
    assert row["preco_snapshot"] == Decimal("600.00")


@pytest.mark.needs_db
async def test_fetiche_pago_sem_servico_vendido_levanta_erro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)

    with pytest.raises(ConflitoEstado) as exc_info:
        await adicionar_fetiche(
            atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
        )

    assert exc_info.value.code == "CONFLITO_ESTADO"
    assert exc_info.value.message == "nenhum_servico_vendido"
