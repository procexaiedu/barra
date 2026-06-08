"""F0.9 — Lembrete de fechamento: reenvio em intervalos + Handoff após silêncio, provados
isolados contra o Postgres real (gêmeo de `test_lembrete_valor_skip_locked.py`).

`test_lembrete_valor.py` usa `FakeConn` e **fabrica** o campo `acao`/`toques` do alvo — prova só
o *despacho* (acao=enviar → card; acao=escalar → handoff), não a decisão. `..._skip_locked.py`
roda o SQL real, mas só na **seleção de alvos** (toques=0 → primeiro card; tolerância). Faltava o
miolo do item: contra o banco real, exercitar pela porta `cobrar_valor_final` ponta a ponta —

  - **reenvio**: card anterior além do intervalo (`< max` toques) dispara um novo card;
  - **gate do intervalo**: card recente (dentro do intervalo) NÃO reenvia;
  - **handoff após silêncio**: atingido `max_toques`, escala — abre escalada (`OBS_ESCALADA`,
    Fernando) e pausa a IA (`ia_pausada=true`), **sem** enviar card, mantendo `Em_execucao`
    (nunca Perdido por silêncio);
  - **idempotência**: com escalada aberta, a varredura seguinte não abre um 2º handoff.

A contagem de toques e o intervalo vivem no SQL real (`count(*)`/`max(created_at)` de
`envios_evolution` + `make_interval`), por isso `needs_db` — um `FakeConn` devolveria o que lhe
dão e não provaria nada disso. ROLLBACK sempre na fixture; nada commita.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.lembrete_valor import CARD_KIND, OBS_ESCALADA, _buscar_alvos, cobrar_valor_final


class _Settings:
    """Stub com só o que o lembrete lê (tolerância/intervalo/max_toques)."""

    lembrete_valor_ativo = True
    lembrete_valor_tolerancia_min = 15
    lembrete_valor_intervalo_min = 30
    lembrete_valor_max_toques = 3
    evolution_grupo_coordenacao_jid = "test@g.us"


class FakeEvolution:
    """Coleta os envios sem tocar a Evolution (não escreve em envios_evolution)."""

    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def enviar_texto(self, **kwargs: Any) -> str:
        self.envios.append(kwargs)
        return f"card-msg-{uuid4().hex}"


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


async def _seed_alvo_vencido(
    c: AsyncConnection[dict[str, Any]], *, min_vencido: int
) -> tuple[UUID, str]:
    """Atendimento Em_execucao com bloqueio vencido há `min_vencido` min e canal de coordenação
    configurado (senão `_enviar_card` viraria 'canal ausente'). Devolve (atendimento_id, instance).
    """
    modelo_id, cliente_id, conversa_id, atendimento_id, bloqueio_id = (uuid4() for _ in range(5))
    instance_id = f"test-inst-{uuid4().hex}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             evolution_instance_id, coordenacao_chat_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Lembrete",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            instance_id,
            f"grupo-coord-{uuid4().hex}@g.us",
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
    return atendimento_id, instance_id


async def _seed_card_lembrete(
    c: AsyncConnection[dict[str, Any]],
    *,
    atendimento_id: UUID,
    instance_id: str,
    enviado_ha_min: int,
) -> None:
    """Card de lembrete já enviado há `enviado_ha_min` min (1 toque em `envios_evolution`)."""
    await c.execute(
        """
        INSERT INTO barravips.envios_evolution
            (id, evolution_message_id, instance_id, remote_jid, contexto, tipo,
             atendimento_id, payload, created_at)
        VALUES (%s, %s, %s, %s, 'grupo_coordenacao', 'card', %s, %s::jsonb, %s)
        """,
        (
            uuid4(),
            f"card-{uuid4().hex}",
            instance_id,
            f"grupo-{uuid4().hex}@g.us",
            atendimento_id,
            json.dumps({"card_kind": CARD_KIND}),
            datetime.now(UTC) - timedelta(minutes=enviado_ha_min),
        ),
    )


def _envios_do(evo: FakeEvolution, atendimento_id: UUID) -> list[dict[str, Any]]:
    """Banco compartilhado: filtra os envios pelo alvo semeado (nunca conta o global)."""
    return [e for e in evo.envios if e.get("atendimento_id") == atendimento_id]


@pytest.mark.needs_db
async def test_reenvio_card_antigo_dispara_novo_card(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # 1 toque enviado há 40 min (> intervalo 30) e toques < max → reenvio. A decisão vem do SQL
    # real (count/max sobre envios_evolution + make_interval), não de um `acao` fabricado.
    atendimento_id, instance_id = await _seed_alvo_vencido(conn, min_vencido=60)
    await _seed_card_lembrete(
        conn, atendimento_id=atendimento_id, instance_id=instance_id, enviado_ha_min=40
    )

    evo = FakeEvolution()
    await cobrar_valor_final(conn, evo, _Settings())  # type: ignore[arg-type]

    enviados = _envios_do(evo, atendimento_id)
    assert len(enviados) == 1, "reenvio: card anterior além do intervalo deveria disparar 1 novo"
    assert enviados[0]["payload"] == {"card_kind": CARD_KIND}
    assert "#1" in enviados[0]["texto"]


@pytest.mark.needs_db
async def test_intervalo_respeitado_card_recente_nao_reenvia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # 1 toque enviado há 10 min (< intervalo 30): ainda dentro do intervalo → não reenvia.
    atendimento_id, instance_id = await _seed_alvo_vencido(conn, min_vencido=60)
    await _seed_card_lembrete(
        conn, atendimento_id=atendimento_id, instance_id=instance_id, enviado_ha_min=10
    )

    # O SQL exclui o alvo (acao NULL) ...
    alvos = await _buscar_alvos(conn, _Settings())  # type: ignore[arg-type]
    assert all(a["id"] != atendimento_id for a in alvos)

    # ... e a varredura ponta a ponta não manda card para ele.
    evo = FakeEvolution()
    await cobrar_valor_final(conn, evo, _Settings())  # type: ignore[arg-type]
    assert _envios_do(evo, atendimento_id) == []


@pytest.mark.needs_db
async def test_handoff_apos_maximo_abre_escalada_e_pausa_ia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # max_toques (3) cards já enviados, o último há 40 min (> intervalo) → escala.
    atendimento_id, instance_id = await _seed_alvo_vencido(conn, min_vencido=60)
    for ha_min in (90, 60, 40):
        await _seed_card_lembrete(
            conn, atendimento_id=atendimento_id, instance_id=instance_id, enviado_ha_min=ha_min
        )

    evo = FakeEvolution()
    await cobrar_valor_final(conn, evo, _Settings())  # type: ignore[arg-type]

    # Escala não envia card ...
    assert _envios_do(evo, atendimento_id) == []

    # ... abre exatamente uma escalada de valor não confirmado para Fernando ...
    esc = await conn.execute(
        """
        SELECT responsavel, observacao, fechada_em
          FROM barravips.escaladas
         WHERE atendimento_id = %s AND observacao = %s
        """,
        (atendimento_id, OBS_ESCALADA),
    )
    rows = await esc.fetchall()
    assert len(rows) == 1
    assert rows[0]["responsavel"] == "Fernando"
    assert rows[0]["fechada_em"] is None

    # ... pausa a IA, sem marcar Perdido (segue em Em_execucao até fechamento manual).
    at = await conn.execute(
        "SELECT estado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    arow = await at.fetchone()
    assert arow is not None
    assert arow["ia_pausada"] is True
    assert arow["estado"] == "Em_execucao"


@pytest.mark.needs_db
async def test_handoff_idempotente_segunda_varredura_nao_duplica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Atingido o máximo, duas varreduras seguidas não devem abrir 2 handoffs: o guard
    # NOT EXISTS (escalada aberta com OBS_ESCALADA) tira o alvo do conjunto na 2ª passada.
    atendimento_id, instance_id = await _seed_alvo_vencido(conn, min_vencido=60)
    for ha_min in (90, 60, 40):
        await _seed_card_lembrete(
            conn, atendimento_id=atendimento_id, instance_id=instance_id, enviado_ha_min=ha_min
        )

    evo = FakeEvolution()
    await cobrar_valor_final(conn, evo, _Settings())  # type: ignore[arg-type]
    await cobrar_valor_final(conn, evo, _Settings())  # type: ignore[arg-type]

    esc = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas "
        "WHERE atendimento_id = %s AND observacao = %s",
        (atendimento_id, OBS_ESCALADA),
    )
    row = await esc.fetchone()
    assert row is not None
    assert row["n"] == 1, "idempotência: a 2ª varredura não pode abrir um 2º handoff"
