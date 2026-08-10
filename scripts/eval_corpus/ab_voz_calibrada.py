"""Variante D do A/B de voz: prompt de PROD (persona.md atual = 4 fabricados) com o `<voz>`
CALIBRADO — emoji/vocativo esparsos, no alvo do corpus real (~14%/21%). Mede, offline, quanto
calibrar a diretriz de calor move o agente em direção à voz real (achado: ele usa ~3× emoji).
NÃO toca prod: edita só o texto renderizado em memória, como o ab_exemplos_render.py.

Uso: cd api && uv run python ../scripts/eval_corpus/ab_voz_calibrada.py
"""

from __future__ import annotations

import json
from pathlib import Path

from barra.agente.persona import IdentidadeModelo, render_bp3, render_prefixo_geral

from ab_exemplos_render import CLIENTES, FETICHES, IDENT, PROGRAMAS  # reusa o fixture "Manu"

SAIDA = Path("/tmp/ab_exemplos")

# Trechos do <voz> que empurram emoji/vocativo "em toda mensagem" → versão calibrada (esparsa).
_SUBS = [
    (
        'O calor é o que te define: sem ele você soa fria e robótica, então ele aparece em toda '
        'mensagem: vocativo carinhoso ("amor", "vida"), tom leve, "rs" no lugar da risada.',
        'O calor está no jeito, não na quantidade. Vocativo carinhoso ("amor", "vida") entra só de '
        'vez em quando, não em toda bolha; a maioria das bolhas vai SEM vocativo e SEM emoji. Tom '
        'leve e "rs" no lugar da risada bastam pra soar humana — encher de emoji/amor te entrega como bot.',
    ),
    (
        '- Emoji entra natural (🥰 😊 😍), um aqui e ali, sem encher. "rs" é o seu riso.',
        '- Emoji é raro: a maioria das bolhas vai sem nenhum; use um (🥰 😊) só de vez em quando, '
        'numa bolha calorosa. "rs" é o seu riso.',
    ),
]

CLIENTES2 = json.loads((SAIDA / "clientes2.json").read_text(encoding="utf-8"))


def main() -> None:
    base = render_prefixo_geral(desconto_max_pct=0.10)
    geral = base
    for alvo, novo in _SUBS:
        if alvo not in geral:
            raise SystemExit(f"trecho do <voz> não encontrado (persona.md mudou?):\n{alvo[:60]}...")
        geral = geral.replace(alvo, novo)
    bp3 = render_bp3(IdentidadeModelo(**IDENT.__dict__), PROGRAMAS, FETICHES)
    texto = f"{geral}\n{bp3}\n"
    (SAIDA / "prompt_D_calibrada.txt").write_text(texto, encoding="utf-8")
    print(f"prompt_D_calibrada.txt ({len(texto)} chars)")
    print(f"clientes rep1={len(CLIENTES)} rep2={len(CLIENTES2)}")


if __name__ == "__main__":
    main()
