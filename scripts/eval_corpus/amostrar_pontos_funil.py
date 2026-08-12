"""Amostra estratificada dos pontos de decisão do funil para o shadow (campanha-subst).

Entrada: os `class_shard_*.jsonl` da varredura F1 (classificação de TODAS as jogadas do
vendedor, feita por agentes Claude). Saída (ambas em `_dados_reais/`, gitignored — PII):

  - pontos_decisao.jsonl          → todos os pontos válidos (auditoria/recorte futuro)
  - pontos_decisao_amostra.jsonl  → amostra estratificada tipo_jogada × desfecho,
                                    semente fixa, pronta para `evals.shadow.funil`

Estratégia: aloca o orçamento por tipo de jogada proporcionalmente à raiz da frequência
(√n) — tipos raros (objeção, desconto, reengajamento) ganham peso relativo maior do que
teriam numa amostra proporcional pura, sem inventar volume onde não há. Dentro do tipo,
espalha pelos desfechos (round-robin determinístico) para não enviesar pró-funil-feliz.
Pontos de mídia pura ficam de fora da amostra (corte separado no relatório).

Uso:
    uv run python scripts/eval_corpus/amostrar_pontos_funil.py \
        --class-dir <dir com class_shard_*.jsonl> [--alvo 150] [--semente 7]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))


def carregar(class_dir: str) -> list[dict]:
    pontos: list[dict] = []
    for arq in sorted(glob.glob(os.path.join(class_dir, "class_shard_*.jsonl"))):
        with open(arq, encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                th = json.loads(linha)
                for p in th.get("pontos", []):
                    pontos.append(
                        {
                            "ref": th["ref"],
                            "idx": p["idx"],
                            "tipo": p.get("tipo", "outro"),
                            "boa": p.get("boa"),
                            "midia": bool(p.get("midia")),
                            "gatilho": p.get("gatilho", ""),
                            "desfecho": th.get("desfecho"),
                            "recorrente": bool(th.get("recorrente_suspeito")),
                            "tipo_atendimento": th.get("tipo_atendimento"),
                        }
                    )
    return pontos


def amostrar(pontos: list[dict], *, alvo: int, semente: int) -> list[dict]:
    rng = random.Random(semente)  # noqa: S311 — reprodutibilidade, não-cripto
    elegiveis = [p for p in pontos if not p["midia"] and p["tipo"] != "outro"]
    por_tipo: dict[str, list[dict]] = defaultdict(list)
    for p in elegiveis:
        por_tipo[p["tipo"]].append(p)

    pesos = {t: math.sqrt(len(ps)) for t, ps in por_tipo.items()}
    soma = sum(pesos.values())
    cotas = {t: max(4, round(alvo * w / soma)) for t, w in pesos.items()}

    amostra: list[dict] = []
    for tipo, ps in sorted(por_tipo.items()):
        rng.shuffle(ps)
        por_desfecho: dict[str, list[dict]] = defaultdict(list)
        for p in ps:
            por_desfecho[p["desfecho"] or "sem_label"].append(p)
        filas = [por_desfecho[d] for d in sorted(por_desfecho)]
        sel: list[dict] = []
        vistos: set[tuple[str, int]] = set()
        i = 0
        while len(sel) < min(cotas[tipo], len(ps)) and any(filas):
            fila = filas[i % len(filas)]
            i += 1
            if fila:
                p = fila.pop()
                chave = (p["ref"], p["idx"])
                if chave not in vistos:
                    vistos.add(chave)
                    sel.append(p)
        amostra.extend(sel)
    rng.shuffle(amostra)
    return amostra


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--class-dir", required=True)
    ap.add_argument("--alvo", type=int, default=150)
    ap.add_argument("--semente", type=int, default=7)
    args = ap.parse_args()

    pontos = carregar(args.class_dir)
    destino = os.path.join(AQUI, "_dados_reais")
    os.makedirs(destino, exist_ok=True)
    with open(os.path.join(destino, "pontos_decisao.jsonl"), "w", encoding="utf-8") as fh:
        for p in pontos:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    amostra = amostrar(pontos, alvo=args.alvo, semente=args.semente)
    with open(
        os.path.join(destino, "pontos_decisao_amostra.jsonl"), "w", encoding="utf-8"
    ) as fh:
        for p in amostra:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    contagem: dict[str, int] = defaultdict(int)
    for p in amostra:
        contagem[p["tipo"]] += 1
    total_por_tipo: dict[str, int] = defaultdict(int)
    for p in pontos:
        if not p["midia"]:
            total_por_tipo[p["tipo"]] += 1
    print(f"pontos totais: {len(pontos)}  amostra: {len(amostra)} (semente {args.semente})")
    for tipo in sorted(contagem):
        print(f"  {tipo:24s} {contagem[tipo]:4d} / {total_por_tipo[tipo]}")


if __name__ == "__main__":
    main()
