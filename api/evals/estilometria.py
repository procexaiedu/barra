"""Estilometria deterministica (Camada 2) — "soa como ela?" como DISTANCIA de distribuicao.

Porte committado da logica pura de `scripts/eval_corpus/estilometria.py` (aquela pasta esta no
.gitignore, entao nao da pra importar dela). Mede o quao perto um conjunto de bolhas geradas (a
fala do agente) esta do **perfil congelado d'ELA** (corpus real do Vendedor). Pure stdlib — sem
numpy/scipy — entao roda offline, sem DB e sem credito de API (§0 do CLAUDE.md).

Features (exatamente as do script original):
1. comprimento de bolha             -> histograma -> Jensen-Shannon
2. ausencia de ponto final          -> taxa       -> |Delta|
3. emoji-rate                       -> taxa       -> |Delta|
4. vocativos ("amor"/"vida")        -> taxa       -> |Delta|
5. "rs" (riso informal)             -> taxa       -> |Delta|
6. n-gramas de caractere (trigrama) -> distrib.   -> Jensen-Shannon
7. diversidade lexical (MATTR-50)   -> escalar    -> |Delta|

Distancia por feature em [0,1]; o **agregado** e a media simples das 7 (0 = identico a voz d'ELA).
Sinal RELATIVO: compare sempre contra o piso de ruido (ELA-vs-ELA) gravado no perfil congelado por
`evals.baselines.gerar`. NAO mede conteudo/correcao nem desfecho.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

# --- tokenizacao de bolhas ------------------------------------------------------------------

_SEP_BOLHA = re.compile(r"\n\s*\n+")


def bolhas(texto: str) -> list[str]:
    """Quebra um turno em bolhas (linha em branco como separador). Strip + descarta vazias."""
    return [b.strip() for b in _SEP_BOLHA.split(texto) if b.strip()]


# --- deteccao de emoji (sem a lib `emoji`; faixas Unicode) -----------------------------------

_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, supplemental, symbols & extended
    "\U00002600-\U000027bf"  # misc symbols + dingbats
    "\U00002190-\U000021ff"  # setas
    "\U00002b00-\U00002bff"  # estrelas/setas suplementares
    "\U0000fe00-\U0000fe0f"  # seletores de variacao (emoji presentation)
    "\U0001f1e6-\U0001f1ff"  # bandeiras (regional indicators)
    "]+"
)


def _conta_emoji(bolha: str) -> int:
    """No de runs de emoji na bolha (emojis colados contam como 1 run)."""
    return len(_EMOJI.findall(bolha))


# --- features por bolha ----------------------------------------------------------------------

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
    """Termina com ponto final (mas nao '...' nem '!'/'?'). A voz d'ELA quase nunca usa ponto."""
    s = bolha.rstrip()
    return s.endswith(".") and not s.endswith("..")


def _trigramas_char(bolha: str) -> list[str]:
    """Trigramas de caractere sobre a bolha normalizada (lower + espaco colapsado)."""
    s = re.sub(r"\s+", " ", bolha.lower()).strip()
    return [s[i : i + 3] for i in range(len(s) - 2)] if len(s) >= 3 else []


def _mattr(tokens: list[str], janela: int = 50) -> float:
    """Moving-Average Type-Token Ratio: diversidade lexical robusta ao tamanho da amostra."""
    if not tokens:
        return 0.0
    if len(tokens) <= janela:
        return len(set(tokens)) / len(tokens)
    ratios = [len(set(tokens[i : i + janela])) / janela for i in range(len(tokens) - janela + 1)]
    return sum(ratios) / len(ratios)


# --- perfil de um conjunto de bolhas ---------------------------------------------------------


def perfil_de_bolhas(lista_bolhas: list[str], *, top_trigramas: int = 200) -> dict[str, Any]:
    """Resume um conjunto de bolhas no formato do perfil estilometrico (distribuicoes + taxas)."""
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


# --- distancias ------------------------------------------------------------------------------


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon em base 2 -> [0,1]. 0 = distribuicoes identicas, 1 = disjuntas."""
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
    """JS sobre trigramas, com a massa 'OUTRO' como um rotulo extra (cauda nao enumerada)."""
    p = dict(ref["trigrama_probs"])
    p["__OUTRO__"] = ref.get("trigrama_outro", 0.0)
    q = dict(cand["trigrama_probs"])
    q["__OUTRO__"] = cand.get("trigrama_outro", 0.0)
    return js_divergence(p, q)


# Pesos da feature no agregado. Iguais por padrao (media simples) — ajuste so com evidencia.
FEATURES = ("comprimento", "ponto_final", "emoji", "vocativo", "rs", "trigramas", "diversidade")


def distancia(ref: dict[str, Any], cand: dict[str, Any]) -> dict[str, float]:
    """Distancia gerado x corpus por feature (cada uma em [0,1]) + 'agregado' (media simples)."""
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
    """Carrega o perfil congelado (JSON gravado por `evals.baselines.gerar`)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    perfil = doc["perfil"] if "perfil" in doc else doc
    if not isinstance(perfil, dict):
        raise ValueError(f"perfil estilometrico invalido em {path}")
    return perfil
