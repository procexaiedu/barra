"""Camada 2 (esqueleto + sanity-check) — style-embedding. Pergunta única do handoff 01:
o embedding de estilo SEPARA dois vendedores nossos (eb02 vs eb04)? Se sim, a Camada 2 tem
sinal em PT-BR e vale construir; se não, documenta e fica-se só na Camada 1 (estilometria).

Dois modos:
  amostra   — extrai do corpus (DATABASE_URL) bolhas com sinal (>= MIN_CHARS) de eb02/eb04 e
              grava em amostra_estilo_eb.json. Não precisa de ML — roda no venv padrão.
  sanity    — carrega a amostra, embeda com um style-model (sentence-transformers) e reporta a
              separação eb02×eb04. EXIGE torch+sentence-transformers — rode em env efêmero:
              uv run --with sentence-transformers --with torch python embedding_estilo.py sanity

Modelo default: StyleDistance/styledistance (content-independent, NAACL 2025; treino majoritário
em inglês → o sanity-check em PT-BR é justamente o teste). Troque por --modelo <hf_id>.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

AMOSTRA = Path(__file__).parent / "amostra_estilo_eb.json"
MIN_CHARS = 20  # bolhas curtíssimas ("Sim", "1707") não carregam estilo; filtra ruído
N_POR_INST = 400
MODELO_DEFAULT = "StyleDistance/styledistance"

SQL = """
    SELECT texto FROM corpus.mensagens_raw
    WHERE from_me AND instancia = %s
      AND message_type IN ('conversation','extendedTextMessage')
      AND texto IS NOT NULL AND char_length(btrim(texto)) >= %s
    ORDER BY ts, msg_id
    LIMIT %s
"""


def cmd_amostra() -> None:
    import psycopg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL não encontrada")
    out: dict[str, list[str]] = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for inst in ("eb02", "eb04"):
            cur.execute(SQL, (inst, MIN_CHARS, N_POR_INST))
            out[inst] = [r[0].strip() for r in cur.fetchall()]
    AMOSTRA.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado {AMOSTRA}: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()))


def _cos(a: list[float], b: list[float]) -> float:
    import math

    num = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


def cmd_sanity(modelo: str) -> None:
    from sentence_transformers import SentenceTransformer

    if not AMOSTRA.exists():
        sys.exit("rode primeiro: python embedding_estilo.py amostra")
    amostra = json.loads(AMOSTRA.read_text(encoding="utf-8"))
    eb02, eb04 = amostra["eb02"], amostra["eb04"]

    print(f"modelo: {modelo}  | eb02={len(eb02)} eb04={len(eb04)}")
    st = SentenceTransformer(modelo)
    emb02 = st.encode(eb02, normalize_embeddings=True, show_progress_bar=False).tolist()
    emb04 = st.encode(eb04, normalize_embeddings=True, show_progress_bar=False).tolist()

    def centroide(embs: list[list[float]]) -> list[float]:
        d = len(embs[0])
        return [sum(e[i] for e in embs) / len(embs) for i in range(d)]

    c02, c04 = centroide(emb02), centroide(emb04)

    # Classificação por centróide mais próximo (leave-one-cluster-centroid): cada bolha é
    # rotulada pela instância cujo centróide está mais perto. Acima de 0.5 = separa.
    acertos = 0
    total = 0
    for embs, verdade in ((emb02, "eb02"), (emb04, "eb04")):
        for e in embs:
            pred = "eb02" if _cos(e, c02) >= _cos(e, c04) else "eb04"
            acertos += pred == verdade
            total += 1
    acc = acertos / total
    sep_centroides = 1 - _cos(c02, c04)

    print(f"distância entre centróides (1-cos): {sep_centroides:.4f}")
    print(f"acurácia nearest-centroid (eb02 vs eb04): {acc:.3f}  (0.5 = acaso)")
    veredito = "SIM, separa" if acc >= 0.65 else ("FRACO" if acc >= 0.55 else "NÃO separa")
    print(f"VEREDITO Camada 2 (PT-BR): {veredito}")
    print(
        "→ "
        + (
            "embedding tem sinal em PT-BR; vale construir a Camada 2 como métrica complementar."
            if acc >= 0.65
            else "sinal fraco/ausente em PT-BR → ficar na Camada 1 (estilometria) por enquanto."
        )
    )


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "amostra"
    if cmd == "amostra":
        cmd_amostra()
    elif cmd == "sanity":
        modelo = MODELO_DEFAULT
        if "--modelo" in sys.argv:
            modelo = sys.argv[sys.argv.index("--modelo") + 1]
        cmd_sanity(modelo)
    else:
        sys.exit("uso: python embedding_estilo.py <amostra|sanity> [--modelo hf_id]")


if __name__ == "__main__":
    main()
