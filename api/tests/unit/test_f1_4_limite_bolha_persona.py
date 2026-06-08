"""F1.4 — limite de bolha verificado com **falas reais da persona**, não só caso sintético (UX).

O gate de `test_chunk_texto.py` exercita `chunk_texto` só com entrada sintética (`"b0"`, `"b1"`,
`"palavra " * 100`). F1.4 fecha o buraco: as **falas reais da persona** (do corpus anonimizado em
`docs/agente/conversas-reais/`) têm de cair no **envelope de bolha esperado** — cada bolha ≤
`MAX_CHARS` (600), o turno ≤ `MAX_CHUNKS` (6) bolhas e **nenhuma** sentença real estourando o cap
(`CHUNK_OVERSIZE` não incrementa). Se a persona real produzisse um paredão >600 ou um turno que o
chunking quebrasse, este gate pega.

As falas em `FALAS_REAIS` são **verbatim do corpus** — `test_falas_sao_reais_do_corpus` prova por
containment (whitespace-normalizado) que cada uma aparece no `.md` de origem, então não são
sintéticas nem inventadas. Os `TURNOS_REAIS` montam turnos no estilo da IA (pensamentos separados
por linha em branco, como `regras.md` instrui) **só com falas de `FALAS_REAIS`**.

Puro (sem banco, sem chave). `CHUNK_OVERSIZE` é Counter global — lê-se o delta (antes/depois).
"""

from pathlib import Path

from prometheus_client import REGISTRY

from barra.workers._chunking import MAX_CHARS, MAX_CHUNKS, chunk_texto

_CORPUS_DIR = Path(__file__).resolve().parents[3] / "docs" / "agente" / "conversas-reais"

# Bolhas reais (uma mensagem de WhatsApp da MODELO cada) extraídas verbatim do corpus. Bolhas
# multi-linha preservam o `\n` simples (lista/endereço como um humano manda). Variadas: cotação,
# recusa de prática, inclusões, localização, fechamento, portaria, dupla, pernoite, pix.
FALAS_REAIS: list[str] = [
    # 001 — interno, recusa de anal, desconto de fechamento
    "Meu cache 800 1h",
    "Beijo na boca, faço oral sem camisinha, faço estilo namoradinha",
    "Não tenho costume 😊",
    "Isso depende amor, para isso acontecer o valor tem que valer a pena\n"
    "e você tem que ser carinhoso ❤️",
    "Mas como disse não tenho costume mesmo...",
    "Sou uma mulher educada, extrovertida",
    "Tenho meu local ou posso ir até você também",
    "Estou barra da Tijuca próximo ao posto 3",
    "800 1h seria no meu local\nIndo até você teria o custo adicional do uber",
    "Se vier agora consigo fazer por 700 1h",
    "Com local já incluso no cachê",
    "Pra mim está ótimo\nTenho disponibilidade para as 22h sim",
    "Combinado",
    "700 1h as 22h",
    "Não inclui anal ok",
    "Confirmado ?",
    "Sou sua durante o período combinado 🥰",
    "Chegando me avisa",
    "Que eu lhe informo o quarto e libero sua visita",
    # 002 — dupla com amiga, cliente escolhe uma
    "Meu cachê 900 1h estou na barra da Tijuca",
    "Estou com uma amiga",
    "Valor individual amor",
    "Só eu 900",
    "Nós duas 1600",
    "Aceito cartão",
    "Pode ser ela",
    "Sem problemas",
    # 003 — gringo bilíngue, pernoite
    "Posso ir até você",
    "Faço pernoite",
    "Podemos passar a noite juntos",
    "Vamos combinar algo bacana amor",
    "Você pode vir no meu apartamento",
    "Quantas horas vamos ficar juntos ?",
    # 004 — videocall, qualificação, pix de 50
    "Livre amor",
    "Estou na barra",
    "Vou enviar meu Pix",
]

# Turnos reais no estilo da IA: pensamentos consecutivos da persona separados por linha em branco
# (como a IA é instruída a fazer). Cada tupla: (descrição, falas-em-ordem, nº de bolhas esperado).
# Só usa falas de FALAS_REAIS — assim o containment cobre todos os constituintes.
TURNOS_REAIS: list[tuple[str, list[str], int]] = [
    (
        "cotação + inclusões positivas",
        ["Meu cache 800 1h", "Beijo na boca, faço oral sem camisinha, faço estilo namoradinha"],
        2,
    ),
    (
        "recusa em camadas (porta entreaberta + reafirma)",
        [
            "Isso depende amor, para isso acontecer o valor tem que valer a pena\n"
            "e você tem que ser carinhoso ❤️",
            "Mas como disse não tenho costume mesmo...",
            "Sou uma mulher educada, extrovertida",
        ],
        3,
    ),
    (
        "trava de escopo no fechamento",
        ["Combinado", "700 1h as 22h", "Não inclui anal ok", "Confirmado ?"],
        4,
    ),
    (
        "dupla: preços individuais",
        ["Valor individual amor", "Só eu 900", "Nós duas 1600", "Aceito cartão"],
        4,
    ),
]


def _norm(texto: str) -> str:
    """Colapsa toda sequência de espaço/quebra em um único espaço (robusto à indentação do .md)."""
    return " ".join(texto.split())


def _corpus_normalizado() -> str:
    arquivos = sorted(_CORPUS_DIR.glob("00*.md"))
    assert arquivos, f"corpus vazio em {_CORPUS_DIR}"  # anti-vácuo: achou os .md
    return _norm("\n".join(p.read_text(encoding="utf-8") for p in arquivos))


# --- as falas são reais (anti-fabricação) ----------------------------------------------------


def test_falas_sao_reais_do_corpus() -> None:
    """Cada fala de FALAS_REAIS aparece verbatim (whitespace-normalizado) no corpus — prova que o
    dataset é a persona real, não sintético/inventado."""
    corpus = _corpus_normalizado()
    assert len(FALAS_REAIS) >= 25  # amostra não-trivial, varrendo os 4 cenários
    ausentes = [f for f in FALAS_REAIS if _norm(f) not in corpus]
    assert not ausentes, f"falas não encontradas no corpus (não são reais?): {ausentes}"


# --- cada bolha real cabe no envelope (≤ MAX_CHARS, 1 bolha, sem oversize) --------------------


def test_cada_fala_real_e_uma_unica_bolha_dentro_do_cap() -> None:
    """Toda bolha real vira exatamente 1 chunk, ≤ MAX_CHARS, sem disparar o oversize. A persona
    real não manda paredão >600 — o sentence-split (que conta CHUNK_OVERSIZE) nunca engata aqui."""
    antes = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    for fala in FALAS_REAIS:
        chunks, flags = chunk_texto(fala)
        assert len(chunks) == 1, f"fala real virou {len(chunks)} bolhas: {fala!r}"
        assert len(chunks[0]) <= MAX_CHARS, f"bolha real estourou o cap: {fala!r}"
        assert flags == [False]
        assert _norm(chunks[0]) == _norm(fala)  # conteúdo preservado
    depois = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    assert depois == antes  # nenhuma fala real conta como oversize


# --- turnos reais de múltiplos pensamentos caem no envelope ----------------------------------


def test_turnos_reais_caem_no_envelope_de_bolhas() -> None:
    """Turno real (pensamentos separados por linha em branco) → uma bolha por pensamento, ≤
    MAX_CHUNKS, cada bolha ≤ MAX_CHARS, sem oversize, e todo pensamento preservado."""
    antes = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    for descricao, falas, n_esperado in TURNOS_REAIS:
        texto = "\n\n".join(falas)
        chunks, flags = chunk_texto(texto)
        assert len(chunks) == n_esperado, f"{descricao}: {len(chunks)} bolhas ≠ {n_esperado}"
        assert len(chunks) <= MAX_CHUNKS
        assert all(len(c) <= MAX_CHARS for c in chunks), f"{descricao}: bolha > cap"
        assert flags == [False] * n_esperado
        corpo = _norm(" ".join(chunks))
        for fala in falas:
            assert _norm(fala) in corpo, f"{descricao}: pensamento perdido: {fala!r}"
    depois = REGISTRY.get_sample_value("agente_chunk_oversize_total") or 0.0
    assert depois == antes


def test_turno_real_acima_do_cap_funde_no_envelope() -> None:
    """Turno real com mais de MAX_CHUNKS pensamentos colapsa em exatamente MAX_CHUNKS bolhas
    (excedente fundido) — o cap engata em conteúdo real, não só no sintético `b0..b7`."""
    falas = FALAS_REAIS[:8]  # 8 > MAX_CHUNKS(6)
    chunks, flags = chunk_texto("\n\n".join(falas))
    assert len(chunks) == MAX_CHUNKS
    assert "\n\n" in chunks[-1]  # excedente fundido no último, conteúdo preservado
    assert len(flags) == len(chunks)
