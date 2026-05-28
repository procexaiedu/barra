"""Montagem dos SystemMessages e tools com cache_control (docs/agente/03 §1, §4, §5).

`build_system_messages` monta o prefixo `system` em blocos cacheados; `build_tools_para_bind`
converte o catálogo de tools no formato dict da Anthropic com `cache_control` na ÚLTIMA tool
(`docs.claude.com/.../tool-use-with-prompt-caching`: "Place cache_control on the last tool ...
This caches the entire tool-definitions prefix"). O `cache_control` vai em CONTENT BLOCKS no
formato langchain-anthropic 1.x (decisão M0), não em `additional_kwargs`. A factory do chat
(`criar_chat_anthropic`) vive em `core/llm.py` — aqui é só a montagem.

Invariante (agente/CLAUDE.md): tools (posição 0) e BP1 (persona+regras) e BP2 (FAQ) são GERAIS
— byte-idênticos entre todas as modelos. Funções puras: mesma entrada → mesma saída sem I/O.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from langchain_anthropic import convert_to_anthropic_tool
from langchain_anthropic.chat_models import AnthropicTool
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool

# TTL mais longo precede o mais curto no array da Anthropic (1h antes de 5m): ttl_tools (cabeça
# do prefixo) ≥ ttl_geral (BP1/BP2) ≥ ttl_modelo (BP3), senão a API rejeita (400). §1/§5.
_RANK = {"5m": 0, "1h": 1}


def _cache_control(ttl: str) -> dict[str, str]:
    """`cache_control` no formato Anthropic 1.x (§5).

    ttl="1h" → {"type": "ephemeral", "ttl": "1h"}
    ttl="5m" → {"type": "ephemeral"}  (default; sem campo ttl)
    """
    cc: dict[str, str] = {"type": "ephemeral"}
    if ttl != "5m":
        cc["ttl"] = ttl
    return cc


def _bloco_texto(texto: str, ttl: str | None) -> dict[str, Any]:
    """Content block de texto. `ttl=None` → bloco sem cache_control."""
    bloco: dict[str, Any] = {"type": "text", "text": texto}
    if ttl is not None:
        bloco["cache_control"] = _cache_control(ttl)
    return bloco


def build_system_messages(
    *,
    geral_md: str,
    ttl_geral: str,
    modelo_md: str | None = None,
    ttl_modelo: str | None = None,
) -> list[SystemMessage]:
    """Blocos `system` cacheados, na ordem de render da Anthropic (§1, §4).

    `geral_md` (persona+regras+FAQ fundidos pelo caller) é GERAL — byte-idêntico entre todas as
    modelos. Quando `modelo_md` é passado (M2-T1+), emite um 2º bloco por-modelo (identidade +
    programas). A ordem é estável e CRÍTICA: geral antes do por-modelo, senão o prefixo deixa de
    ser global (§1, §4.3). O cache_control vai em content blocks (langchain-anthropic 1.x).

    **Fusão BP_GERAL** (decisão posterior ao M0): persona+regras+FAQ entram num bloco system
    único — antes eram 2 separados (BP1+BP2), mas tinham TTL/conteúdo/cadência idênticos e
    consumiam 2 dos 4 breakpoints disponíveis. Fundir libera 1 breakpoint p/ o cache da janela
    de mensagens (`marcar_cache_na_penultima`).

    Função pura: recebe markdown já renderizado, sem I/O nem `render_persona`/DB — mesma
    entrada produz saída byte-idêntica (invariante de prefixo, agente/CLAUDE.md).

    Validação de TTL: a Anthropic exige TTL mais longo ANTES do mais curto no array; como o
    bloco por-modelo vem depois do geral, `ttl_geral` não pode ser mais curto que `ttl_modelo`
    (ex.: geral=5m + modelo=1h → 400). §1/§5.
    """
    if ttl_modelo is not None and _RANK[ttl_geral] < _RANK[ttl_modelo]:
        raise ValueError(
            f"ttl_geral ({ttl_geral}) não pode ser mais curto que ttl_modelo "
            f"({ttl_modelo}): viola a ordenação de TTL da Anthropic (03 §1/§5)"
        )
    mensagens = [
        SystemMessage(content=[_bloco_texto(geral_md, ttl_geral)]),  # BP_GERAL
    ]
    if modelo_md is not None:
        mensagens.append(SystemMessage(content=[_bloco_texto(modelo_md, ttl_modelo)]))  # BP_MODELO
    return mensagens


def marcar_cache_na_penultima(
    mensagens: list[BaseMessage], *, ttl: str
) -> list[BaseMessage]:
    """Aplica `cache_control` na PENÚLTIMA mensagem da janela (BP_JANELA, doc oficial Anthropic
    `prompt-caching` §"Multi-turn conversations").

    Por que penúltima e não última: a última mensagem do turno carrega o **contexto dinâmico**
    + reminder anti-drift (volátil — muda todo turno), então jamais entra em cache. A penúltima
    é a primeira do prefixo "estável" da janela, vista DOS DOIS LADOS dos turnos N e N+1: a
    "última do turno N" vira a "antepenúltima do turno N+1" e o lookback de 20 blocos da
    Anthropic acha o write anterior, lê os tokens cacheados e estende com 2 novos blocos.

    Append-only invariant (pré-req do hit): a janela é `ORDER BY created_at, id` (uuidv7
    time-ordered) — mensagens nunca são editadas em retrospectiva, só inseridas no fim. Logo
    o prefixo até a antepenúltima do turno N+1 bate byte-a-byte com o prefixo até a penúltima
    do turno N — o cache write de N é hit em N+1.

    Janela < 2 mensagens (cliente novo): sem cache (no-op). Sem ganho perdido — o turno tem
    poucos blocos pra cachear de toda forma.

    `ttl` ≥ `ttl_modelo` (que ≥ `ttl_geral` no prefixo) — regra "TTL maior antes do menor" da
    Anthropic. No P0 usar `cache_ttl_modelo` (alinha com o BP_MODELO que vem logo antes).
    """
    if len(mensagens) < 2:
        return mensagens
    penult = mensagens[-2]
    # `content` pode ser str (caminho comum) ou já content blocks (defensivo: no-op p/ não dobrar
    # cache_control nem perder estrutura existente).
    if not isinstance(penult.content, str):
        return mensagens
    novo = type(penult)(
        content=[
            {
                "type": "text",
                "text": penult.content,
                "cache_control": _cache_control(ttl),
            }
        ],
        id=penult.id,
    )
    return [*mensagens[:-2], novo, mensagens[-1]]


def build_tools_para_bind(
    tools: Sequence[BaseTool],
    *,
    ttl: str,
    strict_tools: Collection[str] = (),
    exemplos: Mapping[str, list[dict[str, Any]]] | None = None,
) -> list[AnthropicTool]:
    """Converte BaseTool→dict Anthropic e injeta cache_control na ÚLTIMA tool (BP_TOOLS).

    1. `cache_control` na ÚLTIMA tool (doc oficial Anthropic `tool-use-with-prompt-caching`):
       "Place cache_control on the last tool in your tools array. This caches the entire
       tool-definitions prefix." Sem isso, o array `tools` é input fresh todo turno (1.0×) em vez
       de cache read (0.1×); breakpoints do `system` NÃO cobrem tools retroativamente — cada
       nível é segmento hierárquico independente (tools → system → messages).

    2. `strict_tools` (PER-TOOL; doc oficial `strict-tool-use` + 04 §7): constrained decoding +
       grammar cache 24h, aplicado SÓ às tools cujo nome está no conjunto. Por-tool e não global
       porque o limite "Schema is too complex" da Anthropic é somado em TODAS as tools strict da
       request — ligar nas 3 que não precisam (consultar_agenda/pedir_pix/enviar_midia) pagaria
       latência de compilação à toa. P0: `STRICT_TOOLS = {"escalar"}` (`ferramentas/__init__.py`)
       — enum de roteamento + 2 strings, cabe nos limites. `_sanitizar_para_strict` remove o que o
       strict não aceita (minimum/maximum, min/maxLength, min/maxItems, pattern, anyOf-null).
       PHI-safe: nenhum schema/enum/property name carrega dado de cliente (04 §7).

    3. `exemplos` (per-tool, opcional; doc oficial `tool-use` campo `input_examples`): exemplos de
       input válidos por nome de tool, injetados em `input_examples` da tool. Ajudam tools
       complexas (escalar/registrar_extracao) sem custo de runtime — vivem no segmento `tools`
       cacheado (pago 1x). Cada exemplo DEVE validar contra o `input_schema` enviado (senão 400).

    `tools` é GERAL (byte-idêntico p/ todas as modelos — agente/CLAUDE.md, 03 §1): ordem
    congelada, conversor determinístico. Lista vazia → []; `bind_tools([])` é no-op no chat.

    Mudança em qualquer tool invalida cache de tools E system E messages (hierarquia, doc
    oficial). `ttl` deve ser ≥ ttl_geral (TTL maior antes do menor no array final, §1/§5).
    """
    if not tools:
        return []
    converted = [convert_to_anthropic_tool(t) for t in tools]
    for tool_def in converted:
        nome = tool_def["name"]
        if nome in strict_tools:
            tool_def["strict"] = True
            # langchain envolve `payload: PydModel` em `{"payload": <schema>}` mas NAO propaga
            # `additionalProperties: false` para o top-level. A Anthropic exige em strict mode.
            schema = tool_def.get("input_schema") or {}
            schema.setdefault("additionalProperties", False)
            _sanitizar_para_strict(schema)
        if exemplos and nome in exemplos:
            tool_def["input_examples"] = list(exemplos[nome])
    converted[-1]["cache_control"] = _cache_control(ttl)
    return converted


def _sanitizar_para_strict(schema: Any) -> None:
    """Remove campos JSON Schema que o strict mode da Anthropic ainda nao aceita, recursivamente.

    Hoje, em 2026-05:
    - `minimum`/`maximum` (e `exclusive*`) em number/integer: 400 "properties maximum, minimum
      are not supported".
    - `minLength`/`maxLength` em string: idem nao suportados pelo strict (doc oficial
      `#json-schema-limitations`). O Pydantic gera p/ `Field(min_length=..., max_length=...)`
      (ex.: `resumo_operacional`/`acao_esperada` do `escalar`). Era o blocker do strict no
      `escalar`. Removidos aqui; a validacao real continua no Pydantic post-call.
    - `minItems`/`maxItems` em array: strict so aceita `minItems` 0/1 e nao aceita `maxItems`;
      removidos por seguranca (perde so a "dica" pro grammar; Pydantic valida de verdade).
    - `pattern` com regex avancada (lookahead `(?!...)`, lookbehind, etc.): 400 "Invalid regex
      in pattern field". O Pydantic gera regex desse tipo automaticamente para `Decimal | None`
      e similares. Solucao conservadora: remover TODOS os patterns — a validacao real ja roda
      no Pydantic post-call (server-side), entao perdemos so a "dica" pro grammar do LLM.
    - `anyOf` com `{type: null}`: cada campo `X | None = None` no Pydantic gera
      `anyOf: [{schema X}, {type: null}]`. 12+ desses no `registrar_extracao` estouravam o
      400 "Schema is too complex". O LLM continua podendo OMITIR o campo (nao esta em
      `required`); o que se perde e a possibilidade de passar `null` EXPLICITO — que ninguem
      usava (omissao e o caminho idiomatico). Limpa o `default: null` orfao tambem.

    Doc oficial: `build-with-claude/structured-outputs#json-schema-limitations`. Quando a
    Anthropic relaxar essas restricoes, simplificar/remover esta funcao.
    """
    if isinstance(schema, dict):
        if schema.get("type") in ("number", "integer"):
            schema.pop("minimum", None)
            schema.pop("maximum", None)
            schema.pop("exclusiveMinimum", None)
            schema.pop("exclusiveMaximum", None)
        # string/array: min/maxLength e min/maxItems nao sao suportados pelo strict.
        # `pop(..., None)` e no-op quando ausente, entao nao precisa checar o `type` antes.
        schema.pop("minLength", None)
        schema.pop("maxLength", None)
        schema.pop("minItems", None)
        schema.pop("maxItems", None)
        schema.pop("pattern", None)
        _desencapsular_anyof_null(schema)
        for value in schema.values():
            _sanitizar_para_strict(value)
    elif isinstance(schema, list):
        for item in schema:
            _sanitizar_para_strict(item)


def _desencapsular_anyof_null(schema: dict[str, Any]) -> None:
    """Remove `{type: null}` de `anyOf`; se sobrar 1 elemento, desencapsula no nivel superior.

    Antes:  {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}
    Depois: {"type": "string"}  (default null orfao removido junto)

    Mantem o `description`/`title` do campo (estao no nivel pai do anyOf, nao dentro dele).
    Idempotente: se nao tem null no anyOf, no-op.
    """
    options = schema.get("anyOf")
    if not isinstance(options, list):
        return
    non_null = [opt for opt in options if not (isinstance(opt, dict) and opt.get("type") == "null")]
    if len(non_null) == len(options):
        return  # nao tinha null — no-op
    if len(non_null) == 1:
        # 1 unico tipo restante: desencapsula merging no nivel pai (preservando description/title).
        schema.pop("anyOf")
        for k, v in non_null[0].items():
            schema.setdefault(k, v)
    else:
        schema["anyOf"] = non_null
    # `default: null` perde validade quando null nao e mais um tipo aceito.
    if schema.get("default") is None and "default" in schema:
        schema.pop("default")
