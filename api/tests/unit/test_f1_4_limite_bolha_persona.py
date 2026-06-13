"""F1.4 — limite de bolha verificado com falas no formato de WhatsApp, não só caso sintético (UX).

O gate de `test_chunk_texto.py` exercita `chunk_texto` só com entrada sintética (`"b0"`, `"b1"`,
`"palavra " * 100`). F1.4 fecha o buraco: falas no formato real (bolha curta, multi-linha com `\n`
simples, emoji) têm de cair no **envelope de bolha esperado** — cada bolha ≤ `MAX_CHARS` (600),
o turno ≤ `MAX_CHUNKS` (6) bolhas e **nenhuma** sentença estourando o cap (`CHUNK_OVERSIZE` não
incrementa).

TODO (reset do agente): as falas em `FALAS_REAIS`/`TURNOS_REAIS` são placeholders neutros — o que
importa aqui é o FORMATO (comprimento, `\n` simples, separação por linha em branco), não o
conteúdo. Repopular com falas destiladas do novo corpus quando a persona for reescrita.

Puro (sem banco, sem chave). `CHUNK_OVERSIZE` é Counter global — lê-se o delta (antes/depois).
"""

from prometheus_client import REGISTRY

from barra.workers._chunking import MAX_CHARS, MAX_CHUNKS, chunk_texto

# Placeholders neutros (uma bolha de WhatsApp cada). Variam comprimento e usam `\n` simples nas
# multi-linha (como um humano manda lista/endereço). Sem linha em branco interna (cada uma = 1 bolha).
FALAS_REAIS: list[str] = [
    "oi, tudo bem? 😊",
    "consigo sim",
    "me avisa quando estiver a caminho",
    "primeiro a gente combina\ndepois eu te confirmo",
    "perfeito pra mim",
    "pode ser um pouco mais tarde?",
    "fechado então",
    "qualquer coisa me chama ❤️",
    "tô por aqui",
    "vou verificar e já te falo",
    "anota aí o endereço\nrua das flores, 100",
    "combinado",
]

# Turnos no estilo da IA: pensamentos consecutivos separados por linha em branco. Cada tupla:
# (descrição, falas-em-ordem, nº de bolhas esperado). Só usa falas de FALAS_REAIS — assim o
# containment cobre todos os constituintes.
TURNOS_REAIS: list[tuple[str, list[str], int]] = [
    (
        "saudação + disponibilidade",
        ["oi, tudo bem? 😊", "consigo sim"],
        2,
    ),
    (
        "confirmação em passos",
        [
            "primeiro a gente combina\ndepois eu te confirmo",
            "perfeito pra mim",
            "fechado então",
        ],
        3,
    ),
    (
        "ajuste de horário",
        ["pode ser um pouco mais tarde?", "consigo sim", "combinado", "qualquer coisa me chama ❤️"],
        4,
    ),
    (
        "fechando o combinado",
        [
            "anota aí o endereço\nrua das flores, 100",
            "tô por aqui",
            "me avisa quando estiver a caminho",
            "combinado",
        ],
        4,
    ),
]


def _norm(texto: str) -> str:
    """Colapsa toda sequência de espaço/quebra em um único espaço (robusto à indentação)."""
    return " ".join(texto.split())


# --- cada bolha cabe no envelope (≤ MAX_CHARS, 1 bolha, sem oversize) --------------------------


def test_cada_fala_real_e_uma_unica_bolha_dentro_do_cap() -> None:
    """Toda bolha vira exatamente 1 chunk, ≤ MAX_CHARS, sem disparar o oversize. Bolha no formato
    real não é paredão >600 — o sentence-split (que conta CHUNK_OVERSIZE) nunca engata aqui."""
    antes = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    for fala in FALAS_REAIS:
        chunks, alvos = chunk_texto(fala)
        assert len(chunks) == 1, f"fala virou {len(chunks)} bolhas: {fala!r}"
        assert len(chunks[0]) <= MAX_CHARS, f"bolha estourou o cap: {fala!r}"
        assert alvos == [None]
        assert _norm(chunks[0]) == _norm(fala)  # conteúdo preservado
    depois = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    assert depois == antes  # nenhuma fala conta como oversize


# --- turnos de múltiplos pensamentos caem no envelope ----------------------------------------


def test_turnos_reais_caem_no_envelope_de_bolhas() -> None:
    """Turno (pensamentos separados por linha em branco) → uma bolha por pensamento, ≤
    MAX_CHUNKS, cada bolha ≤ MAX_CHARS, sem oversize, e todo pensamento preservado."""
    antes = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    for descricao, falas, n_esperado in TURNOS_REAIS:
        texto = "\n\n".join(falas)
        chunks, alvos = chunk_texto(texto)
        assert len(chunks) == n_esperado, f"{descricao}: {len(chunks)} bolhas ≠ {n_esperado}"
        assert len(chunks) <= MAX_CHUNKS
        assert all(len(c) <= MAX_CHARS for c in chunks), f"{descricao}: bolha > cap"
        assert alvos == [None] * n_esperado
        corpo = _norm(" ".join(chunks))
        for fala in falas:
            assert _norm(fala) in corpo, f"{descricao}: pensamento perdido: {fala!r}"
    depois = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    assert depois == antes


def test_turno_real_acima_do_cap_funde_no_envelope() -> None:
    """Turno com mais de MAX_CHUNKS pensamentos colapsa em exatamente MAX_CHUNKS bolhas
    (excedente fundido) — o cap engata em conteúdo de verdade, não só no sintético `b0..b7`."""
    falas = FALAS_REAIS[:8]  # 8 > MAX_CHUNKS(6)
    chunks, alvos = chunk_texto("\n\n".join(falas))
    assert len(chunks) == MAX_CHUNKS
    assert "\n\n" in chunks[-1]  # excedente fundido no último, conteúdo preservado
    assert len(alvos) == len(chunks)
