"""Integração determinística dos 3 gaps de comando/timer (checklist E2E secoes 12/13/7-11).

`needs_db` (Postgres via TEST_DATABASE_URL), padrao dos demais testes de integracao:
conn real autocommit=False + ROLLBACK sempre. Cobre funcoes que existiam sem teste:
- `_devolver_para_ia`   (H-02/H-03): IA assume -> despausa + fecha escaladas abertas.
- `_corrigir_registro`  (Corrigir resultado): Fechado<->Perdido + sync do bloqueio vinculado.
- `confirmar_em_execucao` (E-06): cron externo Confirmado -> Em_execucao na hora do bloqueio.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.errors import ConflitoEstado
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff, aplicar_comando
from barra.workers.timeouts import confirmar_em_execucao


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


# --- seeds (espelham test_foto_portaria) -----------------------------------------------------


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
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    estado: str,
    tipo: str = "interno",
    ia_pausada: bool = False,
    valor_final: Decimal | None = None,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, ia_pausada, valor_final)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, %s, %s)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, tipo, ia_pausada, valor_final),
    )
    return atendimento_id


async def _seed_bloqueio(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    inicio: datetime,
    fim: datetime,
    estado: str,
) -> UUID:
    bloqueio_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, fim, estado),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return bloqueio_id


async def _ler_atendimento(c: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT estado::text AS estado, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo,
               responsavel_atual::text AS responsavel_atual,
               motivo_perda::text AS motivo_perda
          FROM barravips.atendimentos WHERE id = %s
        """,
        (aid,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _estado_bloqueio(c: AsyncConnection[dict[str, Any]], bid: UUID) -> str:
    res = await c.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bid,)
    )
    row = await res.fetchone()
    assert row is not None
    return str(row["estado"])


async def _tem_evento(c: AsyncConnection[dict[str, Any]], aid: UUID, tipo: str) -> bool:
    res = await c.execute(
        "SELECT 1 FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s LIMIT 1",
        (aid, tipo),
    )
    return await res.fetchone() is not None


# --- 1. devolucao para IA (H-02/H-03) --------------------------------------------------------


@pytest.mark.needs_db
async def test_devolver_para_ia_despausa_e_fecha_escalada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """IA assume: despausa, responsavel_atual=IA, fecha as escaladas abertas, registra evento."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Qualificado",
    )
    # handoff real abre escalada + pausa a IA.
    await abrir_handoff(
        conn,
        atendimento_id=atendimento_id,
        responsavel="modelo",
        tipo=TipoEscalada.fora_de_oferta,
        resumo_operacional="cliente pediu abaixo do piso",
        acao_esperada="modelo decide",
        origem="agente",
        autor="IA",
    )
    assert (await _ler_atendimento(conn, atendimento_id))["ia_pausada"] is True

    await aplicar_comando(
        conn,
        origem="grupo_coordenacao",
        autor="modelo",
        atendimento_id=atendimento_id,
        comando="devolver_para_ia",
        payload={},
    )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["ia_pausada"] is False
    assert a["ia_pausada_motivo"] is None
    assert a["responsavel_atual"] == "IA"
    assert a["estado"] == "Qualificado"  # devolucao nao mexe no estado comercial
    # escalada aberta foi fechada
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas "
        "WHERE atendimento_id = %s AND fechada_em IS NULL",
        (atendimento_id,),
    )
    abertas = await res.fetchone()
    assert abertas is not None and abertas["n"] == 0
    assert await _tem_evento(conn, atendimento_id, "devolucao_para_ia")


@pytest.mark.needs_db
async def test_devolver_para_ia_rejeita_finalizado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Atendimento Fechado nao pode ser devolvido para a IA (guard de estado)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Fechado",
        valor_final=Decimal("1000"),
    )
    with pytest.raises(ConflitoEstado):
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=atendimento_id,
            comando="devolver_para_ia",
            payload={},
        )


# --- 2. corrigir registro (Fechado <-> Perdido + sync de bloqueio) ---------------------------


@pytest.mark.needs_db
async def test_corrigir_registro_fechado_para_perdido_cancela_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Corrige Fechado->Perdido: estado/motivo atualizados, bloqueio concluido -> cancelado,
    e emite perdido_registrado (porta do Financeiro)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Fechado",
        valor_final=Decimal("1000"),
    )
    inicio = datetime.now(UTC) - timedelta(hours=3)
    bloqueio_id = await _seed_bloqueio(
        conn,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        estado="concluido",
    )

    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="corrigir_registro",
        payload={
            "novo_resultado": "Perdido",
            "motivo": "preco",
            "confirmar_alteracao_bloqueio_finalizado": True,
        },
    )

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Perdido"
    assert a["motivo_perda"] == "preco"
    assert await _estado_bloqueio(conn, bloqueio_id) == "cancelado"
    assert await _tem_evento(conn, atendimento_id, "perdido_registrado")
    assert await _tem_evento(conn, atendimento_id, "correcao_registro")


@pytest.mark.needs_db
async def test_corrigir_registro_bloqueio_finalizado_exige_confirmacao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem confirmar_alteracao_bloqueio_finalizado, alterar bloqueio concluido falha (guard)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Fechado",
        valor_final=Decimal("1000"),
    )
    inicio = datetime.now(UTC) - timedelta(hours=3)
    await _seed_bloqueio(
        conn,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        estado="concluido",
    )
    with pytest.raises(ConflitoEstado):
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=atendimento_id,
            comando="corrigir_registro",
            payload={"novo_resultado": "Perdido", "motivo": "preco"},
        )


# --- 3. confirmar_em_execucao (E-06) ---------------------------------------------------------


@pytest.mark.needs_db
async def test_confirmar_em_execucao_externo_no_horario(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Externo Confirmado + bloqueio cujo inicio ja passou -> Em_execucao + bloqueio em_atendimento."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Confirmado",
        tipo="externo",
    )
    inicio = datetime.now(UTC) - timedelta(minutes=10)
    bloqueio_id = await _seed_bloqueio(
        conn,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        estado="bloqueado",
    )

    n = await confirmar_em_execucao(conn)

    assert n >= 1
    assert (await _ler_atendimento(conn, atendimento_id))["estado"] == "Em_execucao"
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"


@pytest.mark.needs_db
async def test_confirmar_em_execucao_ignora_bloqueio_futuro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Bloqueio que ainda nao comecou nao deve transicionar o atendimento."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Confirmado",
        tipo="externo",
    )
    inicio = datetime.now(UTC) + timedelta(hours=2)
    bloqueio_id = await _seed_bloqueio(
        conn,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        estado="bloqueado",
    )

    await confirmar_em_execucao(conn)

    assert (await _ler_atendimento(conn, atendimento_id))["estado"] == "Confirmado"
    assert await _estado_bloqueio(conn, bloqueio_id) == "bloqueado"


@pytest.mark.needs_db
async def test_confirmar_em_execucao_remoto_no_horario(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Remoto (video chamada, ADR 0021) em Aguardando_confirmacao + bloqueio cujo inicio ja passou
    -> Em_execucao, IA pausada (modelo_em_atendimento), bloqueio em_atendimento e escalada
    'video_chamada' que hospeda o card."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo="remoto",
        ia_pausada=False,
    )
    inicio = datetime.now(UTC) - timedelta(minutes=10)
    bloqueio_id = await _seed_bloqueio(
        conn,
        modelo_id=modelo_id,
        atendimento_id=atendimento_id,
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        estado="bloqueado",
    )

    n = await confirmar_em_execucao(conn)

    assert n >= 1
    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Em_execucao"
    assert a["ia_pausada"] is True
    assert a["ia_pausada_motivo"] == "modelo_em_atendimento"
    assert a["responsavel_atual"] == "modelo"
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"

    # Escalada 'video_chamada' para a modelo hospeda o card "Hora da vídeo chamada".
    res = await conn.execute(
        "SELECT tipo::text AS tipo, responsavel::text AS responsavel "
        "FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["tipo"] == "video_chamada"
    assert esc["responsavel"] == "modelo"
