"""CLI de calibracao do LLM-judge contra golden humano (EVAL-10 / ADR 0015). needs_anthropic_api.

Fecha os passos 2-3 do README desta pasta: le o golden.jsonl rotulado por Fernando + socia, roda
`runners/judge.py:julgar` sobre cada linha (Sonnet 4.6 -> custa credito), consolida os dois rotulos
humanos numa golden-truth, mede o acordo humano-humano (o TETO da meta) PRIMEIRO, e computa
TPR/TNR/kappa de Cohen/Gwet AC2/Youden por rubrica + agregado, imprimindo o veredito de
`promove_a_blocker`.

NAO flipa `JUDGE_VINCULANTE` -- a promocao e decisao humana: depois de ler este relatorio, edite
`runners/judge.py` (False -> True) e mova o ADR 0015 para accepted.

`calibracao.py` e `judge.py` vivem fora do pacote `barra` -> carregados por caminho (igual
tests/evals/test_calibracao.py). `julgar` importa `barra` em runtime, entao rode de `api/` via
`uv run` para o pacote estar disponivel:

    uv run python evals/calibracao/calibrar.py
    uv run python evals/calibracao/calibrar.py --golden evals/calibracao/golden.jsonl --consolidacao and
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_AQUI = Path(__file__).resolve().parent
_RUNNERS = _AQUI.parent / "runners"


def _carregar(nome: str, caminho: Path) -> ModuleType:
    """Carrega um modulo de evals/ por caminho (estao fora do pacote `barra`)."""
    spec = importlib.util.spec_from_file_location(nome, caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


calibracao = _carregar("eval_calibracao", _AQUI / "calibracao.py")
judge = _carregar("eval_judge", _RUNNERS / "judge.py")


def _consolidar(fernando: bool, socia: bool, modo: str) -> bool:
    """Golden-truth a partir dos dois rotulos humanos. 'and' (seguranca) ou 'or'."""
    return (fernando and socia) if modo == "and" else (fernando or socia)


def _ler_golden(caminho: Path) -> list[dict]:
    """Le o golden.jsonl, pulando cabecalho/template (sem rotulos humanos)."""
    linhas: list[dict] = []
    for bruto in caminho.read_text(encoding="utf-8").splitlines():
        bruto = bruto.strip()
        if not bruto:
            continue
        obj = json.loads(bruto)
        if "_header" in obj or "rotulo_humano_fernando" not in obj:
            continue
        linhas.append(obj)
    return linhas


async def _julgar_linhas(linhas: list[dict]) -> list[bool]:
    """`passou` do judge por linha (sequencial, p/ nao estourar rate limit). needs_key.

    Linha COM `rubrica` -> julga aquela rubrica (golden legado, por-rubrica). Linha SEM `rubrica`
    (golden por-conversa, HOLISTICO) -> UMA chamada `julgar_holistico` avalia as 4 rubricas LLM de
    uma vez com o `historico` da conversa; a fala "passa" se passa em TODAS (`holistico_passou`),
    espelhando o veredito holistico do humano na UI. Uma chamada por fala em vez de quatro corta
    ~75% do custo do juiz nesta calibracao (EVAL-10)."""
    resultados: list[bool] = []
    for ln in linhas:
        historico = ln.get("historico")
        if ln.get("rubrica"):
            veredito = await judge.julgar(ln["rubrica"], ln["texto_resposta"], historico=historico)
            resultados.append(bool(veredito.passou))
            continue
        holistico = await judge.julgar_holistico(ln["texto_resposta"], historico=historico)
        resultados.append(judge.holistico_passou(holistico))
    return resultados


def _relatorio(
    nome: str,
    fernando: list[bool],
    socia: list[bool],
    judge_passou: list[bool],
    modo: str,
    mins: tuple[float, float, float],
) -> bool:
    """Imprime as metricas de uma rubrica (ou GERAL) e devolve o veredito de promocao."""
    humano = [_consolidar(f, s, modo) for f, s in zip(fernando, socia, strict=True)]
    kappa_humano = calibracao.acordo_humano_humano(fernando, socia)
    t = calibracao.tpr(humano, judge_passou)
    n = calibracao.tnr(humano, judge_passou)
    k = calibracao.kappa_cohen(humano, judge_passou)
    g = calibracao.gwet_ac2(humano, judge_passou)
    j = calibracao.youden_j(t, n)
    passa = calibracao.promove_a_blocker(
        t, n, k, min_tpr=mins[0], min_tnr=mins[1], min_kappa=mins[2]
    )
    print(f"\n[{nome}]  n={len(humano)}")
    print(f"  kappa humano-humano (TETO): {kappa_humano:.3f}")
    if kappa_humano < mins[2]:
        print(
            f"  AVISO: teto humano < {mins[2]} -> rubrica mal definida; afie judge.md e "
            "re-rotule ANTES de cobrar o judge (refino 08b 3.1)."
        )
    print(f"  TPR={t:.3f}  TNR={n:.3f}  kappa={k:.3f}  GwetAC2={g:.3f}  Youden_J={j:.3f}")
    print(f"  promove_a_blocker: {'SIM' if passa else 'NAO'}")
    return passa


def main() -> int:
    p = argparse.ArgumentParser(description="Calibracao do LLM-judge (EVAL-10).")
    p.add_argument("--golden", type=Path, default=_AQUI / "golden.jsonl")
    p.add_argument(
        "--cenario",
        action="append",
        help="filtra o golden por cenario (repetivel; default todos). Rode 2-3 cenarios enquanto "
        "afina o judge.md p/ gastar menos credito antes da rodada completa.",
    )
    p.add_argument("--consolidacao", choices=["and", "or"], default="and")
    p.add_argument("--min-tpr", type=float, default=0.9)
    p.add_argument("--min-tnr", type=float, default=0.85)
    p.add_argument("--min-kappa", type=float, default=0.6)
    args = p.parse_args()

    if not args.golden.exists():
        print(
            f"golden nao encontrado: {args.golden}\nRotule-o primeiro (ver README.md, passo 1).",
            file=sys.stderr,
        )
        return 2
    linhas = _ler_golden(args.golden)
    if not linhas:
        print("golden sem linhas rotuladas (so cabecalho?). Ver README.md.", file=sys.stderr)
        return 2
    if args.cenario:
        alvo = set(args.cenario)
        linhas = [ln for ln in linhas if ln.get("cenario") in alvo]
        if not linhas:
            print(
                f"nenhuma linha do golden casou --cenario {sorted(alvo)}.",
                file=sys.stderr,
            )
            return 2

    judge_passou = asyncio.run(_julgar_linhas(linhas))
    mins = (args.min_tpr, args.min_tnr, args.min_kappa)
    # Golden por-CONVERSA (holistico) nao tem `rubrica` por linha -> so o relatorio GERAL. Golden
    # legado (por-rubrica) detalha cada rubrica + GERAL.
    por_rubrica = "rubrica" in linhas[0]

    todas_passam = True
    if por_rubrica:
        for rub in sorted({ln["rubrica"] for ln in linhas}):
            idx = [i for i, ln in enumerate(linhas) if ln["rubrica"] == rub]
            f = [bool(linhas[i]["rotulo_humano_fernando"]) for i in idx]
            s = [bool(linhas[i]["rotulo_humano_socia"]) for i in idx]
            jp = [judge_passou[i] for i in idx]
            todas_passam &= _relatorio(rub, f, s, jp, args.consolidacao, mins)

    f_all = [bool(ln["rotulo_humano_fernando"]) for ln in linhas]
    s_all = [bool(ln["rotulo_humano_socia"]) for ln in linhas]
    nome_geral = (
        "GERAL" if por_rubrica else "GERAL (holistico: fala passa se respeita as 4 rubricas)"
    )
    geral = _relatorio(nome_geral, f_all, s_all, judge_passou, args.consolidacao, mins)

    print("\n" + "=" * 60)
    if geral and todas_passam:
        print(
            "VEREDITO: promover -> editar runners/judge.py: JUDGE_VINCULANTE = True "
            "(e ADR 0015 -> accepted)."
        )
        return 0
    print("VEREDITO: judge permanece ADVISORY (algum limiar nao atingido).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
