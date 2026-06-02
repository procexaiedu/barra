"""Lembrete de fechamento — cron que cobra o valor_final da modelo (ADR-0009).

Passado o fim previsto do atendimento (`bloqueios.fim` + tolerância) e ainda em `Em_execucao`,
manda um card no grupo de Coordenação por modelo pedindo o valor final; reenvia em intervalos
fixos até `lembrete_valor_max_toques` e, sem resposta, abre handoff para Fernando.

Determinístico, sem LLM: a modelo fecha respondendo (quote) o card com o valor, pela mesma porta
`finalizado/fechado [valor]` (`webhook/parser` + `escaladas.service`). Toques/último envio e a
resolução do quote derivam de `envios_evolution` (`payload.card_kind`), sem coluna nova. O
atendimento NUNCA é auto-fechado nem marcado Perdido por silêncio — fica em `Em_execucao` até
fechamento manual (`Em_execucao` é, por design, fora do timeout de 24h).
"""

import logging
from typing import Any

from psycopg import AsyncConnection

from barra.core.evolution import EvolutionClient
from barra.core.metrics import LEMBRETE_VALOR
from barra.settings import Settings

logger = logging.getLogger(__name__)

# Marca dos cards de lembrete em envios_evolution.payload e da escalada que encerra o ciclo.
CARD_KIND = "lembrete_valor"
OBS_ESCALADA = "valor_final_nao_confirmado"


async def cobrar_valor_final(
    conn: AsyncConnection[Any],
    evolution: EvolutionClient,
    settings: Settings,
) -> int:
    """Varre atendimentos vencidos em `Em_execucao` e envia/reenvia/escala. Devolve nº de ações.

    Best-effort por alvo (o fluxo nunca trava por card): falha de um envio é logada e contada na
    métrica, sem abortar o lote nem ser contada como ação concluída.

    Tudo roda numa transação única: `_buscar_alvos` trava cada alvo (`FOR UPDATE OF a SKIP
    LOCKED`) e o lock é mantido até o card/handoff commitar, então um worker concorrente pula o
    alvo em vez de disparar o mesmo card 2x (REL-05, espelha `workers/timeouts.py`). O savepoint
    por alvo isola a falha de um envio (rollback só do seu savepoint) sem abortar o lote nem
    soltar os locks dos demais.
    """
    if not settings.lembrete_valor_ativo:
        return 0

    acoes = 0
    async with conn.transaction():
        alvos = await _buscar_alvos(conn, settings)
        for alvo in alvos:
            try:
                async with conn.transaction():  # savepoint: isola a falha de um alvo
                    if alvo["acao"] == "escalar":
                        await _escalar(conn, alvo, settings)
                        label = "escalado"
                    else:
                        await _enviar_card(conn, evolution, alvo)
                        label = "reenviado" if alvo["toques"] else "enviado"
                LEMBRETE_VALOR.labels(label).inc()
                acoes += 1
            except Exception:
                logger.exception("lembrete_valor_falha atendimento_id=%s", alvo["id"])
                LEMBRETE_VALOR.labels("falha").inc()
    return acoes


async def _buscar_alvos(conn: AsyncConnection[Any], settings: Settings) -> list[dict[str, Any]]:
    """Atendimentos em `Em_execucao` cujo bloqueio terminou (+ tolerância), com a ação a tomar.

    Toques e último envio vêm de `envios_evolution`. Já escalados (escalada aberta com
    `OBS_ESCALADA`) saem do conjunto — não recobram nem reenviam. `make_interval` aplica os
    intervalos no banco para não comparar timestamp aware/naive em Python.

    `FOR UPDATE OF a SKIP LOCKED` trava cada atendimento elegível; deve rodar na transação do
    chamador (`cobrar_valor_final`), que segura o lock até o envio commitar — daí um worker
    concorrente pular o alvo (REL-05). O `OF a` é obrigatório: sem ele o `count(*)` do LATERAL
    dispara `FOR UPDATE is not allowed with aggregate functions` (regressão do #67 em `timeouts`).
    """
    res = await conn.execute(
        """
        SELECT id, numero_curto, evolution_instance_id, coordenacao_chat_id,
               cliente_nome, toques, acao
          FROM (
            SELECT a.id, a.numero_curto, m.evolution_instance_id, m.coordenacao_chat_id,
                   c.nome AS cliente_nome,
                   t.toques,
                   CASE
                     WHEN t.toques = 0 THEN 'enviar'
                     WHEN t.toques < %s
                          AND t.ultimo < now() - make_interval(mins => %s) THEN 'enviar'
                     WHEN t.toques >= %s
                          AND t.ultimo < now() - make_interval(mins => %s) THEN 'escalar'
                     ELSE NULL
                   END AS acao
              FROM barravips.atendimentos a
              JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
              JOIN barravips.modelos m ON m.id = a.modelo_id
              JOIN barravips.clientes c ON c.id = a.cliente_id
              CROSS JOIN LATERAL (
                SELECT count(*) AS toques, max(created_at) AS ultimo
                  FROM barravips.envios_evolution e
                 WHERE e.atendimento_id = a.id
                   AND e.payload->>'card_kind' = %s
              ) t
             WHERE a.estado = 'Em_execucao'
               AND b.fim < now() - make_interval(mins => %s)
               AND NOT EXISTS (
                 SELECT 1 FROM barravips.escaladas e
                  WHERE e.atendimento_id = a.id
                    AND e.observacao = %s
                    AND e.fechada_em IS NULL
               )
             FOR UPDATE OF a SKIP LOCKED
          ) q
         WHERE q.acao IS NOT NULL
        """,
        (
            settings.lembrete_valor_max_toques,
            settings.lembrete_valor_intervalo_min,
            settings.lembrete_valor_max_toques,
            settings.lembrete_valor_intervalo_min,
            CARD_KIND,
            settings.lembrete_valor_tolerancia_min,
            OBS_ESCALADA,
        ),
    )
    return list(await res.fetchall())


async def _enviar_card(
    conn: AsyncConnection[Any],
    evolution: EvolutionClient,
    alvo: dict[str, Any],
) -> None:
    instance_id = alvo["evolution_instance_id"]
    # Grupo de Coordenacao DA MODELO dona do atendimento (nao um JID global) -- senao o card com
    # o nome do cliente da modelo B cairia no grupo de outra modelo (isolamento por par).
    grupo_jid = alvo["coordenacao_chat_id"]
    if not instance_id or not grupo_jid:
        raise RuntimeError(f"canal ausente (instance={instance_id!r} grupo={grupo_jid!r})")

    cliente = alvo["cliente_nome"] or "cliente"
    texto = (
        f"#{alvo['numero_curto']} — atendimento com {cliente} encerrado. "
        f"Qual foi o valor final cobrado? Responda este card com o valor (ex.: 1500). "
        f"Se não rolou: perdido <motivo>."
    )
    await evolution.enviar_texto(
        conn=conn,
        instance_id=instance_id,
        remote_jid=grupo_jid,
        texto=texto,
        contexto="grupo_coordenacao",
        tipo="card",
        atendimento_id=alvo["id"],
        payload={"card_kind": CARD_KIND},
    )


async def _escalar(conn: AsyncConnection[Any], alvo: dict[str, Any], settings: Settings) -> None:
    """Abre handoff para Fernando (tipo=outro). Não muda estado: fica em `Em_execucao` e some do
    conjunto na próxima varredura (escalada aberta com OBS_ESCALADA)."""
    from barra.dominio.escaladas.modelos import TipoEscalada
    from barra.dominio.escaladas.service import abrir_handoff

    await abrir_handoff(
        conn,
        atendimento_id=alvo["id"],
        responsavel="Fernando",
        tipo=TipoEscalada.outro,
        resumo_operacional=(
            f"Valor final não confirmado pela modelo após "
            f"{settings.lembrete_valor_max_toques} lembretes (atendimento #{alvo['numero_curto']})."
        ),
        acao_esperada="Confirmar o valor final com a modelo e fechar o atendimento no painel.",
        origem="cron",
        autor="sistema",
        observacao=OBS_ESCALADA,
    )
