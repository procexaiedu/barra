"""Normalizacao de texto NAO-confiavel antes de QUALQUER classificador/regex de defesa.

Buraco conhecido (memoria `classificador_disclosure_depende_acento`): o classificador casava o
"e" ACENTUADO e deixava passar "vc e um bot" (sem acento) -> caia no LLM. "Accent/character
manipulation" e uma classe documentada de evasao de guardrail, ate 100% de bypass
(arXiv:2504.11168; guardrail PT-BR fragil a perturbacao, arXiv:2504.15241). O fix de maior ROI e
normalizar o texto ANTES da regex -- custo ~0 (CPU puro, sub-ms, zero chamada LLM).

Essencial e suficiente p/ PT-BR (decisao do handoff): remocao de diacriticos (NFKD + strip de
combining marks) + casefold + colapso de whitespace. De-leet e deteccao de base64 ficam DE FORA
ate haver evidencia de uso real -- nao especular (CLAUDE.md §2).
"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Reduz o texto a forma canonica p/ casar regex de defesa de modo acento-insensivel.

    "E um BOT" / "e um bot" / " e  um   bot " -> "e um bot". NFKD decompoe cada acento em
    base + combining mark; `combining()` filtra as marks (e->e, o->o, a->a). `casefold` e o
    lower-case agressivo do Unicode (mais forte que `.lower()`). O colapso de whitespace mata o
    ruido de espaco/quebra repetidos. Idempotente: `normalizar(normalizar(x)) == normalizar(x)`.
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_diacritico = "".join(c for c in decomposto if not unicodedata.combining(c))
    return _WHITESPACE.sub(" ", sem_diacritico.casefold()).strip()
