"""Pontua a voz de um candidato SEGMENTADA por momento do funil, contra o perfil congelado por ato.

Fecha o loop da alavanca de voz mais forte: o agregado de `estilometria.py` dilui "emoji na hora
errada" (muito na cotação, pouco na saudação). Aqui cada bolha é rotulada por ato
(`barra.agente.fluxo.rotular_turno`, o rotulador de prod) e comparada contra o perfil d'ELA NAQUELE
ato — revelando se o agente põe emoji na cotação (que o humano corta) ou abre seco demais.

Reusa estilometria.py (distância) + o perfil congelado de `gerar_perfil_por_momento.py`. Roda pelo
env do api (importa barra). Dois modos:

  # candidato em arquivo (saída do simulador A/B, ou bolhas coladas):
  cd api && uv run python ../scripts/eval_corpus/estilo_por_momento.py \\
      ../scripts/eval_corpus/perfil_estilo_por_momento.json <cand.json|txt>

  # saída REAL do agente em prod (mede o AGENTE vivo, não o prompt) — read-only, §0:
  cd api && DATABASE_URL=... uv run python ../scripts/eval_corpus/estilo_por_momento.py \\
      ../scripts/eval_corpus/perfil_estilo_por_momento.json --prod [N]
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from estilometria import FEATURES, _ler_candidato, distancia, perfil_de_bolhas

from barra.agente.fluxo import rotular_turno

MIN_BOLHAS_ATO = 5  # abaixo disso a distância do ato é só indicativa (marcada com '~')


def agrupar_por_ato(lista_bolhas: list[str]) -> dict[str, list[str]]:
    """Rotula cada bolha pelo ato do funil (mesmo rotulador do filtro de emoji do worker)."""
    por_ato: dict[str, list[str]] = defaultdict(list)
    for b in lista_bolhas:
        por_ato[rotular_turno(b)].append(b)
    return por_ato


def _alertas(ref: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    """Sinaliza os desvios de voz mais caros (a direção que delata bot), com folga de tolerância."""
    a: list[str] = []
    if cand["taxa_emoji"] - ref["taxa_emoji"] > 0.10:
        a.append(f"emoji ALTO {cand['taxa_emoji']:.2f} vs ref {ref['taxa_emoji']:.2f}")
    if cand["taxa_vocativo"] - ref["taxa_vocativo"] > 0.15:
        a.append(f"vocativo ALTO {cand['taxa_vocativo']:.2f} vs {ref['taxa_vocativo']:.2f}")
    if cand["taxa_ponto_final"] - ref["taxa_ponto_final"] > 0.10:
        a.append(f"ponto final {cand['taxa_ponto_final']:.2f} vs {ref['taxa_ponto_final']:.2f}")
    if ref["taxa_rs"] - cand["taxa_rs"] > 0.05:
        a.append(f"rs BAIXO {cand['taxa_rs']:.2f} vs ref {ref['taxa_rs']:.2f}")
    return a


def distancia_por_ato(ref_por_ato: dict[str, Any], cand_bolhas: list[str]) -> dict[str, Any]:
    """Distância candidato vs corpus por ato do funil. Cada ato traz agregado, razão/piso e alertas."""
    cand_por_ato = agrupar_por_ato(cand_bolhas)
    out: dict[str, Any] = {}
    for ato, bolhas_ato in sorted(cand_por_ato.items()):
        ref = ref_por_ato.get(ato)
        if not ref:
            out[ato] = {"n": len(bolhas_ato), "obs": "ato sem referência no perfil congelado"}
            continue
        cand_perfil = perfil_de_bolhas(bolhas_ato)
        d = distancia(ref["perfil"], cand_perfil)
        piso = ref.get("piso_ela_vs_ela")
        out[ato] = {
            "n": len(bolhas_ato),
            "confiavel": len(bolhas_ato) >= MIN_BOLHAS_ATO,
            "agregado": round(d["agregado"], 4),
            "piso": piso,
            "razao_piso": round(d["agregado"] / piso, 1) if piso else None,
            "features": {k: round(d[k], 4) for k in FEATURES},
            "alertas": _alertas(ref["perfil"], cand_perfil),
        }
    return out


def _bolhas_de_prod(n: int) -> list[str]:
    """Lê as últimas N bolhas REAIS despachadas pelo agente (direcao='ia', texto). Read-only."""
    import psycopg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("--prod exige DATABASE_URL (leitura read-only de barravips.mensagens)")
    sql = """
        SELECT conteudo FROM barravips.mensagens
        WHERE direcao = 'ia' AND tipo = 'texto'
          AND conteudo IS NOT NULL AND btrim(conteudo) <> ''
        ORDER BY created_at DESC
        LIMIT %s
    """
    out: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, (n,))
        for (conteudo,) in cur:
            out.extend(b for b in conteudo.split("\n\n") if b.strip())  # 1 linha-branca = 1 bolha
    return [b.strip() for b in out if b.strip()]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(
            "uso: estilo_por_momento.py <perfil_por_momento.json> <cand.(json|txt) | --prod [N]>"
        )
    doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    ref_por_ato = doc.get("por_ato", doc)

    if sys.argv[2] == "--prod":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        cand = _bolhas_de_prod(n)
        origem = f"prod (últimas {len(cand)} bolhas ia/texto)"
    else:
        cand = _ler_candidato(sys.argv[2])
        origem = sys.argv[2]
    if not cand:
        sys.exit("candidato sem bolhas")

    res = distancia_por_ato(ref_por_ato, cand)
    print(f"candidato: {origem}  ({len(cand)} bolhas)\n")
    print(f"{'ato':<11}{'n':>6}{'agg':>8}{'piso':>8}{'x_piso':>8}  alertas")
    print("-" * 70)
    for ato, r in res.items():
        if "obs" in r:
            print(f"{ato:<11}{r['n']:>6}  {r['obs']}")
            continue
        flag = "" if r["confiavel"] else "~"
        alertas = "; ".join(r["alertas"]) or "ok"
        print(
            f"{ato:<11}{r['n']:>6}{r['agregado']:>8.3f}"
            f"{r['piso'] or '—'!s:>8}{str(r['razao_piso'] or '—') + flag:>8}  {alertas}"
        )
    print("\n(x_piso = quantas vezes o piso ELA-vs-ELA daquele ato; ~ = n abaixo do confiável)")


if __name__ == "__main__":
    main()
