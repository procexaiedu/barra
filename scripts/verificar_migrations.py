"""Drift-check estático de migrations (DEPLOY-05/06), sem banco.

No CI não há Postgres (roda sem secrets), então o drift "repo x banco" via
`schema_migrations` não roda lá. Este check é a parte ESTÁTICA, sempre-on: valida
que todo `.sql` de `infra/sql/` tem naming aceito e que a sequência legacy `NNNN`
não tem buraco nem duplicata. Isso pega o erro mais comum — migration commitada
com nome fora do padrão, número pulado ou colidido — antes de chegar ao deploy.

A comparação contra o que está registrado em `barravips.schema_migrations`
(drift de aplicação) é um passo do operador/CI com banco — ver o runbook
`infra/runbooks/aplicar-migrations-prod.md`.

Uso (da raiz do repo):
    uv run python scripts/verificar_migrations.py
Saída: 0 se tudo válido, 1 se houver problema (lista os motivos no stderr).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# A) legacy 4 dígitos: NNNN_descricao.sql   B) timestamp UTC: YYYYMMDDHHMMSS_descricao.sql
RE_LEGACY = re.compile(r"^(\d{4})_[a-z0-9].*\.sql$")
RE_TIMESTAMP = re.compile(r"^(\d{14})_[a-z0-9].*\.sql$")


def diretorio_sql() -> Path:
    return Path(__file__).resolve().parents[1] / "infra" / "sql"


def verificar(arquivos: list[str]) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia = tudo OK). Função pura."""
    problemas: list[str] = []
    legacy: dict[str, str] = {}
    timestamps: dict[str, str] = {}

    for nome in arquivos:
        m_leg = RE_LEGACY.match(nome)
        m_ts = RE_TIMESTAMP.match(nome)
        if m_leg:
            num = m_leg.group(1)
            if num in legacy:
                problemas.append(f"NNNN duplicado {num}: {legacy[num]} e {nome}")
            legacy[num] = nome
        elif m_ts:
            ts = m_ts.group(1)
            if ts in timestamps:
                problemas.append(f"timestamp duplicado {ts}: {timestamps[ts]} e {nome}")
            timestamps[ts] = nome
        else:
            problemas.append(f"nome fora do padrao (NNNN_ ou YYYYMMDDHHMMSS_): {nome}")

    # Contiguidade da sequência legacy (sem buraco). Replacements imutáveis pegam
    # número novo no fim, então a faixa 0001..max deve ser contínua.
    if legacy:
        nums = sorted(int(n) for n in legacy)
        esperado = set(range(nums[0], nums[-1] + 1))
        faltando = sorted(esperado - set(nums))
        if faltando:
            buracos = ", ".join(f"{n:04d}" for n in faltando)
            problemas.append(f"buraco na sequencia legacy NNNN: faltam {buracos}")

    return problemas


def main() -> int:
    diretorio = diretorio_sql()
    arquivos = sorted(p.name for p in diretorio.glob("*.sql"))
    problemas = verificar(arquivos)
    if problemas:
        print("drift-check FALHOU:", file=sys.stderr)
        for p in problemas:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"drift-check OK: {len(arquivos)} migrations com naming/ordenacao validos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
