"""Gate de CONDUTA: o agente conduz a venda como o Vendedor (forma + voz + disciplina) e chega
a confirmacao? Roda o NUCLEO estratificado de personas reais (`extrair_nucleo`, 6 eixos de
comportamento) contra o grafo REAL com `ClienteRoteirizado`, aplica os scorers de `evals.conduta`
+ os invariantes do veredito e2e, e AFIRMA os limiares (pass bar). Exit 1 se reprovar.

⚠️ §0: a corrida REAL gasta credito do agente (1 ainvoke/turno) e exige TEST_DATABASE_URL (le o
corpus READ-ONLY p/ as personas + seed efemero com ROLLBACK). `--fake` injeta um grafo mock (sem
credito) e so valida o ENCANAMENTO — os numeros de conduta NAO sao significativos com texto canned.

Os limiares vivem aqui (`_LIMIARES`), como multiplos dos pisos congelados; recalibre apos a 1a
corrida real. Sem os baselines (`evals/baselines/*.json`), os checks de FORMA/VOZ sao PULADOS com
aviso (so empurrao/conduziu/violacoes valem) — ver `evals/baselines/README.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from evals.conduta import carregar_baseline_fluxo, carregar_perfil_estilo, fluxo_jsd_populacao
from evals.e2e.avaliacao import avaliar_e2e
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.extracao import extrair_nucleo
from evals.e2e.runner import ResultadoE2E, rodar_e2e
from evals.e2e.transcritos import salvar_transcritos
from evals.harness import habilitar_tracing

# Pass bar inicial (TUNAVEL apos a 1a corrida real). Forma/voz como MULTIPLOS do piso congelado.
_LIMIARES: dict[str, Any] = {
    "conduziu_min_por_eixo": {"decidido_rapido": 0.8, "objetor": 0.6, "externo": 0.6},
    "conduziu_min_default": 0.5,
    "empurrao_pct_max": 2.0,
    "estilo_dist_max_mult_piso": 3.0,
    "fluxo_jsd_max_mult_piso": 2.0,
    "violacoes_duras_max": 0,
}


def _agregar(
    resultados: list[tuple[Any, ResultadoE2E, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Agrega conduta por eixo + global e afirma os limiares. Devolve (relatorio, motivos_falha).
    motivos vazio = passou. Checks de forma/voz sao PULADOS (nao falham) sem baseline congelado."""
    motivos: list[str] = []
    res_list = [res for _, res, _ in resultados]

    # conduziu por eixo
    por_eixo: dict[str, list[bool]] = {}
    for perfil, _res, ver in resultados:
        por_eixo.setdefault(perfil.eixo_comportamento or "?", []).append(ver.conduziu)
    conduziu_eixo: dict[str, float] = {}
    for eixo, oks in sorted(por_eixo.items()):
        taxa = sum(oks) / len(oks)
        conduziu_eixo[eixo] = round(taxa, 3)
        alvo = _LIMIARES["conduziu_min_por_eixo"].get(eixo, _LIMIARES["conduziu_min_default"])
        if taxa < alvo:
            motivos.append(f"conduziu[{eixo}]={taxa:.0%} < {alvo:.0%}")

    # disciplina: empurrao entre as corridas que cotaram
    cotaram = [ver for _, _, ver in resultados if ver.conduta and ver.conduta.cotou]
    n_cot = len(cotaram) or 1
    empurrao_pct = 100.0 * sum(1 for v in cotaram if v.conduta.empurrao) / n_cot
    if empurrao_pct > _LIMIARES["empurrao_pct_max"]:
        motivos.append(f"empurrao={empurrao_pct:.1f}% > {_LIMIARES['empurrao_pct_max']}%")

    # invariantes duras
    viol = sum(len(ver.violacoes) for _, _, ver in resultados)
    if viol > _LIMIARES["violacoes_duras_max"]:
        motivos.append(f"violacoes_duras={viol} > {_LIMIARES['violacoes_duras_max']}")

    rel: dict[str, Any] = {
        "n_corridas": len(resultados),
        "conduziu_por_eixo": conduziu_eixo,
        "empurrao_pct": round(empurrao_pct, 2),
        "violacoes_duras": viol,
        "custo_brl": round(sum(res.custo_brl for res in res_list), 4),
    }

    # VOZ (per-conversa) — so com baseline congelado
    estilos = [
        v.conduta.estilo_dist
        for _, _, v in resultados
        if v.conduta and v.conduta.estilo_dist is not None
    ]
    try:
        piso_estilo = carregar_perfil_estilo().get("__meta__", {}).get("piso_ela_vs_ela")
    except FileNotFoundError:
        piso_estilo = None
    if estilos and piso_estilo:
        medio = statistics.mean(estilos)
        teto = piso_estilo * _LIMIARES["estilo_dist_max_mult_piso"]
        rel["estilo_dist_medio"] = round(medio, 4)
        rel["estilo_teto"] = round(teto, 4)
        if medio > teto:
            motivos.append(
                f"estilo_dist={medio:.4f} > {teto:.4f} ({_LIMIARES['estilo_dist_max_mult_piso']}x piso)"
            )
    else:
        rel["estilo_dist_medio"] = "PULADO (sem baseline)"

    # FORMA (populacional) — so com baseline congelado
    try:
        base_fluxo, meta_fluxo = carregar_baseline_fluxo()
        piso_fluxo = meta_fluxo.get("piso_jsd_eb_split")
        jsd = fluxo_jsd_populacao(res_list, baseline=base_fluxo)
        teto = (piso_fluxo or 0) * _LIMIARES["fluxo_jsd_max_mult_piso"]
        rel["fluxo_jsd"] = round(jsd, 4)
        rel["fluxo_teto"] = round(teto, 4)
        if piso_fluxo and jsd > teto:
            motivos.append(
                f"fluxo_jsd={jsd:.4f} > {teto:.4f} ({_LIMIARES['fluxo_jsd_max_mult_piso']}x piso)"
            )
    except FileNotFoundError:
        rel["fluxo_jsd"] = "PULADO (sem baseline)"

    return rel, motivos


async def rodar_gate(
    conn: AsyncConnection[dict[str, Any]],
    graph: Any,
    *,
    por_eixo: int = 2,
    max_turnos: int = 12,
) -> tuple[dict[str, Any], list[str], list[tuple[Any, ResultadoE2E, Any]]]:
    perfis = await extrair_nucleo(conn, por_eixo=por_eixo)
    if not perfis:
        raise SystemExit("nucleo vazio — corpus.threads nao retornou personas (DSN/§0?).")
    resultados: list[tuple[Any, ResultadoE2E, Any]] = []
    for perfil in perfis:
        res = await rodar_e2e(
            conn,
            perfil,
            ClienteRoteirizado(perfil.roteiro_cliente),
            graph=graph,
            max_turnos=max_turnos,
            escopar_trace=True,
        )
        resultados.append((perfil, res, avaliar_e2e(res, perfil)))
    rel, motivos = _agregar(resultados)
    return rel, motivos, resultados


def _formatar(rel: dict[str, Any], motivos: list[str]) -> str:
    linhas = [
        "",
        "=== Gate de Conduta ===",
        f"corridas: {rel['n_corridas']}  custo: R$ {rel['custo_brl']}",
    ]
    linhas.append(
        "conduziu por eixo: "
        + ", ".join(f"{k}={v:.0%}" for k, v in rel["conduziu_por_eixo"].items())
    )
    linhas.append(f"empurrao: {rel['empurrao_pct']}%   violacoes_duras: {rel['violacoes_duras']}")
    linhas.append(
        f"voz (estilo_dist medio): {rel.get('estilo_dist_medio')}   forma (fluxo_jsd): {rel.get('fluxo_jsd')}"
    )
    linhas.append(
        "VEREDITO: " + ("APROVADO ✅" if not motivos else "REPROVADO ❌ — " + "; ".join(motivos))
    )
    return "\n".join(linhas)


async def _main(args: argparse.Namespace) -> None:
    from barra.agente.graph import build_graph
    from evals.e2e.sessao import _graph_fake

    ligou = habilitar_tracing()
    print(f"langfuse: {'ligado' if ligou else 'desligado (sem LANGFUSE_*)'}")
    graph = _graph_fake() if args.fake else build_graph()

    conn = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        rel, motivos, corridas = await rodar_gate(
            conn, graph, por_eixo=args.por_eixo, max_turnos=args.max_turnos
        )
    finally:
        await conn.rollback()  # seed efemero nunca commita (§0)
        await conn.close()

    # Salva TODAS as conversas (antes do exit) para avaliacao humana posterior — requisito do dev.
    saida = (
        Path(args.saida)
        if args.saida
        else Path("evals/saidas") / time.strftime("conduta-%Y%m%d-%H%M%S")
    )
    destino = salvar_transcritos(saida, corridas, titulo="Gate de Conduta — transcritos", rel=rel)
    print(_formatar(rel, motivos))
    print(f"\n💾 {len(corridas)} conversas salvas em: {destino}")
    print(f"   abra no navegador: {destino / 'transcritos.html'}")
    if motivos:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gate de conduta (forma+voz+disciplina) sobre o nucleo."
    )
    ap.add_argument("--por-eixo", type=int, default=2, help="personas por eixo de comportamento")
    ap.add_argument("--max-turnos", type=int, default=12)
    ap.add_argument(
        "--saida", help="diretorio dos transcritos (default: evals/saidas/conduta-<timestamp>)"
    )
    ap.add_argument(
        "--fake", action="store_true", help="grafo mockado: valida encanamento sem credito"
    )
    args = ap.parse_args()
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit(
            "Defina TEST_DATABASE_URL (prod self-hosted; le o corpus read-only + seed)."
        )
    if not args.fake and os.environ.get("E2E_AUTORIZADO") != "1":
        raise SystemExit(
            "Corrida REAL do gate gasta credito do agente (§0). Defina E2E_AUTORIZADO=1 apos a "
            "autorizacao do dev, ou use --fake para validar o encanamento sem credito."
        )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
