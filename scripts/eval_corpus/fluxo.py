"""CLI da metrica de FLUXO conversacional (corpus humano vs. agente).

Mede se uma populacao de conversas percorre o funil com a MESMA FORMA que outra — nao o
anti-padrao pontual (empurrao, ver score_v1) nem o desfecho (judge fraco). A logica pura (labeler +
JSD) vive em `barra.agente.fluxo`; aqui ficam so a carga corpus-vs-corpus e o CLI.

v1 determinismo total: rotulador por regex (sem LLM-judge, sem credito), JSD em pure-python (sem
numpy). Calibra corpus-vs-corpus (eb04 hold-out vs eb01-03) como piso de ruido; o lado do agente
entra via --transcript <dump do wf_simulador.js> quando houver.

Uso (importa de `barra.agente.fluxo`, entao roda pelo env do api):
  cd api && DATABASE_URL=<prod> uv run python ../scripts/eval_corpus/fluxo.py
  cd api && DATABASE_URL=<prod> uv run python ../scripts/eval_corpus/fluxo.py --transcript dump.json

§0: a query do corpus e READ-ONLY (so SELECT). Sem escrita em prod, sem credito.

Limitacoes (v1 coarse, de proposito):
  - 1 ato dominante por turno por precedencia: "consigo por 350" cai em `cotacao` (tem preco), nao
    `desconto` — o empurrao/desconto fino fica pro score_v1; aqui mede-se a FORMA da sequencia.
  - `midia` no corpus vem da coluna `corpus.turnos.tem_midia`; no transcript do simulador, de um
    marcador textual ([midia]/[foto]) — pode subcontar se o simulador nao marcar.
  - Agregado cross-modelo (como eval_v1_score); metrica OFFLINE, nunca alimenta o agente ao vivo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from barra.agente.fluxo import relatorio, rotular_turno


def _carregar_corpus() -> dict[str, list[list[str]]]:
    """Le corpus.turnos (READ-ONLY) e devolve sequencias de atos do Vendedor por split de instancia.

    Filtro: threads com cotacao, nao-operacionais, 2..10 turnos de cliente (mesma populacao das
    analises existentes). Split: eb04 (hold-out) vs eb01-03.
    """
    import psycopg

    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL (ou TEST_DATABASE_URL) ausente — necessario para ler corpus.turnos")

    sql = """
        SELECT t.instancia, t.remote_jid, t.turno_idx, t.from_me, t.texto, t.tem_midia
        FROM corpus.turnos t
        JOIN corpus.threads th USING (instancia, remote_jid)
        WHERE NOT th.thread_ops AND th.tem_valor AND th.n_cli BETWEEN 2 AND 10
        ORDER BY t.instancia, t.remote_jid, t.turno_idx
    """
    seqs: dict[str, dict[tuple[str, str], list[str]]] = {"eb04": {}, "eb01-03": {}}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for inst, jid, _idx, from_me, texto, tem_midia in cur:
            if not from_me:  # so o lado do Vendedor compoe o fluxo
                continue
            split = "eb04" if inst == "eb04" else "eb01-03"
            seqs[split].setdefault((inst, jid), []).append(rotular_turno(texto, tem_midia))
    return {k: list(v.values()) for k, v in seqs.items()}


def _carregar_transcript(path: str) -> list[list[str]]:
    """Le um dump do wf_simulador.js e devolve as sequencias de atos do Vendedor (lado 'M')."""
    with open(path, encoding="utf-8") as f:
        dados = json.load(f)
    seqs: list[list[str]] = []
    for conv in dados.get("transcripts", []):
        seq = [
            rotular_turno(h.get("bolhas"))
            for h in conv.get("transcript", [])
            if h.get("lado") == "M"
        ]
        if seq:
            seqs.append(seq)
    return seqs


def main() -> None:
    ap = argparse.ArgumentParser(description="Divergencia de fluxo conversacional (corpus vs agente)")
    ap.add_argument("--transcript", help="dump JSON do wf_simulador.js (lado agente)")
    args = ap.parse_args()

    corpus = _carregar_corpus()
    print(relatorio("eb01-03", corpus["eb01-03"], "eb04", corpus["eb04"]))

    if args.transcript:
        agente = _carregar_transcript(args.transcript)
        base = corpus["eb01-03"] + corpus["eb04"]
        print("\n" + "=" * 60 + "\n")
        print(relatorio("corpus", base, "agente", agente))


if __name__ == "__main__":
    main()
