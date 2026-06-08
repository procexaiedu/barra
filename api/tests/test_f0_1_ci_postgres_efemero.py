"""F0.1 — gate: a CI provisiona um Postgres efêmero e roda os `needs_db` nele.

Critério do roadmap (F0.1): "needs-DB roda no CI limpo, não pulado nem apontando
p/ prod Postgres real (FOR UPDATE + agregação)". Este teste é a REDE que reprova o
PR se a CI regredir — se alguém remover o service container, o wiring de
`TEST_DATABASE_URL` ou o passo de schema, o gate fica vermelho. Determinístico: lê
só YAML/arquivos do repo, sem tocar banco nem API (roda no `make test` comum).

Gêmeo vivo: `tests/integracao/test_timeout_longo.py` (24h, FOR UPDATE + max()) é um
dos `needs_db` que passam a rodar de verdade a cada PR graças a esta wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _raiz_repo() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / ".github" / "workflows" / "ci.yml").is_file():
            return ancestor
    raise AssertionError("não achei a raiz do repo (.github/workflows/ci.yml)")


def _ci() -> dict[str, Any]:
    raiz = _raiz_repo()
    return yaml.safe_load((raiz / ".github" / "workflows" / "ci.yml").read_text("utf-8"))


def _job_do_pytest(ci: dict[str, Any]) -> dict[str, Any]:
    for job in ci["jobs"].values():
        for step in job.get("steps", []):
            if "pytest" in str(step.get("run", "")):
                return job
    raise AssertionError("nenhum job da CI roda pytest")


def test_ci_provisiona_postgres_efemero() -> None:
    """O job que roda pytest precisa de um service container Postgres descartável."""
    job = _job_do_pytest(_ci())
    services = job.get("services", {})
    imagens = [str(s.get("image", "")) for s in services.values()]
    assert any(img.startswith("postgres:") for img in imagens), (
        f"o job do pytest precisa de um service container postgres efêmero; services={services}"
    )


def test_ci_seta_test_database_url_local_nao_prod() -> None:
    """TEST_DATABASE_URL setado (needs_db NÃO pulado) e apontando p/ o efêmero local."""
    job = _job_do_pytest(_ci())
    envs: dict[str, str] = dict(job.get("env", {}) or {})
    for step in job.get("steps", []):
        if "pytest" in str(step.get("run", "")):
            envs.update(step.get("env", {}) or {})
    url = envs.get("TEST_DATABASE_URL")
    assert url, "TEST_DATABASE_URL precisa estar setado p/ os needs_db NÃO serem pulados na CI"
    assert ("localhost" in url) or ("127.0.0.1" in url), (
        f"TEST_DATABASE_URL deve apontar p/ o Postgres efêmero local, não prod: {url}"
    )
    for proibido in ("procexai", "supabase.co", "supabase.in", "amazonaws", "pooler", "neon.tech"):
        assert proibido not in url, f"TEST_DATABASE_URL parece apontar p/ prod ({proibido}): {url}"


def test_ci_aplica_schema_antes_do_pytest() -> None:
    """As migrations (schema) têm de rodar ANTES do pytest, senão o banco fica vazio."""
    steps = _job_do_pytest(_ci()).get("steps", [])
    idx_migrate = next(
        (i for i, s in enumerate(steps) if "make migrate" in str(s.get("run", ""))), None
    )
    idx_pytest = next((i for i, s in enumerate(steps) if "pytest" in str(s.get("run", ""))), None)
    assert idx_migrate is not None, (
        "a CI precisa aplicar as migrations no Postgres efêmero (make migrate)"
    )
    assert idx_pytest is not None
    assert idx_migrate < idx_pytest, "as migrations têm de rodar ANTES do pytest"


def test_bootstrap_supabase_existe_e_referenciado() -> None:
    """Postgres limpo não tem auth.users/roles/supabase_realtime: o bootstrap stuba isso."""
    raiz = _raiz_repo()
    bootstrap = raiz / "infra" / "sql" / "ci" / "bootstrap_supabase.sql"
    assert bootstrap.is_file(), (
        "falta infra/sql/ci/bootstrap_supabase.sql (auth.users, roles authenticated/"
        "service_role, publication supabase_realtime) p/ o schema aplicar num PG limpo"
    )
    texto_ci = (raiz / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "bootstrap_supabase.sql" in texto_ci, (
        "a CI precisa aplicar o bootstrap Supabase antes do make migrate"
    )
