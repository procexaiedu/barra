"""Limpa do `barra_test` o resíduo COMMITADO pelo seed do harness e2e.

Por que existe: os testes `needs_db` rodam em ROLLBACK, mas o seed do harness
(`evals/harness.py:seedar`) COMMITA — cada corrida e2e deixa conversas/clientes/atendimentos
com o naming `test-chat-*`/`test-tel-*` no banco, e esse resíduo quebra os testes que fazem
aritmética sobre a janela viva (`test_reengajamento.py`, `test_rollback_watch_recorte_rig.py` —
modo de falha já registrado na memória do projeto). Rodar após cada rodada do loop de massa,
DEPOIS de o diário da rodada estar escrito (os transcritos são a cópia de inspeção; o banco não
precisa guardar nada).

Guarda-corpos:
  - Recusa DATABASE_URL: só aceita TEST_DATABASE_URL (nunca aponta para prod).
  - Filtro estrito pelo naming do harness (`test-chat-%` / `test-tel-%`); nada de data ou "hoje".
  - `--apagar` é opt-in; sem ele é dry-run (só conta).

Uso:
    uv run python -m evals.e2e.limpar_residuo            # dry-run
    uv run python -m evals.e2e.limpar_residuo --apagar   # apaga e commita
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import psycopg

_SQL_APAGAR = """
WITH conv AS (
    SELECT id FROM barravips.conversas WHERE evolution_chat_id LIKE 'test-chat-%%'
), atd AS (
    SELECT id FROM barravips.atendimentos WHERE conversa_id IN (SELECT id FROM conv)
),
_j  AS (DELETE FROM barravips.julgamentos_turno    WHERE conversa_id    IN (SELECT id FROM conv) RETURNING 1),
_ev AS (DELETE FROM barravips.envios_evolution     WHERE conversa_id    IN (SELECT id FROM conv)
                                                      OR atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_m  AS (DELETE FROM barravips.mensagens            WHERE conversa_id    IN (SELECT id FROM conv) RETURNING 1),
_b  AS (DELETE FROM barravips.bloqueios            WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_cp AS (DELETE FROM barravips.comprovantes_pix     WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_es AS (DELETE FROM barravips.escaladas            WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_e  AS (DELETE FROM barravips.eventos              WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_as AS (DELETE FROM barravips.atendimento_servicos WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_am AS (DELETE FROM barravips.atendimento_midias   WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_af AS (DELETE FROM barravips.atendimento_fetiches WHERE atendimento_id IN (SELECT id FROM atd) RETURNING 1),
_a  AS (DELETE FROM barravips.atendimentos         WHERE id             IN (SELECT id FROM atd) RETURNING 1),
_c  AS (DELETE FROM barravips.conversas            WHERE id             IN (SELECT id FROM conv) RETURNING 1)
SELECT (SELECT count(*) FROM _m)  AS mensagens,
       (SELECT count(*) FROM _a)  AS atendimentos,
       (SELECT count(*) FROM _c)  AS conversas
"""

# Clientes do harness que ficaram sem conversa/atendimento depois da varredura acima.
_SQL_CLIENTES = """
DELETE FROM barravips.clientes
 WHERE telefone LIKE 'test-tel-%%'
   AND NOT EXISTS (SELECT 1 FROM barravips.conversas   c WHERE c.cliente_id = clientes.id)
   AND NOT EXISTS (SELECT 1 FROM barravips.atendimentos a WHERE a.cliente_id = clientes.id)
"""

_SQL_CONTAR = """
SELECT (SELECT count(*) FROM barravips.conversas WHERE evolution_chat_id LIKE 'test-chat-%%'),
       (SELECT count(*) FROM barravips.clientes  WHERE telefone          LIKE 'test-tel-%%')
"""


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apagar", action="store_true", help="apaga de fato (sem = dry-run)")
    args = parser.parse_args()

    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        print("TEST_DATABASE_URL ausente — este utilitário só roda no barra_test.", file=sys.stderr)
        return 2
    url = url.replace("postgresql+psycopg://", "postgresql://")

    async with await psycopg.AsyncConnection.connect(url) as conn:
        cur = await conn.execute(_SQL_CONTAR)
        convs, clis = (await cur.fetchone()) or (0, 0)
        print(f"resíduo atual: {convs} conversas test-chat-*, {clis} clientes test-tel-*")
        if not args.apagar:
            print("dry-run (use --apagar para limpar).")
            return 0
        cur = await conn.execute(_SQL_APAGAR)
        row = await cur.fetchone()
        cur = await conn.execute(_SQL_CLIENTES)
        print(f"apagado: {row} + {cur.rowcount} clientes")
        await conn.commit()
        cur = await conn.execute(_SQL_CONTAR)
        print("restante:", await cur.fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
