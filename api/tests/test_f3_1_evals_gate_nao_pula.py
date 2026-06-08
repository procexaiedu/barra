"""F3.1 — gate: o workflow de evals NUNCA pula em silêncio.

Critério do roadmap (F3.1): "job não pula em silêncio; evals barram merge". O que
torna o gate de evals vinculante tem duas metades:

- **Operador (fora do repo):** adicionar os secrets `TEST_DATABASE_URL` +
  `ANTHROPIC_API_KEY` e marcar o check `evals` como obrigatório na branch protection
  da `main` (passos em `infra/runbooks/evals-gate-vinculante.md`). Bloqueado por billing
  do GitHub + crédito Anthropic; não é código.
- **Repo (este gate):** o workflow não pode mais se **auto-pular em silêncio** quando os
  secrets faltam. Antes (`Guard de secrets` → `rodar=false` → todos os passos com
  `if: steps.guard.outputs.rodar == 'true'`) o job terminava **verde sem rodar nada** —
  teatro de segurança: um PR que toca `agente/**` passava sem uma única fixture rodar.
  Agora o guard **falha alto** (`exit 1`) e o runner é **incondicional**, então um check
  verde do `evals` só pode significar que o runner rodou.

Este teste é a REDE que reprova o PR se o workflow regredir p/ o skip silencioso.
Determinístico: lê só o YAML do repo, sem tocar banco nem API (roda no `make test`).
Espelha o gate de wiring de CI da F0.1 (`test_f0_1_ci_postgres_efemero.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _raiz_repo() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / ".github" / "workflows" / "evals.yml").is_file():
            return ancestor
    raise AssertionError("não achei a raiz do repo (.github/workflows/evals.yml)")


def _evals() -> dict[str, Any]:
    raiz = _raiz_repo()
    return yaml.safe_load((raiz / ".github" / "workflows" / "evals.yml").read_text("utf-8"))


def _job_do_gate(evals: dict[str, Any]) -> dict[str, Any]:
    for job in evals["jobs"].values():
        for step in job.get("steps", []):
            if "runner.py" in str(step.get("run", "")):
                return job
    raise AssertionError("nenhum job do evals roda o runner.py")


def _passo_do_runner(job: dict[str, Any]) -> dict[str, Any]:
    for step in job.get("steps", []):
        if "runner.py" in str(step.get("run", "")):
            return step
    raise AssertionError("não achei o passo que roda o runner.py")


def test_runner_roda_com_k5() -> None:
    """Âncora anti-vácuo: o gate só vale se o runner roda K=5 (pass^k, não pass^1)."""
    passo = _passo_do_runner(_job_do_gate(_evals()))
    run = str(passo.get("run", ""))
    assert "--k 5" in run, f"o runner do gate precisa rodar K=5 (08 §4.1), não {run!r}"


def test_runner_e_incondicional() -> None:
    """O passo do runner NÃO pode ter `if:` — senão ele pula (silenciosamente) sem rodar.

    Era exatamente o `if: steps.guard.outputs.rodar == 'true'` do skip antigo.
    """
    passo = _passo_do_runner(_job_do_gate(_evals()))
    assert "if" not in passo, (
        "o passo do runner não pode ser condicional (`if:`) — um runner gateado por "
        f"presença de secret pula em silêncio e o job fica verde sem rodar: {passo!r}"
    )


def test_guard_de_secret_falha_alto_nao_pula() -> None:
    """Tem de existir um passo que, sem os secrets, FALHA o job (`exit 1`), não o pula.

    Reprova o skip silencioso antigo, cujo guard só escrevia `rodar=false` no
    GITHUB_OUTPUT e deixava o job terminar verde.
    """
    job = _job_do_gate(_evals())
    guards = [
        s
        for s in job.get("steps", [])
        if "TEST_DATABASE_URL" in str(s.get("run", ""))
        and "ANTHROPIC_API_KEY" in str(s.get("run", ""))
    ]
    assert guards, (
        "falta um passo que cheque os secrets do gate (TEST_DATABASE_URL + "
        "ANTHROPIC_API_KEY) e falhe quando ausentes"
    )
    assert any("exit 1" in str(s.get("run", "")) for s in guards), (
        "o guard de secrets precisa FALHAR (`exit 1`) quando os secrets faltam — "
        "nunca apenas pular/seguir verde (job não pula em silêncio)"
    )


def test_guard_roda_antes_do_runner() -> None:
    """O guard fail-loud tem de vir ANTES do runner, senão o job gasta crédito à toa."""
    steps = _job_do_gate(_evals()).get("steps", [])
    idx_guard = next(
        (
            i
            for i, s in enumerate(steps)
            if "exit 1" in str(s.get("run", "")) and "TEST_DATABASE_URL" in str(s.get("run", ""))
        ),
        None,
    )
    idx_runner = next(
        (i for i, s in enumerate(steps) if "runner.py" in str(s.get("run", ""))), None
    )
    assert idx_guard is not None, "falta o guard fail-loud de secrets"
    assert idx_runner is not None
    assert idx_guard < idx_runner, "o guard de secrets tem de rodar ANTES do runner"


def test_nenhum_passo_pula_em_silencio() -> None:
    """Nenhum passo pode escrever um output de skip que neutralize o runner.

    O skip antigo escrevia `rodar=false` em `$GITHUB_OUTPUT` e gateava o runner nele;
    qualquer ressurreição desse padrão (output booleano + `if:` no runner) reabre o
    buraco do verde-vazio.
    """
    job = _job_do_gate(_evals())
    for step in job.get("steps", []):
        run = str(step.get("run", ""))
        assert "rodar=false" not in run, (
            "ressurgiu o output de skip silencioso (`rodar=false`): o gate voltaria a "
            f"terminar verde sem rodar o runner — {step!r}"
        )


def test_secrets_estao_wirados_no_env() -> None:
    """Os secrets do gate têm de chegar ao job via env (senão nunca rodam de verdade)."""
    job = _job_do_gate(_evals())
    env_texto = str(job.get("env", {}))
    assert "secrets.TEST_DATABASE_URL" in env_texto, (
        "TEST_DATABASE_URL precisa vir de secrets.* no env do job"
    )
    assert "secrets.ANTHROPIC_API_KEY" in env_texto, (
        "ANTHROPIC_API_KEY precisa vir de secrets.* no env do job"
    )
