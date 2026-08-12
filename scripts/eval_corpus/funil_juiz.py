"""Juiz cego do shadow do FUNIL (2 braços): prep + merge determinísticos.

Extensão do shadow_juiz.py para a campanha-subst: cada ponto tem ATÉ 3 comparações
cegas — A-vs-humano (AH), B-vs-humano (BH) e A-vs-B (AB) — todas com ordem
aleatorizada por comparação e mapa que o painel nunca vê.

Regras de exclusão/auto-veredito (nunca silenciosas; tudo vai no manifesto):
  - handoff (ia_pausada): braço fica FORA das comparações com o humano (conduta, não
    derrota) — vira contagem própria;
  - resposta vazia sem handoff: DERROTA AUTOMÁTICA do braço (em prod é silêncio ao
    cliente) — não vai ao painel, vai direto ao placar;
  - mídia-essência já ficou fora na amostragem.

Uso:
  uv run python scripts/eval_corpus/funil_juiz.py prep \
      --a funil_a.json --b funil_b.json --out-cegos cegos.json --out-jsonl cegos.jsonl
  # painel Claude (Workflow) produz verdicts.json: [{"cid","melhor":"1"|"2"|"empate",
  #   "votos","justificativa"}]
  uv run python scripts/eval_corpus/funil_juiz.py merge \
      --a funil_a.json --b funil_b.json --cegos cegos.json --verdicts verdicts.json \
      --out julgado.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from shadow_juiz import _render_cliente  # noqa: E402


def _ctx(par: dict[str, Any], n: int = 8) -> str:
    """Contexto do card cego: 8 turnos x 300 chars — o suficiente p/ o juiz avaliar CONDUTA
    (não só a última troca). Cortes agressivos penalizavam quem escreve mais e escondiam o fio."""
    turnos = (par.get("contexto") or [])[-n:]
    return "\n".join(
        ("CLIENTE: " if t["direcao"] == "cliente" else "MODELO: ") + t["texto"][:300]
        for t in turnos
    )


def _indexar(doc: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    return {(p["ref"], p["idx"]): p for p in doc["pares"]}


def prep(
    doc_a: dict[str, Any],
    doc_b: dict[str, Any],
    *,
    semente: int = 13,
    tags: set[str] | None = None,
) -> dict[str, Any]:
    """`tags` filtra quais comparações emitir ({"AH","BH","AB"}, default todas): com muitos
    braços o head-to-head todos-contra-todos explode o painel — cada prep colhe só os pares
    vs humano (métrica primária) e o AB fica p/ o desempate final entre vencedores."""
    if tags is None:
        tags = {"AH", "BH", "AB"}
    rng = random.Random(semente)  # noqa: S311 — ordem cega, não-cripto
    idx_a, idx_b = _indexar(doc_a), _indexar(doc_b)
    chaves = sorted(set(idx_a) | set(idx_b))
    cegos: list[dict[str, Any]] = []
    mapa: dict[str, str] = {}  # cid -> quem é resp_1 ('a'|'b'|'humano')
    autos: list[dict[str, Any]] = []  # vereditos automáticos (vazia = derrota)

    def candidato(p: dict[str, Any] | None) -> str | None:
        """Texto client-facing do braço, None se o braço não joga (handoff/ausente)."""
        if p is None or p["handoff"]:
            return None
        txt = _render_cliente((p.get("resposta_ia") or "").strip())
        return txt  # vazio = joga e perde (auto)

    for ref, idx in chaves:
        pa, pb = idx_a.get((ref, idx)), idx_b.get((ref, idx))
        base = pa or pb
        assert base is not None
        humano = (base.get("resposta_humano") or "").strip()[:1000]
        comparacoes = []
        ta, tb = candidato(pa), candidato(pb)
        if ta is not None:
            comparacoes.append(("AH", ta, humano, "a", "humano"))
        if tb is not None:
            comparacoes.append(("BH", tb, humano, "b", "humano"))
        if ta is not None and tb is not None:
            comparacoes.append(("AB", ta, tb, "a", "b"))
        for tag, r1, r2, quem1, quem2 in comparacoes:
            if tag not in tags:
                continue
            cid = f"{ref}#{idx}#{tag}"
            vazio1, vazio2 = not r1.strip(), not r2.strip()
            if vazio1 or vazio2:
                melhor = "empate" if vazio1 and vazio2 else (quem2 if vazio1 else quem1)
                autos.append({"cid": cid, "melhor": melhor, "motivo": "resposta_vazia"})
                continue
            invertido = rng.random() < 0.5
            resp_1, resp_2 = (r2, r1) if invertido else (r1, r2)
            mapa[cid] = quem2 if invertido else quem1
            cegos.append(
                {
                    "cid": cid,
                    "tipo": base.get("tipo"),
                    "contexto": _ctx(base),
                    "cliente": (base.get("turno_cliente") or "").strip()[:400],
                    "resp_1": resp_1[:1000],
                    "resp_2": resp_2[:1000],
                }
            )
    rng.shuffle(cegos)
    return {"cegos": cegos, "mapa": mapa, "autos": autos, "semente": semente}


def merge(
    doc_a: dict[str, Any],
    doc_b: dict[str, Any],
    cegos: dict[str, Any],
    verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    mapa, autos = cegos["mapa"], cegos.get("autos", [])
    por_cid = {v["cid"]: v for v in verdicts}
    idx_a, idx_b = _indexar(doc_a), _indexar(doc_b)
    julgados: list[dict[str, Any]] = []
    chaves = sorted(set(idx_a) | set(idx_b))
    autos_por_cid = {a["cid"]: a for a in autos}
    for ref, idx in chaves:
        base = idx_a.get((ref, idx)) or idx_b.get((ref, idx))
        assert base is not None
        item: dict[str, Any] = {
            "ref": ref,
            "idx": idx,
            "tipo": base.get("tipo"),
            "desfecho": base.get("desfecho"),
            "recorrente": base.get("recorrente"),
            "turno_cliente": base.get("turno_cliente"),
            "resposta_humano": base.get("resposta_humano"),
            "handoff_a": (idx_a.get((ref, idx)) or {}).get("handoff"),
            "handoff_b": (idx_b.get((ref, idx)) or {}).get("handoff"),
            "resposta_a": (idx_a.get((ref, idx)) or {}).get("resposta_ia"),
            "resposta_b": (idx_b.get((ref, idx)) or {}).get("resposta_ia"),
        }
        for tag in ("AH", "BH", "AB"):
            cid = f"{ref}#{idx}#{tag}"
            if cid in autos_por_cid:
                a = autos_por_cid[cid]
                item[tag] = {"melhor": a["melhor"], "auto": a["motivo"]}
                continue
            v = por_cid.get(cid)
            if not v:
                continue
            escolha = str(v.get("melhor", "")).strip()
            quem_1 = mapa.get(cid)
            assert quem_1 is not None
            pares_tag = {"AH": ("a", "humano"), "BH": ("b", "humano"), "AB": ("a", "b")}
            quem_2 = next(q for q in pares_tag[tag] if q != quem_1)
            if escolha == "1":
                melhor = quem_1
            elif escolha == "2":
                melhor = quem_2
            else:
                melhor = "empate"
            item[tag] = {
                "melhor": melhor,
                "votos": v.get("votos"),
                "justificativa": v.get("justificativa", ""),
            }
        julgados.append(item)
    return {"julgados": julgados, "n": len(julgados)}


def _carregar(caminho: str) -> Any:
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def _main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prep")
    pp.add_argument("--a", required=True)
    pp.add_argument("--b", required=True)
    pp.add_argument("--out-cegos", required=True)
    pp.add_argument("--out-jsonl", default=None)
    pp.add_argument("--semente", type=int, default=13)
    pp.add_argument(
        "--comparacoes",
        default="AH,BH,AB",
        help="tags a emitir (ex.: 'AH,BH' p/ só os pares vs humano)",
    )
    pm = sub.add_parser("merge")
    pm.add_argument("--a", required=True)
    pm.add_argument("--b", required=True)
    pm.add_argument("--cegos", required=True)
    pm.add_argument("--verdicts", required=True)
    pm.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.cmd == "prep":
        tags = {t.strip().upper() for t in args.comparacoes.split(",") if t.strip()}
        res = prep(_carregar(args.a), _carregar(args.b), semente=args.semente, tags=tags)
        with open(args.out_cegos, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(
            f"prep: {len(res['cegos'])} comparações cegas, {len(res['autos'])} autos "
            f"-> {args.out_cegos}"
        )
        if args.out_jsonl:
            with open(args.out_jsonl, "w", encoding="utf-8") as fh:
                for c in res["cegos"]:
                    fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    else:
        verdicts = _carregar(args.verdicts)
        if isinstance(verdicts, dict):
            verdicts = verdicts.get("verdicts", [])
        res = merge(_carregar(args.a), _carregar(args.b), _carregar(args.cegos), verdicts)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"merge: {res['n']} pontos julgados -> {args.out}")


if __name__ == "__main__":
    _main()
