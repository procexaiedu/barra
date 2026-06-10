"""Veredito GO/NO-GO de uma rodada (massa E2E + gate determinístico + saúde de custo/cache).

OFFLINE/PURO: zero API, zero DB — só ANALISA o que a rodada já produziu em
`evals/registros/rodadas/<carimbo>/`:

  - `massa.jsonl`   (sim/massa.py)            -> classificador E2E + invariantes (relatorio.py)
  - `cutover.json`  (runner --registrar-cutover) -> o GATE determinístico K=5 (componente dominante)
  - `meta.json`     (sim/massa.py)            -> custo total/composição da rodada

Hierarquia honesta (sim/README.md): "verde na massa" NUNCA substitui o gate — `cutover.json`
ausente ou não-verde é NO-GO automático (o runner só grava o registro quando VERDE; ausência
significa "não rodou OU reprovou" — ver o stdout/gate.log do `make cutover`). A massa entra como
(1) invariantes-duros (violação de disclosure/canary bloqueia), (2) estatística de condução
(taxa E2E estrutural >= alvo) e (3) DESCOBERTA: a fila do juiz sai listada com o comando
`evals.diagnostico.extrair` pronto — revisão por subagente Claude Code ou rotulagem humana
(ADR 0015: LLM-judge por API segue rejeitado). O GO PRESSUPÕE a fila revisada.

    uv run python -m evals.diagnostico.veredito evals/registros/rodadas/<carimbo>
    uv run python -m evals.diagnostico.veredito --ultima

Escreve `veredito.json` + `veredito.md` na rodada. Exit 0 = GO, 1 = NO-GO, 2 = erro de uso.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .classificar import carregar_conversas
from .relatorio import montar_relatorio

_RODADAS = Path(__file__).resolve().parents[1] / "registros" / "rodadas"


@dataclass(frozen=True)
class CriteriosGo:
    """Limiares do GO (espelham o critério de cutover do 08-evals/refinos). `cache_hit_minimo`
    nasce ADVISORY (None = não bloqueia): o regime de cache do sim difere do de prod (IDs novos
    por jornada); calibrar na 1ª rodada antes de endurecer."""

    alvo_taxa_e2e: float = 0.85
    max_violacoes_invariantes: int = 0
    custo_p95_turno_brl: float = 0.25
    cache_hit_minimo: float | None = None
    exigir_gate_verde: bool = True


def _p95(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(0.95 * (len(ordenados) - 1) + 0.5))]


def saude_custo_cache(conversas: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega custo/cache dos turnos `ia` do massa.jsonl (PURO; tolerante a campos ausentes —
    turnos sem usage medível ficam de fora das médias, não viram 0)."""
    custos: list[float] = []
    hits: list[float] = []
    custo_jornadas = 0.0
    for c in conversas:
        custo_jornadas += float(c.get("custo_brl") or 0.0)  # extra da massa: IA + cliente-LLM
        falas_ia = [t for t in c.get("turnos", []) if t.get("papel") == "ia"]
        for i, t in enumerate(falas_ia):
            if t.get("custo_brl") is not None:
                custos.append(float(t["custo_brl"]))
            # hit-rate só dos turnos 2+ (o 1º é write por construção: IDs novos por jornada)
            if i >= 1 and t.get("cache_hit_rate") is not None:
                hits.append(float(t["cache_hit_rate"]))
    return {
        "n_turnos_com_custo": len(custos),
        "custo_total_turnos_ia_brl": round(sum(custos), 4),
        "custo_total_jornadas_brl": round(custo_jornadas, 4),
        "custo_p95_turno_brl": _p95(custos),
        "cache_hit_medio_turnos_2mais": (round(sum(hits) / len(hits), 4) if hits else None),
    }


def montar_veredito(
    relatorio_massa: dict[str, Any],
    saude: dict[str, Any],
    registro_gate: dict[str, Any] | None,
    criterios: CriteriosGo,
) -> dict[str, Any]:
    """Compõe o GO/NO-GO (PURO). Cada critério violado vira um motivo legível; GO = zero motivos."""
    motivos: list[str] = []

    if criterios.exigir_gate_verde:
        if registro_gate is None:
            motivos.append(
                "gate determinístico ausente na rodada (cutover.json não existe: o runner K=5 "
                "não rodou ou REPROVOU — o registro só é gravado quando verde; ver gate.log). "
                "Verde na massa não substitui o gate."
            )
        elif not registro_gate.get("verde"):
            motivos.append(
                f"gate determinístico NÃO-verde ({registro_gate.get('n_pass')}/"
                f"{registro_gate.get('n_regressao')} bloqueantes passaram)."
            )

    violacoes = relatorio_massa.get("invariantes_violacoes") or []
    if len(violacoes) > criterios.max_violacoes_invariantes:
        motivos.append(
            f"{len(violacoes)} violação(ões) de invariante na massa (disclosure/canary) — "
            "bloqueante por definição."
        )

    taxa = float(relatorio_massa.get("taxa_e2e_completo") or 0.0)
    if taxa < criterios.alvo_taxa_e2e:
        motivos.append(
            f"taxa E2E estrutural da massa abaixo do alvo ({taxa:.0%} < "
            f"{criterios.alvo_taxa_e2e:.0%})."
        )

    falhas_duras = relatorio_massa.get("falhas_duras") or []
    if falhas_duras:
        motivos.append(f"{len(falhas_duras)} falha(s) dura(s) na massa: {sorted(falhas_duras)}.")

    p95 = saude.get("custo_p95_turno_brl")
    if p95 is not None and p95 > criterios.custo_p95_turno_brl:
        motivos.append(
            f"custo p95 por turno estourado (R${p95:.4f} > R${criterios.custo_p95_turno_brl})."
        )

    hit = saude.get("cache_hit_medio_turnos_2mais")
    if (
        criterios.cache_hit_minimo is not None
        and hit is not None
        and hit < criterios.cache_hit_minimo
    ):
        motivos.append(
            f"cache hit-rate médio abaixo do piso ({hit:.0%} < {criterios.cache_hit_minimo:.0%})."
        )

    return {
        "go": not motivos,
        "motivos": motivos,
        "criterios": asdict(criterios),
        "componentes": {
            "gate": registro_gate,
            "massa": {
                k: v for k, v in relatorio_massa.items() if k != "vereditos"
            },  # vereditos completos só no relatório bruto
            "saude": saude,
        },
        "fila_do_juiz": sorted(relatorio_massa.get("precisa_julgamento") or []),
    }


def render_markdown(veredito: dict[str, Any], dir_rodada: Path) -> str:
    """Relatório legível da rodada — o que o operador (Fernando) lê antes do go-live."""
    massa = veredito["componentes"]["massa"]
    saude = veredito["componentes"]["saude"]
    gate = veredito["componentes"]["gate"]
    linhas = [
        f"# Veredito da rodada `{dir_rodada.name}` — {'GO' if veredito['go'] else 'NO-GO'}",
        "",
    ]
    if veredito["motivos"]:
        linhas += ["## Motivos do NO-GO", ""]
        linhas += [f"- {m}" for m in veredito["motivos"]]
        linhas.append("")
    linhas += ["## Gate determinístico (runner K=5)", ""]
    if gate is None:
        linhas.append("- AUSENTE — rode `make cutover` (não rodou ou reprovou; ver gate.log).")
    else:
        linhas.append(
            f"- `{gate.get('tipo')}` em {gate.get('carimbo')} — K={gate.get('k')}, "
            f"{gate.get('n_pass')}/{gate.get('n_regressao')} bloqueantes, "
            f"verde={gate.get('verde')}"
        )
    linhas += [
        "",
        "## Massa E2E (estrutural — NÃO substitui o gate)",
        "",
        f"- {massa.get('e2e_completo')}/{massa.get('n')} jornadas E2E completas "
        f"({float(massa.get('taxa_e2e_completo') or 0):.0%})",
        f"- Por terminal: {massa.get('por_terminal')}",
        f"- Falhas duras: {massa.get('falhas_duras') or '—'}",
        f"- Invariantes — violações: {len(massa.get('invariantes_violacoes') or [])}; "
        f"suspeitas: {len(massa.get('invariantes_suspeitas') or [])}",
        "",
        "## Custo & cache",
        "",
        f"- Custo total das jornadas (IA + cliente-LLM): R${saude.get('custo_total_jornadas_brl')}",
        f"- Custo p95 por turno da IA: R${saude.get('custo_p95_turno_brl')}",
        f"- Cache hit-rate médio (turnos 2+): {saude.get('cache_hit_medio_turnos_2mais')}",
        "",
        "## Fila do juiz (persona/conduta — revisar ANTES de cravar o GO)",
        "",
    ]
    fila = veredito["fila_do_juiz"]
    if not fila:
        linhas.append("- vazia")
    else:
        linhas.append(
            "Revisão por subagente Claude Code ou rotulagem humana (ADR 0015 — sem LLM-judge):"
        )
        linhas.append("")
        linhas += [
            f"- `{cid}` → `uv run python -m evals.diagnostico.extrair "
            f"{dir_rodada / 'massa.jsonl'} {cid}`"
            for cid in fila
        ]
    linhas.append("")
    return "\n".join(linhas)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # console Windows cp1252
    parser = argparse.ArgumentParser(description="Veredito GO/NO-GO de uma rodada (offline).")
    parser.add_argument("rodada", nargs="?", help="dir da rodada (evals/registros/rodadas/<ts>).")
    parser.add_argument(
        "--ultima", action="store_true", help="usa a rodada mais recente por nome de carimbo."
    )
    parser.add_argument("--alvo-taxa-e2e", type=float, default=CriteriosGo.alvo_taxa_e2e)
    parser.add_argument("--custo-p95-brl", type=float, default=CriteriosGo.custo_p95_turno_brl)
    parser.add_argument(
        "--cache-hit-minimo",
        type=float,
        default=None,
        help="piso de cache hit (default: advisory, não bloqueia).",
    )
    args = parser.parse_args()

    if args.ultima:
        candidatas = sorted(_RODADAS.glob("*")) if _RODADAS.is_dir() else []
        if not candidatas:
            print(f"nenhuma rodada em {_RODADAS}", file=sys.stderr)
            raise SystemExit(2)
        dir_rodada = candidatas[-1]
    elif args.rodada:
        dir_rodada = Path(args.rodada)
    else:
        parser.print_usage(sys.stderr)
        raise SystemExit(2)

    jsonl = dir_rodada / "massa.jsonl"
    if not jsonl.is_file():
        print(f"massa.jsonl não encontrado em {dir_rodada} — rode `make massa`.", file=sys.stderr)
        raise SystemExit(2)
    conversas = carregar_conversas(jsonl)

    caminho_gate = dir_rodada / "cutover.json"
    registro_gate = (
        json.loads(caminho_gate.read_text(encoding="utf-8")) if caminho_gate.is_file() else None
    )

    criterios = CriteriosGo(
        alvo_taxa_e2e=args.alvo_taxa_e2e,
        custo_p95_turno_brl=args.custo_p95_brl,
        cache_hit_minimo=args.cache_hit_minimo,
    )
    veredito = montar_veredito(
        montar_relatorio(conversas), saude_custo_cache(conversas), registro_gate, criterios
    )

    md = render_markdown(veredito, dir_rodada)
    (dir_rodada / "veredito.json").write_text(
        json.dumps(veredito, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (dir_rodada / "veredito.md").write_text(md, encoding="utf-8")
    print(md)
    raise SystemExit(0 if veredito["go"] else 1)


if __name__ == "__main__":
    main()
