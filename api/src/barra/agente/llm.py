"""Montagem dos SystemMessages com cache_control (docs/agente/03 §1, §4, §5).

`build_system_messages` monta o prefixo `system` em blocos cacheados; o `cache_control`
vai em CONTENT BLOCKS no formato langchain-anthropic 1.x (decisão M0), não em
`additional_kwargs`. A factory do chat (`criar_chat_anthropic`) vive em `core/llm.py` —
aqui é só a montagem das mensagens.

Invariante (agente/CLAUDE.md): BP1 (persona+regras) e BP2 (FAQ) são GERAIS — byte-idênticos
entre todas as modelos. Função pura: mesma entrada → mesma saída (determinístico), sem I/O.
"""

from typing import Any

from langchain_core.messages import SystemMessage

# TTL mais longo precede o mais curto no array da Anthropic (1h antes de 5m): ttl_geral
# (BP1/BP2) não pode ser mais curto que ttl_modelo (BP3), senão a API rejeita (400). §1/§5.
_RANK = {"5m": 0, "1h": 1}


def _bloco_texto(texto: str, ttl: str | None) -> dict[str, Any]:
    """Content block de texto com cache_control no formato Anthropic 1.x (§5).

    ttl="1h" → cache_control {"type": "ephemeral", "ttl": "1h"}
    ttl="5m" → cache_control {"type": "ephemeral"} (default 5min, sem campo ttl)
    ttl=None → sem cache_control (bloco não cacheado)
    """
    bloco: dict[str, Any] = {"type": "text", "text": texto}
    if ttl is not None:
        cc: dict[str, Any] = {"type": "ephemeral"}
        if ttl != "5m":
            cc["ttl"] = ttl
        bloco["cache_control"] = cc
    return bloco


def build_system_messages(
    *,
    geral_md: str,
    faq_md: str,
    ttl_geral: str,
    modelo_md: str | None = None,
    ttl_modelo: str | None = None,
) -> list[SystemMessage]:
    """Blocos `system` cacheados, na ordem de render da Anthropic (§1, §4).

    P0/M0: 2 blocos GERAIS — BP1 (persona+regras) e BP2 (FAQ), byte-idênticos entre todas
    as modelos. O cache_control vai em content blocks (langchain-anthropic 1.x, decisão M0).

    `modelo_md`/`ttl_modelo` ficam reservados para o BP3 por-modelo (identidade + programas);
    o 3º bloco só é emitido a partir do M2 (M2-T1). A ordem é estável e CRÍTICA: gerais
    (BP1-BP2) antes do por-modelo (BP3), senão o prefixo deixa de ser global (§1, §4.3).

    Função pura: recebe markdown já renderizado, sem I/O nem `render_persona`/DB — mesma
    entrada produz saída byte-idêntica (invariante de prefixo, agente/CLAUDE.md).

    Validação de TTL (dispara quando o BP3 entrar): a Anthropic exige TTL mais longo ANTES
    do mais curto no array; como o BP3 vem depois de BP1/BP2, `ttl_geral` não pode ser mais
    curto que `ttl_modelo` (ex.: geral=5m + modelo=1h → 400). §1/§5.
    """
    if ttl_modelo is not None and _RANK[ttl_geral] < _RANK[ttl_modelo]:
        raise ValueError(
            f"ttl_geral ({ttl_geral}) não pode ser mais curto que ttl_modelo "
            f"({ttl_modelo}): viola a ordenação de TTL da Anthropic (03 §1/§5)"
        )
    return [
        SystemMessage(content=[_bloco_texto(geral_md, ttl_geral)]),  # BP1 — geral
        SystemMessage(content=[_bloco_texto(faq_md, ttl_geral)]),  # BP2 — geral
        # BP3 (modelo_md, ttl_modelo) entra no M2 (M2-T1) — não emitido no M0.
    ]
