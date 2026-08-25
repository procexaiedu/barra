"""Gate de regressao em duas fases — mede o mesmo por ~1/6 do custo.

    Fase A (gratis)  : monta o contexto dos 73 cenarios com o chat FAKE e compara o carimbo
                       (`carimbo.carimbar`) com o baseline versionado. ~R$ 0,01, ~40s.
    Fase B (paga)    : chama o LLM SO nos cenarios cujo contexto mudou + os SENTINELAS.

A economia nao vem de medir menos: vem de parar de perguntar ao modelo o que o contexto ja
responde. Um cenario cujo prompt saiu byte-identico ao da ultima corrida verde nao tem como ter
regredido por causa do NOSSO codigo — so por drift do provider, que e exatamente o que os
sentinelas existem para pegar.

Uso:
    python -m evals.e2e.regressao --gravar-baseline   # apos uma corrida REAL verde
    python -m evals.e2e.regressao                     # Fase A; lista quem precisa de Fase B
    python -m evals.e2e.regressao --executar-fase-b   # Fase A + roda o LLM no que ela selecionou
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .carimbo import carregar_baseline, comparar, gravar_baseline

# Os cenarios que rodam no LLM SEMPRE, mesmo com o contexto intacto. Nao sao "os mais
# importantes": sao aqueles cuja falha o carimbo nao enxergaria, porque o contexto continua certo
# e quem erra e o modelo. Cada um esta aqui por um incidente que ja aconteceu.
SENTINELAS: dict[str, str] = {
    # 14/08: 2 de 20 runs recusaram o pedido ilegal SEM escalar. Contexto identico nas 20 — a
    # diferenca estava so na decisao do modelo de chamar a tool. E o caso-tese do sentinela.
    "conteudo_ilegal_insiste": "linha 7 do nucleo; unica regra sem classificador deterministico",
    # A escada de desconto e aritmetica DO MODELO sobre numeros que o contexto entrega certos.
    "desconto_abaixo_teto": "piso do desconto (ADR-0031): o contexto nunca erra, a conta sim",
    # ADR-0035 revogado pelo 0039: o regime de composicao ja enganou o projeto duas vezes, e o
    # bloco renderiza igual nos dois — quem muda de ideia e o modelo.
    "menage_com_secao": "composicao soma UM extra, nao dobra (ADR-0039)",
    # Regressao real do c7: a conduta de book mudou sem o contexto mudar.
    "duvida_das_fotos": "book de uma vez; regrediu no c7 com contexto intacto",
    # eb01:210917388210413: o piso ANDOU entre a oferta e o aceite. Timing, nao montagem.
    "piso_que_andou": "caso real de piso deslizante",
    # O output_guard e a rede que salva o resto; ele decide sobre a bolha, nao sobre o prompt.
    "agora_com_ela_ocupada": "nega o agora sem revelar o outro cliente",
    # SEC-11 ponta a ponta: a cerca do spotlight e montagem (o carimbo a ve), mas OBEDECER a
    # cerca e decisao do modelo — e e a metade que nenhum hash mede.
    "injecao_pelo_audio": "red team: o modelo obedece a cerca do spotlight?",
}


async def _colher_carimbos() -> dict[str, Any]:
    """Fase A: roda a massa com o chat fake e devolve o carimbo de cada cenario."""
    from evals.e2e.massa import rodar_massa
    from evals.e2e.sessao import _graph_fake

    carimbos: dict[str, Any] = {}
    conn: AsyncConnection[dict[str, Any]] = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        await rodar_massa(conn, _graph_fake(), k=1, carimbos=carimbos)
    finally:
        # ROLLBACK sempre: a Fase A nao deixa rastro no banco (§0).
        await conn.rollback()
        await conn.close()
    return carimbos


def _selecionar(carimbos: dict[str, Any], baseline: dict[str, Any]) -> tuple[set[str], list[str]]:
    """Quem vai para a Fase B + o relatorio legivel da Fase A."""
    linhas: list[str] = []
    mudaram: set[str] = set()
    for nome, carimbo in sorted(carimbos.items()):
        velho = baseline.get(nome)
        if velho is None:
            # Cenario NOVO nao tem baseline: nao ha o que comparar, e "igual" seria mentira.
            mudaram.add(nome)
            linhas.append(f"  + {nome}: cenario novo (sem baseline)")
            continue
        diffs = comparar(carimbo, velho)
        if diffs:
            mudaram.add(nome)
            linhas.append(f"  ⚠ {nome}")
            linhas.extend(f"      {d}" for d in diffs)
    # O baseline que perdeu o cenario: renomear um cenario o tira da medicao em silencio.
    for nome in sorted(set(baseline) - set(carimbos)):
        linhas.append(f"  - {nome}: sumiu da lista de cenarios (renomeado? removido?)")
    return mudaram, linhas


async def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--gravar-baseline",
        action="store_true",
        help="grava o carimbo atual como baseline (faca APOS uma corrida real verde)",
    )
    ap.add_argument(
        "--executar-fase-b",
        action="store_true",
        help="roda o LLM real nos cenarios selecionados (gasta credito)",
    )
    ap.add_argument("--run-tag", help="tag do veredito da Fase B em corpus.eval_e2e")
    args = ap.parse_args()

    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL.")

    print("FASE A — contexto montado (chat fake, sem credito)")
    carimbos = await _colher_carimbos()

    if args.gravar_baseline:
        gravar_baseline(carimbos)
        print(f"  baseline gravado: {len(carimbos)} cenarios")
        return

    baseline = carregar_baseline()
    if not baseline:
        raise SystemExit("Sem baseline. Rode --gravar-baseline apos uma corrida real verde.")

    mudaram, linhas = _selecionar(carimbos, baseline)
    iguais = len(carimbos) - len(mudaram)
    print(f"  {len(carimbos)} cenarios · {iguais} com o contexto intacto")
    for linha in linhas:
        print(linha)

    alvo = mudaram | set(SENTINELAS)
    print(f"\nFASE B — LLM real em {len(alvo)} de {len(carimbos)}")
    print(f"  por mudanca de contexto: {len(mudaram)}")
    print(f"  sentinelas (sempre):     {len(SENTINELAS)}")
    if not args.executar_fase_b:
        print("\n  (--executar-fase-b para rodar; sem ele isto foi so o diagnostico gratuito)")
        print(f"  alvo: {' '.join(sorted(alvo))}")
        return

    if os.environ.get("E2E_AUTORIZADO") != "1":
        raise SystemExit("Fase B gasta credito: exporte E2E_AUTORIZADO=1.")

    from barra.agente.graph import build_graph
    from evals.e2e.massa import rodar_massa

    conn: AsyncConnection[dict[str, Any]] = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    conn_eval: AsyncConnection[dict[str, Any]] | None = None
    if args.run_tag:
        conn_eval = await AsyncConnection.connect(
            os.environ["TEST_DATABASE_URL"],
            autocommit=True,
            row_factory=dict_row,
            prepare_threshold=None,
        )
    try:
        resultados = await rodar_massa(
            conn, build_graph(), k=1, somente=alvo, run_tag=args.run_tag, conn_eval=conn_eval
        )
    finally:
        await conn.rollback()
        await conn.close()
        if conn_eval is not None:
            await conn_eval.close()

    reprovados = [
        r for r in resultados if any(v is False for k, v in r.items() if k.endswith("_ok"))
    ]
    print(f"\n  {len(resultados) - len(reprovados)}/{len(resultados)} sem check reprovado")
    for r in reprovados:
        falhos = [k for k, v in r.items() if k.endswith("_ok") and v is False]
        print(f"  ⚠ {r['cenario']}: {', '.join(falhos)}")


if __name__ == "__main__":
    asyncio.run(_main())
