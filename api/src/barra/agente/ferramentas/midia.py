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

from langchain_core.tools import InjectedToolArg, ToolException, tool
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
    """Anexa uma mídia pré-aprovada da modelo (foto ou vídeo, escolhida pelo sistema) à resposta
    do turno.

    Use quando o cliente quer te ver, pede mais fotos ou quando uma foto ajuda a fechar a venda;
    siga sua conduta de mídia (nas suas regras) para a ordem foto→vídeo. NÃO mande na saudação
    nem antes de qualquer qualificação.

    Args:
        tag: categoria da mídia. O sistema escolhe QUAL item da tag (rotação:
             menos-recente-enviada), evitando repetir — você não escolhe o item específico.
        legenda: opcional, texto curto que aparece junto da mídia no WhatsApp.
        tipo: "foto" (default) ou "video" — qual mídia anexar. O vídeo vai como visualização
              única quando a plataforma suportar.

    Pode ser chamada várias vezes no mesmo turno (ex.: 2 fotos da mesma tag);
    as mídias são enviadas após o texto.
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    # `conn.transaction()` explicito: o pool do worker e autocommit=True (core/db.py), entao sem ele
    # cada execute commitaria sozinho e o lock de linha da SELECT (abaixo) soltaria antes do INSERT.
    # A transacao segura o lock da selecao ate `_executar_idempotente` gravar — serializa duas
    # chamadas concorrentes da mesma tag. O `_executar_idempotente` abre `conn.transaction()` aninhado
    # (vira SAVEPOINT), inalterado.
    async with pool.connection() as conn, conn.transaction():
        ja_no_turno = await _midias_do_turno(conn, turno_id)

        # NULLS FIRST coloca midia nunca enviada no topo (preferencia por novidade);
        # `created_at` desempata. `NOT (id = ANY(...))` exclui midias ja anexadas neste turno
        # — duas chamadas da mesma tag no MESMO turno entregam fotos diferentes.
        # `FOR UPDATE SKIP LOCKED`: duas `enviar_midia` da MESMA tag no mesmo turno rodam em paralelo
        # (asyncio.gather do ToolNode `_afunc`) e, sem lock, AMBAS leem `ja_no_turno` vazio e escolhem
        # a MESMA foto (TOCTOU) -> cliente recebe a foto repetida. O lock de linha serializa: a 1a
        # trava sua foto, a 2a PULA a travada (SKIP LOCKED) e pega a proxima distinta. Esgotou (so
        # fotos travadas / nenhuma sobrando) -> None, mesmo caminho de "indisponivel".
        res = await conn.execute(
            """
            SELECT id, object_key
              FROM barravips.modelo_midia
             WHERE modelo_id = %s AND tag = %s AND tipo = %s AND aprovada = true
               AND NOT (id = ANY(%s::uuid[]))
             ORDER BY ultimo_envio_em NULLS FIRST, created_at
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (modelo_id, tag, tipo, ja_no_turno),
        )
        escolhida = await res.fetchone()
        if escolhida is None:
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("enviar_midia", "midia_indisponivel").inc()
            raise ToolException(f"ERRO: nenhuma mídia tipo '{tipo}' disponível para a tag '{tag}'.")

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

    return f"{tipo.capitalize()} de '{tag}' anexada (enviada após o texto)."


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
