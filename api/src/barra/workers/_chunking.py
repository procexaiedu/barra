"""Chunking de texto da humanização (05 §2).

Divide o `AIMessage` final do turno em mensagens WhatsApp separadas: split por linha em
branco, preserva `\\n` simples dentro de um bloco, cap soft de 600 chars/chunk e cap de 6
bolhas. Consumido pelo coordenador antes de despachar `enviar_turno`.
"""

import re

from barra.core.metrics import CHUNK_OVERSIZE

MAX_CHARS = 600
MAX_CHUNKS = 6


def chunk_texto(texto: str) -> list[str]:
    """Divide o texto da IA em mensagens WhatsApp separadas.

    Regras:
    - separa por \\n\\n (uma ou mais linhas em branco) → uma mensagem por bloco;
    - dentro de um bloco, PRESERVA \\n simples (lista de horários, endereço continuam
      multi-linha): colapsa só espaços/tabs por linha e descarta linhas vazias;
    - se um bloco passa de ~600 chars, sub-divide por sentença ("! ", "? ", ". ");
      uma sentença única > 600 sai INTEIRA (o cap é alvo, não garantia) e incrementa
      CHUNK_OVERSIZE — sinal de prompt que ignorou o \\n\\n instruído, não de erro de envio;
    - cap final de MAX_CHUNKS bolhas: o excedente é FUNDIDO no último chunk (anti-spam de
      40 mensagens + mantém o turno abaixo do job_timeout de 90s).
    """
    blocos = re.split(r"\n\s*\n", texto.strip())
    out: list[str] = []
    for bruto in blocos:
        bloco = _normaliza_bloco(bruto)
        if not bloco:
            continue
        if len(bloco) <= MAX_CHARS:
            out.append(bloco)
        else:
            out.extend(_subdividir(bloco))
    return _cap_bolhas(out)


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


def _cap_bolhas(out: list[str]) -> list[str]:
    if len(out) <= MAX_CHUNKS:
        return out
    # funde o excedente no último chunk permitido — preserva conteúdo, não dropa
    return [*out[: MAX_CHUNKS - 1], "\n\n".join(out[MAX_CHUNKS - 1 :])]
