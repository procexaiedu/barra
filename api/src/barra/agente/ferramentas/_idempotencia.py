"""Idempotencia das tools de escrita do agente (04 §3, 02 §8.2).

Cada chamada de tool de escrita grava em `barravips.tool_calls` com a chave
`(turno_id, tool_name, call_idx)`. Um retry do ARQ ou replay do turno re-executa a
tool com a MESMA chave: aqui o `ON CONFLICT` deduplica e o efeito colateral roda
no maximo UMA vez — a 2a execucao devolve o `resultado` persistido da 1a.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection

# Funcao que aplica o efeito da tool e devolve o resultado a persistir/devolver.
Executor = Callable[[AsyncConnection[Any], dict[str, Any]], Awaitable[dict[str, Any]]]


async def _executar_idempotente(
    conn: AsyncConnection[Any],
    turno_id: str,
    tool_name: str,
    call_idx: int,
    payload: dict[str, Any],
    executor: Executor,
) -> dict[str, Any]:
    """Roda `executor(conn, payload)` no maximo uma vez por `(turno_id, tool_name, call_idx)`.

    Numa transacao (SAVEPOINT, se ja houver uma aberta), tenta inserir a chave:
    - ja existia (conflito) -> devolve o `resultado` anterior SEM rodar o executor;
    - inseriu -> roda o executor, grava o `resultado` e o devolve.

    INSERT/executor/UPDATE sao atomicos: se a linha existe, o `resultado` ja esta gravado.
    `payload`/`resultado` vao como `%s::jsonb` com `json.dumps` — psycopg3 nao adapta
    dict cru para jsonb (memoria jsonb_param_psycopg).
    """
    async with conn.transaction():
        res = await conn.execute(
            """
            INSERT INTO barravips.tool_calls (turno_id, tool_name, call_idx, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (turno_id, tool_name, call_idx) DO NOTHING
            RETURNING turno_id
            """,
            (turno_id, tool_name, call_idx, json.dumps(payload)),
        )
        if await res.fetchone() is None:
            # Chave ja existe — devolve o resultado da 1a execucao, sem reexecutar.
            res = await conn.execute(
                "SELECT resultado FROM barravips.tool_calls"
                " WHERE turno_id = %s AND tool_name = %s AND call_idx = %s",
                (turno_id, tool_name, call_idx),
            )
            linha = await res.fetchone()
            assert linha is not None  # acabamos de detectar o conflito: a linha existe
            anterior: dict[str, Any] = linha["resultado"]
            return anterior

        resultado = await executor(conn, payload)
        await conn.execute(
            "UPDATE barravips.tool_calls SET resultado = %s::jsonb"
            " WHERE turno_id = %s AND tool_name = %s AND call_idx = %s",
            (json.dumps(resultado), turno_id, tool_name, call_idx),
        )
        return resultado
