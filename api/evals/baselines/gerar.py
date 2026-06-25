"""Gera os baselines humanos CONGELADOS do gate de conduta a partir do corpus do Vendedor.

Roda UMA vez (ou quando o corpus mudar): le SO `corpus.*` (read-only, SELECT — §0 nao mutavel,
sem credito) e grava 3 JSONs AGREGADOS (sem nenhuma mensagem literal) em `evals/baselines/`:

  - fluxo_atos.json   transicoes de atos do funil (Counter) + piso JSD eb01-03 vs eb04
  - estilo_corpus.json perfil estilometrico d'ELA + piso ELA-vs-ELA (split de paridade)
  - empurrao.json      taxa de empurrao do detector regex sobre os turnos de cotacao humanos

Os baselines sao commitados (agregados, baixo risco de PII; o corpus em si segue no .gitignore).
Os scorers (`evals.conduta`) erram com mensagem clara se algum JSON estiver ausente.

Uso (do diretorio api/, le DATABASE_URL de prod):
  DATABASE_URL=<prod> uv run python -m evals.baselines.gerar
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg

from barra.agente.fluxo import js_divergencia, matriz_transicao, rotular_turno
from evals.conduta import tem_empurrao
from evals.estilometria import distancia, perfil_de_bolhas

_DIR = Path(__file__).parent

# Mesma populacao das analises existentes (fluxo.py): threads com valor, nao-ops, 2..10 cli.
_SQL_TURNOS = """
    SELECT t.instancia, t.remote_jid, t.turno_idx, t.from_me, t.texto, t.tem_midia
    FROM corpus.turnos t
    JOIN corpus.threads th USING (instancia, remote_jid)
    WHERE NOT th.thread_ops AND th.tem_valor AND th.n_cli BETWEEN 2 AND 10
    ORDER BY t.instancia, t.remote_jid, t.turno_idx
"""

# Voz-alvo geral d'ELA (gerar_perfil_estilo.py): from_me, tipos textuais, nao-vazio.
_SQL_BOLHAS = """
    SELECT instancia, texto
    FROM corpus.mensagens_raw
    WHERE from_me
      AND message_type IN ('conversation', 'extendedTextMessage')
      AND texto IS NOT NULL AND btrim(texto) <> ''
    ORDER BY instancia, ts, msg_id
"""


def _gerar_fluxo_e_empurrao(conn: psycopg.Connection[Any]) -> None:
    """Sequencias de atos do Vendedor por thread (split eb04 hold-out) -> transicoes + piso JSD;
    e taxa de empurrao do detector sobre o 1o turno de cotacao de cada thread."""
    seqs: dict[str, dict[tuple[str, str], list[str]]] = {"eb04": {}, "eb01-03": {}}
    cotacao_por_thread: dict[tuple[str, str], str] = {}
    with conn.cursor() as cur:
        cur.execute(_SQL_TURNOS)
        for inst, jid, _idx, from_me, texto, tem_midia in cur:
            if not from_me:  # so o lado do Vendedor compoe o funil
                continue
            ato = rotular_turno(texto, tem_midia)
            split = "eb04" if inst == "eb04" else "eb01-03"
            seqs[split].setdefault((inst, jid), []).append(ato)
            if ato == "cotacao" and (inst, jid) not in cotacao_por_thread:
                cotacao_por_thread[(inst, jid)] = texto or ""

    pop = {k: list(v.values()) for k, v in seqs.items()}
    todas = pop["eb01-03"] + pop["eb04"]
    base = matriz_transicao(todas)
    piso_jsd = js_divergencia(matriz_transicao(pop["eb01-03"]), matriz_transicao(pop["eb04"]))

    (_DIR / "fluxo_atos.json").write_text(
        json.dumps(
            {
                "__meta__": {
                    "fonte": "corpus.turnos from_me (threads tem_valor, nao-ops, 2..10 cli)",
                    "n_threads": len(todas),
                    "piso_jsd_eb_split": round(piso_jsd, 4),
                },
                "transicoes": {f"{a}>{b}": c for (a, b), c in sorted(base.items())},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cotacoes = list(cotacao_por_thread.values())
    n_cot = len(cotacoes) or 1
    pct = 100.0 * sum(1 for t in cotacoes if tem_empurrao(t)) / n_cot
    (_DIR / "empurrao.json").write_text(
        json.dumps(
            {
                "__meta__": {
                    "fonte": "detector regex (evals.conduta.tem_empurrao) sobre turnos de cotacao humanos",
                    "n_cotacoes": len(cotacoes),
                    "ref_humano_judge_pct": 26.0,  # juiz LLM (corpus.eval_v1_score) — referencia
                    "ref_v1_pct": 0.3,  # agente v1 sob o mesmo juiz — referencia
                },
                "baseline_humano_pct": round(pct, 2),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"fluxo: {len(todas)} threads, piso JSD eb-split={piso_jsd:.4f}")
    print(f"empurrao: {len(cotacoes)} cotacoes humanas, detector regex={pct:.2f}%")


def _gerar_estilo(conn: psycopg.Connection[Any]) -> None:
    """Perfil estilometrico congelado d'ELA + piso ELA-vs-ELA (split por paridade de indice)."""
    todas: list[str] = []
    por_instancia: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(_SQL_BOLHAS)
        for instancia, texto in cur.fetchall():
            todas.append(texto)
            por_instancia[instancia] = por_instancia.get(instancia, 0) + 1
    if not todas:
        sys.exit("corpus de estilo vazio — DSN aponta pro banco errado?")

    perfil = perfil_de_bolhas(todas)
    piso = distancia(perfil_de_bolhas(todas[0::2]), perfil_de_bolhas(todas[1::2]))
    perfil["__meta__"] = {
        "fonte": "corpus.mensagens_raw (from_me, texto)",
        "n_bolhas_total": len(todas),
        "n_por_instancia": dict(sorted(por_instancia.items())),
        "piso_ela_vs_ela": round(piso["agregado"], 4),
        "piso_por_feature": {k: round(v, 4) for k, v in piso.items()},
    }
    (_DIR / "estilo_corpus.json").write_text(
        json.dumps({"perfil": perfil}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"estilo: {len(todas)} bolhas, piso ELA-vs-ELA={piso['agregado']:.4f}")


def main() -> None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL (ou TEST_DATABASE_URL) ausente — necessario para ler o corpus.")
    with psycopg.connect(dsn) as conn:
        _gerar_fluxo_e_empurrao(conn)
        _gerar_estilo(conn)
    print(f"baselines gravados em {_DIR}")


if __name__ == "__main__":
    main()
