"""Voz do Vendedor SEGMENTADA por momento do funil — emoji / vocativo / comprimento por ato.

A estilometria (`estilometria.py`) mede a voz AGREGADA: uma taxa de emoji e uma de vocativo para o
corpus inteiro. Isso já mostrou que o v1 está OVERcalibrado (emoji/vocativo super-aplicados), mas
não diz ONDE: o humano não distribui emoji/vocativo de forma uniforme — ele varia por momento
(uma saudação calorosa, uma cotação seca, uma logística objetiva). Este script abre a taxa por
ATO do funil (reusa `barra.agente.fluxo.rotular_turno`) para revelar a forma real da calibração.

Pure stdlib + reuso dos detectores de `estilometria.py` (sem numpy, sem LLM-judge, sem crédito).
A query de `corpus.mensagens_raw` é READ-ONLY (só SELECT) — §0 do CLAUDE.md.

Uso (importa de `barra.agente.fluxo`, então roda pelo env do api):
  cd api && DATABASE_URL=<prod> uv run python ../scripts/eval_corpus/voz_por_momento.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict

# reuso dos detectores já validados (mesma faixa de emoji da estilometria)
sys.path.insert(0, os.path.dirname(__file__))
from estilometria import _EMOJI  # noqa: E402

from barra.agente.fluxo import rotular_turno  # noqa: E402

# Vocativos AMPLOS para a mineração (a estilometria só conta amor|vida; aqui queremos descobrir
# QUAIS o humano usa por momento, então abrimos o leque). Conta por ocorrência de token.
_VOCATIVOS = re.compile(
    r"\b("
    r"amor|vida|gata|gato|gatinha|linda|lindo|lindeza|gostosa|gostoso|delicia|"
    r"princesa|nega|nego|bb|nenem|meu bem|meu anjo|anjo|flor|querido|querida|docinho|bebe"
    r")\b",
    re.IGNORECASE,
)


def _carregar() -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Lê corpus.mensagens_raw (READ-ONLY) e devolve, por thread, a lista (texto, ato) do Vendedor."""
    import psycopg

    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL (ou TEST_DATABASE_URL) ausente — necessário para ler o corpus")

    sql = """
        SELECT instancia, remote_jid, texto
        FROM corpus.mensagens_raw
        WHERE from_me = true AND message_type = 'conversation'
          AND texto IS NOT NULL AND texto <> ''
        ORDER BY instancia, remote_jid, ts
    """
    threads: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for inst, jid, texto in cur:
            threads[(inst, jid)].append((texto, rotular_turno(texto)))
    return threads


def main() -> None:
    threads = _carregar()

    n_msg: Counter[str] = Counter()
    n_com_emoji: Counter[str] = Counter()
    n_emoji_total: Counter[str] = Counter()
    n_com_vocativo: Counter[str] = Counter()
    comprimentos: dict[str, list[int]] = defaultdict(list)
    vocativos_por_ato: dict[str, Counter[str]] = defaultdict(Counter)

    for msgs in threads.values():
        for texto, ato in msgs:
            n_msg[ato] += 1
            e = len(_EMOJI.findall(texto))
            if e:
                n_com_emoji[ato] += 1
                n_emoji_total[ato] += e
            vs = _VOCATIVOS.findall(texto)
            if vs:
                n_com_vocativo[ato] += 1
                for v in vs:
                    vocativos_por_ato[ato][v.lower()] += 1
            comprimentos[ato].append(len(texto))

    total = sum(n_msg.values())
    ordem = ["saudacao", "sondagem", "cotacao", "desconto", "logistica", "outro"]

    print(f"\n=== VOZ POR MOMENTO DO FUNIL ({total} bolhas do Vendedor) ===\n")
    hdr = f"{'ato':<11}{'n':>7}{'%msg':>7}{'emoji%':>8}{'emoji/msg':>11}{'vocat%':>8}{'len_p50':>9}"
    print(hdr)
    print("-" * len(hdr))
    for ato in ordem:
        n = n_msg[ato]
        if not n:
            continue
        comp = sorted(comprimentos[ato])
        p50 = comp[len(comp) // 2]
        print(
            f"{ato:<11}{n:>7}{100 * n / total:>6.1f}%"
            f"{100 * n_com_emoji[ato] / n:>7.1f}%"
            f"{n_emoji_total[ato] / n:>11.3f}"
            f"{100 * n_com_vocativo[ato] / n:>7.1f}%"
            f"{p50:>9}"
        )

    print("\n=== TOP VOCATIVOS POR ATO ===")
    for ato in ordem:
        if vocativos_por_ato[ato]:
            top = ", ".join(f"{v}:{c}" for v, c in vocativos_por_ato[ato].most_common(6))
            print(f"  {ato:<11} {top}")

    # agregado para comparar com o piso da estilometria
    ge = sum(n_com_emoji.values()) / total
    gv = sum(n_com_vocativo.values()) / total
    print(f"\nAGREGADO: emoji {100 * ge:.1f}% das bolhas | vocativo {100 * gv:.1f}% das bolhas")


if __name__ == "__main__":
    main()
