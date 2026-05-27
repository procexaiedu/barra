"""Chunking de texto da humanização (05 §2).

Divide o `AIMessage` final do turno em mensagens WhatsApp separadas: split por linha em
branco, preserva `\\n` simples dentro de um bloco, cap soft de 600 chars/chunk e cap de 6
bolhas. Consumido pelo coordenador antes de despachar `enviar_turno`.

Marker `[quote]` (no início de um bloco) sinaliza que aquela bolha responde, no WhatsApp,
à última mensagem do cliente — o prefixo é removido do texto enviado e a posição entra na
lista paralela `quote_flags`. Quem casa flag → `evolution_message_id` é o coordenador.
"""

import re

from barra.core.metrics import CHUNK_OVERSIZE

MAX_CHARS = 600
MAX_CHUNKS = 6
_QUOTE_PREFIX = re.compile(r"^\s*\[quote\]\s*", re.IGNORECASE)


def chunk_texto(texto: str) -> tuple[list[str], list[bool]]:
    """Divide o texto da IA em mensagens WhatsApp separadas + flag de quote por bolha.

    Regras:
    - separa por \\n\\n (uma ou mais linhas em branco) → uma mensagem por bloco;
    - bloco prefixado por `[quote]` (case-insensitive, opcionalmente seguido de espaço) tem
      o prefixo removido e a posição correspondente vira `True` em `quote_flags`;
    - dentro de um bloco, PRESERVA \\n simples (lista de horários, endereço continuam
      multi-linha): colapsa só espaços/tabs por linha e descarta linhas vazias;
    - se um bloco passa de ~600 chars, sub-divide por sentença ("! ", "? ", ". ");
      uma sentença única > 600 sai INTEIRA (o cap é alvo, não garantia) e incrementa
      CHUNK_OVERSIZE — sinal de prompt que ignorou o \\n\\n instruído, não de erro de envio;
    - sub-bolhas herdam a flag de quote do bloco que as gerou (caso raro, mas estável);
    - cap final de MAX_CHUNKS bolhas: o excedente é FUNDIDO no último chunk (anti-spam de
      40 mensagens + mantém o turno abaixo do job_timeout de 90s) e a flag desse último
      chunk fica True se QUALQUER dos chunks fundidos pedia quote.

    Devolve `(chunks, quote_flags)` com `len(chunks) == len(quote_flags)`.
    """
    blocos = re.split(r"\n\s*\n", texto.strip())
    out: list[str] = []
    flags: list[bool] = []
    for bruto in blocos:
        bloco_raw, quote = _strip_quote_prefix(bruto)
        bloco = _normaliza_bloco(bloco_raw)
        if not bloco:
            continue
        if len(bloco) <= MAX_CHARS:
            out.append(bloco)
            flags.append(quote)
        else:
            subdiv = _subdividir(bloco)
            out.extend(subdiv)
            flags.extend([quote] * len(subdiv))
    return _cap_bolhas(out, flags)


def _strip_quote_prefix(bloco: str) -> tuple[str, bool]:
    """Detecta e remove o marker `[quote]` no início do bloco."""
    if _QUOTE_PREFIX.match(bloco):
        return _QUOTE_PREFIX.sub("", bloco, count=1), True
    return bloco, False


def _normaliza_bloco(bloco: str) -> str:
    """Colapsa espaços/tabs POR LINHA, preserva \\n simples, descarta linhas vazias."""
    linhas = [" ".join(linha.split()) for linha in bloco.split("\n")]
    return "\n".join(linha for linha in linhas if linha)


def _subdividir(bloco: str) -> list[str]:
    """Fallback só quando o LLM não respeitou o \\n\\n e o bloco passou de 600 chars."""
    out: list[str] = []
    atual = ""
    for p in re.split(r"(?<=[.!?])\s+", bloco):
        if len(p) > MAX_CHARS:
            # sentença única estoura o cap: emite inteira (não corta no meio da frase)
            if atual:
                out.append(atual)
                atual = ""
            out.append(p)
            CHUNK_OVERSIZE.inc()
        elif len(atual) + len(p) + 1 > MAX_CHARS:
            out.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        out.append(atual)
    return out


def _cap_bolhas(out: list[str], flags: list[bool]) -> tuple[list[str], list[bool]]:
    if len(out) <= MAX_CHUNKS:
        return out, flags
    # funde o excedente no último chunk permitido — preserva conteúdo, não dropa.
    # flag do último vira True se QUALQUER dos fundidos pedia quote (preserva a intenção).
    cabeca, cauda = out[: MAX_CHUNKS - 1], out[MAX_CHUNKS - 1 :]
    cabeca_flags, cauda_flags = flags[: MAX_CHUNKS - 1], flags[MAX_CHUNKS - 1 :]
    return [*cabeca, "\n\n".join(cauda)], [*cabeca_flags, any(cauda_flags)]
