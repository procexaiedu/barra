"""Serviço de agenda: reserva de slot (bloqueio prévio) ao entrar em Aguardando_confirmacao.

Compartilhado por `registrar_extracao` (fluxo interno, M3d) e `pedir_pix_deslocamento`
(fluxo externo, M3e): ambos reservam o slot da modelo no mesmo ponto do funil. O bloqueio
nasce `estado='bloqueado'`, `origem='ia'`; o timeout de 24h o cancela se a confirmação
(foto de portaria / Pix) nunca vier (07 §4).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

# Operação roda em horário de Brasília: data_desejada (date) + horario_desejado (time) são
# locais. Combinar com BRT evita o bug naive-vs-aware contra a coluna timestamptz (mesmo
# tratamento de painel/routes.py:_calcular_previsao; memória deploy_e_topologia_prod).
BRT = timezone(timedelta(hours=-3))

DURACAO_PADRAO_HORAS = 1  # fallback quando atendimento.duracao_horas é NULL


class ConflitoAgenda(Exception):
    """Slot já reservado por outra conversa da mesma modelo (EXCLUDE de bloqueios)."""


async def criar_bloqueio_previo(conn: AsyncConnection[Any], *, atendimento: dict[str, Any]) -> None:
    """Reserva o slot do `atendimento` como bloqueio prévio (`bloqueado`/`ia`).

    `inicio = data_desejada + horario_desejado`; `fim = inicio + (duracao_horas ou padrão)`.
    Serializa booking concorrente da mesma modelo com `pg_advisory_xact_lock` (mesmo padrão
    do trigger `gen_numero_curto`, 0001:193) e conta com a EXCLUDE constraint
    `bloqueios_sem_sobreposicao` (0001:515) como backstop. Sobreposição com slot ativo de
    outra conversa levanta `ConflitoAgenda` (recuperável: a IA re-oferta outro horário).
    """
    inicio = datetime.combine(
        atendimento["data_desejada"], atendimento["horario_desejado"], tzinfo=BRT
    )
    duracao = atendimento["duracao_horas"] or DURACAO_PADRAO_HORAS
    fim = inicio + timedelta(hours=float(duracao))

    # Serializa por modelo: dois turnos concorrentes da mesma modelo não cravam o mesmo slot.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (str(atendimento["modelo_id"]),),
    )
    try:
        res = await conn.execute(
            """
            INSERT INTO barravips.bloqueios (modelo_id, atendimento_id, inicio, fim, origem, estado)
            VALUES (%s, %s, %s, %s, 'ia', 'bloqueado')
            RETURNING id
            """,
            (atendimento["modelo_id"], atendimento["id"], inicio, fim),
        )
        row = await res.fetchone()
    except ExclusionViolation as exc:
        raise ConflitoAgenda("Slot já reservado por outra conversa da modelo.") from exc
    assert row is not None

    # Back-link da FK circular: sem ele o trigger sync_bloqueio_estado e os crons de agenda
    # (que leem atendimentos.bloqueio_id) nunca tocam neste bloqueio (precedente em routes.py).
    await conn.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (row["id"], atendimento["id"]),
    )
