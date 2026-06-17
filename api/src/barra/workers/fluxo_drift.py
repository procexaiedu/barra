"""Sensor autônomo de deriva de fluxo conversacional (corpus humano vs. agente).

Cron semanal, observacional (flag `fluxo_drift_ativo`, default OFF). Lê as bolhas da IA de
`barravips.mensagens` por origem (prod/e2e), rotula com o labeler de `barra.agente.fluxo`, calcula a
divergência Jensen-Shannon vs. a distribuição humana (`corpus.turnos`) e escreve no Langfuse: dataset
`fluxo-conversas` (1 item/conversa) + score `fluxo_jsd_<origem>`.

Invariante de isolamento: tudo READ-ONLY no banco; cada item do dataset é UMA conversa (um par); o
JSD é estatística agregada offline e NUNCA volta ao contexto da IA ao vivo (mesma postura do
eval_v1_score / Mapa de clientes). Langfuse self-hosted (ADR 0019).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from barra.agente.fluxo import js_divergencia, matriz_transicao, rotular_turno
from barra.core.metrics import FLUXO_DRIFT
from barra.core.tracing import garantir_dataset, registrar_score_agregado, upsert_item_dataset
from barra.settings import Settings

logger = logging.getLogger(__name__)

DATASET_FLUXO = "fluxo-conversas"
ORIGENS = ("prod", "e2e")

# Referência humana: mesma população do CLI (corpus.fluxo) — threads com cotação, não-operacionais,
# 2..10 turnos de cliente; só o lado do Vendedor (from_me) compõe o fluxo.
_SQL_REFERENCIA = """
    SELECT t.texto, t.tem_midia, t.instancia, t.remote_jid
    FROM corpus.turnos t
    JOIN corpus.threads th USING (instancia, remote_jid)
    WHERE NOT th.thread_ops AND th.tem_valor AND th.n_cli BETWEEN 2 AND 10 AND t.from_me
    ORDER BY t.instancia, t.remote_jid, t.turno_idx
"""

_SQL_AGENTE = """
    SELECT m.conversa_id, m.conteudo, m.tipo
    FROM barravips.mensagens m
    JOIN barravips.conversas c ON c.id = m.conversa_id
    WHERE m.direcao = 'ia' AND c.origem = %s
      AND m.created_at >= now() - make_interval(days => %s)
    ORDER BY m.conversa_id, m.created_at, m.id
"""


async def _distribuicao_referencia(conn: AsyncConnection[Any]) -> Counter[tuple[str, str]]:
    seqs: dict[tuple[str, str], list[str]] = defaultdict(list)
    res = await conn.execute(_SQL_REFERENCIA)
    for row in await res.fetchall():
        seqs[(row["instancia"], row["remote_jid"])].append(
            rotular_turno(row["texto"], row["tem_midia"])
        )
    return matriz_transicao(list(seqs.values()))


async def _sequencias_agente(
    conn: AsyncConnection[Any], origem: str, janela_dias: int
) -> dict[Any, list[str]]:
    seqs: dict[Any, list[str]] = defaultdict(list)
    res = await conn.execute(_SQL_AGENTE, (origem, janela_dias))
    for row in await res.fetchall():
        seqs[row["conversa_id"]].append(rotular_turno(row["conteudo"], row["tipo"] != "texto"))
    return seqs


def _janela_iso() -> str:
    ano, semana, _ = datetime.now(UTC).date().isocalendar()
    return f"{ano}-W{semana:02d}"


async def medir_fluxo_drift(conn: AsyncConnection[Any], settings: Settings) -> int:
    """Mede a deriva de fluxo por origem e escreve dataset+score no Langfuse. Retorna nº de conversas."""
    if not settings.fluxo_drift_ativo:
        for origem in ORIGENS:
            FLUXO_DRIFT.labels(origem, "flag_off").inc()
        return 0

    ref = await _distribuicao_referencia(conn)
    garantir_dataset(DATASET_FLUXO)
    janela = _janela_iso()
    total = 0

    for origem in ORIGENS:
        seqs = await _sequencias_agente(conn, origem, settings.fluxo_drift_janela_dias)
        if not seqs:
            FLUXO_DRIFT.labels(origem, "sem_dado").inc()
            continue

        jsd = js_divergencia(matriz_transicao(list(seqs.values())), ref)
        for conversa_id, atos in seqs.items():
            upsert_item_dataset(
                DATASET_FLUXO,
                f"{origem}:{conversa_id}",
                {"origem": origem, "atos": atos, "n_turnos": len(atos), "janela": janela},
            )
        registrar_score_agregado(f"fluxo_jsd_{origem}", jsd, janela=janela)
        registrar_score_agregado(f"fluxo_n_conversas_{origem}", float(len(seqs)), janela=janela)
        FLUXO_DRIFT.labels(origem, "ok").inc()
        logger.info("fluxo_drift origem=%s jsd=%.4f n=%d janela=%s", origem, jsd, len(seqs), janela)
        total += len(seqs)

    return total
