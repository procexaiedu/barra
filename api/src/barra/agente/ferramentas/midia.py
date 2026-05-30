"""Tool de escrita `enviar_midia` (04 §3.3).

Anexa uma midia pre-aprovada da modelo (rotacao menos-recente-enviada por tag) ao turno
corrente. A IA so pede por tag — o sistema escolhe qual foto especifica, evitando repetir e
mantendo `midia_id` fora do LLM (elimina a classe de bug de transcricao de UUID).

`call_idx` e injetado pelo no `tools` (ordinal por-invocacao, doc 04 §3.3 nota "Por que
call_idx NAO migra para ToolRuntime"), nao pelo LLM: no replay reinicia em 0 -> ON CONFLICT
deduplica, sem reenvio. JAMAIS COUNT(*) no DB para esse indice — no replay COUNT(*) sobre as
linhas ja persistidas geraria `call_idx` novos e a deduplicacao falharia.

A selecao da foto roda ANTES de `_executar_idempotente`: no replay, o ON CONFLICT devolve o
`payload` cacheado (mesmo `midia_id`) e a re-selecao desta chamada e descartada -- replay-safe.

Imports de `ContextAgente` em runtime (top-level), nao TYPE_CHECKING: `ToolRuntime[ContextAgente]`
forca `get_type_hints(ContextAgente)` ao montar o args-schema; com forward refs nao resolviveis
o langchain engole o NameError em silencio e a tool envia args vazias ao LLM (memoria
`toolruntime_ctx_forward_refs`).
"""

from typing import Annotated, Any, Literal

from langchain_core.tools import InjectedToolArg, tool
from langgraph.prebuilt import ToolRuntime
from psycopg import AsyncConnection

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente

TagMidia = Literal["apresentacao", "corpo", "lifestyle", "evento"]


@tool
async def enviar_midia(
    tag: TagMidia,
    runtime: ToolRuntime[ContextAgente],
    legenda: str | None = None,
    tipo: Literal["foto", "video"] = "foto",
    call_idx: Annotated[int, InjectedToolArg] = 0,
) -> str:
    """Anexa uma foto pre-aprovada da modelo (escolhida pelo sistema) a resposta do turno.

    Args:
        tag: categoria da foto. O sistema escolhe QUAL foto da tag (rotacao:
             menos-recente-enviada), evitando repetir — voce nao escolhe foto especifica.
        legenda: opcional, texto curto que aparece junto da midia no WhatsApp.
        tipo: "foto" (default) ou "video". Mande fotos primeiro; use "video" depois,
              apresentando-o como exclusivo/ao vivo na legenda (estrategia foto->video, 05 §5).
              Video vai como visualizacao unica quando a plataforma suportar (pre-req, 05 §5).

    Pode ser chamada varias vezes no mesmo turno (ex.: 2 fotos da mesma tag);
    as midias sao enviadas apos o texto.
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        ja_no_turno = await _midias_do_turno(conn, turno_id)

        # NULLS FIRST coloca midia nunca enviada no topo (preferencia por novidade);
        # `created_at` desempata. `NOT (id = ANY(...))` exclui midias ja anexadas neste turno
        # — duas chamadas da mesma tag no MESMO turno entregam fotos diferentes.
        res = await conn.execute(
            """
            SELECT id, object_key
              FROM barravips.modelo_midia
             WHERE modelo_id = %s AND tag = %s AND tipo = %s AND aprovada = true
               AND NOT (id = ANY(%s::uuid[]))
             ORDER BY ultimo_envio_em NULLS FIRST, created_at
             LIMIT 1
            """,
            (modelo_id, tag, tipo, ja_no_turno),
        )
        escolhida = await res.fetchone()
        if escolhida is None:
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("enviar_midia", "midia_indisponivel").inc()
            return f"ERRO: nenhuma midia tipo '{tipo}' disponivel para a tag '{tag}'."

        await _executar_idempotente(
            conn,
            turno_id,
            "enviar_midia",
            call_idx,
            payload={
                "midia_id": str(escolhida["id"]),
                "tag": tag,
                "tipo": tipo,
                "legenda": legenda or "",
            },
            executor=_registrar_envio_midia,
        )

    return f"{tipo.capitalize()} de '{tag}' anexada (enviada apos o texto)."


async def _midias_do_turno(conn: AsyncConnection[Any], turno_id: str) -> list[str]:
    """IDs das midias ja anexadas a este turno (lidas de `tool_calls`).

    Replay-safe: a 1a execucao grava `midia_id` no payload de tool_calls; uma 2a chamada
    de `enviar_midia` (na mesma ainvoke OU em retry/replay) le esses IDs aqui e os exclui
    da selecao — garante midia diferente em cada chamada do MESMO turno, e o ON CONFLICT
    do `_executar_idempotente` cuida do replay.
    """
    res = await conn.execute(
        """
        SELECT payload->>'midia_id' AS midia_id
          FROM barravips.tool_calls
         WHERE turno_id = %s AND tool_name = 'enviar_midia'
        """,
        (turno_id,),
    )
    rows = await res.fetchall()
    return [r["midia_id"] for r in rows if r.get("midia_id")]


async def _registrar_envio_midia(
    conn: AsyncConnection[Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Marca `ultimo_envio_em = now()` na midia escolhida. Roda 1x por chave
    `(turno_id, "enviar_midia", call_idx)` — o ON CONFLICT do `_executar_idempotente`
    nao a re-executa no replay."""
    await conn.execute(
        "UPDATE barravips.modelo_midia SET ultimo_envio_em = now() WHERE id = %s",
        (payload["midia_id"],),
    )
    return {"midia_id": payload["midia_id"], "tag": payload["tag"], "tipo": payload["tipo"]}
