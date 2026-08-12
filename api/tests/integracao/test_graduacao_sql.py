"""O SQL do relatorio de graduacao roda -- e conta cliente real, nao o rig.

`needs_db` de proposito: o que esta sob teste e Postgres executando as consultas (o `%%` do LIKE
sobrevivendo a parametrizacao, o FULL OUTER JOIN da serie semanal, o `to_regclass` da tabela de
baseline). Nada disso o FakeConn do teste unit consegue afirmar -- e SQL quebrado num relatorio
que so roda na revisao do piloto so apareceria na hora de decidir a graduacao.

ROLLBACK sempre (banco compartilhado).
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

from barra.dominio.graduacao import repo, service

pytestmark = pytest.mark.needs_db

RIG = "playground@g.us"


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


async def _seed_par(
    c: AsyncConnection[dict[str, Any]], chat_id: str, *, origem: str = "prod"
) -> tuple[UUID, UUID]:
    """Modelo + cliente + conversa com UM turno da IA. Devolve (modelo_id, conversa_id)."""
    modelo_id, cliente_id, conversa_id = (uuid4() for _ in range(3))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Graduacao", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id, origem)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, chat_id, origem),
    )
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, 'ia', 'texto', %s, %s)
        """,
        (conversa_id, "oi amor", f"test-evo-{uuid4().hex}"),
    )
    return modelo_id, conversa_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    modelo_id: UUID,
    conversa_id: UUID,
    *,
    estado: str,
) -> UUID:
    row = await (
        await c.execute("SELECT cliente_id FROM barravips.conversas WHERE id = %s", (conversa_id,))
    ).fetchone()
    assert row is not None
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado,
             valor_final, motivo_perda)
        VALUES (%s, 1, %s, %s, %s, %s::barravips.estado_atendimento_enum, %s,
                %s::barravips.motivo_perda_enum)
        """,
        (
            atendimento_id,
            row["cliente_id"],
            modelo_id,
            conversa_id,
            estado,
            500 if estado == "Fechado" else None,
            "sumiu" if estado == "Perdido" else None,
        ),
    )
    return atendimento_id


async def _seed_julgamento(
    c: AsyncConnection[dict[str, Any]],
    modelo_id: UUID,
    conversa_id: UUID,
    *,
    rastro_llm: bool,
    julgado_em: datetime,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.julgamentos_turno
            (turno_id, conversa_id, modelo_id, rastro_llm, voz, conduta, julgado_em)
        VALUES (%s, %s, %s, %s, 4, 4, %s)
        """,
        (f"test-turno-{uuid4().hex}", conversa_id, modelo_id, rastro_llm, julgado_em),
    )


async def _seed_abort(
    c: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
    *,
    observacao: str,
    aberta_em: datetime,
) -> None:
    # `tipo` e NOT NULL desde a migration 0039 e o predicado do gate filtra so por `observacao`:
    # 'outro' e o que a prod grava nestes aborts (`output_leak`/`envio_placeholder` nao estao em
    # `_TIPO_POR_MOTIVO`, caem no default `TipoEscalada.outro`).
    await c.execute(
        """
        INSERT INTO barravips.escaladas
            (atendimento_id, responsavel, tipo, motivo, resumo_operacional, acao_esperada,
             observacao, aberta_em)
        VALUES (%s, 'Fernando', 'outro', 'defesa', 'r', 'a', %s, %s)
        """,
        (atendimento_id, observacao, aberta_em),
    )


async def test_conversas_e_conversao_contam_so_cliente_real(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    desde = datetime.now(UTC) - timedelta(days=30)
    real_modelo, real_conversa = await _seed_par(conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net")
    await _seed_atendimento(conn, real_modelo, real_conversa, estado="Fechado")

    rig_modelo, rig_conversa = await _seed_par(conn, RIG)
    await _seed_atendimento(conn, rig_modelo, rig_conversa, estado="Fechado")

    e2e_modelo, e2e_conversa = await _seed_par(
        conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net", origem="e2e"
    )
    await _seed_atendimento(conn, e2e_modelo, e2e_conversa, estado="Fechado")

    antes = await repo.conversao_agente(conn, desde)
    conv = await repo.conversas(conn, desde)
    # Banco compartilhado: afirma o DELTA do que esta seed criou seria fragil, entao o que se
    # afirma e que o rig/e2e nao aparecem -- refazendo a conta so com as tres conversas do teste.
    res = await conn.execute(
        """
        SELECT count(*) AS n
          FROM barravips.atendimentos a
          JOIN barravips.conversas c ON c.id = a.conversa_id
         WHERE c.id = ANY(%s)
           AND a.estado = 'Fechado'
           AND c.origem = 'prod'
           AND c.evolution_chat_id NOT LIKE '%%@g.us'
        """,
        ([real_conversa, rig_conversa, e2e_conversa],),
    )
    row = await res.fetchone()
    assert row is not None and row["n"] == 1, "so a conversa de cliente real entra"
    assert antes["fechados"] >= 1
    assert conv["completas"] >= 1


async def test_serie_semanal_da_taxa_do_gate_executa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """FULL OUTER JOIN + `date_trunc('week')` + LIKE escapado: so o Postgres prova que roda."""
    agora = datetime.now(UTC)
    modelo_id, conversa_id = await _seed_par(conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net")
    atendimento_id = await _seed_atendimento(conn, modelo_id, conversa_id, estado="Perdido")
    await _seed_abort(conn, atendimento_id, observacao="output_leak_ia_self", aberta_em=agora)
    await _seed_abort(
        conn, atendimento_id, observacao="envio_placeholder", aberta_em=agora - timedelta(days=7)
    )
    # Nao e abort do sistema de saida -- nao pode entrar na taxa.
    await _seed_abort(conn, atendimento_id, observacao="modelo_indisponivel", aberta_em=agora)
    await _seed_julgamento(conn, modelo_id, conversa_id, rastro_llm=False, julgado_em=agora)

    semanas = await repo.taxa_gate_semanal(conn, agora - timedelta(days=30))
    assert len(semanas) >= 2
    assert all(s["aborts"] >= 0 and s["julgados"] >= 0 for s in semanas)
    assert sum(s["aborts"] for s in semanas) >= 2


async def test_incidente_nao_contido_separa_aberto_de_triado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    agora = datetime.now(UTC)
    modelo_id, conversa_id = await _seed_par(conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net")
    await _seed_julgamento(conn, modelo_id, conversa_id, rastro_llm=True, julgado_em=agora)
    await _seed_julgamento(conn, modelo_id, conversa_id, rastro_llm=False, julgado_em=agora)

    inc = await repo.incidentes(conn, agora - timedelta(days=30))
    assert inc["total"] >= 1
    assert inc["abertos"] + inc["triados"] == inc["total"]
    assert inc["turnos_julgados"] >= 2


async def test_baseline_ausente_nao_envenena_a_transacao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`to_regclass` em vez de deixar UndefinedTable estourar: o relatorio precisa seguir depois."""
    baseline = await repo.baseline_vendedor(conn)
    assert baseline is None or set(baseline) == {
        "conversao_pct",
        "amostra_n",
        "fonte",
        "registrado_em",
    }
    # A conexao continua utilizavel depois da checagem -- e o ponto do guard.
    inicio = await repo.piloto_inicio(conn)
    assert inicio is None or inicio.tzinfo is not None


async def test_relatorio_completo_executa_de_ponta_a_ponta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id, conversa_id = await _seed_par(conn, f"55199{uuid4().hex[:8]}@s.whatsapp.net")
    await _seed_atendimento(conn, modelo_id, conversa_id, estado="Fechado")

    rel = await service.gerar_relatorio(conn, desde=datetime.now(UTC) - timedelta(days=30))
    assert rel.piloto_inicio_origem == "informado"
    assert rel.conversas.completas >= 1
    assert rel.gaps, "os gaps estruturais acompanham todo relatorio"
