"""Backfill das flags de disciplina (padrão A2) materializadas na migration
20260723120000_atendimentos_flags_disciplina.sql.

Contexto: a partir da migration, `prepare_context` LÊ `atendimentos.n_contrapropostas`/
`dia_sondado_em`/`book_enviado_em` em vez de reescanear as falas da IA por turno; o carimbo passa a
ser no write-time (workers/envio.py). Atendimentos abertos ANTES do deploy nasceriam com as colunas
no default (0/NULL) e poderiam re-ofertar desconto / re-sondar o dia / reenviar book. Este script
recomputa as 3 flags a partir de `mensagens` (direcao='ia') para cada atendimento NÃO-terminal, com
os MESMOS detectores de agente/_disciplina.py (o de contraproposta tem lookbehind, não roda em SQL
puro — por isso o backfill é Python, não uma migration de dados).

Idempotente: recomputa do zero (não incrementa em cima do valor atual). First-write-wins dos
timestamps = created_at da 1ª mensagem que casa.

⚠️ ESCREVE NO BANCO APONTADO POR --dsn. Rodar contra produção só com autorização explícita
(CLAUDE.md §0). Use --dry-run primeiro (só lista, faz ROLLBACK).

Uso:
    uv run python ../scripts/backfill_flags_disciplina.py --dsn "$PROD_DSN" --dry-run
    uv run python ../scripts/backfill_flags_disciplina.py --dsn "$PROD_DSN"
    # opcional: --modelo <uuid> restringe a uma modelo.
"""

import argparse
import asyncio
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._disciplina import contem_contraproposta, contem_sondagem_dia

# Não-terminais: onde a disciplina ainda importa (negociação viva). Fechado/Perdido ficam de fora.
_ESTADOS_NAO_TERMINAIS = (
    "Novo",
    "Triagem",
    "Qualificado",
    "Aguardando_confirmacao",
    "Confirmado",
    "Em_execucao",
)


def _computar_flags(falas: list[dict[str, Any]]) -> tuple[int, Any, Any]:
    """(n_contrapropostas, dia_sondado_em, book_enviado_em) a partir das falas da IA em ordem."""
    n = 0
    dia_sondado_em = None
    book_enviado_em = None
    for f in falas:
        conteudo = f["conteudo"] or ""
        if contem_contraproposta(conteudo):
            n += 1
        if dia_sondado_em is None and contem_sondagem_dia(conteudo):
            dia_sondado_em = f["created_at"]  # 1ª sondagem (first-write-wins)
        if book_enviado_em is None and f["tipo"] == "imagem":
            book_enviado_em = f["created_at"]  # 1º book
    return n, dia_sondado_em, book_enviado_em


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--modelo", help="modelo_id (uuid) — opcional, restringe a uma modelo")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = await AsyncConnection.connect(args.dsn, row_factory=dict_row)
    try:
        async with conn.transaction():
            res = await conn.execute(
                """
                SELECT id, numero_curto, estado::text AS estado
                  FROM barravips.atendimentos
                 WHERE estado = ANY(%s::barravips.estado_atendimento_enum[])
                   AND (%s::uuid IS NULL OR modelo_id = %s::uuid)
                 ORDER BY created_at
                 FOR UPDATE
                """,
                (list(_ESTADOS_NAO_TERMINAIS), args.modelo, args.modelo),
            )
            atendimentos = await res.fetchall()

            mudancas = 0
            for a in atendimentos:
                falas_res = await conn.execute(
                    """
                    SELECT conteudo, tipo, created_at
                      FROM barravips.mensagens
                     WHERE atendimento_id = %s AND direcao = 'ia'
                     ORDER BY created_at
                    """,
                    (a["id"],),
                )
                falas = await falas_res.fetchall()
                n, dia, book = _computar_flags(falas)
                if n == 0 and dia is None and book is None:
                    continue
                mudancas += 1
                print(
                    f"#{a['numero_curto']} {a['id']} estado={a['estado']}: "
                    f"n_contrapropostas={n} dia_sondado={'sim' if dia else 'não'} "
                    f"book={'sim' if book else 'não'}"
                )
                if not args.dry_run:
                    await conn.execute(
                        """
                        UPDATE barravips.atendimentos
                           SET n_contrapropostas = %s,
                               dia_sondado_em = %s,
                               book_enviado_em = %s
                         WHERE id = %s
                        """,
                        (n, dia, book, a["id"]),
                    )

            if args.dry_run:
                print(f"{mudancas} atendimentos teriam flags (dry-run) — nada alterado.")
                await conn.rollback()
            else:
                print(f"{mudancas} atendimentos com flags carimbadas de {len(atendimentos)} lidos.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
