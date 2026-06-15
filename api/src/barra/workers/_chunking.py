"""Chunking de texto da humanização (05 §2).

Divide o `AIMessage` final do turno em mensagens WhatsApp separadas: split por linha em
branco, preserva `\\n` simples dentro de um bloco, cap soft de 600 chars/chunk e cap de 6
bolhas. Consumido pelo coordenador antes de despachar `enviar_turno`.

Marker `[quote]` (no início de um bloco) sinaliza que aquela bolha responde, no WhatsApp,
a uma mensagem do cliente — o prefixo é removido do texto enviado e a posição entra na lista
paralela `quote_alvos`. Duas formas:
- `[quote]` puro → alvo `""` (a ÚLTIMA mensagem do cliente no turno, retrocompat);
- `[quote: trecho]` → alvo `"trecho"` (a mensagem do cliente que contém aquele trecho).
Quem casa o alvo → `evolution_message_id` é o coordenador. Posição sem marker → `None`.
"""

import re

from barra.core.metrics import CHUNK_OVERSIZE

MAX_CHARS = 600
MAX_CHUNKS = 6
# `[quote]` puro ou `[quote: trecho]` (case-insensitive). O grupo `trecho` é None no puro.
# `\s*` após `quote` tolera variação do LLM (`[quote ]`, `[quote : trecho]`) sem perder o alvo.
_QUOTE_PREFIX = re.compile(r"^\s*\[quote\s*(?::\s*(?P<trecho>[^\]]*?)\s*)?\]\s*", re.IGNORECASE)


def chunk_texto(texto: str) -> tuple[list[str], list[str | None]]:
    """Divide o texto da IA em mensagens WhatsApp separadas + alvo de quote por bolha.

    Regras:
    - separa por \\n\\n (uma ou mais linhas em branco) → uma mensagem por bloco;
    - bloco prefixado por `[quote]`/`[quote: trecho]` (case-insensitive) tem o prefixo
      removido e a posição vira o alvo em `quote_alvos`: `""` para `[quote]` puro (última
      mensagem do cliente), `"trecho"` para `[quote: trecho]`. Sem marker → `None`;
    - dentro de um bloco, PRESERVA \\n simples (lista de horários, endereço continuam
      multi-linha): colapsa só espaços/tabs por linha e descarta linhas vazias;
    - se um bloco passa de ~600 chars, sub-divide por sentença ("! ", "? ", ". ");
      uma sentença única > 600 sai INTEIRA (o cap é alvo, não garantia) e incrementa
      CHUNK_OVERSIZE — sinal de prompt que ignorou o \\n\\n instruído, não de erro de envio;
    - sub-bolhas herdam o alvo de quote do bloco que as gerou (caso raro, mas estável);
    - cap final de MAX_CHUNKS bolhas: o excedente é FUNDIDO no último chunk (anti-spam de
      40 mensagens + mantém o turno abaixo do job_timeout de 90s) e o alvo desse último
      chunk vira o PRIMEIRO alvo não-None dos chunks fundidos.

    Devolve `(chunks, quote_alvos)` com `len(chunks) == len(quote_alvos)`.
    """
    blocos = re.split(r"\n\s*\n", texto.strip())
    out: list[str] = []
    alvos: list[str | None] = []
    for bruto in blocos:
        bloco_raw, alvo = _strip_quote_prefix(bruto)
        bloco = _normaliza_bloco(bloco_raw)
        if not bloco:
            continue
        if len(bloco) <= MAX_CHARS:
            out.append(bloco)
            alvos.append(alvo)
        else:
            subdiv = _subdividir(bloco)
            out.extend(subdiv)
            alvos.extend([alvo] * len(subdiv))
    return _cap_bolhas(out, alvos)


def _strip_quote_prefix(bloco: str) -> tuple[str, str | None]:
    """Detecta e remove o marker `[quote]`/`[quote: trecho]` no início do bloco.

    Devolve `(texto_sem_prefixo, alvo)`: `None` sem marker, `""` para `[quote]` puro,
    `"trecho"` (normalizado por strip via regex) para `[quote: trecho]`.
    """
    m = _QUOTE_PREFIX.match(bloco)
    if not m:
        return bloco, None
    trecho = m.group("trecho")
    return _QUOTE_PREFIX.sub("", bloco, count=1), trecho if trecho else ""


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


def _cap_bolhas(out: list[str], alvos: list[str | None]) -> tuple[list[str], list[str | None]]:
    if len(out) <= MAX_CHUNKS:
        return out, alvos
    # funde o excedente no último chunk permitido — preserva conteúdo, não dropa.
    # alvo do último vira o PRIMEIRO alvo não-None dos fundidos (preserva a intenção).
    cabeca, cauda = out[: MAX_CHUNKS - 1], out[MAX_CHUNKS - 1 :]
    cabeca_alvos, cauda_alvos = alvos[: MAX_CHUNKS - 1], alvos[MAX_CHUNKS - 1 :]
    alvo_fundido = next((a for a in cauda_alvos if a is not None), None)
    return [*cabeca, "\n\n".join(cauda)], [*cabeca_alvos, alvo_fundido]
