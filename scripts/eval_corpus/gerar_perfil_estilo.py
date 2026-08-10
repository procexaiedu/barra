"""Gera o **perfil estilométrico congelado d'ELA** a partir do corpus real e grava em
`perfil_estilo_corpus.json`. Rodar UMA vez (ou quando o corpus mudar); a métrica
(`estilometria.py`) lê o JSON e roda offline, sem DB.

Lê SÓ `corpus.mensagens_raw` (read-only; bolhas from_me, tipos de texto). Grava o perfil
agregado (todas as instâncias = voz-alvo geral do Vendedor, que é GERAL e não por-modelo),
o piso de ruído ELA-vs-ELA (split determinístico por paridade de índice) e os perfis por
instância (insumo do cross-check eb02×eb04 da Camada 2).

Uso:  DATABASE_URL=... uv run python gerar_perfil_estilo.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg

from estilometria import distancia, perfil_de_bolhas

SAIDA = Path(__file__).parent / "perfil_estilo_corpus.json"

# Só texto real d'ELA (from_me), tipos textuais, não-vazio. Ordena por (instancia, ts, msg_id)
# p/ determinismo do split de paridade.
SQL = """
    SELECT instancia, texto
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

    por_instancia: dict[str, list[str]] = {}
    todas: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL)
        for instancia, texto in cur.fetchall():
            por_instancia.setdefault(instancia, []).append(texto)
            todas.append(texto)

    if not todas:
        sys.exit("corpus vazio — DSN aponta pro banco errado?")

    perfil = perfil_de_bolhas(todas)

    # Piso de ruído: ELA-vs-ELA. Split determinístico por paridade (amostras balanceadas do
    # mesmo registro) → distância "esperada por acaso amostral". Toda distância gerado×corpus só
    # é interpretável ACIMA desse piso.
    pares = perfil_de_bolhas(todas[0::2])
    impares = perfil_de_bolhas(todas[1::2])
    piso = distancia(pares, impares)

    # Cross-check de instâncias (insumo da Camada 2): distância estilométrica eb02×eb04.
    perfis_inst = {i: perfil_de_bolhas(b) for i, b in sorted(por_instancia.items())}
    cross = {}
    insts = sorted(perfis_inst)
    for a in insts:
        for b in insts:
            if a < b:
                cross[f"{a}x{b}"] = round(distancia(perfis_inst[a], perfis_inst[b])["agregado"], 4)

    perfil["__meta__"] = {
        "fonte": "corpus.mensagens_raw (from_me, texto)",
        "n_bolhas_total": len(todas),
        "n_por_instancia": {i: len(b) for i, b in sorted(por_instancia.items())},
        "piso_ela_vs_ela": piso["agregado"],
        "piso_por_feature": {k: round(v, 4) for k, v in piso.items()},
        "cross_instancia_agregado": cross,
    }

    doc = {"perfil": perfil, "por_instancia": perfis_inst}
    SAIDA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado: {SAIDA}")
    print(f"n bolhas: {len(todas)}  | piso ELA-vs-ELA (agregado): {piso['agregado']:.4f}")
    print(f"cross-instância (agregado): {json.dumps(cross, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
