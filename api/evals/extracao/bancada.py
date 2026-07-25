"""Bancada offline do extrator: roda, mede e relata — alvo proprio, fora dos gates de conduta.

    make bancada-extracao                      # baseline: o que a producao registrou (sem credito)
    make bancada-extracao ARGS="--real"        # ⚠️ §0: bate no DeepSeek, gasta credito
    make bancada-extracao ARGS="--variantes base,temp-zero --repeticoes 5"
    make bancada-extracao ARGS="--trajetoria"  # exige TEST_DATABASE_URL (nivel de impacto)

O extrator nao precisa de LLM-judge: a saida e estruturada, o rotulo e um conjunto de pares
campo-valor e a metrica e igualdade. Com o extrator `gravado` (baseline) a bancada roda sem
credito e sem banco — e por isso o teste da ferramenta entra no gate padrao.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .extrator import VARIANTES, Extrator, ExtratorDeepSeek, ExtratorGravado, Variante
from .golden import GoldenSet, carregar_golden
from .janela import montar_janela
from .metricas import agregar, avaliar
from .relatorio import formatar
from .replay import rodar_trajetoria

# Fabrica de extrator por variante: a variante muda o extrator (temperatura, descricao do aceite),
# entao ele nasce por variante, nao uma vez so.
CriarExtrator = Callable[[Variante], Extrator]


async def rodar_bancada(
    golden: GoldenSet,
    criar_extrator: CriarExtrator,
    *,
    variantes: list[Variante],
    repeticoes: int = 3,
    conn: AsyncConnection[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roda a bancada e devolve o relatorio como dicionario.

    `repeticoes` distingue melhora de sorte enquanto a extracao rodar com temperatura de sampling:
    cada item roda N vezes e o relatorio mostra a DISPERSAO, nao so a media. Com `conn`, roda
    tambem o nivel trajetoria (uma passada por variante — o custo la e o replay inteiro).
    """
    saida: dict[str, Any] = {}
    nome_extrator = ""
    for variante in variantes:
        extrator: Extrator = criar_extrator(variante)
        nome_extrator = getattr(extrator, "nome", type(extrator).__name__)
        rodadas = []
        for _ in range(repeticoes):
            payloads = {
                item.id: await extrator(
                    item, montar_janela(item, bloco_estado=variante.bloco_estado)
                )
                for item in golden.itens
            }
            rodadas.append(avaliar(golden.itens, payloads, variante=variante))

        trajetorias = []
        if conn is not None:
            for traj in golden.trajetorias:
                resultado = await rodar_trajetoria(conn, traj, extrator, variante=variante)
                trajetorias.append(resultado.como_dict())

        saida[variante.nome] = {**agregar(rodadas), "trajetorias": trajetorias}

    return {
        "meta": {
            "extrator": nome_extrator,
            "repeticoes": repeticoes,
            "itens": len(golden.itens),
            "trajetorias": len(golden.trajetorias) if conn is not None else 0,
            "limites": golden.meta.get("limites", []),
            "origem_golden": golden.meta.get("origem"),
        },
        "variantes": saida,
    }


def _variantes(nomes: str) -> list[Variante]:
    escolhidas = []
    for nome in [n.strip() for n in nomes.split(",") if n.strip()]:
        if nome not in VARIANTES:
            raise SystemExit(f"variante desconhecida: {nome} (disponiveis: {', '.join(VARIANTES)})")
        escolhidas.append(VARIANTES[nome])
    if not escolhidas:
        # Lista vazia rodaria a bancada sem medir nada e imprimiria relatorio vazio — falha alto.
        raise SystemExit(f"nenhuma variante escolhida (disponiveis: {', '.join(VARIANTES)})")
    return escolhidas


async def _rodar(args: argparse.Namespace) -> dict[str, Any]:
    golden = carregar_golden()
    criar_extrator = (
        (lambda variante: ExtratorDeepSeek(variante))
        if args.real
        else (lambda _v: ExtratorGravado())
    )
    conn = None
    if args.trajetoria:
        conn = await AsyncConnection.connect(
            os.environ["TEST_DATABASE_URL"],
            autocommit=False,
            row_factory=dict_row,
            prepare_threshold=None,
        )
    try:
        rel = await rodar_bancada(
            golden,
            criar_extrator,
            variantes=_variantes(args.variantes),
            repeticoes=args.repeticoes,
            conn=conn,
        )
    finally:
        if conn is not None:
            await conn.rollback()  # o Atendimento semeado da trajetoria nunca commita (§0)
            await conn.close()
    return rel


def main() -> None:
    ap = argparse.ArgumentParser(description="Bancada offline de avaliacao do extrator.")
    ap.add_argument(
        "--variantes", default="base", help=f"lista separada por vírgula: {', '.join(VARIANTES)}"
    )
    ap.add_argument("--repeticoes", type=int, default=3, help="repetições por item (dispersão)")
    ap.add_argument(
        "--real",
        action="store_true",
        help="⚠️ §0: roda o extrator de verdade (DeepSeek) — gasta crédito",
    )
    ap.add_argument(
        "--trajetoria",
        action="store_true",
        help="roda também o nível trajetória (exige TEST_DATABASE_URL; seed com ROLLBACK)",
    )
    ap.add_argument("--saida", help="arquivo JSON do relatório (opcional)")
    args = ap.parse_args()
    if args.trajetoria and not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Defina TEST_DATABASE_URL para o nível trajetória (seed com ROLLBACK).")
    if args.real and os.environ.get("EXTRACAO_AUTORIZADA") != "1":
        raise SystemExit(
            "A corrida REAL bate no DeepSeek e gasta crédito (§0). Defina EXTRACAO_AUTORIZADA=1 "
            "após a autorização do dev, ou rode sem --real para o baseline (extrator `gravado`)."
        )
    rel = asyncio.run(_rodar(args))
    print(formatar(rel))
    if args.saida:
        destino = Path(args.saida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n💾 relatório em: {destino}")


if __name__ == "__main__":
    main()
