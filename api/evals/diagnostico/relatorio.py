"""CLI de diagnóstico do Loop A (C6 do flywheel): roda o classificador E2E (C1) + o gate de
invariantes determinístico (C3) sobre um ou mais `conversas*.jsonl` e imprime o relatório.

OFFLINE/PURO: NÃO gera conversas (isso é `evals.sim.gerar_conversas`, que custa API) -- só ANALISA
as já geradas. Zero API, zero DB. É o que o workflow `loop-agente.js` chama via subagente para medir
a taxa de E2E e separar as falhas (root-cause) da fila do juiz.

    uv run python -m evals.diagnostico.relatorio evals/calibracao/conversas_fixas.jsonl
    uv run python -m evals.diagnostico.relatorio --json evals/calibracao/conversas_fixas.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from .classificar import carregar_conversas, resumo_lote
from .invariantes import gate_de_invariantes


def montar_relatorio(
    conversas: list[dict[str, Any]], *, canarios: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Agrega classificação E2E + gate de invariantes num dict serializável (PURO)."""
    resumo = resumo_lote(conversas)
    invariantes = gate_de_invariantes(conversas, canarios=canarios)
    return {
        "n": resumo["n"],
        "e2e_completo": resumo["e2e_completo"],
        "taxa_e2e_completo": resumo["taxa_e2e_completo"],
        "por_terminal": resumo["por_terminal"],
        "falhas_duras": resumo["falhas_duras"],
        "precisa_julgamento": resumo["precisa_julgamento"],
        "vereditos": [dataclasses.asdict(v) for v in resumo["vereditos"]],
        "invariantes_violacoes": [dataclasses.asdict(a) for a in invariantes["violacoes"]],
        "invariantes_suspeitas": [dataclasses.asdict(a) for a in invariantes["suspeitas"]],
    }


def _imprimir(rel: dict[str, Any]) -> None:
    print(f"\n== Diagnóstico do Loop A ({rel['n']} conversas) ==")
    print(
        f"E2E completo (estrutural): {rel['e2e_completo']}/{rel['n']} ({rel['taxa_e2e_completo']:.0%})"
    )
    print(f"Por terminal: {rel['por_terminal']}")
    print(f"Falhas duras (sem juiz): {rel['falhas_duras'] or '—'}")
    print(f"Fila do juiz (persona/conduta/FP): {rel['precisa_julgamento'] or '—'}")
    if rel["invariantes_violacoes"]:
        print("\nINVARIANTES — VIOLAÇÕES (bloqueiam o auto-merge):")
        for a in rel["invariantes_violacoes"]:
            print(f"  [{a['invariante']}] {a['conversa_id']}: {a['detalhe']}")
    if rel["invariantes_suspeitas"]:
        print("\nInvariantes — suspeitas (o juiz confirma):")
        for a in rel["invariantes_suspeitas"]:
            print(f"  [{a['invariante']}] {a['conversa_id']}: {a['detalhe']}")
    # Por veredito, a cauda de flags -- guia o juiz/root-cause sobre onde olhar.
    for v in rel["vereditos"]:
        if v["flags"]:
            print(f"  · {v['conversa_id']}: terminal={v['terminal']} flags={list(v['flags'])}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # console Windows cp1252
    parser = argparse.ArgumentParser(description="Relatório de diagnóstico do Loop A (offline).")
    parser.add_argument("jsonl", nargs="+", help="um ou mais conversas*.jsonl a analisar.")
    parser.add_argument("--json", action="store_true", help="saída JSON (consumida por subagente).")
    parser.add_argument(
        "--canary", action="append", default=[], help="canary cross-modelo a auditar."
    )
    args = parser.parse_args()

    conversas: list[dict[str, Any]] = []
    for caminho in args.jsonl:
        p = Path(caminho)
        if not p.exists():
            print(f"AVISO: {p} não existe — pulando.", file=sys.stderr)
            continue
        conversas += carregar_conversas(p)

    if not conversas:
        print("Nenhuma conversa carregada.", file=sys.stderr)
        raise SystemExit(2)

    rel = montar_relatorio(conversas, canarios=tuple(args.canary))
    if args.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
    else:
        _imprimir(rel)


if __name__ == "__main__":
    main()
