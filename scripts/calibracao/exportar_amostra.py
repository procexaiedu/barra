#!/usr/bin/env python3
"""Exporta uma amostra ESTRATIFICADA de julgamentos dos judges para rotulagem humana.

Objetivo: medir o κ (Cohen) entre o judge automático e o rótulo humano — hoje nenhum dos dois
judges de produção foi calibrado contra ground-truth, então ninguém sabe se um `reprovado` do
judge significa alguma coisa.

Dois judges, duas fontes de verdade DIFERENTES no banco:

  * `pos_envio`  — worker `judge_pos_envio.py`, telemetria de 100% dos turnos ENVIADOS.
                   Carimba `barravips.julgamentos_turno` (rastro_llm/voz/conduta).
                   REPROVADO = `rastro_llm = true`.
  * `aup`        — judge de AUP VINCULANTE do `agente/nos/output_guard.py` (fail-closed, roda
                   ANTES do envio). Não tem tabela própria: quando reprova, a bolha é zerada e
                   o que fica é uma linha em `barravips.escaladas` com
                   `observacao LIKE 'aup_saida_%'`. Quando aprova, não carimba nada — a bolha
                   simplesmente sai e vira `mensagens(direcao='ia')`.

                   ⚠️ LIMITE ESTRUTURAL: o TEXTO da bolha reprovada pela AUP **não é persistido
                   em lugar nenhum do Postgres** (o guard zera a bolha antes do envio). Só o
                   trace do Langfuse tem o texto. Por isso a coluna `texto_bolha` sai vazia nas
                   linhas `aup/reprovado` e o CSV traz `onde_achar_o_texto` apontando o caminho.
                   Sem o texto o humano não rotula — ver README, seção "Judge de AUP".

Leitura PURA: abre a transação como READ ONLY e só roda SELECT. Ainda assim, apontar para o DSN
de produção é ação que atinge produção (CLAUDE.md §0) — precisa de `--confirmo-remoto` explícito.

Uso:
    # dry-run: mostra o SQL e os parâmetros, não conecta em nada
    uv run --project api python scripts/calibracao/exportar_amostra.py --explicar

    # export de verdade (DSN por env, nunca hardcode)
    CALIBRACAO_DSN="postgresql://..." uv run --project api \
        python scripts/calibracao/exportar_amostra.py \
        --judge ambos -n 100 --dias 30 --saida /tmp/amostra.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

COLUNAS = [
    "judge",  # pos_envio | aup
    "id",  # PK da linha de origem (julgamentos_turno.id / escaladas.id / mensagens.id)
    "turno_id",  # só pos_envio
    "conversa_id",
    "modelo_id",
    "julgado_em",
    "veredicto_judge",  # rótulo BINÁRIO do judge: aprovado | reprovado
    "motivo_judge",  # rastro_llm / aup_saida_<motivo>
    "voz",  # só pos_envio (1-5)
    "conduta",  # só pos_envio (1-5)
    "comentario_judge",
    "contexto",  # mensagens anteriores (para o humano julgar em contexto)
    "texto_bolha",  # o que a IA disse (vazio em aup/reprovado — ver docstring)
    "onde_achar_o_texto",
    "rotulo_humano",  # <- VOCÊ preenche: aprovado | reprovado
    "nota_humana",  # <- opcional: por que
]

# Janela em minutos usada para reconstruir o TEXTO do turno a partir de `julgado_em`.
# `julgamentos_turno` não guarda o texto nem aponta para `mensagens` (não há turno_id lá), então
# o turno é reconstruído pelas bolhas da IA imediatamente ANTERIORES ao carimbo do judge — que
# roda com defer curto depois do envio. Aproximação: turnos muito próximos podem se fundir.
JANELA_TURNO_MIN_PADRAO = 8
N_CONTEXTO_PADRAO = 8

_SQL_POS_ENVIO = """
SELECT j.id::text                              AS id,
       j.turno_id                              AS turno_id,
       j.conversa_id::text                     AS conversa_id,
       j.modelo_id::text                       AS modelo_id,
       j.julgado_em                            AS julgado_em,
       j.rastro_llm                            AS rastro_llm,
       j.voz                                   AS voz,
       j.conduta                               AS conduta,
       j.comentario                            AS comentario_judge,
       t.texto_bolha                           AS texto_bolha,
       c.contexto                              AS contexto
  FROM barravips.julgamentos_turno j
  LEFT JOIN LATERAL (
        SELECT string_agg(m.conteudo, E'\\n\\n' ORDER BY m.created_at, m.id) AS texto_bolha
          FROM barravips.mensagens m
         WHERE m.conversa_id = j.conversa_id
           AND m.direcao = 'ia'
           AND m.conteudo <> ''
           AND m.created_at <= j.julgado_em
           AND m.created_at >= j.julgado_em - make_interval(mins => %(janela)s)
  ) t ON true
  LEFT JOIN LATERAL (
        SELECT string_agg(x.linha, E'\\n' ORDER BY x.created_at, x.id) AS contexto
          FROM (SELECT m.created_at, m.id,
                       (CASE m.direcao WHEN 'cliente' THEN 'cliente: ' ELSE 'ela: ' END
                        || m.conteudo) AS linha
                  FROM barravips.mensagens m
                 WHERE m.conversa_id = j.conversa_id
                   AND m.conteudo <> ''
                   AND m.created_at < j.julgado_em - make_interval(mins => %(janela)s)
                 ORDER BY m.created_at DESC, m.id DESC
                 LIMIT %(n_contexto)s) x
  ) c ON true
 WHERE j.julgado_em >= now() - make_interval(days => %(dias)s)
   AND j.rastro_llm = %(rastro)s
 ORDER BY random()
 LIMIT %(limite)s
"""

# AUP reprovado: a única marca durável é a escalada de defesa aberta pelo output_guard.
_SQL_AUP_REPROVADO = """
SELECT e.id::text                              AS id,
       a.conversa_id::text                     AS conversa_id,
       a.modelo_id::text                       AS modelo_id,
       e.aberta_em                             AS julgado_em,
       e.observacao                            AS motivo_judge,
       e.resumo_operacional                    AS comentario_judge,
       c.contexto                              AS contexto
  FROM barravips.escaladas e
  JOIN barravips.atendimentos a ON a.id = e.atendimento_id
  LEFT JOIN LATERAL (
        SELECT string_agg(x.linha, E'\\n' ORDER BY x.created_at, x.id) AS contexto
          FROM (SELECT m.created_at, m.id,
                       (CASE m.direcao WHEN 'cliente' THEN 'cliente: ' ELSE 'ela: ' END
                        || m.conteudo) AS linha
                  FROM barravips.mensagens m
                 WHERE m.conversa_id = a.conversa_id
                   AND m.conteudo <> ''
                   AND m.created_at <= e.aberta_em
                 ORDER BY m.created_at DESC, m.id DESC
                 LIMIT %(n_contexto)s) x
  ) c ON true
 WHERE e.aberta_em >= now() - make_interval(days => %(dias)s)
   AND e.observacao LIKE 'aup_saida%%'
 ORDER BY random()
 LIMIT %(limite)s
"""

# AUP aprovado: toda bolha de texto que SAIU passou pelo judge de AUP sem violar.
_SQL_AUP_APROVADO = """
SELECT m.id::text                              AS id,
       m.conversa_id::text                     AS conversa_id,
       cv.modelo_id::text                      AS modelo_id,
       m.created_at                            AS julgado_em,
       m.conteudo                              AS texto_bolha,
       c.contexto                              AS contexto
  FROM barravips.mensagens m
  JOIN barravips.conversas cv ON cv.id = m.conversa_id
  LEFT JOIN LATERAL (
        SELECT string_agg(x.linha, E'\\n' ORDER BY x.created_at, x.id) AS contexto
          FROM (SELECT m2.created_at, m2.id,
                       (CASE m2.direcao WHEN 'cliente' THEN 'cliente: ' ELSE 'ela: ' END
                        || m2.conteudo) AS linha
                  FROM barravips.mensagens m2
                 WHERE m2.conversa_id = m.conversa_id
                   AND m2.conteudo <> ''
                   AND m2.created_at < m.created_at
                 ORDER BY m2.created_at DESC, m2.id DESC
                 LIMIT %(n_contexto)s) x
  ) c ON true
 WHERE m.created_at >= now() - make_interval(days => %(dias)s)
   AND m.direcao = 'ia'
   AND m.conteudo <> ''
 ORDER BY random()
 LIMIT %(limite)s
"""

_LANGFUSE = (
    "Langfuse: filtre o trace pela conversa/janela e leia o span do output_guard "
    "(o texto barrado nunca é persistido no Postgres)"
)


def resolver_dsn(args: argparse.Namespace) -> str:
    """DSN só por argumento ou env — nunca hardcode, nunca `DATABASE_URL` implícito."""
    dsn = args.dsn or os.environ.get("CALIBRACAO_DSN") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        sys.exit(
            "sem DSN: passe --dsn ou exporte CALIBRACAO_DSN (ou TEST_DATABASE_URL).\n"
            "DATABASE_URL NÃO é lida de propósito — apontar para prod tem de ser explícito."
        )
    host = (urlsplit(dsn).hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1", ""} or "test" in host
    if not local and not args.confirmo_remoto:
        sys.exit(
            f"DSN aponta para host remoto ({host}). Ler produção é ação de produção "
            "(CLAUDE.md §0): rode de novo com --confirmo-remoto se estiver autorizado."
        )
    return dsn


def _metade(n: int) -> tuple[int, int]:
    """Divide N em (reprovados, aprovados) — sobra vai para os reprovados (classe rara)."""
    aprovados = n // 2
    return n - aprovados, aprovados


def _linha_pos_envio(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "judge": "pos_envio",
        "id": r["id"],
        "turno_id": r["turno_id"],
        "conversa_id": r["conversa_id"],
        "modelo_id": r["modelo_id"],
        "julgado_em": r["julgado_em"],
        "veredicto_judge": "reprovado" if r["rastro_llm"] else "aprovado",
        "motivo_judge": "rastro_llm" if r["rastro_llm"] else "",
        "voz": r["voz"],
        "conduta": r["conduta"],
        "comentario_judge": r["comentario_judge"],
        "contexto": r["contexto"] or "",
        "texto_bolha": r["texto_bolha"] or "",
        "onde_achar_o_texto": "" if r["texto_bolha"] else "reconstrução por janela não achou bolha",
        "rotulo_humano": "",
        "nota_humana": "",
    }


def _linha_aup(r: dict[str, Any], *, veredicto: str) -> dict[str, Any]:
    reprovado = veredicto == "reprovado"
    return {
        "judge": "aup",
        "id": r["id"],
        "turno_id": "",
        "conversa_id": r["conversa_id"],
        "modelo_id": r["modelo_id"],
        "julgado_em": r["julgado_em"],
        "veredicto_judge": veredicto,
        "motivo_judge": r.get("motivo_judge") or "",
        "voz": "",
        "conduta": "",
        "comentario_judge": r.get("comentario_judge") or "",
        "contexto": r["contexto"] or "",
        "texto_bolha": r.get("texto_bolha") or "",
        "onde_achar_o_texto": _LANGFUSE if reprovado else "",
        "rotulo_humano": "",
        "nota_humana": "",
    }


def _consultas(args: argparse.Namespace) -> list[tuple[str, str, dict[str, Any]]]:
    """(rótulo, SQL, params) de cada estrato pedido — a mesma lista que `--explicar` imprime."""
    n_rep, n_apr = _metade(args.n)
    judges = ["pos_envio", "aup"] if args.judge == "ambos" else [args.judge]
    if len(judges) == 2:  # divide o N entre os dois judges
        n_rep, n_apr = _metade(args.n // 2)
    base = {"dias": args.dias, "n_contexto": args.n_contexto}
    out: list[tuple[str, str, dict[str, Any]]] = []
    for judge in judges:
        if judge == "pos_envio":
            for rastro, limite in ((True, n_rep), (False, n_apr)):
                out.append(
                    (
                        f"pos_envio/{'reprovado' if rastro else 'aprovado'}",
                        _SQL_POS_ENVIO,
                        {
                            **base,
                            "janela": args.janela_turno_min,
                            "rastro": rastro,
                            "limite": limite,
                        },
                    )
                )
        else:
            out.append(("aup/reprovado", _SQL_AUP_REPROVADO, {**base, "limite": n_rep}))
            out.append(("aup/aprovado", _SQL_AUP_APROVADO, {**base, "limite": n_apr}))
    return out


def coletar(dsn: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    linhas: list[dict[str, Any]] = []
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.read_only = True  # trava de segurança: nenhum SELECT daqui pode virar escrita
        with conn.cursor() as cur:
            cur.execute("SELECT setseed(%s)", (args.seed,))  # amostra reprodutível
            for rotulo, sql, params in _consultas(args):
                cur.execute(sql, params)
                brutas = cur.fetchall()
                print(f"  {rotulo}: {len(brutas)} linha(s)", file=sys.stderr)
                for r in brutas:
                    if rotulo.startswith("pos_envio"):
                        linhas.append(_linha_pos_envio(r))
                    else:
                        linhas.append(_linha_aup(r, veredicto=rotulo.split("/")[1]))
    return linhas


def escrever_csv(linhas: list[dict[str, Any]], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUNAS)
        w.writeheader()
        for linha in linhas:
            w.writerow({c: linha.get(c, "") for c in COLUNAS})


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dsn", help="DSN Postgres. Default: $CALIBRACAO_DSN ou $TEST_DATABASE_URL.")
    p.add_argument("--judge", choices=("pos_envio", "aup", "ambos"), default="pos_envio")
    p.add_argument("-n", "--n", type=int, default=60, help="tamanho total da amostra (default 60)")
    p.add_argument("--dias", type=int, default=30, help="janela em dias (default 30)")
    p.add_argument("--janela-turno-min", type=int, default=JANELA_TURNO_MIN_PADRAO)
    p.add_argument("--n-contexto", type=int, default=N_CONTEXTO_PADRAO)
    p.add_argument("--seed", type=float, default=0.42, help="setseed do Postgres (-1..1)")
    p.add_argument("--saida", type=Path, default=Path("amostra_calibracao.csv"))
    p.add_argument("--confirmo-remoto", action="store_true", help="autoriza DSN não-local")
    p.add_argument("--explicar", action="store_true", help="dry-run: imprime SQL e sai")
    args = p.parse_args()

    if args.n < 2:
        sys.exit("-n precisa ser >= 2 (a amostra é estratificada em duas metades)")

    if args.explicar:
        n_rep, n_apr = _metade(args.n)
        print(
            f"# dry-run — judge={args.judge} n={args.n} (rep={n_rep} apr={n_apr}) dias={args.dias}"
        )
        print(f"# saida={args.saida}  seed={args.seed}  colunas={len(COLUNAS)}")
        for rotulo, sql, params in _consultas(args):
            print(f"\n--- {rotulo} | params={params}\n{sql.strip()}")
        return 0

    dsn = resolver_dsn(args)
    print(f"amostrando (judge={args.judge}, n={args.n}, dias={args.dias})...", file=sys.stderr)
    linhas = coletar(dsn, args)
    escrever_csv(linhas, args.saida)
    sem_texto = sum(1 for x in linhas if not x["texto_bolha"])
    print(f"\n{len(linhas)} linha(s) -> {args.saida}", file=sys.stderr)
    if sem_texto:
        print(
            f"⚠️  {sem_texto} linha(s) SEM texto da bolha (ver coluna onde_achar_o_texto): "
            "rotular exige buscar o texto no Langfuse.",
            file=sys.stderr,
        )
    print(
        "agora: preencha a coluna `rotulo_humano` (aprovado|reprovado) e rode computar_kappa.py",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
