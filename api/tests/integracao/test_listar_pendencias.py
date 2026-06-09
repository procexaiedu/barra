"""Fase 4 — `listar_pendencias_modelo` (UX §6.4): o digest "o que aguarda você".

needs_db (padrão de test_enviar_card / test_lembrete_valor): TEST_DATABASE_URL, autocommit=False,
dict_row, ROLLBACK SEMPRE — nada commita no prod self-hosted.

Cobre as três origens (handoff de owner=modelo, falta_valor por Em_execucao vencido, Pix
em_revisao), a exclusão de owner=Fernando e de terminais, e a dedup por atendimento (um mesmo
atendimento em duas origens aparece uma vez, na de maior prioridade).
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

from barra.dominio.atendimentos.service import listar_pendencias_modelo


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


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             evolution_instance_id, coordenacao_chat_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Digest",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            f"test-inst-{uuid4().hex}",
            f"grupo-coord-{uuid4().hex}@g.us",
        ),
    )
    return modelo_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    numero_curto: int,
    estado: str,
    pix_status: str = "nao_solicitado",
    valor_final: int | None = None,
) -> UUID:
    # Um cliente próprio por atendimento: a Conversa é única por par (cliente, modelo), e o digest
    # lista clientes distintos da modelo — não vários atendimentos do mesmo par.
    cliente_id, conversa_id, atendimento_id = uuid4(), uuid4(), uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Digest"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    # CHECK atendimentos_fechado_exige_valor_final: Fechado precisa de valor_final.
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, pix_status, valor_final)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.pix_status_enum, %s)
        """,
        (
            atendimento_id,
            numero_curto,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            pix_status,
            valor_final,
        ),
    )
    return atendimento_id


async def _seed_escalada(
    c: AsyncConnection[dict[str, Any]],
    *,
    atendimento_id: UUID,
    responsavel: str,
    motivo: str = "Cliente pediu valor fora da tabela",
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.escaladas
            (id, atendimento_id, responsavel, tipo, motivo, resumo_operacional, acao_esperada)
        VALUES (%s, %s, %s, 'fora_de_oferta', %s, %s, %s)
        """,
        (uuid4(), atendimento_id, responsavel, motivo, "resumo", "acao"),
    )


async def _seed_bloqueio_vencido(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    min_vencido: int,
) -> None:
    bloqueio_id = uuid4()
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


@pytest.mark.needs_db
async def test_listar_pendencias_cobre_as_tres_origens_e_filtra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)

    # handoff (owner=modelo) — aparece
    a_handoff = await _seed_atendimento(
        conn, modelo_id=modelo_id, numero_curto=10, estado="Triagem"
    )
    await _seed_escalada(conn, atendimento_id=a_handoff, responsavel="modelo")

    # escalada owner=Fernando — NÃO aparece (vai pro painel, UX §9.6)
    a_fernando = await _seed_atendimento(
        conn, modelo_id=modelo_id, numero_curto=20, estado="Triagem"
    )
    await _seed_escalada(conn, atendimento_id=a_fernando, responsavel="Fernando")

    # falta_valor — Em_execucao com bloqueio vencido
    a_valor = await _seed_atendimento(
        conn, modelo_id=modelo_id, numero_curto=30, estado="Em_execucao"
    )
    await _seed_bloqueio_vencido(conn, modelo_id=modelo_id, atendimento_id=a_valor, min_vencido=60)

    # pix em_revisao — aparece
    await _seed_atendimento(
        conn,
        modelo_id=modelo_id,
        numero_curto=40,
        estado="Confirmado",
        pix_status="em_revisao",
    )

    # terminal com escalada owner=modelo aberta — NÃO aparece (Fechado)
    a_fechado = await _seed_atendimento(
        conn, modelo_id=modelo_id, numero_curto=50, estado="Fechado", valor_final=500
    )
    await _seed_escalada(conn, atendimento_id=a_fechado, responsavel="modelo")

    pendencias = await listar_pendencias_modelo(conn, modelo_id, tolerancia_min=10)

    por_numero = {p.numero_curto: p for p in pendencias}
    assert set(por_numero) == {10, 30, 40}
    assert por_numero[10].categoria == "handoff"
    assert por_numero[10].detalhe == "Cliente pediu valor fora da tabela"
    assert por_numero[30].categoria == "falta_valor"
    assert por_numero[30].encerrado_em is not None  # bloqueios.fim convertido p/ exibição
    assert por_numero[40].categoria == "pix"


@pytest.mark.needs_db
async def test_listar_pendencias_deduplica_por_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Mesmo atendimento em duas origens (pix em_revisao + escalada owner=modelo): uma linha só,
    # na de maior prioridade (handoff > pix).
    modelo_id = await _seed_modelo(conn)
    a_duplo = await _seed_atendimento(
        conn,
        modelo_id=modelo_id,
        numero_curto=60,
        estado="Confirmado",
        pix_status="em_revisao",
    )
    await _seed_escalada(conn, atendimento_id=a_duplo, responsavel="modelo")

    pendencias = await listar_pendencias_modelo(conn, modelo_id, tolerancia_min=10)

    assert len(pendencias) == 1
    assert pendencias[0].numero_curto == 60
    assert pendencias[0].categoria == "handoff"


@pytest.mark.needs_db
async def test_listar_pendencias_vazio_quando_nada_aguarda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)
    await _seed_atendimento(conn, modelo_id=modelo_id, numero_curto=70, estado="Triagem")
    pendencias = await listar_pendencias_modelo(conn, modelo_id, tolerancia_min=10)
    assert pendencias == []
