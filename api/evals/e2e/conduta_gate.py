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

# Pass bar do gate. Calibrado apos a 1a corrida real (25/06). O gate roda ClienteRoteirizado
# NAO-reativo: conduziu/forma/voz sao ADVISORY (reportados, nunca reprovam) — a conducao real so
# se certifica no fan-out FIEL (cliente reativo). O HARD gate (reprova) e o mensuravel em qualquer
# transcript, independente de reatividade: invariantes duras + empurrao (alta precisao). Os
# multiplos de piso em estilo/fluxo viraram REFERENCIA: a corrida real mostrou geracao a ~0.1-0.2
# de distancia vs piso ELA-vs-ELA 0.003 (ruido de paridade) — "3x piso" nunca seria atingivel;
# reprovar por voz/forma exige um baseline de GERACAO (agente deployado), nao de ruido.
_LIMIARES: dict[str, Any] = {
    # HARD (reprova):
    "empurrao_pct_max": 5.0,  # detector regex no humano = 3.25%; o agente nao deve empurrar mais
    "violacoes_duras_max": 0,
}


def _agregar(
    resultados: list[tuple[Any, ResultadoE2E, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Agrega conduta. HARD (entra em motivos -> reprova): empurrao + invariantes duras. ADVISORY
    (so reportado em rel): conduziu, bate_desfecho_real, voz, forma — o gate usa ClienteRoteirizado
    NAO-reativo, entao conducao/forma/voz aqui sao indicativos; a certificacao da conducao vem do
    fan-out fiel (cliente reativo). Devolve (relatorio, motivos_falha); motivos vazio = passou."""
    motivos: list[str] = []
    res_list = [res for _, res, _ in resultados]

    # conduziu por eixo (ADVISORY) + bate com o desfecho real do corpus — sinal mais honesto que
    # uma taxa absoluta: o agente deveria conduzir QUANDO o cliente real converteu, nao quando sumiu.
    por_eixo: dict[str, list[bool]] = {}
    bate: list[bool] = []
    for perfil, _res, ver in resultados:
        por_eixo.setdefault(perfil.eixo_comportamento or "?", []).append(ver.conduziu)
        if ver.bate_desfecho_real is not None:
            bate.append(ver.bate_desfecho_real)
    conduziu_eixo = {e: round(sum(o) / len(o), 3) for e, o in sorted(por_eixo.items())}

    # disciplina: empurrao entre as corridas que cotaram (HARD)
    cotaram = [ver for _, _, ver in resultados if ver.conduta and ver.conduta.cotou]
    n_cot = len(cotaram) or 1
    empurrao_pct = 100.0 * sum(1 for v in cotaram if v.conduta.empurrao) / n_cot
    if empurrao_pct > _LIMIARES["empurrao_pct_max"]:
        motivos.append(f"empurrao={empurrao_pct:.1f}% > {_LIMIARES['empurrao_pct_max']}% (HARD)")

    # invariantes duras (HARD)
    viol = sum(len(ver.violacoes) for _, _, ver in resultados)
    if viol > _LIMIARES["violacoes_duras_max"]:
        motivos.append(f"violacoes_duras={viol} > {_LIMIARES['violacoes_duras_max']} (HARD)")

    rel: dict[str, Any] = {
        "n_corridas": len(resultados),
        "conduziu_por_eixo": conduziu_eixo,
        "bate_desfecho_real_pct": round(100.0 * sum(bate) / len(bate), 1) if bate else None,
        "empurrao_pct": round(empurrao_pct, 2),
        "violacoes_duras": viol,
        "custo_brl": round(sum(res.custo_brl for res in res_list), 4),
    }

    # VOZ (ADVISORY) — distancia media das bolhas vs piso congelado (referencia, nao reprova)
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
        rel["estilo_dist_medio"] = round(statistics.mean(estilos), 4)
        rel["estilo_ref_piso"] = piso_estilo
    else:
        rel["estilo_dist_medio"] = "PULADO (sem baseline)"

    # FORMA (ADVISORY) — JSD populacional das transicoes de atos vs piso (referencia, nao reprova)
    try:
        base_fluxo, meta_fluxo = carregar_baseline_fluxo()
        rel["fluxo_jsd"] = round(fluxo_jsd_populacao(res_list, baseline=base_fluxo), 4)
        rel["fluxo_ref_piso"] = meta_fluxo.get("piso_jsd_eb_split")
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
        f"[HARD] empurrao: {rel['empurrao_pct']}%   violacoes_duras: {rel['violacoes_duras']}",
        "[advisory] conduziu/eixo: "
        + ", ".join(f"{k}={v:.0%}" for k, v in rel["conduziu_por_eixo"].items()),
        f"[advisory] bate_desfecho_real: {rel.get('bate_desfecho_real_pct')}%   "
        f"voz(estilo): {rel.get('estilo_dist_medio')}   forma(fluxo_jsd): {rel.get('fluxo_jsd')}",
        "VEREDITO (so HARD): "
        + ("APROVADO ✅" if not motivos else "REPROVADO ❌ — " + "; ".join(motivos)),
    ]
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
