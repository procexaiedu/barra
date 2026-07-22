"""Workers deterministicos de timeout e transicao cron."""

from typing import Any
from uuid import uuid5

from arq import ArqRedis
from psycopg import AsyncConnection

from barra.agente._canned import escolher_cancelamento_piloto, escolher_reengajamento
from barra.core.metrics import PILOTO_CANCELAMENTO, REENGAJAMENTO, TIMEOUTS
from barra.dominio.escaladas.service import aplicar_comando
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
                 -- Reserva FUTURA legítima (o prompt manda cravar encontro pra outro dia, com o
                 -- ônus de confirmar no dia sobre o cliente): não mate o slot só porque ele ficou
                 -- em silêncio até a data. Passado o horário sem comparecer, o bloqueio deixa de
                 -- ser futuro e o timeout de 24h volta a valer.
                 AND NOT EXISTS (
                   SELECT 1 FROM barravips.bloqueios b
                    WHERE b.id = a.bloqueio_id AND b.inicio > now()
                 )
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
              SELECT a.id, a.bloqueio_id, a.estado AS estado_anterior
                FROM barravips.atendimentos a
                JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
               WHERE a.tipo_atendimento = 'interno'
                 AND a.estado = 'Aguardando_confirmacao'
                 AND a.aviso_saida_em IS NOT NULL
                 AND a.foto_portaria_em IS NULL
                 AND GREATEST(a.aviso_saida_em, b.inicio) < now() - interval '45 minutes'
               FOR UPDATE OF a SKIP LOCKED
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
    """Reabre proativamente clientes que sumiram apos a cotacao (07 §4.5, ADR 0022, CONTEXT.md).

    Atomico: CTE com FOR UPDATE SKIP LOCKED + UPDATE reengajado_em=now() garante 1 toque por
    atendimento entre execucoes concorrentes. Alvo ancorado no evento REAL da cotacao (ADR 0022):
    Triagem/Qualificado, ia_pausada=false, reengajado_em IS NULL, `cotacao_enviada_em` (a IA
    apresentou o preco) entre `reengajamento_delay_min` e 24h atras (acima de 24h o `timeout_longo`
    cobre como Perdido/sumiu), e NENHUMA msg do CLIENTE depois da cotacao (silencio genuino — isso
    exclui "vou pensar", "ja marquei" etc). Hora local BRT dentro de [operacao_hora_inicio,
    operacao_hora_fim). Substitui o proxy `intencao IN ('cotacao','agendamento')`, que disparava
    antes de a IA cotar.

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
               WHERE a.estado IN ('Triagem', 'Qualificado')
                 AND a.ia_pausada = false
                 AND a.reengajado_em IS NULL
                 AND a.cotacao_enviada_em IS NOT NULL
                 AND a.cotacao_enviada_em <= now() - make_interval(mins => %s)
                 AND a.cotacao_enviada_em >= now() - interval '24 hours'
                 AND NOT EXISTS (
                   SELECT 1 FROM barravips.mensagens m
                    WHERE m.atendimento_id = a.id
                      AND m.direcao = 'cliente'
                      AND m.created_at > a.cotacao_enviada_em
                 )
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


async def cancelar_piloto_teste(
    conn: AsyncConnection[Any],
    redis: ArqRedis,
    settings: Settings,
) -> int:
    """Cancelamento automatico de seguranca do piloto de teste (ADR-0033, spec 0004).

    O piloto roda sem modelo real (anuncio generico, sem intencao de atender ninguem de verdade) --
    sem salvaguarda, um cliente real poderia negociar ate o horario combinado e mandar o Pix de
    deslocamento por um encontro que nunca vai acontecer. Gatilho por tipo (feedback Fernando
    21/07 -- cancelar 10min apos o crava matava o sinal de "iria marcar de verdade"):

    - interno: deixa o agendamento consolidar e cancela quando o cliente avisa que saiu
      (`aviso_saida_em`) OU perto do horario combinado (`bloqueios.inicio` menos
      `piloto_cancela_antes_min`) -- o que vier primeiro. Sem Pix no interno, esperar e seguro.
      O Aviso de saida e opcional: quem chega cedo sem avisar manda a Foto de portaria e transiciona
      automatico pra Em_execucao (IA pausada) -- por isso o cron TAMBEM cancela Em_execucao interno
      nao-processado (a desculpa sai na hora; `pausar_ia` e idempotente pra ja-pausado).
    - externo/remoto: 10min depois de entrar em Aguardando_confirmacao
      (`aguardando_confirmacao_em`, carimbado na transicao -- ver dominio/atendimentos/service.py
      -- e distinto de `bloqueios.inicio`, o horario do encontro em si). Nesses tipos o crava
      dispara solicitacao de Pix (deslocamento no externo, valor da chamada no remoto); o
      invariante do ADR-0033 e cancelar antes de dinheiro em jogo, entao o cancelamento cedo fica.

    Ao disparar, cancela: desculpa generica ao cliente (sorteada, evita padrao identico repetido),
    marca o Atendimento como Perdido (motivo `outro`) e pausa a IA (Handoff manual, ADR-0032).

    Atomico: `FOR UPDATE OF a SKIP LOCKED` mantem o lock das linhas alvo pela transacao INTEIRA --
    selecao, pausa da IA, marca de Perdido, cancelamento do bloqueio, eventos de auditoria e o
    carimbo `piloto_cancelado_em` saem TODOS na mesma transacao. Sem isso, uma falha a meio-caminho
    deixaria o atendimento marcado como "ja processado" (nunca mais reexaminado) sem de fato ter
    sido cancelado/pausado -- justamente o cenario que o ADR-0033 existe pra evitar. So depois do
    commit e que os efeitos de rede (mensagem ao cliente) saem, num loop separado: reenfileirar
    um job idempotente (`_job_id` deterministico) e seguro se o processo cair antes do commit
    (nada foi persistido) ou depois (o job so roda uma vez).

    A pausa da IA roda ANTES de marcar Perdido: `aplicar_comando(pausar_ia)` recusa atendimento ja
    finalizado (Fechado/Perdido). O UPDATE de Perdido, aqui, e feito DIRETO (nao via
    `aplicar_comando(registrar_perdido)`) porque esse comando reativa a IA (`ia_pausada=false`) --
    desfaria a pausa que acabamos de aplicar. Mesmo padrao dos demais timeouts (`aplicar_timeout_*`):
    UPDATE direto + cancela o bloqueio vinculado + eventos de auditoria.
    """
    if not settings.piloto_auto_cancela_ativo:
        PILOTO_CANCELAMENTO.labels("flag_off").inc()
        return 0

    async with conn.transaction():
        # LEFT JOIN: o bloqueio previo e criado na transicao p/ Aguardando_confirmacao, mas um
        # atendimento sem bloqueio (borda) nao pode travar o cron dos demais -- no interno sem
        # bloqueio o gatilho fica so no aviso de saida.
        # O braco de Em_execucao interno fecha o furo da Foto de portaria (review 22/07): cliente
        # que nao avisa e chega cedo manda a foto -> transicao automatica pra Em_execucao com IA
        # pausada, fora do funil de Aguardando_confirmacao -- sem este braco ele ficaria na
        # portaria sem desculpa, exatamente o cenario que o ADR-0033 existe pra evitar.
        result = await conn.execute(
            """
            SELECT a.id, a.conversa_id, a.estado::text AS estado_anterior
              FROM barravips.atendimentos a
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE a.aguardando_confirmacao_em IS NOT NULL
               AND a.piloto_cancelado_em IS NULL
               AND (
                     (a.estado = 'Aguardando_confirmacao' AND (
                          (a.tipo_atendimento = 'interno' AND (
                               a.aviso_saida_em IS NOT NULL
                            OR (b.inicio IS NOT NULL
                                AND b.inicio - make_interval(mins => %s) <= now())
                          ))
                       OR (a.tipo_atendimento IS DISTINCT FROM 'interno'
                           AND a.aguardando_confirmacao_em < now() - interval '10 minutes')
                     ))
                  OR (a.estado = 'Em_execucao' AND a.tipo_atendimento = 'interno')
                   )
             FOR UPDATE OF a SKIP LOCKED
            """,
            (settings.piloto_cancela_antes_min,),
        )
        alvos = await result.fetchall()

        if not alvos:
            PILOTO_CANCELAMENTO.labels("sem_alvo").inc()
            return 0

        for a in alvos:
            atendimento_id = a["id"]

            await aplicar_comando(
                conn,
                origem="cron",
                autor="sistema",
                atendimento_id=atendimento_id,
                comando="pausar_ia",
                payload={"observacao": "cancelamento automático — piloto de teste"},
            )
            await conn.execute(
                """
                UPDATE barravips.atendimentos
                   SET estado = 'Perdido',
                       motivo_perda = 'outro',
                       motivo_perda_obs = 'cancelamento automático — piloto de teste',
                       fonte_decisao_ultima_transicao = 'auto_cancelamento_piloto',
                       piloto_cancelado_em = now()
                 WHERE id = %s
                """,
                (atendimento_id,),
            )
            await conn.execute(
                """
                UPDATE barravips.bloqueios b
                   SET estado = 'cancelado'
                  FROM barravips.atendimentos a
                 WHERE a.id = %s AND b.id = a.bloqueio_id
                   AND b.estado NOT IN ('em_atendimento', 'concluido')
                """,
                (atendimento_id,),
            )
            await conn.execute(
                """
                INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
                VALUES (%s, 'transicao_estado', 'cron', 'sistema',
                        jsonb_build_object('de', %s::text, 'para', 'Perdido',
                                            'fonte', 'auto_cancelamento_piloto'))
                """,
                (atendimento_id, a["estado_anterior"]),
            )
            await conn.execute(
                """
                INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
                VALUES (%s, 'perdido_registrado', 'cron', 'sistema',
                        '{"fonte": "auto_cancelamento_piloto"}'::jsonb)
                """,
                (atendimento_id,),
            )

    for a in alvos:
        atendimento_id = a["id"]
        conversa_id = str(a["conversa_id"])
        turno_id = str(uuid5(NS_TURNO, f"cancelamento_piloto:{atendimento_id}"))
        await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)
        await redis.enqueue_job(
            "enviar_turno",
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=[escolher_cancelamento_piloto()],
            midias=[],
            msg_ids_cliente=[],
            chars_inbound=0,
            # `critico=True`: o efeito de dominio JA foi commitado (Perdido + IA pausada + bloqueio
            # cancelado) e nada mais vai falar com o cliente depois disto -- a desculpa TEM de sair.
            # Sem isto, o `enviar_turno` cancelaria a bolha em dois pontos: (a) gate de pausa no
            # fire (`ia_pausada`) e (b) cancel-on-new-message, que dispara se o cliente mandar
            # qualquer mensagem entre o enqueue e o fire (o turno leva reading/typing delay) --
            # justamente o cliente que esta esperando a confirmacao. Nos dois casos ele ficaria no
            # vacuo, com o atendimento morto e a IA muda. Critico tambem faz a falha final do envio
            # abrir handoff (dead-end, 05 §7) em vez de perder a desculpa em silencio.
            critico=True,
            _job_id=f"cancelamento_piloto:{atendimento_id}",
        )
        PILOTO_CANCELAMENTO.labels("enviado").inc()

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

    # Remoto / video chamada (ADR 0021): ninguem se desloca — o atendimento espera em
    # Aguardando_confirmacao ate a hora da chamada (bloqueio.inicio). Aqui entra em execucao COM
    # pausa da IA (modelo_em_atendimento, como o Pix recebido faria no Uber) e a escalada tipo
    # 'video_chamada' hospeda o card "Hora da vídeo chamada", entregue pelo reconciliar_cards no
    # grupo de Coordenacao. Guard ia_pausada=false (nao re-pausa nem re-escala um atendimento ja
    # pausado). O Pix antecipado do remoto (ADR 0029) NAO gateia a transicao — nunca trava por
    # Pix — entao nao filtra pix_status: na hora da chamada o card exibe o status e a modelo decide.
    async with conn.transaction():
        result = await conn.execute(
            """
            WITH alvo AS (
              SELECT a.id, a.bloqueio_id
                FROM barravips.atendimentos a
                JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
               WHERE a.tipo_atendimento = 'remoto'
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
              SELECT id, 'modelo', 'video_chamada', 'Hora da vídeo chamada',
                     'Chegou a hora da sua vídeo chamada com o cliente.',
                     'Faça a chamada; ao encerrar, responda o card com finalizado [valor].'
                FROM upd
              RETURNING atendimento_id
            )
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            SELECT id, 'transicao_estado', 'cron', 'sistema',
                   jsonb_build_object('de', 'Aguardando_confirmacao', 'para', 'Em_execucao',
                                      'fonte', 'cron_em_execucao', 'gatilho', 'video_chamada')
              FROM upd
            RETURNING atendimento_id
            """
        )
        rows_remoto = await result.fetchall()
    TIMEOUTS.labels("em_execucao_remoto").inc(len(rows_remoto))
    return len(rows) + len(rows_remoto)
