"""Aplica um arquivo .sql no banco via psycopg (ambiente sem `psql` local).

`make migrate` depende de `psql`, que não temos no Windows local. Este script lê um
arquivo de migration, separa os statements (respeitando blocos dollar-quoted `$$...$$` e
strings) e aplica cada um em autocommit. Idempotência é responsabilidade da própria
migration (IF NOT EXISTS / DROP ... IF EXISTS), como manda infra/sql/CLAUDE.md.

DATABASE_URL vem do ambiente ou, se ausente, de api/.env (via barra.settings).

Guarda de ambiente (DEPLOY-05/06): quando `settings.ambiente == 'producao'`, recusa
aplicar qualquer arquivo de seed (nome contém `seed`). Ao aplicar uma migration de
schema, registra o filename em `barravips.schema_migrations` (idempotente).

Uso (da raiz do repo):
    uv run python scripts/aplicar_sql.py infra/sql/20260525202843_modelo_disponibilidade.sql
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api" / "src"))

import psycopg

from barra.core.migracoes import e_arquivo_seed, seed_bloqueado
from barra.settings import get_settings


def split_sql(sql: str) -> list[str]:
    """Separa em statements por ';', ignorando ';' dentro de strings, dollar-quotes e comentários."""
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_single = False
    dollar_tag: str | None = None
    while i < n:
        ch = sql[i]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue
        if in_single:
            buf.append(ch)
            i += 1
            if ch == "'":
                in_single = False
            continue
        if sql.startswith("--", i):  # comentário de linha
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            m = re.match(r"\$[A-Za-z0-9_]*\$", sql[i:])
            if m:
                dollar_tag = m.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Lê api/.env diretamente (independe do CWD; pydantic resolve .env pelo CWD).
    env_path = Path(__file__).resolve().parents[1] / "api" / ".env"
    if env_path.exists():
        for linha in env_path.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("DATABASE_URL="):
                return linha.split("=", 1)[1].strip().strip("'").strip('"')
    raise SystemExit("DATABASE_URL não encontrado (env var nem api/.env)")


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: uv run python scripts/aplicar_sql.py <arquivo.sql>", file=sys.stderr)
        return 2
    caminho = Path(sys.argv[1])
    ambiente = get_settings().ambiente
    # Guarda de ambiente: em producao, NUNCA aplicar seed (dados de teste descartaveis).
    if seed_bloqueado(caminho.name, ambiente):
        print(
            f"RECUSADO: '{caminho.name}' e um seed e ambiente={ambiente} (seeds nao vao para prod).",
            file=sys.stderr,
        )
        return 3
    sql = caminho.read_text(encoding="utf-8")
    statements = split_sql(sql)
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        for st in statements:
            conn.execute(st)  # type: ignore[arg-type]
            print("OK:", st.splitlines()[0][:70])
        # Registra a aplicacao no tracking (idempotente; seeds NAO sao rastreados).
        if not e_arquivo_seed(caminho.name):
            conn.execute(
                "INSERT INTO barravips.schema_migrations (filename) VALUES (%s) "
                "ON CONFLICT (filename) DO NOTHING",
                (caminho.name,),
            )
    print(f"--- {caminho.name}: {len(statements)} statements aplicados ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
