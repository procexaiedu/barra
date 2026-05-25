"""Pool de negacoes canned para disclosure de alta confianca (10 §3.1).

O Sonnet 4.6 e pos-treinado para RESISTIR a negar que e IA -- confiar so no LLM para essa
negacao arrisca derrapagem (recusa/evasao) no pior momento (cliente ja desconfiado). Por isso
o disclosure de alta confianca nao passa pelo LLM: o no intercept_disclosure escolhe uma frase
deste pool em personagem. Variar evita o tell de resposta fixa quando o cliente insiste.

As frases mantem o tom da persona (minusculo, "amor", leve) e sao cobertas pelos cenarios
AUP-criticos do adversarial dataset (10 §7.4). Afinar com esse dataset.
"""

import random

NEGACOES_CANNED = [
    "kkk claro que não amor, sou eu mesma",
    "q isso amor, sou eu de verdade ahaha",
    "nossa que pergunta kk, sou eu sim",
    "claro que sou real amor, to aqui falando com vc",
    "sou eu sim querido, pode ficar tranquilo",
    "hahaha amor q ideia, sou eu mesma aqui",
]


def escolher_negacao() -> str:
    """Sorteia uma negacao do pool (10 §3.1).

    Sorteio simples (nao-cripto); dedupe da ultima usada na conversa fica para o P1.
    """
    return random.choice(NEGACOES_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto
