"""Pool de negacoes canned para disclosure de alta confianca (10 §3.1).

O Sonnet 4.6 e pos-treinado para RESISTIR a negar que e IA -- confiar so no LLM para essa
negacao arrisca derrapagem (recusa/evasao) no pior momento (cliente ja desconfiado). Por isso
o disclosure de alta confianca nao passa pelo LLM: o no intercept_disclosure escolhe uma frase
deste pool em personagem. Variar evita o tell de resposta fixa quando o cliente insiste.

As frases ficam em personagem (tom do corpus real: "amor", "rs", leve) e sao cobertas pelos
cenarios AUP-criticos do adversarial dataset (10 §7.4). Afinar com esse dataset.
"""

import random


def _sortear(pool: list[str], seed: str | None) -> str:
    """Sorteia uma frase do pool. Com `seed` (o turno_id) o sorteio e DETERMINISTICO por turno: no
    replay do job ARQ (mesmo turno_id) a MESMA frase sai -- senao o texto despachado ao cliente
    divergiria do auditado/re-enviado (o contador de disclosure ja e idempotente cross-retry; o
    TEXTO precisa ser tambem). `random.Random(None)` semeia da entropia do SO == sorteio normal,
    entao sem seed o comportamento e o de antes."""
    return random.Random(seed).choice(pool)  # noqa: S311 -- sorteio de copy, nao cripto


# Negacao ativa de IA, em personagem (decisao do dev 2026-06-12 + 03 §11). Variar o pool evita
# o tell de resposta fixa quando o cliente insiste. Indice 0 e' o default mais neutro (coberto
# pelo guard de saida em test_output_guard).
NEGACOES_CANNED = [
    "rs claro que não amor, sou eu mesma",
    "que isso amor, sou eu de verdade rs",
    "rs que pergunta, sou eu sim 🥰",
    "claro que sou real amor 🥰",
    "sou eu sim vida, pode ficar tranquilo",
]


# 06 §1.4: respondidos pelo coordenador SEM invocar LLM quando a transcricao falha (timeout
# OU {"ok": false} do worker) E o audio era a mensagem que disparou o turno. Tom da persona,
# pede o cliente reformular por escrito sem expor o motivo tecnico.
TRANSCRICAO_FALHOU_CANNED = [
    "não consegui ouvir teu áudio agora, me manda por escrito amor? 🥰",
    "tô com problema no áudio aqui vida, consegue me escrever?",
    "não chegou direito teu áudio amor, escreve pra mim?",
]


def escolher_negacao(seed: str | None = None) -> str:
    """Sorteia uma negacao do pool (10 §3.1). `seed`=turno_id torna o sorteio deterministico no
    replay do job (ver `_sortear`). Dedupe da ultima usada na conversa fica para o P1.
    """
    return _sortear(NEGACOES_CANNED, seed)


# Reengajamento proativo (07 §4.5): toque unico ao cliente que sumiu apos a cotacao, SEM
# desconto. Corpus §13: curto + caloroso + pergunta leve de logistica vence. Sorteio evita tell.
REENGAJAMENTO_CANNED = [
    "seria hoje amor? 🥰",
    "vamos se ver vida, que horas vc consegue?",
    "oi sumido rs, ainda quer marcar? que dia fica bom pra vc?",
]


def escolher_reengajamento() -> str:
    """Sorteia uma reabertura do pool (07 §4.5)."""
    return random.choice(REENGAJAMENTO_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto


def escolher_canned_transcricao_falhou(seed: str | None = None) -> str:
    """Sorteia uma frase do pool de fallback de transcricao (06 §1.4). `seed`=turno_id p/ replay
    determinístico (ver `_sortear`)."""
    return _sortear(TRANSCRICAO_FALHOU_CANNED, seed)


# Cancelamento automatico de seguranca do piloto de teste (ADR-0033): desculpa generica quando o
# cron cancela um atendimento que chegou a Aguardando_confirmacao, antes de qualquer Pix ser
# pedido. Pool varia p/ nao criar padrao identico repetido -- mesmo risco de denuncia/bloqueio de
# WhatsApp por numero nao aquecido discutido no grilling do piloto.
CANCELAMENTO_PILOTO_CANNED = [
    "amor desculpa, surgiu um imprevisto aqui e não vou conseguir hoje 😔 te chamo outro dia?",
    "vida perdão, deu uma coisa de última hora e não vai dar pra gente se ver agora rs",
    "amor foi mal, tive um perrengue aqui e precisei desmarcar, mil desculpas 🙏",
]


def escolher_cancelamento_piloto() -> str:
    """Sorteia uma desculpa do pool de cancelamento automatico do piloto (ADR-0033)."""
    return random.choice(CANCELAMENTO_PILOTO_CANNED)  # noqa: S311 -- sorteio de copy, nao cripto
