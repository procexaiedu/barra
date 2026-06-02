#!/usr/bin/env python
"""Repara mojibake (dupla codificacao latin-1 <-> utf-8) nas fixtures de eval.

Contexto do bug: texto PT-BR salvo com dupla codificacao tem os bytes UTF-8
reinterpretados como Latin-1, entao "sabado" vira "sA-til-bado" etc. O reparo de
uma string e `s.encode("latin-1").decode("utf-8")`.

Garantias:
- IDEMPOTENTE: so repara uma string quando o round-trip recupera texto valido,
  diferente, e que tem MENOS marcadores de mojibake (U+00C3 "A-til" / U+00C2
  "A-circ") que o original. Texto ja correto nunca e re-corrompido; rodar de novo
  nao faz nada. (Ex.: "NAO" maiusculo, que contem o codepoint U+00C3 legitimo,
  nao e tocado porque seu round-trip falha no decode.)
- CIRURGICO: so reescreve um arquivo se alguma string mudou. Linhas inalteradas
  ficam byte-a-byte identicas; linhas alteradas sao re-serializadas no mesmo
  estilo compacto JSON (separadores sem espaco, acentos crus). Ordem das linhas,
  chaves e estrutura preservadas. Saida em UTF-8 sem BOM.

Uso:
    python scripts/repara_encoding_evals.py            # repara in-place
    python scripts/repara_encoding_evals.py --dry-run  # so reporta, nao escreve
"""

import argparse
import glob
import json
import os
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api", "evals"))

# Codepoints que sinalizam mojibake quando aparecem em texto PT-BR.
MARCADORES = "ÃÂ"  # A-til, A-circ


def _marcas(s: str) -> int:
    return sum(c in MARCADORES for c in s)


def repara_str(s: str) -> str:
    """Aplica o round-trip de reparo apenas quando recupera texto valido e melhor."""
    try:
        cand = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    if cand != s and _marcas(cand) < _marcas(s):
        return cand
    return s


def repara_obj(obj):
    """Repara recursivamente todos os valores string. Retorna (novo, n_mudancas)."""
    if isinstance(obj, str):
        novo = repara_str(obj)
        return novo, int(novo != obj)
    if isinstance(obj, dict):
        n = 0
        out = {}
        for k, v in obj.items():
            nv, c = repara_obj(v)
            out[k] = nv
            n += c
        return out, n
    if isinstance(obj, list):
        n = 0
        out = []
        for v in obj:
            nv, c = repara_obj(v)
            out.append(nv)
            n += c
        return out, n
    return obj, 0


def processa_arquivo(path: str, dry_run: bool) -> tuple[int, int]:
    """Repara um .jsonl in-place. Retorna (linhas_alteradas, strings_reparadas)."""
    raw = open(path, "rb").read().decode("utf-8")
    linhas = raw.split("\n")
    saida = []
    linhas_alteradas = 0
    strings_reparadas = 0
    for ln in linhas:
        if not ln.strip():
            saida.append(ln)  # linha em branco / so-espaco: preserva verbatim
            continue
        obj = json.loads(ln)
        novo, n = repara_obj(obj)
        if n:
            linhas_alteradas += 1
            strings_reparadas += n
            saida.append(json.dumps(novo, ensure_ascii=False, separators=(",", ":")))
        else:
            saida.append(ln)  # nada mudou: mantem bytes originais
    novo_raw = "\n".join(saida)
    if strings_reparadas and novo_raw != raw and not dry_run:
        with open(path, "wb") as fh:
            fh.write(novo_raw.encode("utf-8"))  # UTF-8 sem BOM
    return linhas_alteradas, strings_reparadas


def selftest() -> None:
    """Prova que repara_str conserta mojibake sintetico e e idempotente."""
    casos = {
        "sÃ¡bado": "sábado",   # "sabado" duplamente codificado
        "horÃ¡rio": "horário",
        "VocÃª": "Você",
        "confirmaÃ§Ã£o": "confirmação",
    }
    for ruim, bom in casos.items():
        assert repara_str(ruim) == bom, (ruim, repara_str(ruim), bom)
        assert repara_str(bom) == bom, f"nao-idempotente em texto correto: {bom!r}"
    # texto correto com U+00C3 legitimo ("NAO" maiusculo) nao pode ser tocado
    assert repara_str("NÃO é o gate") == "NÃO é o gate"
    print("self-test: OK (conserta mojibake sintetico; idempotente; preserva 'NAO')")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="nao escreve, so reporta")
    args = ap.parse_args()

    selftest()

    files = sorted(glob.glob(os.path.join(BASE, "**", "*.jsonl"), recursive=True))
    tot_arq = 0
    tot_linhas = 0
    tot_strings = 0
    for f in files:
        la, sr = processa_arquivo(f, args.dry_run)
        if sr:
            tot_arq += 1
            tot_linhas += la
            tot_strings += sr
            print(f"  reparado: {os.path.relpath(f, BASE)}  linhas={la} strings={sr}")

    modo = "[dry-run] " if args.dry_run else ""
    print(
        f"{modo}{len(files)} arquivos varridos; "
        f"{tot_arq} arquivos com reparo; "
        f"{tot_linhas} linhas alteradas; {tot_strings} strings reparadas."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
