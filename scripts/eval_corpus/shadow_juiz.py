"""Juiz cego head-to-head do shadow (Camada 2): preparo + merge.

O JULGAMENTO em si roda como painel de subagentes Claude Code (Workflow, Moeda A — sem credito de
API), conforme o desenho do README do shadow. Este modulo so faz o entorno deterministico em
Python:

  prep:  pares (resposta_ia/humano) -> pares CEGOS (resp_a/resp_b em ordem aleatorizada por par,
         sem rotulo de quem e' quem) + um MAPA {idx: 'ia'|'humano' que e' o resp_a}. O juiz nunca
         ve o mapa -> cegueira real (controla position bias: a ordem alterna por par via semente).
  merge: vereditos do painel (idx -> 'A'|'B'|'empate') + mapa -> grava `p["juiz"]` em cada par
         (melhor='ia'|'humano'|'empate', votos, justificativa), pronto p/ o render.

Uso:
  python shadow_juiz.py prep  --pares massa.json --out-cegos cegos.json
  # (rodar o Workflow painel sobre cegos["cegos"], coletar verdicts.json)
  python shadow_juiz.py merge --pares massa.json --cegos cegos.json --verdicts verdicts.json --out massa_julgado.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from typing import Any

# Marker `[quote: trecho]` (espelha barra.workers._chunking): em prod o `_chunking` resolve o
# quoted-reply e remove o marker; o harness captura `res.texto` cru, entao o juiz veria markup.
_QUOTE_PREFIX = re.compile(r"^\s*\[quote\s*(?::\s*[^\]]*?\s*)?\]\s*", re.IGNORECASE)


def _handoff(p: dict[str, Any]) -> bool:
    """Ponto onde a IA pausou/escalou (serviço fora da oferta, preço abaixo do piso): NAO manda
    bolha ao cliente. Julgar texto vazio vs cotacao do humano e' injusto — fica FORA do painel."""
    return bool((p.get("ia") or {}).get("estado_final", {}).get("ia_pausada"))


def _render_cliente(texto: str) -> str:
    """Texto client-facing: strippa `[quote: trecho]` de cada bloco (bolha), como o cliente veria."""
    if not texto or "[quote" not in texto.lower():
        return texto
    return "\n\n".join(_QUOTE_PREFIX.sub("", b) for b in re.split(r"\n\s*\n", texto.strip()))


def _ctx_curto(par: dict[str, Any], n: int = 3) -> str:
    turnos = (par.get("contexto") or [])[-n:]
    return " · ".join(
        ("CLIENTE" if t["direcao"] == "cliente" else "MODELO") + ": " + t["texto"][:70]
        for t in turnos
    )


def prep(pares: list[dict[str, Any]], *, semente: int = 13) -> dict[str, Any]:
    """Monta os pares cegos (ordem A/B aleatorizada por par) + o mapa de desanonimizacao.

    HANDOFF fica fora do painel (a IA declinou/escalou certo -> texto vazio nao e' comparavel); o
    texto da IA e' RENDERIZADO (markers `[quote:]` removidos) pro juiz ver o que o cliente veria.
    """
    rng = random.Random(semente)  # noqa: S311 — aleatorizacao de ordem, nao-cripto
    cegos: list[dict[str, Any]] = []
    mapa: dict[str, str] = {}
    for i, p in enumerate(pares):
        if _handoff(p):
            continue  # escalada/handoff: idx some do painel -> fica sem juiz -> fora do placar
        a_eh_ia = rng.random() < 0.5
        resp_ia = _render_cliente((p.get("resposta_ia") or "").strip())[:400]
        resp_hu = (p.get("resposta_humano") or "").strip()[:400]
        resp_a, resp_b = (resp_ia, resp_hu) if a_eh_ia else (resp_hu, resp_ia)
        cegos.append(
            {
                "idx": i,
                "contexto": _ctx_curto(p),
                "cliente": (p.get("turno_cliente") or "").strip()[:220],
                "resp_a": resp_a,
                "resp_b": resp_b,
            }
        )
        mapa[str(i)] = "ia" if a_eh_ia else "humano"
    return {"cegos": cegos, "mapa": mapa, "semente": semente}


_ROTULO = {"ia": "Agente", "humano": "Vendedor"}
# token de resposta "A"/"B" isolado (nunca artigo: o juiz sempre escreve "A responde"/"B ignora",
# nunca "A resposta"; artigo em PT sai minusculo). Boundary que ignora acentos/digitos.
_TOK_AB = re.compile(r"(?<![0-9A-Za-zÀ-ÿ])([AB])(?![0-9A-Za-zÀ-ÿ])")


def _desanon_justificativa(just: str, a_eh: str) -> str:
    """Troca os rotulos cegos A/B da justificativa pelos papeis reais (Agente/Vendedor).

    Deixa o exemplo lado a lado legivel: sem isto o leitor ve colunas 'Agente'/'Vendedor' mas a
    justificativa fala de 'A'/'B' e precisa adivinhar o mapeamento.
    """
    b_eh = "humano" if a_eh == "ia" else "ia"
    troca = {"A": _ROTULO[a_eh], "B": _ROTULO[b_eh]}
    return _TOK_AB.sub(lambda m: troca[m.group(1)], just or "")


def merge(
    pares: list[dict[str, Any]], mapa: dict[str, str], verdicts: list[dict[str, Any]]
) -> int:
    """Aplica os vereditos do painel (idx, melhor in A/B/empate, votos, justificativa) aos pares.

    Mapeia A/B -> ia/humano via `mapa` (resp_a e' `mapa[idx]`). Retorna quantos pares julgados.
    """
    por_idx = {int(v["idx"]): v for v in verdicts}
    n = 0
    for i, p in enumerate(pares):
        v = por_idx.get(i)
        if not v:
            continue
        escolha = str(v.get("melhor", "")).upper()
        a_eh = mapa.get(str(i), "ia")
        b_eh = "humano" if a_eh == "ia" else "ia"
        if escolha == "A":
            melhor = a_eh
        elif escolha == "B":
            melhor = b_eh
        else:
            melhor = "empate"
        p["juiz"] = {
            "melhor": melhor,
            "votos": v.get("votos"),
            "confianca": v.get("confianca"),
            "justificativa": _desanon_justificativa(v.get("justificativa", ""), a_eh),
        }
        n += 1
    return n


def _main() -> None:
    ap = argparse.ArgumentParser(description="Juiz cego shadow: prep/merge (deterministico).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prep")
    pp.add_argument("--pares", required=True)
    pp.add_argument("--out-cegos", required=True)
    pp.add_argument(
        "--out-jsonl", default=None, help="JSONL cego (1 par/linha, sem mapa) p/ o painel ler"
    )
    pp.add_argument("--semente", type=int, default=13)

    pm = sub.add_parser("merge")
    pm.add_argument("--pares", required=True)
    pm.add_argument("--cegos", required=True)
    pm.add_argument("--verdicts", required=True)
    pm.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.cmd == "prep":
        with open(args.pares, encoding="utf-8") as fh:
            doc = json.load(fh)
        res = prep(doc["pares"], semente=args.semente)
        with open(args.out_cegos, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"prep: {len(res['cegos'])} pares cegos -> {args.out_cegos}")
        if args.out_jsonl:
            with open(args.out_jsonl, "w", encoding="utf-8") as fh:
                for c in res["cegos"]:
                    fh.write(json.dumps(c, ensure_ascii=False) + "\n")
            print(f"      JSONL cego (1 par/linha) -> {args.out_jsonl}")
    else:
        with open(args.pares, encoding="utf-8") as fh:
            doc = json.load(fh)
        with open(args.cegos, encoding="utf-8") as fh:
            cegos = json.load(fh)
        with open(args.verdicts, encoding="utf-8") as fh:
            verdicts = json.load(fh)
        if isinstance(verdicts, dict):
            verdicts = verdicts.get("verdicts", verdicts.get("vereditos", []))
        n = merge(doc["pares"], cegos["mapa"], verdicts)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print(f"merge: {n} pares julgados -> {args.out}")


if __name__ == "__main__":
    _main()
