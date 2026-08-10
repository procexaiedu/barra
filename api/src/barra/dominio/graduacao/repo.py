"""SQL puro do relatorio de graduacao (psycopg3, sempre parametrizado). Read-only.

Todo recorte aqui e de CLIENTE REAL: `origem='prod'` (fora o harness e2e) e `evolution_chat_id`
que nao termina em `@g.us` (fora o rig de teste do Playground). Mesmo recorte do
`workers/rollback_watch` -- os numeros do piloto sao sobre gente de verdade, e provocar o agente
no Playground e trabalho de dev, nao sinal de piloto saudavel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

# Recorte de cliente real. `%%` porque o psycopg processa o `%` do LIKE junto dos parametros.
_SO_CLIENTE_REAL = "c.origem = 'prod' AND c.evolution_chat_id NOT LIKE '%%@g.us'"

# ---------------------------------------------------------------------------------------------
# Inicio do piloto
# ---------------------------------------------------------------------------------------------

# O cutover (`JID_PERMITIDO=[]`, ADR-0034 "A porta ainda esta fechada") nao deixa carimbo no banco
# -- e mudanca de Env, nao de dado. Ancora derivavel e equivalente: o PRIMEIRO turno que a IA
# produziu para um cliente real. Antes dele, por construcao, nenhum cliente real falou com o
# agente; depois dele, o piloto esta correndo. Sobrevive a redeploy e a perda do Env.
_SQL_PILOTO_INICIO = f"""
SELECT min(m.created_at) AS inicio
  FROM barravips.mensagens m
  JOIN barravips.conversas c ON c.id = m.conversa_id
 WHERE m.direcao = 'ia'
   AND {_SO_CLIENTE_REAL}
"""


async def piloto_inicio(conn: AsyncConnection[Any]) -> datetime | None:
    res = await conn.execute(_SQL_PILOTO_INICIO)
    row = await res.fetchone()
    return row["inicio"] if row else None


# ---------------------------------------------------------------------------------------------
# Criterio 1 -- conversas conduzidas pela IA
# ---------------------------------------------------------------------------------------------

# "Conduzida pela IA" = a conversa tem ao menos um turno `direcao='ia'`. Um par em que so o humano
# respondeu (handoff desde o primeiro contato) nao e amostra do agente e nao pode contar para o
# limiar de 100. "Completa" = tem ao menos um atendimento em estado TERMINAL.
_SQL_CONVERSAS = f"""
SELECT count(*) AS com_atendimento,
       count(*) FILTER (WHERE x.tem_terminal) AS completas
  FROM (
    SELECT c.id,
           bool_or(a.estado IN ('Fechado', 'Perdido')) AS tem_terminal
      FROM barravips.conversas c
      JOIN barravips.atendimentos a ON a.conversa_id = c.id
     WHERE a.created_at >= %s
       AND {_SO_CLIENTE_REAL}
       AND EXISTS (
             SELECT 1 FROM barravips.mensagens m
              WHERE m.conversa_id = c.id AND m.direcao = 'ia'
           )
     GROUP BY c.id
  ) x
"""


async def conversas(conn: AsyncConnection[Any], desde: datetime) -> dict[str, int]:
    res = await conn.execute(_SQL_CONVERSAS, (desde,))
    row = await res.fetchone() or {}
    return {
        "com_atendimento": int(row.get("com_atendimento") or 0),
        "completas": int(row.get("completas") or 0),
    }


# ---------------------------------------------------------------------------------------------
# Criterio 2 -- incidentes criticos nao-contidos
# ---------------------------------------------------------------------------------------------

# "Nao-contido" = o turno CHEGOU ao cliente com rastro de LLM: o gate pre-envio nao segurou e o
# judge pos-envio viu depois (`julgamentos_turno.rastro_llm`). Mesma definicao do gatilho de
# rollback -- a diferenca e a janela (o gatilho olha 7 dias; a graduacao olha o piloto inteiro) e
# a triagem (o gatilho gateia pelos ABERTOS, porque mede risco em aberto; a graduacao gateia pelo
# TOTAL, porque o ADR pede "zero" historico e um incidente triado ainda aconteceu).
_SQL_INCIDENTES = f"""
SELECT count(*) AS total,
       count(*) FILTER (WHERE j.tratado_em IS NULL) AS abertos,
       count(*) FILTER (WHERE j.tratado_em IS NOT NULL) AS triados
  FROM barravips.julgamentos_turno j
  JOIN barravips.conversas c ON c.id = j.conversa_id
 WHERE j.rastro_llm
   AND j.julgado_em >= %s
   AND {_SO_CLIENTE_REAL}
"""

_SQL_TURNOS_JULGADOS = f"""
SELECT count(*) AS n
  FROM barravips.julgamentos_turno j
  JOIN barravips.conversas c ON c.id = j.conversa_id
 WHERE j.julgado_em >= %s
   AND {_SO_CLIENTE_REAL}
"""


async def incidentes(conn: AsyncConnection[Any], desde: datetime) -> dict[str, int]:
    res = await conn.execute(_SQL_INCIDENTES, (desde,))
    row = await res.fetchone() or {}
    res = await conn.execute(_SQL_TURNOS_JULGADOS, (desde,))
    julgados = await res.fetchone() or {}
    return {
        "total": int(row.get("total") or 0),
        "abertos": int(row.get("abertos") or 0),
        "triados": int(row.get("triados") or 0),
        "turnos_julgados": int(julgados.get("n") or 0),
    }


# ---------------------------------------------------------------------------------------------
# Criterio 3 -- taxa do gate, semana a semana
# ---------------------------------------------------------------------------------------------

# ESPELHO de `workers/rollback_watch._SQL_GATE_ABORTS` -- mesma definicao de abort do sistema de
# saida (gate pre-envio `output_leak_*`/`aup_saida_*` + rede final do envio). Duplicado porque
# `dominio/` nao pode importar `workers/` (direcao das dependencias, ver dominio/CLAUDE.md);
# `tests/test_graduacao.py` afirma que os dois textos seguem identicos, para a copia nao derivar
# em silencio. Mudou la, mude aqui.
PREDICADO_ABORT_GATE = (
    "(e.observacao LIKE 'output\\_leak%%' OR e.observacao LIKE 'aup\\_saida%%'\n"
    "        OR e.observacao IN ('envio_leak', 'envio_placeholder'))"
)

# Serie semanal. `date_trunc('week')` (segunda-feira, TZ da sessao) alinha aborts e julgados na
# mesma grade; o FULL OUTER JOIN mantem semana sem abort (taxa 0) e semana so de abort (judge
# fora do ar) -- as duas informam, e some-las seria esconder as duas pontas.
#
# SUBCONTAGEM herdada do gatilho: abort sem `atendimento_id` e abort cujo handoff ja estava aberto
# nao deixam linha em `escaladas`, entao a taxa real e >= a medida (ADR-0034, Consequencias).
_SQL_TAXA_GATE = f"""
WITH aborts AS (
  SELECT date_trunc('week', e.aberta_em) AS semana, count(*) AS n
    FROM barravips.escaladas e
    JOIN barravips.atendimentos a ON a.id = e.atendimento_id
    JOIN barravips.conversas c ON c.id = a.conversa_id
   WHERE {PREDICADO_ABORT_GATE}
     AND e.aberta_em >= %s
     AND {_SO_CLIENTE_REAL}
   GROUP BY 1
), julgados AS (
  SELECT date_trunc('week', j.julgado_em) AS semana, count(*) AS n
    FROM barravips.julgamentos_turno j
    JOIN barravips.conversas c ON c.id = j.conversa_id
   WHERE j.julgado_em >= %s
     AND {_SO_CLIENTE_REAL}
   GROUP BY 1
)
SELECT COALESCE(a.semana, j.semana)::date AS semana,
       COALESCE(a.n, 0) AS aborts,
       COALESCE(j.n, 0) AS julgados
  FROM aborts a
  FULL OUTER JOIN julgados j ON j.semana = a.semana
 ORDER BY 1
"""


async def taxa_gate_semanal(conn: AsyncConnection[Any], desde: datetime) -> list[dict[str, Any]]:
    res = await conn.execute(_SQL_TAXA_GATE, (desde, desde))
    return [
        {
            "semana": row["semana"],
            "aborts": int(row["aborts"] or 0),
            "julgados": int(row["julgados"] or 0),
        }
        for row in await res.fetchall()
    ]


# ---------------------------------------------------------------------------------------------
# Criterio 4 -- conversao do agente e baseline do vendedor
# ---------------------------------------------------------------------------------------------

# Denominador = atendimentos TERMINAIS (Fechado + Perdido) nascidos na janela do piloto. Os que
# ainda estao em curso ficam de fora dos dois lados -- incluir so infla o denominador com
# negociacao que ainda pode fechar.
_SQL_CONVERSAO = f"""
SELECT count(*) AS terminais,
       count(*) FILTER (WHERE a.estado = 'Fechado') AS fechados
  FROM barravips.atendimentos a
  JOIN barravips.conversas c ON c.id = a.conversa_id
 WHERE a.estado IN ('Fechado', 'Perdido')
   AND a.created_at >= %s
   AND {_SO_CLIENTE_REAL}
"""


async def conversao_agente(conn: AsyncConnection[Any], desde: datetime) -> dict[str, int]:
    res = await conn.execute(_SQL_CONVERSAO, (desde,))
    row = await res.fetchone() or {}
    return {
        "terminais": int(row.get("terminais") or 0),
        "fechados": int(row.get("fechados") or 0),
    }


# `to_regclass` em vez de try/except na migration ausente: o relatorio precisa rodar ANTES de a
# migration `graduacao_baseline` chegar no ambiente (e util justamente para mostrar que ela falta),
# e uma UndefinedTable no meio da transacao envenenaria a conexao para as consultas seguintes.
_SQL_BASELINE_EXISTE = "SELECT to_regclass('barravips.graduacao_baseline') IS NOT NULL AS existe"

# Append-only: vale a apuracao mais recente. O `id` desempata (uuidv7 e monotonico) quando duas
# linhas compartilham o mesmo `registrado_em`.
_SQL_BASELINE = """
SELECT conversao_pct, amostra_n, fonte, registrado_em
  FROM barravips.graduacao_baseline
 ORDER BY registrado_em DESC, id DESC
 LIMIT 1
"""


async def baseline_vendedor(conn: AsyncConnection[Any]) -> dict[str, Any] | None:
    """Baseline mais recente, ou None se a tabela nao existe / esta vazia."""
    res = await conn.execute(_SQL_BASELINE_EXISTE)
    row = await res.fetchone()
    if not row or not row.get("existe"):
        return None
    res = await conn.execute(_SQL_BASELINE)
    linha = await res.fetchone()
    if linha is None:
        return None
    return {
        "conversao_pct": float(linha["conversao_pct"]),
        "amostra_n": int(linha["amostra_n"]),
        "fonte": str(linha["fonte"]),
        "registrado_em": linha["registrado_em"],
    }


__all__ = [
    "PREDICADO_ABORT_GATE",
    "baseline_vendedor",
    "conversao_agente",
    "conversas",
    "incidentes",
    "piloto_inicio",
    "taxa_gate_semanal",
]
