#!/usr/bin/env python3
"""Lê o CSV rotulado por humano e responde: dá pra confiar no judge?

Entrada: o CSV de `exportar_amostra.py` com a coluna `rotulo_humano` preenchida
(`aprovado` / `reprovado`; linhas em branco são ignoradas e contadas à parte).

Saída: por judge (`pos_envio` / `aup`) e no agregado —
  * matriz de confusão judge vs. humano;
  * acurácia e concordância esperada por acaso;
  * **Cohen's κ** com a leitura de Landis & Koch;
  * precision / recall / F1 de cada classe, tomando o humano como verdade.

Sem dependência nenhuma: κ implementado à mão (stdlib pura).

Uso:
    python3 scripts/calibracao/computar_kappa.py amostra_rotulada.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

CLASSES = ("aprovado", "reprovado")

# Landis & Koch (1977). O corte que importa na prática: abaixo de 0.20 o judge não carrega
# informação sobre o rótulo humano além do acaso — usar como gate vinculante é ruído com autoridade.
FAIXAS = (
    (0.81, "quase perfeita — o judge é substituto do humano"),
    (0.61, "substancial — confiável como gate, revisar só as bordas"),
    (0.41, "moderada — serve de triagem, NÃO de gate vinculante sozinho"),
    (0.21, "razoável (fair) — sinal fraco; recalibrar a rubrica antes de confiar"),
    (0.00, "leve/nenhuma — JUDGE NÃO CONFIÁVEL: reprova quase por acaso"),
)


def ler(caminho: Path) -> tuple[list[tuple[str, str, str]], int, list[str]]:
    """-> (pares (judge, judge_label, humano_label), n_sem_rotulo, avisos)."""
    pares: list[tuple[str, str, str]] = []
    sem_rotulo = 0
    avisos: list[str] = []
    with caminho.open(encoding="utf-8", newline="") as fh:
        leitor = csv.DictReader(fh)
        faltando = {"judge", "veredicto_judge", "rotulo_humano"} - set(leitor.fieldnames or [])
        if faltando:
            sys.exit(f"CSV sem as colunas obrigatórias: {sorted(faltando)}")
        for i, linha in enumerate(leitor, start=2):
            humano = (linha.get("rotulo_humano") or "").strip().lower()
            judge = (linha.get("veredicto_judge") or "").strip().lower()
            if not humano:
                sem_rotulo += 1
                continue
            if humano not in CLASSES:
                avisos.append(f"linha {i}: rotulo_humano='{humano}' fora de {CLASSES} — ignorada")
                continue
            if judge not in CLASSES:
                avisos.append(f"linha {i}: veredicto_judge='{judge}' fora de {CLASSES} — ignorada")
                continue
            pares.append(((linha.get("judge") or "?").strip() or "?", judge, humano))
    return pares, sem_rotulo, avisos


def kappa(pares: list[tuple[str, str]]) -> tuple[float, float, float]:
    """Cohen's κ para 2 avaliadores / 2 classes. -> (κ, p_observado, p_esperado)."""
    n = len(pares)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    concordou = sum(1 for a, b in pares if a == b)
    po = concordou / n
    marg_a = Counter(a for a, _ in pares)
    marg_b = Counter(b for _, b in pares)
    pe = sum((marg_a[c] / n) * (marg_b[c] / n) for c in CLASSES)
    if pe == 1.0:  # ambos cravaram a mesma classe em tudo: κ indefinido
        return float("nan"), po, pe
    return (po - pe) / (1 - pe), po, pe


def leitura(k: float) -> str:
    if k != k:  # NaN
        return "indefinido (um dos avaliadores usou uma classe só)"
    if k < 0:
        return "NEGATIVO — o judge discorda do humano mais que o acaso; algo está invertido"
    for piso, texto in FAIXAS:
        if k >= piso:
            return texto
    return "?"


def por_classe(pares: list[tuple[str, str]], classe: str) -> tuple[float, float, float, int]:
    """precision/recall/F1 do judge para `classe`, com o humano como verdade. -> (p, r, f1, suporte)."""
    tp = sum(1 for j, h in pares if j == classe and h == classe)
    fp = sum(1 for j, h in pares if j == classe and h != classe)
    fn = sum(1 for j, h in pares if j != classe and h == classe)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = (
        2 * prec * rec / (prec + rec)
        if prec == prec and rec == rec and prec + rec
        else float("nan")
    )
    return prec, rec, f1, tp + fn


def _num(x: float) -> str:
    return "  n/a" if x != x else f"{x:5.3f}"


def relatorio(titulo: str, pares: list[tuple[str, str]]) -> None:
    n = len(pares)
    print(f"\n{'=' * 72}\n{titulo}  (n={n})\n{'=' * 72}")
    if n == 0:
        print("  sem linhas rotuladas.")
        return

    m = {(j, h): 0 for j in CLASSES for h in CLASSES}
    for j, h in pares:
        m[(j, h)] += 1
    print("\n  matriz de confusão (linha = judge, coluna = humano)")
    print(f"    {'':<12}{'aprovado':>10}{'reprovado':>11}")
    for j in CLASSES:
        print(f"    {j:<12}{m[(j, 'aprovado')]:>10}{m[(j, 'reprovado')]:>11}")

    k, po, pe = kappa(pares)
    print(f"\n  acurácia (concordância bruta) : {po:.3f}")
    print(f"  concordância esperada por acaso: {pe:.3f}")
    print(f"  Cohen's κ                      : {'n/a' if k != k else f'{k:.3f}'}")
    print(f"  leitura                        : {leitura(k)}")

    print(f"\n  {'classe':<12}{'precision':>10}{'recall':>9}{'F1':>8}{'suporte':>9}")
    for c in CLASSES:
        p, r, f1, sup = por_classe(pares, c)
        print(f"  {c:<12}{_num(p):>10}{_num(r):>9}{_num(f1):>8}{sup:>9}")
    print(
        "\n  precision(reprovado) = das bolhas que o judge barrou, quantas o humano barraria."
        "\n  recall(reprovado)    = das que o humano barraria, quantas o judge pegou."
    )
    if n < 40:
        print(f"\n  ⚠️  n={n} é pequeno: o κ tem intervalo de confiança largo. Mire em 50-100.")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("csv", type=Path, help="CSV rotulado (saída de exportar_amostra.py)")
    args = p.parse_args()
    if not args.csv.exists():
        sys.exit(f"arquivo não encontrado: {args.csv}")

    pares, sem_rotulo, avisos = ler(args.csv)
    for a in avisos:
        print(f"aviso: {a}", file=sys.stderr)
    if sem_rotulo:
        print(f"aviso: {sem_rotulo} linha(s) sem rotulo_humano — ignoradas.", file=sys.stderr)
    if not pares:
        sys.exit("nenhuma linha rotulada: preencha a coluna `rotulo_humano` antes de rodar.")

    judges = sorted({j for j, _, _ in pares})
    for judge in judges:  # o recorte separado só aparece quando o judge está na amostra
        relatorio(f"judge: {judge}", [(j, h) for jd, j, h in pares if jd == judge])
    if len(judges) > 1:
        relatorio("AGREGADO (os dois judges juntos)", [(j, h) for _, j, h in pares])

    print(
        "\nNota de método: a amostra é ESTRATIFICADA 50/50 de propósito (reprovado é raro em"
        "\nprodução). Isso é o certo para estimar precision/recall por classe, mas o κ medido"
        "\naqui NÃO é o κ da população — na prevalência real ele tende a ser menor. Use-o como"
        "\nteto otimista: se já der baixo aqui, em produção é pior."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
