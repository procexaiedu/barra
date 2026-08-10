"""Perfil estilométrico congelado POR MOMENTO do funil (emoji/vocativo/rs/comprimento por ato).

A estilometria agregada (`gerar_perfil_estilo.py`) mede UMA taxa para o corpus inteiro. Mas o
humano varia a voz por ato — abre quente (emoji ~27% na saudação) e cota seco (~1-11%), o vocativo
CAI na cotação (~13% vs ~23% agregado). O agregado dilui "emoji na hora errada". Este script
congela um perfil POR ATO para a métrica capturar se o agente acerta a DISTRIBUIÇÃO, não só a
média — a alavanca que o estudo de voz (`voz_estilometria.md`) apontou como a maior.

Lê SÓ `corpus.mensagens_raw` (read-only, §0). Rotula cada bolha do Vendedor com
`barra.agente.fluxo.rotular_turno` (o MESMO rotulador do filtro de emoji do worker e da métrica de
fluxo — consistência por construção), agrupa por ato e congela {perfil, piso ELA-vs-ELA por ato, n}
em `perfil_estilo_por_momento.json`. Roda pelo env do api (importa barra):

  cd api && DATABASE_URL=... uv run python ../scripts/eval_corpus/gerar_perfil_por_momento.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

sys.path.insert(0, os.path.dirname(__file__))
from estilometria import distancia, perfil_de_bolhas

from barra.agente.fluxo import rotular_turno

SAIDA = Path(__file__).parent / "perfil_estilo_por_momento.json"
MIN_BOLHAS_PISO = 40  # abaixo disso o piso por paridade é ruidoso; o perfil ainda é gravado

# Mesmas regras de `gerar_perfil_estilo.py`: só texto real d'ELA (from_me), tipos textuais.
SQL = """
    SELECT texto
    FROM corpus.mensagens_raw
    WHERE from_me
      AND message_type IN ('conversation', 'extendedTextMessage')
      AND texto IS NOT NULL AND btrim(texto) <> ''
    ORDER BY instancia, ts, msg_id
"""


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL não encontrada (.env / export)")

    por_ato: dict[str, list[str]] = defaultdict(list)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL)
        for (texto,) in cur:
            por_ato[rotular_turno(texto)].append(texto)

    if not por_ato:
        sys.exit("corpus vazio — DSN aponta pro banco errado?")

    saida: dict[str, dict] = {}
    for ato, bolhas_ato in sorted(por_ato.items()):
        entrada: dict = {"n_bolhas": len(bolhas_ato), "perfil": perfil_de_bolhas(bolhas_ato)}
        if len(bolhas_ato) >= MIN_BOLHAS_PISO:
            # Piso ELA-vs-ELA DENTRO do ato (split por paridade) — distância esperada por acaso
            # amostral naquele ato; a distância do agente só é interpretável acima dele.
            piso = distancia(perfil_de_bolhas(bolhas_ato[0::2]), perfil_de_bolhas(bolhas_ato[1::2]))
            entrada["piso_ela_vs_ela"] = round(piso["agregado"], 4)
            entrada["piso_por_feature"] = {k: round(v, 4) for k, v in piso.items()}
        saida[ato] = entrada

    total = sum(len(b) for b in por_ato.values())
    doc = {
        "por_ato": saida,
        "__meta__": {
            "fonte": "corpus.mensagens_raw (from_me, texto) — rotulado por barra.agente.fluxo.rotular_turno",
            "n_bolhas_total": total,
            "atos": {a: len(b) for a, b in sorted(por_ato.items())},
            "min_bolhas_piso": MIN_BOLHAS_PISO,
        },
    }
    SAIDA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"gravado: {SAIDA}  ({total} bolhas, {len(saida)} atos)\n")
    print(f"{'ato':<11}{'n':>7}{'emoji':>8}{'vocat':>8}{'rs':>7}{'len_p?':>8}{'piso':>8}")
    print("-" * 56)
    for ato, e in sorted(saida.items()):
        p = e["perfil"]
        piso = e.get("piso_ela_vs_ela", "—")
        print(
            f"{ato:<11}{e['n_bolhas']:>7}{p['taxa_emoji']:>8.3f}"
            f"{p['taxa_vocativo']:>8.3f}{p['taxa_rs']:>7.3f}{'':>8}{piso!s:>8}"
        )


if __name__ == "__main__":
    main()
