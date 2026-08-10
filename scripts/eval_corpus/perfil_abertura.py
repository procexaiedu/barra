"""Perfil estilométrico congelado d'ELA RESTRITO aos turnos de ABERTURA/venda (early sales),
para tirar o confound de mistura de turnos do A/B de exemplos (voz_estilometria.md).

O candidato do A/B são todas bolhas de 1º turno (saudação/cotação/serviço — quentes). O perfil
agregado (gerar_perfil_estilo.py) inclui a cauda de logística seca ("Sim", "1707") → punia calor
que pode ser legítimo. Aqui a referência é casada: só as primeiras K bolhas d'ELA de cada thread
(a fase de abertura), via window sobre corpus.mensagens_raw.

Uso: cd api && DATABASE_URL=... uv run python ../scripts/eval_corpus/perfil_abertura.py [K]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg

from estilometria import distancia, perfil_de_bolhas

SAIDA = Path(__file__).parent / "perfil_estilo_abertura.json"

# Primeiras K bolhas d'ELA por thread (ordem temporal) = fase de abertura/qualificação/1ª cotação,
# antes da cauda de logística. Threads com pelo menos 2 bolhas d'ELA (descarta ruído de 1 toque).
SQL = """
    WITH ela AS (
      SELECT instancia, remote_jid, texto,
             row_number() OVER (PARTITION BY instancia, remote_jid ORDER BY ts, msg_id) AS rn
      FROM corpus.mensagens_raw
      WHERE from_me
        AND message_type IN ('conversation','extendedTextMessage')
        AND texto IS NOT NULL AND btrim(texto) <> ''
    )
    SELECT instancia, texto FROM ela WHERE rn <= %s ORDER BY instancia
"""


def main() -> None:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL não encontrada")

    todas: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL, (k,))
        todas = [r[1].strip() for r in cur.fetchall()]
    if not todas:
        sys.exit("vazio")

    perfil = perfil_de_bolhas(todas)
    pares = perfil_de_bolhas(todas[0::2])
    impares = perfil_de_bolhas(todas[1::2])
    perfil["__meta__"] = {
        "fonte": f"corpus.mensagens_raw, primeiras {k} bolhas d'ELA por thread (abertura)",
        "n_bolhas_total": len(todas),
        "k_aberturas": k,
        "piso_ela_vs_ela": distancia(pares, impares)["agregado"],
    }
    SAIDA.write_text(json.dumps({"perfil": perfil}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado {SAIDA}  | n={len(todas)} K={k}")
    print(
        f"abertura: emoji {perfil['taxa_emoji']:.3f} · vocativo {perfil['taxa_vocativo']:.3f} · "
        f"ponto {perfil['taxa_ponto_final']:.3f} · piso {perfil['__meta__']['piso_ela_vs_ela']:.4f}"
    )


if __name__ == "__main__":
    main()
