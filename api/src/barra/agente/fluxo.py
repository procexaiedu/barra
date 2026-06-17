"""Logica pura da metrica de FLUXO conversacional (labeler + divergencia). Sem DB, sem rede.

Cada turno do VENDEDOR vira um "ato" (alfabeto do funil de regras.md.j2); uma conversa vira uma
sequencia de atos; a divergencia entre duas populacoes e a Jensen-Shannon sobre a distribuicao de
TRANSICOES (bigramas). Determinismo total: rotulador por regex (sem LLM-judge, sem credito), JSD em
pure-python (sem numpy).

Reusado por: `scripts/eval_corpus/fluxo.py` (CLI corpus-vs-corpus) e `barra.workers.fluxo_drift`
(sensor de deriva autonomo). Limitacoes coarse documentadas no script CLI.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter

# Alfabeto do funil (regras.md.j2: sondagem -> apresentar/midia -> cotar -> fechar; + desconto).
ATOS = ["saudacao", "sondagem", "cotacao", "midia", "desconto", "logistica", "outro"]

# Portado de wf_simulador.js:226 (sondagem de horario/agendamento).
SOND_RE = re.compile(
    r"seria\s+(hoje|pra\s+hoje|agora)|vamos\s+hoje|que\s+horas\s+(vc|voc[êe]|tu|costuma)|"
    r"me\s+(avisa|chama|fala)\s+(quando|que\s+horas|assim\s+que)",
    re.IGNORECASE,
)
# Preco no turno: R$ + digitos, ou numero de 3-4 digitos solto que NAO seja hora ("22h", "20:00").
PRECO_RE = re.compile(r"r\$\s*\d{2,}|(?<![\d:])\b\d{3,4}\b(?!\s*h\b)(?!:)", re.IGNORECASE)
DESCONTO_RE = re.compile(
    r"desconto|descontinho|consigo (fazer|te (fazer|dar))|um precinho|"
    r"fa[çc]o por menos|pre[çc]o (melhor|especial)",
    re.IGNORECASE,
)
LOGISTICA_RE = re.compile(
    r"endere[çc]o|ponto de (encontro|refer[êe]ncia)|me manda o pix|manda o pix|chave pix|"
    r"forma de pagamento|cart[ãa]o|dinheiro|te espero|pode vir|combinado então|fechad[oa]|confirmad",
    re.IGNORECASE,
)
SAUDACAO_RE = re.compile(
    r"^\s*(oi|ol[áa]|bom dia|boa (tarde|noite)|opa|e a[íi]|hey)\b|tudo bem|tudo certo",
    re.IGNORECASE,
)
# Marcador de midia textual (lado do agente/transcript, quando nao ha coluna tem_midia).
MIDIA_RE = re.compile(r"\[\s*(midia|m[íi]dia|foto|v[íi]deo|audio|[áa]udio)\s*\]", re.IGNORECASE)


def rotular_turno(texto: str | None, tem_midia: bool | None = None) -> str:
    """Ato dominante de um turno do Vendedor, por precedencia (primeira que casa vence)."""
    t = (texto or "").lower()
    if PRECO_RE.search(t):
        return "cotacao"
    if tem_midia or MIDIA_RE.search(t):
        return "midia"
    if DESCONTO_RE.search(t):
        return "desconto"
    if LOGISTICA_RE.search(t):
        return "logistica"
    if SOND_RE.search(t):
        return "sondagem"
    if SAUDACAO_RE.search(t):
        return "saudacao"
    return "outro"


def matriz_transicao(sequencias: list[list[str]]) -> Counter[tuple[str, str]]:
    """Conta as transicoes ato_t -> ato_{t+1} sobre todas as sequencias de uma populacao."""
    c: Counter[tuple[str, str]] = Counter()
    for seq in sequencias:
        for a, b in itertools.pairwise(seq):
            c[(a, b)] += 1
    return c


def _dist(counter: Counter) -> dict:  # type: ignore[type-arg]
    total = sum(counter.values()) or 1
    return {k: v / total for k, v in counter.items()}


def js_divergencia(p_counter: Counter, q_counter: Counter) -> float:  # type: ignore[type-arg]
    """Jensen-Shannon (log2) entre duas distribuicoes de contagem. Em [0,1]; JSD(P,P)=0."""
    p, q = _dist(p_counter), _dist(q_counter)
    chaves = set(p) | set(q)
    m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in chaves}

    def _kl(a: dict) -> float:  # type: ignore[type-arg]
        s = 0.0
        for k in chaves:
            ak = a.get(k, 0.0)
            if ak > 0:
                s += ak * math.log2(ak / m[k])
        return s

    return 0.5 * _kl(p) + 0.5 * _kl(q)


def relatorio(
    nome_p: str,
    seqs_p: list[list[str]],
    nome_q: str,
    seqs_q: list[list[str]],
    top_k: int = 8,
) -> str:
    """Tabela de frequencia de atos + JSD das transicoes + top transicoes que mais divergem."""
    uni_p = Counter(a for seq in seqs_p for a in seq)
    uni_q = Counter(a for seq in seqs_q for a in seq)
    tot_p, tot_q = sum(uni_p.values()) or 1, sum(uni_q.values()) or 1

    linhas = [
        f"# Fluxo: {nome_p} (n={len(seqs_p)} threads) vs {nome_q} (n={len(seqs_q)} threads)",
        "",
        f"{'ato':<11} {nome_p:>10} {nome_q:>10}   delta",
    ]
    for a in ATOS:
        fp, fq = uni_p[a] / tot_p, uni_q[a] / tot_q
        linhas.append(f"{a:<11} {fp:>10.1%} {fq:>10.1%}   {(fq - fp):+.1%}")

    trans_p, trans_q = matriz_transicao(seqs_p), matriz_transicao(seqs_q)
    jsd = js_divergencia(trans_p, trans_q)
    linhas += ["", f"JSD(transicoes) = {jsd:.4f}  (0 = identico, 1 = disjunto)", ""]

    dp, dq = _dist(trans_p), _dist(trans_q)
    chaves = set(dp) | set(dq)
    div = sorted(chaves, key=lambda k: abs(dq.get(k, 0) - dp.get(k, 0)), reverse=True)
    linhas.append(f"Top {top_k} transicoes que mais divergem (delta = {nome_q} - {nome_p}):")
    for k in div[:top_k]:
        linhas.append(
            f"  {k[0]:>10} -> {k[1]:<10} {nome_p}={dp.get(k, 0):.1%}  {nome_q}={dq.get(k, 0):.1%}"
        )
    return "\n".join(linhas)
