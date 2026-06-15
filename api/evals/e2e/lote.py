"""Monta o NUCLEO de refs do corpus para a corrida e2e multi-perfil (o orquestrador faz fan-out
de um sub-agente-cliente por ref). So SELECT — offline, sem credito (§0).

Diversidade = estratificacao por EIXO DE COMPORTAMENTO do cliente (`extracao.extrair_nucleo`):
decidido_rapido, objetor, ghost_pos_cotacao, explorador_ambiguo, pre_cotacao_sumiu, externo — para
o agente ser testado contra TIPOS de cliente, nao so desfechos (literatura: personas diversas pegam
falhas diferentes). Cada item ja vem com a porta sugerida (base + indice) para o orquestrador subir
uma `sessao.py` por ref sem colisao. Com `--run-tag`, pula refs ja testadas naquele tag (dedup).

Uso:
    TEST_DATABASE_URL=... uv run python -m evals.e2e.lote --por-eixo 2 --porta-base 8800
    # -> imprime um JSON [{ref, eixo, desfecho_real, tipo_esperado, porta, abertura}, ...] no stdout
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .extracao import extrair_nucleo


async def montar_lote(
    conn: AsyncConnection[dict[str, Any]],
    *,
    por_eixo: int,
    porta_base: int,
    run_tag: str | None = None,
) -> list[dict[str, Any]]:
    perfis = await extrair_nucleo(conn, por_eixo=por_eixo)

    feitos: set[str] = set()
    if run_tag:
        cur = await conn.execute(
            "SELECT thread_ref FROM corpus.eval_e2e WHERE run_tag = %s AND thread_ref IS NOT NULL",
            (run_tag,),
        )
        feitos = {r["thread_ref"] for r in await cur.fetchall()}

    itens: list[dict[str, Any]] = []
    for p in perfis:
        if p.thread_ref in feitos:
            continue  # ja testado neste run_tag (dedup)
        itens.append(
            {
                "ref": p.thread_ref,
                "eixo": p.eixo_comportamento,
                "desfecho_real": p.desfecho_real,
                "tipo_esperado": p.tipo_esperado,
                "n_falas": len([p.abertura, *p.roteiro_cliente]),
                "abertura": p.abertura,
            }
        )
    # porta por item so depois de ter a lista final (indice estavel).
    for i, item in enumerate(itens):
        item["porta"] = porta_base + i
    return itens


async def _main(args: argparse.Namespace) -> None:
    conn = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"], autocommit=True, row_factory=dict_row
    )
    try:
        lote = await montar_lote(
            conn, por_eixo=args.por_eixo, porta_base=args.porta_base, run_tag=args.run_tag
        )
    finally:
        await conn.close()
    print(json.dumps(lote, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta o nucleo de refs do corpus por eixo (e2e).")
    ap.add_argument(
        "--por-eixo", type=int, default=2, help="nº de perfis por eixo de comportamento"
    )
    ap.add_argument("--porta-base", type=int, default=8800, help="porta da 1ª sessão (incrementa)")
    ap.add_argument("--run-tag", help="pula refs ja testadas neste tag em corpus.eval_e2e (dedup)")
    args = ap.parse_args()
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL (prod self-hosted; so SELECT aqui).")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
