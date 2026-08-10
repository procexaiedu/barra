"""CLI do relatorio de graduacao -- `make graduacao` (-> `python -m barra.dominio.graduacao`).

READ-ONLY: so SELECT, e a transacao termina em ROLLBACK. Aponta para o `DATABASE_URL` do
ambiente; contra producao continua sendo leitura (nao cai na regra de escrita/deploy do §0), mas
o cabecalho imprime o host para ninguem ler numero de um banco e achar que e de outro.

Uso:
    make graduacao                          # janela derivada (1o turno da IA p/ cliente real)
    make graduacao ARGS="--desde 2026-08-01"
    make graduacao ARGS="--json"            # DTO cru, para diff/arquivo
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings

from . import service
from .relatorio import renderizar


def _parse_desde(valor: str) -> datetime:
    """Aceita `YYYY-MM-DD` ou ISO completo. Naive vira UTC (o banco guarda timestamptz)."""
    quando = datetime.fromisoformat(valor)
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def _host(database_url: str) -> str:
    """Host do DSN, sem credencial -- so para o cabecalho dizer de qual banco veio o numero."""
    sem_esquema = database_url.split("://", 1)[-1]
    return sem_esquema.rsplit("@", 1)[-1].split("/", 1)[0] or "?"


async def _executar(desde: datetime | None, como_json: bool) -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL obrigatorio (relatorio le o banco).", file=sys.stderr)
        return 2

    conn: AsyncConnection[Any] = await AsyncConnection.connect(
        settings.database_url,
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        relatorio = await service.gerar_relatorio(conn, desde=desde)
    finally:
        # Nada a persistir: o ROLLBACK e garantia, nao limpeza.
        await conn.rollback()
        await conn.close()

    if como_json:
        print(relatorio.model_dump_json(indent=2))
    else:
        print(f"banco          : {_host(settings.database_url)}")
        print(renderizar(relatorio))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="graduacao",
        description="Relatorio dos 4 criterios de graduacao do piloto (ADR-0034). Read-only.",
    )
    parser.add_argument(
        "--desde",
        type=_parse_desde,
        default=None,
        help=(
            "Inicio da janela (YYYY-MM-DD ou ISO). Sem isto, e derivado do primeiro turno da IA "
            "para cliente real."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Imprime o DTO em JSON.")
    args = parser.parse_args()
    return asyncio.run(_executar(args.desde, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
