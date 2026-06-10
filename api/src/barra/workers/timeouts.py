"""Workers deterministicos de timeout e transicao cron."""

from typing import Any
from uuid import uuid5

from arq import ArqRedis
from psycopg import AsyncConnection

from barra.agente._canned import escolher_reengajamento
from barra.core.metrics import REENGAJAMENTO, TIMEOUTS
from barra.settings import Settings
from barra.workers.coordenador import NS_TURNO


async def aplicar_timeout_longo(conn: AsyncConnection[Any]) -> int:
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id, a.bloqueio_id, a.estado AS estado_anterior
                FROM barravips.atendimentos a
                LEFT JOIN LATERAL (
                  SELECT max(created_at) AS ultima_cliente
                    FROM barravips.mensagens m
                   WHERE m.atendimento_id = a.id AND m.direcao = 'cliente'
                ) msg ON true
               WHERE a.estado IN ('Novo', 'Triagem', 'Qualificado', 'Aguardando_confirmacao')
                 AND a.ia_pausada = false
                 AND COALESCE(msg.ultima_cliente, a.created_at) < now() - interval '24 hours'
               FOR UPDATE OF a SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Perdido',
                     motivo_perda = 'sumiu',
                     fonte_decisao_ultima_transicao = 'auto_timeout'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id, alvo.estado_anterior
            ),
            cancel_bloqueio AS (
              UPDATE barravips.bloqueios b
                 SET estado = 'cancelado'
                FROM alvo
               WHERE b.id = alvo.bloqueio_id
                 AND b.estado NOT IN ('em_atendimento', 'concluido')
              RETURNING b.id
            ),
            evt_transicao AS (
              INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
              SELECT id, 'transicao_estado', 'cron', 'sistema',
                     jsonb_build_object('de', estado_anterior, 'para', 'Perdido', 'fonte', 'auto_timeout')
                FROM upd
              RETURNING id
            )
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            SELECT id, 'perdido_registrado', 'cron', 'sistema', '{"fonte":"auto_timeout"}'::jsonb
              FROM upd
            RETURNING atendimento_id
            """
        )
        rows = await result.fetchall()
    TIMEOUTS.labels("longo").inc(len(rows))
    return len(rows)


async def aplicar_timeout_interno(conn: AsyncConnection[Any]) -> int:
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT id, bloqueio_id, estado AS estado_anterior
                FROM barravips.atendimentos
               WHERE tipo_atendimento = 'interno'
                 AND estado = 'Aguardando_confirmacao'
                 AND aviso_saida_em IS NOT NULL
                 AND foto_portaria_em IS NULL
                 AND aviso_saida_em < now() - interval '45 minutes'
               FOR UPDATE SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Perdido',
                     motivo_perda = 'sumiu',
                     fonte_decisao_ultima_transicao = 'auto_timeout_interno'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id, alvo.estado_anterior
            ),
            cancel_bloqueio AS (
              UPDATE barravips.bloqueios b
                 SET estado = 'cancelado'
                FROM alvo
               WHERE b.id = alvo.bloqueio_id
                 AND b.estado NOT IN ('em_atendimento', 'concluido')
              RETURNING b.id
            ),
            evt_transicao AS (
              INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
              SELECT id, 'transicao_estado', 'cron', 'sistema',
                     jsonb_build_object('de', estado_anterior, 'para', 'Perdido', 'fonte', 'auto_timeout_interno')
                FROM upd
              RETURNING id
            )
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            SELECT id, 'perdido_registrado', 'cron', 'sistema', '{"fonte":"auto_timeout_interno"}'::jsonb
              FROM upd
            RETURNING atendimento_id
            """
        )
        rows = await result.fetchall()
    TIMEOUTS.labels("interno").inc(len(rows))
    return len(rows)


def _dentro_da_janela(hora: int, inicio: int, fim: int) -> bool:
    """Hora atual cabe na janela [inicio, fim)? Quando fim < inicio, cruza meia-noite
    (ex.: 10-2h -> 10..23 ou 0..1)."""
    if fim > inicio:
        return inicio <= hora < fim
    if fim < inicio:
        return hora >= inicio or hora < fim
    return True  # inicio == fim: janela cobre 24h


async def reengajar_silenciosos(
    conn: AsyncConnection[Any],
    redis: ArqRedis,
    settings: Settings,
) -> int:
    """Reabre proativamente clientes que sumiram apos a cotacao (07 §4.5, ADR/CONTEXT.md).

    Atomico: CTE com FOR UPDATE SKIP LOCKED + UPDATE reengajado_em=now() garante 1 toque por
    atendimento entre execucoes concorrentes. Alvo: Triagem/Qualificado com intencao em
    cotacao/agendamento, ia_pausada=false, reengajado_em IS NULL, ultima msg do CLIENTE entre
    `reengajamento_delay_min` e 24h atras (acima de 24h o `timeout_longo` ja vai cobrir como
    Perdido/sumiu). Hora local BRT dentro de [operacao_hora_inicio, operacao_hora_fim).

    Para cada alvo, enfileira `enviar_turno` reusando a humanizacao (toque canned, sem desconto,
    nao critico). O `turno_atual:{conversa_id}` aponta o turno do reengajo -> cancel-on-new-message
    cancela o toque se o cliente responder antes do envio (05 §3.1).
    """
    if not settings.reengajamento_ativo:
        REENGAJAMENTO.labels("flag_off").inc()
        return 0

    # Hora local BRT direto do banco (single clock entre instancias do cron).
    res = await conn.execute(
        "SELECT extract(hour FROM now() AT TIME ZONE 'America/Sao_Paulo')::int AS h"
    )
    row = await res.fetchone()
    if not row or not _dentro_da_janela(
        int(row["h"]), settings.operacao_hora_inicio, settings.operacao_hora_fim
    ):
        REENGAJAMENTO.labels("sem_alvo").inc()
        return 0

    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id, a.conversa_id
                FROM barravips.atendimentos a
                LEFT JOIN LATERAL (
                  SELECT max(created_at) AS ultima_cliente
                    FROM barravips.mensagens m
                   WHERE m.atendimento_id = a.id AND m.direcao = 'cliente'
                ) msg ON true
               WHERE a.estado IN ('Triagem', 'Qualificado')
                 AND a.ia_pausada = false
                 AND a.intencao IN ('cotacao', 'agendamento')
                 AND a.reengajado_em IS NULL
                 AND msg.ultima_cliente IS NOT NULL
                 AND msg.ultima_cliente <= now() - make_interval(mins => %s)
                 AND msg.ultima_cliente >= now() - interval '24 hours'
                 FOR UPDATE OF a SKIP LOCKED
            )
            UPDATE barravips.atendimentos a
               SET reengajado_em = now()
              FROM alvo
             WHERE a.id = alvo.id
            RETURNING a.id, alvo.conversa_id
            """,
            (settings.reengajamento_delay_min,),
        )
        alvos = await result.fetchall()

    if not alvos:
        REENGAJAMENTO.labels("sem_alvo").inc()
        return 0

    for a in alvos:
        atendimento_id = str(a["id"])
        conversa_id = str(a["conversa_id"])
        turno_id = str(uuid5(NS_TURNO, f"reengajo:{atendimento_id}"))
        await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)
        await redis.enqueue_job(
            "enviar_turno",
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=[escolher_reengajamento()],
            midias=[],
            msg_ids_cliente=[],
            chars_inbound=0,
            critico=False,
            _job_id=f"reengajo:{atendimento_id}",
        )
        REENGAJAMENTO.labels("enviado").inc()

    return len(alvos)


async def confirmar_em_execucao(conn: AsyncConnection[Any]) -> int:
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id, a.bloqueio_id
                FROM barravips.atendimentos a
                JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
               WHERE a.tipo_atendimento = 'externo'
                 AND a.estado = 'Confirmado'
                 AND b.inicio <= now()
               FOR UPDATE OF a SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Em_execucao',
                     fonte_decisao_ultima_transicao = 'cron_em_execucao'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id, a.bloqueio_id
            )
            UPDATE barravips.bloqueios b
               SET estado = 'em_atendimento'
              FROM upd
             WHERE b.id = upd.bloqueio_id
            RETURNING upd.id
            """
        )
        rows = await result.fetchall()
    TIMEOUTS.labels("em_execucao").inc(len(rows))

    # Externo-pickup (ADR 0020): cliente busca a modelo — sem Pix, o atendimento espera em
    # Aguardando_confirmacao ate a hora do encontro (bloqueio.inicio). Aqui ele entra em
    # execucao COM pausa da IA (modelo_em_atendimento, como o Pix recebido faria no Uber) e a
    # escalada tipo 'cliente_busca' hospeda o card "Cliente vem te buscar", entregue pelo
    # reconciliar_cards no grupo de Coordenacao. Guards: ia_pausada=false (nao re-pausa nem
    # re-escala um atendimento ja pausado) e pix_status='nao_solicitado' (ordem inversa do ADR
    # 0020: cliente_busca marcado DEPOIS de pedir_pix nao reclassifica — o fluxo Uber vence).
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id, a.bloqueio_id
                FROM barravips.atendimentos a
                JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
               WHERE a.tipo_atendimento = 'externo'
                 AND a.cliente_busca = true
                 AND a.pix_status = 'nao_solicitado'
                 AND a.estado = 'Aguardando_confirmacao'
                 AND a.ia_pausada = false
                 AND b.inicio <= now()
               FOR UPDATE OF a SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Em_execucao',
                     ia_pausada = true,
                     ia_pausada_motivo = 'modelo_em_atendimento',
                     responsavel_atual = 'modelo',
                     fonte_decisao_ultima_transicao = 'cron_em_execucao'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id, a.bloqueio_id
            ),
            bloq AS (
              UPDATE barravips.bloqueios b
                 SET estado = 'em_atendimento'
                FROM upd
               WHERE b.id = upd.bloqueio_id AND b.estado = 'bloqueado'
              RETURNING b.id
            ),
            esc AS (
              INSERT INTO barravips.escaladas (
                atendimento_id, responsavel, tipo, motivo,
                resumo_operacional, acao_esperada
              )
              SELECT id, 'modelo', 'cliente_busca', 'Hora do encontro (cliente vem buscar)',
                     'Chegou a hora do encontro: o cliente vem te buscar.',
                     'Saia para o encontro; ao encerrar, responda o card com finalizado [valor].'
                FROM upd
              RETURNING atendimento_id
            )
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            SELECT id, 'transicao_estado', 'cron', 'sistema',
                   jsonb_build_object('de', 'Aguardando_confirmacao', 'para', 'Em_execucao',
                                      'fonte', 'cron_em_execucao', 'gatilho', 'cliente_busca')
              FROM upd
            RETURNING atendimento_id
            """
        )
        rows_pickup = await result.fetchall()
    TIMEOUTS.labels("em_execucao_pickup").inc(len(rows_pickup))
    return len(rows) + len(rows_pickup)
