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

Os 3 contam só CLIENTE REAL: conversa de grupo (`...@g.us`, o rig de teste) fica fora — provocar
o agente no Playground é trabalho de dev, não sinal de piloto doente.

Disparou => ALERTA no canal dev: log ERROR estruturado (a revisão diária grepa), gauge
Prometheus `barra_rollback_gatilho` e Sentry (quando configurado). NUNCA pausa a modelo sozinho:
o rollback em si (status da modelo) é decisão humana — este cron só garante que ninguém precisa
ficar olhando dashboard pra saber que o critério bateu. Read-only no banco. Como o gauge vive no
processo, o worker reavalia no boot (`workers/settings.startup`): sem isso todo force-update
apagaria a série e um alerta ativo "resolveria" sozinho até a corrida seguinte.
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
# Limiares do plano do piloto (ADR 0034) — mudá-los é decisão de plano, não tuning: emende o ADR.
LIMIAR_NAO_CONTIDOS = 2
LIMIAR_ACUSACOES = 3
LIMIAR_TAXA_GATE = 0.20
# Denominador mínimo pra taxa do gate significar algo (1 abort em 3 turnos não é sinal de rollback,
# é semana de tráfego baixo — os gatilhos 1 e 2 continuam cobrindo o caso grave).
_MIN_TURNOS_TAXA = 20

# Conversa de CLIENTE REAL: `evolution_chat_id` de cliente é `<E.164>@s.whatsapp.net`; o rig de
# teste (grupo Playground) é `...@g.us` e está no JID permitido, então vira conversa/mensagem/turno
# julgado como qualquer outra. Sem este recorte, provocação adversarial do rig ("vc é robô?",
# jailbreak de teste) contava como acusação de cliente e podia disparar rollback de um piloto
# saudável. Vale nos 3 gatilhos — os números do piloto são sobre gente de verdade.
_SO_CLIENTE_REAL = "c.evolution_chat_id NOT LIKE '%%@g.us'"

_SQL_NAO_CONTIDOS = f"""
SELECT count(*) AS n
  FROM barravips.julgamentos_turno j
  JOIN barravips.conversas c ON c.id = j.conversa_id
 WHERE j.rastro_llm
   AND j.julgado_em >= now() - make_interval(days => %s)
   AND {_SO_CLIENTE_REAL}
"""

# Mensagens de cliente da janela p/ o scan de acusação (texto puro; mídia não acusa). LIMIT de
# segurança bem acima do volume do piloto — estourar o teto indica que o scan precisa paginar.
_SQL_MSGS_CLIENTE = f"""
SELECT m.conversa_id, m.conteudo
  FROM barravips.mensagens m
  JOIN barravips.conversas c ON c.id = m.conversa_id
 WHERE m.direcao = 'cliente'
   AND m.conteudo <> ''
   AND m.created_at >= now() - make_interval(days => %s)
   AND {_SO_CLIENTE_REAL}
 ORDER BY m.created_at
 LIMIT 20000
"""

# Aborts do sistema de saída: gate pré-envio (output_leak_*/aup_saida_*) E rede final do
# enviar_turno (envio_leak/envio_placeholder) — nos dois casos o turno morreu antes do cliente.
# O judge pós-envio pula turnos sem marcador de envio, então esses aborts também não entram no
# denominador de julgados: somar aqui mantém o universo coerente.
#
# SUBCONTAGEM CONHECIDA (a taxa real é >= a medida, nunca <): a contagem é DB-only, e dois aborts
# não deixam linha em `escaladas` — o abort sem `atendimento_id` (só loga) e o abort cujo handoff
# já estava aberto (o INSERT tem guard de handoff aberto e não duplica). Fechá-la exige rastro
# próprio em `eventos` (tipo novo = migration do enum). Enquanto isso, o gatilho erra para o lado
# seguro: se ele disparou, disparou de verdade.
_SQL_GATE_ABORTS = f"""
SELECT count(*) AS n
  FROM barravips.escaladas e
  JOIN barravips.atendimentos a ON a.id = e.atendimento_id
  JOIN barravips.conversas c ON c.id = a.conversa_id
 WHERE (e.observacao LIKE 'output\\_leak%%' OR e.observacao LIKE 'aup\\_saida%%'
        OR e.observacao IN ('envio_leak', 'envio_placeholder'))
   AND e.aberta_em >= now() - make_interval(days => %s)
   AND {_SO_CLIENTE_REAL}
"""

_SQL_TURNOS_JULGADOS = f"""
SELECT count(*) AS n
  FROM barravips.julgamentos_turno j
  JOIN barravips.conversas c ON c.id = j.conversa_id
 WHERE j.julgado_em >= now() - make_interval(days => %s)
   AND {_SO_CLIENTE_REAL}
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
        # `turnos > 0` é anti-alarme-falso de judge caído, não tuning do limiar: sem julgamento na
        # janela o universo vira só aborts, a taxa sobe a 100% e o gatilho dispara medindo a saúde
        # do judge, não a do gate. Na mesma janela `nao_contidos` deflaciona em silêncio — por isso
        # o log/alerta abaixo carrega os julgados: quem lê o alerta precisa ver o denominador.
        "taxa_gate": turnos > 0 and universo >= _MIN_TURNOS_TAXA and taxa_gate > LIMIAR_TAXA_GATE,
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
            f"gate abortou {aborts}/{universo} turnos ({taxa_gate:.0%}, limiar "
            f"{LIMIAR_TAXA_GATE:.0%}; {turnos} julgados na janela)",
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
