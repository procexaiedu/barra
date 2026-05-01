"""Workers deterministicos de timeout e transicao cron."""

from typing import Any

from psycopg import AsyncConnection

from barra.core.metrics import TIMEOUTS


async def aplicar_timeout_longo(conn: AsyncConnection[Any]) -> int:
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id
                FROM barravips.atendimentos a
                LEFT JOIN LATERAL (
                  SELECT max(created_at) AS ultima_cliente
                    FROM barravips.mensagens m
                   WHERE m.atendimento_id = a.id AND m.direcao = 'cliente'
                ) msg ON true
               WHERE a.estado IN ('Novo', 'Triagem', 'Qualificado', 'Aguardando_confirmacao')
                 AND a.ia_pausada = false
                 AND COALESCE(msg.ultima_cliente, a.created_at) < now() - interval '24 hours'
               FOR UPDATE SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Perdido',
                     motivo_perda = 'sumiu',
                     fonte_decisao_ultima_transicao = 'auto_timeout'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id
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
              SELECT id
                FROM barravips.atendimentos
               WHERE tipo_atendimento = 'interno'
                 AND estado = 'Aguardando_confirmacao'
                 AND aviso_saida_em IS NOT NULL
                 AND foto_portaria_em IS NULL
                 AND aviso_saida_em < now() - interval '30 minutes'
               FOR UPDATE SKIP LOCKED
            ),
            upd AS (
              UPDATE barravips.atendimentos a
                 SET estado = 'Perdido',
                     motivo_perda = 'sumiu',
                     fonte_decisao_ultima_transicao = 'auto_timeout_interno'
                FROM alvo
               WHERE a.id = alvo.id
              RETURNING a.id
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
    return len(rows)
