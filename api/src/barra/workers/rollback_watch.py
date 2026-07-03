"""Vigia dos gatilhos de rollback do piloto — cron diário (produção assistida, semana 1).

O plano do piloto fixou 3 gatilhos OBJETIVOS de rollback (janela deslizante de 7 dias), e quem
os monitora é um cron, não um humano:

  1. `nao_contidos`  — >= 2 incidentes críticos NÃO-CONTIDOS/semana: turnos JÁ enviados em que o
     judge pós-envio viu rastro de LLM (`julgamentos_turno.rastro_llm`).
  2. `acusacoes`     — >= 3 conversas/semana com acusação-padrão do cliente ("é robô?", pedido de
     prova impossível): regexes do `agente/_classificador` (fonte única, determinístico, sem
     custo de LLM) sobre as mensagens de cliente da janela.
  3. `taxa_gate`     — sistema de saída abortando > 20% dos turnos: handoffs de defesa do
     output_guard (`output_leak_*`/`aup_saida_*`) e da rede final do envio
     (`envio_leak`/`envio_placeholder`) sobre o total de turnos enviados (aproximado pelos
     turnos julgados; turno com judge `indisponivel` sai do denominador — instabilidade do
     judge infla a taxa, cheque a métrica antes de agir). Regen que LIMPOU não é abort — só o
     fallback que segurou o turno.

Disparou => ALERTA no canal dev: log ERROR estruturado (a revisão diária grepa), gauge
Prometheus `barra_rollback_gatilho` e Sentry (quando configurado). NUNCA pausa a modelo sozinho:
o rollback em si (status da modelo) é decisão humana — este cron só garante que ninguém precisa
ficar olhando dashboard pra saber que o critério bateu. Read-only no banco.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from psycopg import AsyncConnection

from barra.core.metrics import ROLLBACK_GATILHO
from barra.core.tracing import sentry_sdk
from barra.settings import Settings

logger = logging.getLogger(__name__)

_JANELA_DIAS = 7
# Limiares acordados no plano do piloto (grilling 02/07) — mudá-los é decisão de plano, não tuning.
LIMIAR_NAO_CONTIDOS = 2
LIMIAR_ACUSACOES = 3
LIMIAR_TAXA_GATE = 0.20
# Denominador mínimo pra taxa do gate significar algo (1 abort em 3 turnos não é sinal de rollback,
# é semana de tráfego baixo — os gatilhos 1 e 2 continuam cobrindo o caso grave).
_MIN_TURNOS_TAXA = 20

_SQL_NAO_CONTIDOS = """
SELECT count(*) AS n
  FROM barravips.julgamentos_turno
 WHERE rastro_llm
   AND julgado_em >= now() - make_interval(days => %s)
"""

# Mensagens de cliente da janela p/ o scan de acusação (texto puro; mídia não acusa). LIMIT de
# segurança bem acima do volume do piloto — estourar o teto indica que o scan precisa paginar.
_SQL_MSGS_CLIENTE = """
SELECT conversa_id, conteudo
  FROM barravips.mensagens
 WHERE direcao = 'cliente'
   AND conteudo <> ''
   AND created_at >= now() - make_interval(days => %s)
 ORDER BY created_at
 LIMIT 20000
"""

# Aborts do sistema de saída: gate pré-envio (output_leak_*/aup_saida_*) E rede final do
# enviar_turno (envio_leak/envio_placeholder) — nos dois casos o turno morreu antes do cliente.
# O judge pós-envio pula turnos sem marcador de envio, então esses aborts também não entram no
# denominador de julgados: somar aqui mantém o universo coerente.
_SQL_GATE_ABORTS = """
SELECT count(*) AS n
  FROM barravips.escaladas
 WHERE (observacao LIKE 'output\\_leak%%' OR observacao LIKE 'aup\\_saida%%'
        OR observacao IN ('envio_leak', 'envio_placeholder'))
   AND aberta_em >= now() - make_interval(days => %s)
"""

_SQL_TURNOS_JULGADOS = """
SELECT count(*) AS n
  FROM barravips.julgamentos_turno
 WHERE julgado_em >= now() - make_interval(days => %s)
"""


def contar_conversas_com_acusacao(mensagens: list[dict[str, Any]]) -> int:
    """Conversas distintas com acusação-padrão (PURA): disclosure ("vc é robô?") OU pedido de
    prova impossível (áudio/foto agora). Reusa os regexes do _classificador — fonte única; o
    texto passa por `normalizar` antes (os padrões operam sem acento, gotcha durável)."""
    from barra.agente._classificador import PADROES_DISCLOSURE, PADROES_PROVA
    from barra.agente._normalizar import normalizar

    padroes = [re.compile(p) for p in (*PADROES_DISCLOSURE, *PADROES_PROVA)]
    conversas: set[Any] = set()
    for m in mensagens:
        if m["conversa_id"] in conversas:
            continue
        t = normalizar(m["conteudo"])
        if any(p.search(t) for p in padroes):
            conversas.add(m["conversa_id"])
    return len(conversas)


async def _contar(conn: AsyncConnection[Any], sql: str) -> int:
    res = await conn.execute(sql, (_JANELA_DIAS,))
    row = await res.fetchone()
    return int(row["n"]) if row else 0


def _alertar(gatilho: str, detalhe: str) -> None:
    """Canal DEV (nunca Fernando): log ERROR grepável + Sentry quando configurado."""
    msg = (
        f"ROLLBACK_GATILHO {gatilho}: {detalhe} (janela {_JANELA_DIAS}d) — avaliar pausa do piloto"
    )
    logger.error(msg)
    if sentry_sdk is not None:
        sentry_sdk.capture_message(msg, level="error")


async def vigiar_gatilhos_rollback(conn: AsyncConnection[Any], settings: Settings) -> int:
    """Avalia os 3 gatilhos na janela de 7d e alerta os que dispararam. Devolve o nº disparado.

    O gauge é sempre re-setado (1/0) pros 3 — um gatilho que voltou ao normal zera sozinho na
    corrida seguinte, sem estado residual.
    """
    if not settings.rollback_watch_ativo:
        return 0

    nao_contidos = await _contar(conn, _SQL_NAO_CONTIDOS)

    res = await conn.execute(_SQL_MSGS_CLIENTE, (_JANELA_DIAS,))
    acusacoes = contar_conversas_com_acusacao(list(await res.fetchall()))

    aborts = await _contar(conn, _SQL_GATE_ABORTS)
    turnos = await _contar(conn, _SQL_TURNOS_JULGADOS)
    universo = (
        turnos + aborts
    )  # abort não vira julgamento (o turno não saiu) — soma, não subconjunto
    taxa_gate = (aborts / universo) if universo else 0.0

    disparos = {
        "nao_contidos": nao_contidos >= LIMIAR_NAO_CONTIDOS,
        "acusacoes": acusacoes >= LIMIAR_ACUSACOES,
        "taxa_gate": universo >= _MIN_TURNOS_TAXA and taxa_gate > LIMIAR_TAXA_GATE,
    }
    for gatilho, disparou in disparos.items():
        ROLLBACK_GATILHO.labels(gatilho).set(1.0 if disparou else 0.0)

    if disparos["nao_contidos"]:
        _alertar(
            "nao_contidos", f"{nao_contidos} incidentes não-contidos (limiar {LIMIAR_NAO_CONTIDOS})"
        )
    if disparos["acusacoes"]:
        _alertar(
            "acusacoes", f"{acusacoes} conversas com acusação-padrão (limiar {LIMIAR_ACUSACOES})"
        )
    if disparos["taxa_gate"]:
        _alertar(
            "taxa_gate",
            f"gate abortou {aborts}/{universo} turnos ({taxa_gate:.0%}, limiar {LIMIAR_TAXA_GATE:.0%})",
        )

    logger.info(
        "rollback_watch nao_contidos=%d acusacoes=%d gate=%d/%d disparados=%d",
        nao_contidos,
        acusacoes,
        aborts,
        universo,
        sum(disparos.values()),
    )
    return sum(disparos.values())
