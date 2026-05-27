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
    "ahaha claro que não amor, sou eu mesma",
    "q isso amor, sou eu de verdade ahaha",
    "nossa que pergunta hahaha, sou eu sim",
    "claro que sou real amor, to aqui falando com vc",
    "sou eu sim querido, pode ficar tranquilo",
    "hahaha amor q ideia, sou eu mesma aqui",
]


# 06 §1.4: respondidos pelo coordenador SEM invocar LLM quando a transcricao falha (timeout
# OU {"ok": false} do worker) E o audio era a mensagem que disparou o turno. Tom da persona,
# pede o cliente reformular por escrito sem expor o motivo tecnico.
TRANSCRICAO_FALHOU_CANNED = [
    "amor, nao consegui ouvir teu audio agora, me manda por escrito?",
    "to com problema no audio aqui, tu consegue me escrever?",
    "deu ruim pra ouvir teu audio amor, manda por texto?",
    "aqui nao chegou direito o audio, escreve pra mim?",
]


def escolher_negacao() -> str:
    """Sorteia uma negacao do pool (10 §3.1).

    Sorteio simples (nao-cripto); dedupe da ultima usada na conversa fica para o P1.
    """
    return random.choice(NEGACOES_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto


# Reengajamento proativo (07 §4.5): toque unico ao cliente que sumiu apos a cotacao,
# em persona, SEM desconto. O reativo de preco vem depois pelo Desconto de fechamento
# (03 §3.1, ADR-0004). Sorteio simples evita o tell de mensagem fixa.
REENGAJAMENTO_CANNED = [
    "amor, vamos se ver hoje? to com a agenda boa hj",
    "oi sumido, ainda quer marcar? consigo um horario gostoso pra gente",
    "e ai amor, vamos marcar? to pensando em vc",
]


def escolher_reengajamento() -> str:
    """Sorteia uma reabertura do pool (07 §4.5)."""
    return random.choice(REENGAJAMENTO_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto


def escolher_canned_transcricao_falhou() -> str:
    """Sorteia uma frase do pool de fallback de transcricao (06 §1.4)."""
    return random.choice(TRANSCRICAO_FALHOU_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto
