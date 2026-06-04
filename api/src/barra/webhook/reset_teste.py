"""Comando de teste `#reset` — zera o estado transacional de uma modelo de teste.

Apaga conversas, mensagens, atendimentos, bloqueios, escaladas, eventos, envios/cards e
clientes que ficarem órfãos de UMA modelo (resolvida por `evolution_instance_id`), deixando
cadastro (modelos/programas/disponibilidade) e as outras modelos intactos — para recomeçar
um teste de ponta a ponta do zero.

Fonte única dos DELETEs (`DELETES_RESET`): reaproveitada pelo `scripts/reset_agente.py` (CLI)
e pelo gatilho `#reset` no grupo (`webhook/routes.py`, com gate em
`settings.reset_teste_instances`). Escopo decidido em 2026-05-29 — ver o docstring do script
para o racional completo (`tool_calls` não é tocado; ids do Redis limpos à parte).
"""

from typing import Any

from psycopg import AsyncConnection

# Ordem filhos -> pais. (rótulo, SQL). Subquery por modelo_id evita materializar listas grandes;
# `clientes` é tratado à parte (precisa dos ids capturados antes dos deletes). `envios_evolution`
# recebe modelo_id DUAS vezes (filtra por conversa OU atendimento).
DELETES_RESET: list[tuple[str, str]] = [
    (
        "atendimento_servicos",
        "DELETE FROM barravips.atendimento_servicos WHERE atendimento_id IN "
        "(SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "atendimento_midias",
        "DELETE FROM barravips.atendimento_midias WHERE atendimento_id IN "
        "(SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "comprovantes_pix",
        "DELETE FROM barravips.comprovantes_pix WHERE atendimento_id IN "
        "(SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "escaladas",
        "DELETE FROM barravips.escaladas WHERE atendimento_id IN "
        "(SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "eventos",
        "DELETE FROM barravips.eventos WHERE atendimento_id IN "
        "(SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "envios_evolution",
        "DELETE FROM barravips.envios_evolution WHERE "
        "conversa_id IN (SELECT id FROM barravips.conversas WHERE modelo_id = %s) "
        "OR atendimento_id IN (SELECT id FROM barravips.atendimentos WHERE modelo_id = %s)",
    ),
    (
        "mensagens",
        "DELETE FROM barravips.mensagens WHERE conversa_id IN "
        "(SELECT id FROM barravips.conversas WHERE modelo_id = %s)",
    ),
    ("bloqueios", "DELETE FROM barravips.bloqueios WHERE modelo_id = %s"),
    ("atendimentos", "DELETE FROM barravips.atendimentos WHERE modelo_id = %s"),
    ("conversas", "DELETE FROM barravips.conversas WHERE modelo_id = %s"),
]


async def resetar_modelo(conn: AsyncConnection[Any], instance_id: str) -> dict[str, Any] | None:
    """Zera o estado transacional da modelo dona de `instance_id` + clientes órfãos.

    Roda numa transação única (atômico). Devolve `{modelo_id, conversa_ids, atendimento_ids,
    contagens}` ou `None` se a instância não resolve nenhuma modelo. Os ids voltam para a
    limpeza do Redis (chaves de lock/turno por conversa/atendimento).
    """
    cur = await conn.execute(
        "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
        (instance_id,),
    )
    modelo = await cur.fetchone()
    if modelo is None:
        return None
    modelo_id = modelo["id"]

    async with conn.transaction():
        # Capturar ANTES dos deletes: ids p/ o Redis e clientes candidatos a órfão.
        cur = await conn.execute(
            "SELECT id FROM barravips.conversas WHERE modelo_id = %s", (modelo_id,)
        )
        conversa_ids = [r["id"] for r in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT id FROM barravips.atendimentos WHERE modelo_id = %s", (modelo_id,)
        )
        atendimento_ids = [r["id"] for r in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT cliente_id FROM barravips.conversas WHERE modelo_id = %s "
            "UNION SELECT cliente_id FROM barravips.atendimentos WHERE modelo_id = %s",
            (modelo_id, modelo_id),
        )
        cliente_ids = [r["cliente_id"] for r in await cur.fetchall()]

        contagens: dict[str, int] = {}
        for rotulo, sql in DELETES_RESET:
            params = (modelo_id, modelo_id) if rotulo == "envios_evolution" else (modelo_id,)
            cur = await conn.execute(sql, params)
            contagens[rotulo] = cur.rowcount

        # Clientes órfãos: dos vinculados à modelo, os que não têm mais nenhuma conversa/
        # atendimento (com qualquer modelo) após os deletes acima — preserva o cliente
        # cross-modelo e os seeds do mapa.
        if cliente_ids:
            cur = await conn.execute(
                "DELETE FROM barravips.clientes c WHERE c.id = ANY(%s) "
                "AND NOT EXISTS (SELECT 1 FROM barravips.conversas WHERE cliente_id = c.id) "
                "AND NOT EXISTS (SELECT 1 FROM barravips.atendimentos WHERE cliente_id = c.id)",
                (cliente_ids,),
            )
            contagens["clientes_orfaos"] = cur.rowcount

    return {
        "modelo_id": modelo_id,
        "conversa_ids": conversa_ids,
        "atendimento_ids": atendimento_ids,
        "contagens": contagens,
    }


async def limpar_redis_modelo(arq: Any, conversa_ids: list[Any], atendimento_ids: list[Any]) -> int:
    """SCAN+DEL best-effort das chaves Redis pelos ids da modelo (locks de conversa, turno
    coalescido). Sem FLUSHDB — não toca a fila ARQ das outras modelos. Devolve o nº de chaves
    apagadas. `arq` é o pool ARQ (redis.asyncio.Redis); `None` = no-op (dev sem Redis)."""
    if arq is None:
        return 0
    ids = [str(i) for i in (*conversa_ids, *atendimento_ids)]
    chaves: set[Any] = set()
    for ident in ids:
        async for chave in arq.scan_iter(match=f"*{ident}*", count=500):
            chaves.add(chave)
    if chaves:
        await arq.delete(*chaves)
    return len(chaves)
