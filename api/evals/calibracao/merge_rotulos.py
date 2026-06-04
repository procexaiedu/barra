"""Merge dos dois exports de rotulo num golden.jsonl de DUAS colunas (EVAL-10 / ADR 0015).

A UI `docs/agente/evals-notas.html` exporta UM arquivo por rotulador
(`golden_fernando.jsonl` / `golden_socia.jsonl`), cada um preenchendo SO a sua coluna
(`rotulo_humano_fernando` OU `rotulo_humano_socia`). Mas `calibracao/calibrar.py` exige as DUAS
colunas na MESMA linha por `id` (`_ler_golden` pula linha sem `rotulo_humano_fernando`; `main` le
`rotulo_humano_socia`). Esta ferramenta faz o INNER JOIN por `id`: so as falas rotuladas pelos
DOIS humanos entram no golden -- a calibracao precisa do par para medir o acordo humano-humano (o
TETO) e TPR/TNR/kappa.

Sem rede/DB/LLM (stdlib puro): roda no `make test`/CI. `merge_golden` e PURO (testavel offline);
`main` faz a I/O. Fora do pacote `barra` -> carregado por caminho nos testes (igual judge.py).

    # da raiz de api/, depois dos dois exports salvos em evals/calibracao/:
    uv run python evals/calibracao/merge_rotulos.py
    uv run python evals/calibracao/merge_rotulos.py \
        --fernando evals/calibracao/golden_fernando.jsonl \
        --socia    evals/calibracao/golden_socia.jsonl \
        --saida    evals/calibracao/golden.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_AQUI = Path(__file__).resolve().parent

# campos compartilhados (vem do mesmo conversas.jsonl): tem que bater entre os dois exports.
_CAMPOS_COMPARTILHADOS = ("texto_resposta", "historico", "cenario", "conversa_id")


def _rotulo_e_obs(linha: dict[str, Any]) -> tuple[bool | None, str | None]:
    """Extrai (rotulo, observacao) de uma linha de export, seja qual for a coluna do rotulador.

    A UI nomeia `rotulo_humano_<rotulador>` e `observacao_<rotulador>`; aqui detectamos pelo
    prefixo, robusto a qual rotulador gerou o arquivo. Linha de export sempre tem o rotulo (a UI
    so exporta falas marcadas) -- `None` sinaliza linha malformada (descartada pelo merge)."""
    rotulo: bool | None = None
    obs: str | None = None
    for chave, valor in linha.items():
        if chave.startswith("rotulo_humano_"):
            rotulo = bool(valor)
        elif chave.startswith("observacao_"):
            obs = valor if isinstance(valor, str) else None
    return rotulo, obs


def merge_golden(
    fernando: list[dict[str, Any]], socia: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """INNER JOIN dos dois exports por `id` -> golden de duas colunas (PURO; testavel offline).

    So entram as falas rotuladas pelos DOIS (calibrar.py exige o par). Falas rotuladas por um so
    sao DESCARTADAS com aviso (no silent cap). Campos compartilhados vem da linha de Fernando; se
    divergirem entre os rotuladores (nao deviam -- mesmo conversas.jsonl), avisa. Preserva a ordem
    de aparicao no export de Fernando. Devolve (linhas_merged, avisos)."""
    avisos: list[str] = []
    por_id_socia = {ln["id"]: ln for ln in socia if "id" in ln}
    vistos_socia: set[str] = set()
    merged: list[dict[str, Any]] = []
    so_fernando: list[str] = []

    for lf in fernando:
        fid = lf.get("id")
        if fid is None:
            avisos.append("linha de Fernando sem `id` -- ignorada")
            continue
        ls = por_id_socia.get(fid)
        if ls is None:
            so_fernando.append(fid)
            continue
        vistos_socia.add(fid)
        rot_f, obs_f = _rotulo_e_obs(lf)
        rot_s, obs_s = _rotulo_e_obs(ls)
        if rot_f is None or rot_s is None:
            avisos.append(f"{fid}: rotulo ausente em um dos exports -- descartada")
            continue
        for campo in _CAMPOS_COMPARTILHADOS:
            if campo in lf and campo in ls and lf[campo] != ls[campo]:
                avisos.append(
                    f"{fid}: campo {campo!r} difere entre os rotuladores (usando o de Fernando)"
                )
        linha: dict[str, Any] = {
            "id": fid,
            "conversa_id": lf.get("conversa_id"),
            "cenario": lf.get("cenario"),
            "texto_resposta": lf.get("texto_resposta", ""),
            "historico": lf.get("historico", []),
            "rotulo_humano_fernando": rot_f,
            "rotulo_humano_socia": rot_s,
        }
        if obs_f:
            linha["observacao_fernando"] = obs_f
        if obs_s:
            linha["observacao_socia"] = obs_s
        merged.append(linha)

    so_socia = [ln["id"] for ln in socia if ln.get("id") not in vistos_socia and "id" in ln]
    if so_fernando:
        avisos.append(
            f"{len(so_fernando)} fala(s) so rotuladas por Fernando (descartadas; calibrar.py exige "
            f"as duas colunas): {so_fernando}"
        )
    if so_socia:
        avisos.append(
            f"{len(so_socia)} fala(s) so rotuladas pela socia (descartadas; calibrar.py exige as "
            f"duas colunas): {so_socia}"
        )
    return merged, avisos


def _ler_export(caminho: Path) -> list[dict[str, Any]]:
    """Le um export .jsonl da UI (uma fala por linha), pulando cabecalho/template e linhas vazias."""
    linhas: list[dict[str, Any]] = []
    for bruto in caminho.read_text(encoding="utf-8").splitlines():
        bruto = bruto.strip()
        if not bruto:
            continue
        obj = json.loads(bruto)
        if "_header" in obj:
            continue
        linhas.append(obj)
    return linhas


def main() -> int:
    p = argparse.ArgumentParser(description="Merge dos golden_<rotulador>.jsonl (EVAL-10).")
    p.add_argument("--fernando", type=Path, default=_AQUI / "golden_fernando.jsonl")
    p.add_argument("--socia", type=Path, default=_AQUI / "golden_socia.jsonl")
    p.add_argument("--saida", type=Path, default=_AQUI / "golden.jsonl")
    args = p.parse_args()

    for caminho in (args.fernando, args.socia):
        if not caminho.exists():
            print(
                f"export nao encontrado: {caminho}\n"
                "Rotule e exporte os dois na docs/agente/evals-notas.html primeiro (README, passo 1).",
                file=sys.stderr,
            )
            return 2

    merged, avisos = merge_golden(_ler_export(args.fernando), _ler_export(args.socia))
    for aviso in avisos:
        print(f"AVISO: {aviso}", file=sys.stderr)
    if not merged:
        print(
            "nenhuma fala rotulada por AMBOS -- golden vazio (calibrar.py nao roda). Confira se os "
            "dois exports cobrem as mesmas falas.",
            file=sys.stderr,
        )
        return 1

    args.saida.write_text(
        "\n".join(json.dumps(linha, ensure_ascii=False) for linha in merged) + "\n",
        encoding="utf-8",
    )
    print(f"Gravado: {args.saida} ({len(merged)} falas rotuladas por ambos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
