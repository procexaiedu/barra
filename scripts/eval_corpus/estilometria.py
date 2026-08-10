"""Estilometria determinística (Camada 1) — "soa como ela?" como DISTÂNCIA de distribuição.

Mede o quão perto um conjunto de bolhas geradas (a fala do agente) está do **perfil congelado
d'ELA** (corpus real do Vendedor, `corpus.mensagens_raw`). Pure stdlib — sem numpy/scipy/torch —
então roda offline, sem DB e sem crédito de API (§0 do CLAUDE.md).

Features (handoff 01, exatamente as nomeadas):
1. comprimento de bolha            → histograma → Jensen-Shannon
2. ausência de ponto final         → taxa      → |Δ|
3. emoji-rate                      → taxa      → |Δ|
4. vocativos ("amor"/"vida")       → taxa      → |Δ|
5. "rs" (riso informal)            → taxa      → |Δ|
6. n-gramas de caractere (trigrama)→ distrib.  → Jensen-Shannon
7. diversidade lexical (MATTR-50)  → escalar   → |Δ|

Distância por feature em [0,1]: Jensen-Shannon em base 2 (limitada a [0,1]) para distribuições;
|Δ| para taxas/escalares (já em [0,1]). O **agregado** é a média simples das 7 — 0 = idêntico
ao perfil d'ELA, quanto maior mais "fora da voz". É um sinal RELATIVO: compare sempre contra o
piso de ruído (ELA-vs-ELA) que `gerar_perfil_estilo.py` grava em `meta.piso_ela_vs_ela`.

NÃO mede conteúdo/correção nem desfecho (ponte @lid→telefone é irrecuperável — medir estilo é
independente do desfecho). É a Camada 1 do flywheel de voz; a Camada 2 (style-embedding) vive em
`embedding_estilo.py`.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

# --- tokenização de bolhas ------------------------------------------------------------------

# Um "turno" do agente são várias bolhas separadas por linha em branco (persona.md <voz>); no
# corpus, cada linha de `mensagens_raw` (from_me) já é UMA bolha. `bolhas()` aceita os dois:
# quebra por linha em branco e também por " / " (separador usado no render do corpus em threads).
_SEP_BOLHA = re.compile(r"\n\s*\n+")


def bolhas(texto: str) -> list[str]:
    """Quebra um turno em bolhas (linha em branco como separador). Strip + descarta vazias."""
    return [b.strip() for b in _SEP_BOLHA.split(texto) if b.strip()]


# --- detecção de emoji (sem a lib `emoji`; faixas Unicode + propriedade) ---------------------

# Faixas dos blocos de emoji mais comuns no WhatsApp PT-BR. Inclui Misc Symbols & Pictographs,
# Emoticons, Transport, Supplemental, Dingbats, Misc Symbols, e os seletores de variação.
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, supplemental, symbols & extended
    "\U00002600-\U000027bf"  # misc symbols + dingbats (☺️ ✨ ❤ etc.)
    "\U00002190-\U000021ff"  # setas
    "\U00002b00-\U00002bff"  # estrelas/setas suplementares (⭐ etc.)
    "\U0000fe00-\U0000fe0f"  # seletores de variação (emoji presentation)
    "\U0001f1e6-\U0001f1ff"  # bandeiras (regional indicators)
    "]+"
)


def _conta_emoji(bolha: str) -> int:
    """Nº de runs de emoji na bolha (☺️ conta 1; 🥰😍 colados contam como 1 run)."""
    return len(_EMOJI.findall(bolha))


# --- features por bolha ----------------------------------------------------------------------

# Bins de comprimento (chars). Granular no pé da curva: ELA tem mediana ~14 chars.
_LEN_BINS = [(0, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 50), (51, 100), (101, 10**9)]
_VOCATIVO = re.compile(r"\b(amor|vida)\b", re.IGNORECASE)
_RS = re.compile(r"\brs+\b", re.IGNORECASE)
_PALAVRA = re.compile(r"[0-9a-zà-ÿ]+", re.IGNORECASE)


def _bin_len(n: int) -> str:
    for lo, hi in _LEN_BINS:
        if lo <= n <= hi:
            return f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
    return "?"


def _termina_em_ponto(bolha: str) -> bool:
    """Termina com ponto final (mas não '...' nem '!'/'?' — reticências/exclamação não são
    'frase fechada de SAC'). A voz d'ELA quase nunca usa ponto final."""
    s = bolha.rstrip()
    return s.endswith(".") and not s.endswith("..")


def _trigramas_char(bolha: str) -> list[str]:
    """Trigramas de caractere sobre a bolha normalizada (lower + espaço colapsado). Captura
    idiossincrasia de registro informal (assinatura de estilo content-independent)."""
    s = re.sub(r"\s+", " ", bolha.lower()).strip()
    return [s[i : i + 3] for i in range(len(s) - 2)] if len(s) >= 3 else []


def _mattr(tokens: list[str], janela: int = 50) -> float:
    """Moving-Average Type-Token Ratio: diversidade lexical robusta ao tamanho da amostra
    (TTR cru cai com o nº de tokens; MATTR usa janelas fixas). 0 tokens → 0.0."""
    if not tokens:
        return 0.0
    if len(tokens) <= janela:
        return len(set(tokens)) / len(tokens)
    ratios = [
        len(set(tokens[i : i + janela])) / janela for i in range(len(tokens) - janela + 1)
    ]
    return sum(ratios) / len(ratios)


# --- perfil de um conjunto de bolhas ---------------------------------------------------------


def perfil_de_bolhas(lista_bolhas: list[str], *, top_trigramas: int = 200) -> dict[str, Any]:
    """Resume um conjunto de bolhas no formato do perfil estilométrico (distribuições + taxas).

    `top_trigramas` limita a cauda dos trigramas (o resto vira a massa 'OUTRO') — mantém o JSON
    pequeno e o JS estável; a cobertura fica em `trigrama_cobertura`."""
    n = len(lista_bolhas)
    if n == 0:
        raise ValueError("perfil_de_bolhas: lista de bolhas vazia")

    len_hist: Counter[str] = Counter()
    emoji_hist: Counter[str] = Counter()
    n_ponto = 0
    n_vocativo = 0
    n_rs = 0
    tri_total: Counter[str] = Counter()
    tokens_todos: list[str] = []

    for b in lista_bolhas:
        len_hist[_bin_len(len(b))] += 1
        ne = _conta_emoji(b)
        emoji_hist["3+" if ne >= 3 else str(ne)] += 1
        if _termina_em_ponto(b):
            n_ponto += 1
        if _VOCATIVO.search(b):
            n_vocativo += 1
        if _RS.search(b):
            n_rs += 1
        tri_total.update(_trigramas_char(b))
        tokens_todos.extend(m.group(0).lower() for m in _PALAVRA.finditer(b))

    tri_n = sum(tri_total.values())
    top = tri_total.most_common(top_trigramas)
    tri_probs = {t: c / tri_n for t, c in top} if tri_n else {}
    cobertura = sum(c for _, c in top) / tri_n if tri_n else 0.0

    return {
        "n_bolhas": n,
        "len_hist": {k: v / n for k, v in len_hist.items()},
        "emoji_hist": {k: v / n for k, v in emoji_hist.items()},
        "taxa_ponto_final": n_ponto / n,
        "taxa_emoji": sum(v for k, v in emoji_hist.items() if k != "0") / n,
        "taxa_vocativo": n_vocativo / n,
        "taxa_rs": n_rs / n,
        "trigrama_probs": tri_probs,
        "trigrama_outro": max(0.0, 1.0 - cobertura),
        "trigrama_cobertura": cobertura,
        "mattr": _mattr(tokens_todos),
    }


# --- distâncias ------------------------------------------------------------------------------


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon em base 2 → [0,1]. 0 = distribuições idênticas, 1 = disjuntas."""
    labels = set(p) | set(q)
    m = {k: (p.get(k, 0.0) + q.get(k, 0.0)) / 2 for k in labels}

    def _kl(a: dict[str, float]) -> float:
        s = 0.0
        for k in labels:
            ak = a.get(k, 0.0)
            if ak > 0 and m[k] > 0:
                s += ak * math.log2(ak / m[k])
        return s

    return max(0.0, min(1.0, 0.5 * _kl(p) + 0.5 * _kl(q)))


def _dist_trigramas(ref: dict[str, Any], cand: dict[str, Any]) -> float:
    """JS sobre trigramas, com a massa 'OUTRO' como um rótulo extra (cauda não enumerada)."""
    p = dict(ref["trigrama_probs"])
    p["__OUTRO__"] = ref.get("trigrama_outro", 0.0)
    q = dict(cand["trigrama_probs"])
    q["__OUTRO__"] = cand.get("trigrama_outro", 0.0)
    return js_divergence(p, q)


# Pesos da feature no agregado. Iguais por padrão (média simples) — ajuste só com evidência.
# "rs" entrou como feature (o <voz> instrui "rs no meio da venda" e o modelo tende a sub-usar
# gíria de chat — medir a frequência fecha o loop dessa instrução).
FEATURES = ("comprimento", "ponto_final", "emoji", "vocativo", "rs", "trigramas", "diversidade")


def distancia(ref: dict[str, Any], cand: dict[str, Any]) -> dict[str, float]:
    """Distância gerado×corpus por feature (cada uma em [0,1]) + 'agregado' (média simples)."""
    d = {
        "comprimento": js_divergence(ref["len_hist"], cand["len_hist"]),
        "ponto_final": abs(ref["taxa_ponto_final"] - cand["taxa_ponto_final"]),
        "emoji": abs(ref["taxa_emoji"] - cand["taxa_emoji"]),
        "vocativo": abs(ref["taxa_vocativo"] - cand["taxa_vocativo"]),
        "rs": abs(ref["taxa_rs"] - cand["taxa_rs"]),
        "trigramas": _dist_trigramas(ref, cand),
        "diversidade": abs(ref["mattr"] - cand["mattr"]),
    }
    d["agregado"] = sum(d[f] for f in FEATURES) / len(FEATURES)
    return d


def carregar_perfil(path: str | Path) -> dict[str, Any]:
    """Carrega o perfil congelado (JSON gravado por `gerar_perfil_estilo.py`)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc["perfil"] if "perfil" in doc else doc


# --- CLI: pontuar um arquivo de bolhas contra o perfil congelado -----------------------------


def _ler_candidato(path: str) -> list[str]:
    """Lê o candidato. `.json` → lista de strings (turnos) ou {'turnos': [...]}; senão texto
    cru (turnos separados por linha em branco)."""
    raw = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        doc = json.loads(raw)
        turnos = doc["turnos"] if isinstance(doc, dict) else doc
    else:
        turnos = _SEP_BOLHA.split(raw)
    out: list[str] = []
    for t in turnos:
        out.extend(bolhas(t) if isinstance(t, str) else [])
    return out


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("uso: python estilometria.py <perfil.json> <candidato.(json|txt)>")
    ref = carregar_perfil(sys.argv[1])
    cand_bolhas = _ler_candidato(sys.argv[2])
    if not cand_bolhas:
        sys.exit("candidato sem bolhas")
    cand = perfil_de_bolhas(cand_bolhas)
    d = distancia(ref, cand)
    piso = ref.get("__meta__", {}).get("piso_ela_vs_ela")  # se embutido no perfil
    print(f"bolhas candidato: {cand['n_bolhas']}")
    print(json.dumps({k: round(v, 4) for k, v in d.items()}, ensure_ascii=False, indent=2))
    if piso is not None:
        print(f"piso ELA-vs-ELA (agregado): {round(piso, 4)}")


if __name__ == "__main__":
    _ = unicodedata  # mantém o import (normalização futura); evita F401 sem alterar comportamento
    main()
