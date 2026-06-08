"""Reconstroi o golden.jsonl a partir das falas + rotulos persistidos (puro/offline).

Espelha a regra de `evals/calibracao/merge_rotulos.py:merge_golden` (INNER JOIN: so falas
rotuladas pelos DOIS entram, pois `calibrar.py` exige as duas colunas) — mas operando sobre
os dados ja juntados pelo repo, sem importar `evals/`. A saida e o shape EXATO que
`calibrar.py:_ler_golden` consome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RotuloFala:
    """Rotulo de uma fala por um rotulador (vindo do repo)."""

    passou: bool
    observacao: str | None = None


def separar_rotulos(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, RotuloFala], dict[str, RotuloFala]]:
    """Particiona os rotulos da rodada nas duas colunas do golden (PURO; testavel offline).

    `rows`: dicts com `fala_id, rotulador, passou, observacao`. So 'fernando' e 'socia'
    compoem o golden; rotuladores fora dele (ex.: 'procex', 3o revisor independente) sao
    IGNORADOS — nunca caem na coluna do outro.
    """
    rot_f: dict[str, RotuloFala] = {}
    rot_s: dict[str, RotuloFala] = {}
    for r in rows:
        if r["rotulador"] == "fernando":
            rot_f[r["fala_id"]] = RotuloFala(passou=r["passou"], observacao=r["observacao"])
        elif r["rotulador"] == "socia":
            rot_s[r["fala_id"]] = RotuloFala(passou=r["passou"], observacao=r["observacao"])
    return rot_f, rot_s


def montar_golden(
    falas: list[dict[str, Any]],
    rotulos_fernando: dict[str, RotuloFala],
    rotulos_socia: dict[str, RotuloFala],
) -> tuple[list[dict[str, Any]], list[str]]:
    """INNER JOIN por `fala_id` -> linhas no formato golden + avisos (PURO; testavel offline).

    `falas`: dicts com `fala_id, conversa_id, cenario, texto_resposta, historico`.
    Cada mapa: `fala_id -> RotuloFala`. So entram as falas rotuladas por AMBOS; falas de um so
    sao descartadas com aviso (no silent cap). `observacao_*` so incluida se nao-vazia.
    """
    golden: list[dict[str, Any]] = []
    so_um: list[str] = []
    for fala in falas:
        fid = fala["fala_id"]
        rf = rotulos_fernando.get(fid)
        rs = rotulos_socia.get(fid)
        if rf is None and rs is None:
            continue
        if rf is None or rs is None:
            so_um.append(fid)
            continue
        linha: dict[str, Any] = {
            "id": fid,
            "conversa_id": fala["conversa_id"],
            "cenario": fala["cenario"],
            "texto_resposta": fala["texto_resposta"],
            "historico": fala["historico"],
            "rotulo_humano_fernando": rf.passou,
            "rotulo_humano_socia": rs.passou,
        }
        if rf.observacao and rf.observacao.strip():
            linha["observacao_fernando"] = rf.observacao.strip()
        if rs.observacao and rs.observacao.strip():
            linha["observacao_socia"] = rs.observacao.strip()
        golden.append(linha)

    avisos: list[str] = []
    if so_um:
        avisos.append(
            f"{len(so_um)} fala(s) rotulada(s) por apenas um rotulador — descartadas "
            f"(calibrar.py exige as duas colunas): {so_um}"
        )
    return golden, avisos
