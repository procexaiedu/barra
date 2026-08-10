"""Pontua o A/B de exemplos canônicos: distância estilométrica gerado×corpus por variante +
red-flag de cópia literal dos exemplos. Lê os gen_*.json escritos pelos subagentes.

Uso: python ab_score.py   (de scripts/eval_corpus/)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import estilometria as e

GEN = Path("/tmp/ab_exemplos")
PERFIL = Path(__file__).parent / "perfil_estilo_corpus.json"

# Bolhas <ela> dos 6 exemplos reais (variante C) — para o red-flag de cópia literal.
EXEMPLOS_C = [
    "Oii\n\nBoa noite 😊\n\ntudo bem amor?",
    "sou bem tranquila\n\nestilo namoradinha rs\n\nbeijo na boca, oral sem 🥰\n\nsou carinhosa e atenciosa amor",
    "{valor} 1h no meu local 🥰\n\naceito cartao amor",
    "seria agora amor? 😊",
    "faço sim amor 🥰",
    "quando chegar me avisa que te passo o número amor",
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _bolhas_exemplo() -> set[str]:
    out: set[str] = set()
    for ex in EXEMPLOS_C:
        out.update(_norm(b) for b in e.bolhas(ex))
    return out


def _bolhas_de(prefixo: str, tag: str) -> list[str]:
    path = GEN / f"{prefixo}_{tag}.json"
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for t in doc["turnos"]:
        out.extend(e.bolhas(t["agente"]))
    return out


def _linha(ref: dict, tag: str, bolhas: list[str], ex_bolhas: set[str]) -> None:
    if not bolhas:
        print(f"{tag:<14} (sem dados)")
        return
    cand = e.perfil_de_bolhas(bolhas)
    d = e.distancia(ref, cand)
    copias = sum(1 for b in bolhas if _norm(b) in ex_bolhas)
    print(
        f"{tag:<14} {d['agregado']:>7.4f} {d['comprimento']:>7.4f} {d['ponto_final']:>7.4f} "
        f"{d['emoji']:>7.4f} {d['vocativo']:>7.4f} {d['trigramas']:>7.4f} {d['diversidade']:>7.4f} "
        f"{cand['n_bolhas']:>7} {copias:>6}"
    )


def main() -> None:
    ref = e.carregar_perfil(PERFIL)
    piso = ref["__meta__"]["piso_ela_vs_ela"]
    ex_bolhas = _bolhas_exemplo()
    hdr = (
        f"{'variante':<14} {'agg':>7} {'compr':>7} {'ponto':>7} {'emoji':>7} {'vocat':>7} "
        f"{'trigr':>7} {'diver':>7} {'nbolha':>7} {'copia':>6}"
    )
    print(f"piso ELA-vs-ELA (agregado): {piso:.4f}")

    for rep, prefixo, desc in (
        ("REP1", "gen", "clientes que ESPELHAM os exemplos"),
        ("REP2", "gen2", "clientes HELD-OUT (não espelham)"),
        ("COMBINADO", None, "rep1+rep2"),
    ):
        print(f"\n== {rep} ({desc}) ==")
        print(hdr)
        for tag in ("A_sem", "B_fabricados", "C_reais"):
            if prefixo is None:
                bolhas = _bolhas_de("gen", tag) + _bolhas_de("gen2", tag)
            else:
                bolhas = _bolhas_de(prefixo, tag)
            _linha(ref, tag, bolhas, ex_bolhas)

    print(
        f"\nLeitura: 'agg' = distância agregada gerado×corpus (menor = mais perto da voz; piso "
        f"{piso:.4f}). 'copia' = bolhas geradas idênticas a uma bolha de exemplo (red-flag de cópia)."
    )


if __name__ == "__main__":
    main()
