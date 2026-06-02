"""DEPLOY-05/06: drift-check estático de naming/ordenação das migrations.

Testa a função PURA `verificar` de `scripts/verificar_migrations.py` (offline) e,
como guarda-trilho, roda o check contra o `infra/sql/` real do repo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_SCRIPT = _RAIZ / "scripts" / "verificar_migrations.py"

_spec = importlib.util.spec_from_file_location("verificar_migrations", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
verificar = _mod.verificar


def test_aceita_legacy_e_timestamp() -> None:
    arquivos = [
        "0001_init.sql",
        "0002_segundo.sql",
        "20260529220000_fetiches.sql",
        "20260601100000_schema_migrations.sql",
    ]
    assert verificar(arquivos) == []


def test_pega_nome_fora_do_padrao() -> None:
    problemas = verificar(["0001_init.sql", "migration_solta.sql"])
    assert any("fora do padrao" in p for p in problemas)


def test_pega_buraco_na_sequencia_legacy() -> None:
    problemas = verificar(["0001_a.sql", "0003_c.sql"])  # falta 0002
    assert any("buraco" in p and "0002" in p for p in problemas)


def test_pega_nnnn_duplicado() -> None:
    problemas = verificar(["0001_a.sql", "0001_b.sql"])
    assert any("duplicado" in p for p in problemas)


def test_pega_timestamp_duplicado() -> None:
    problemas = verificar(["20260601100000_a.sql", "20260601100000_b.sql"])
    assert any("duplicado" in p for p in problemas)


def test_repo_real_passa() -> None:
    diretorio = _RAIZ / "infra" / "sql"
    arquivos = sorted(p.name for p in diretorio.glob("*.sql"))
    assert verificar(arquivos) == []
