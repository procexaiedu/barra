"""Seed de cardapio para a modelo eval (EVAL-12 jornadas conversacionais E2E).

`runner._seed_entidades` cria uma modelo MINIMA (sem programas/fetiches/disponibilidade), entao a
IA nao teria preco para cotar numa jornada simulada (BP3 de programas vazio -> "escale para
Fernando"). Esta funcao popula o cardapio da modelo recem-seedada referenciando o CATALOGO GLOBAL
real do banco (programas/duracoes/fetiches) por NOME -- robusto a IDs diferentes entre ambientes.

SQL puro parametrizado (psycopg3), na MESMA transacao do seed (sem commit; o caller da rollback).
Idempotente (ON CONFLICT DO NOTHING) por seguranca. needs_db -- nao roda offline.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

# Combinacoes programa x duracao do cardapio da modelo eval (por NOME do catalogo global) + preco.
# Espelha um cardapio plausivel (cf. infra/sql/0013_seed_ricardo.sql): Programa Completo em varias
# duracoes + Pernoite + um social. A IA cota a partir disto (prepare_context._carregar_bp3).
_PROGRAMAS: list[tuple[str, str, int]] = [
    ("Programa Completo", "1 hora", 900),
    ("Programa Completo", "2 horas", 1500),
    ("Programa Completo", "3 horas", 2100),
    ("Acompanhante Jantar", "3 horas", 1200),
    ("Pernoite", "Pernoite", 4000),
]

# Fetiches que a modelo FAZ (preco None = incluso; com preco = extra cotado "+R$X"). Por NOME do
# catalogo global. So o que existe hoje em barravips.fetiches.
_FETICHES: list[tuple[str, int | None]] = [
    ("Beijo Grego", None),
]


async def seed_cardapio(conn: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> None:
    """Popula modelo_programas + modelo_fetiches da modelo eval, por nome do catalogo global.

    Resolve os ids do catalogo por NOME no proprio INSERT (sem hardcode de UUID). Se um nome nao
    existir no catalogo, aquela linha simplesmente nao e inserida (SELECT vazio) -- a jornada segue
    com o cardapio parcial. Sem disponibilidade/bloqueio: modelo sem regra e reservavel sempre
    (CONTEXT.md "Disponibilidade"), o que basta para os cenarios de cotacao/qualificacao.
    """
    for programa_nome, duracao_nome, preco in _PROGRAMAS:
        await conn.execute(
            """
            INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco)
            SELECT %s, p.id, d.id, %s
              FROM barravips.programas p, barravips.duracoes d
             WHERE p.nome = %s AND d.nome = %s
            ON CONFLICT DO NOTHING
            """,
            (modelo_id, preco, programa_nome, duracao_nome),
        )
    for fetiche_nome, preco_fet in _FETICHES:
        await conn.execute(
            """
            INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco)
            SELECT %s, f.id, %s
              FROM barravips.fetiches f
             WHERE f.nome = %s
            ON CONFLICT DO NOTHING
            """,
            (modelo_id, preco_fet, fetiche_nome),
        )
