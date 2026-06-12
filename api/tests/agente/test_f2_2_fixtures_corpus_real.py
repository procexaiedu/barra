"""F2.2 — README de evals não regride à alegação de "templates ilustrativos".

Gate determinístico **sem banco** (regex/leitura pura, roda no `make test` padrão, não
`needs_db`). Originalmente este gate também travava a rastreabilidade fixture→conversa real
(`#NNN` → `docs/agente/conversas-reais/NNN-*.md`); o corpus anonimizado foi removido do repo
(2026-06-12) e essa parte saiu junto. Resta o anti-regressão do README: ele não pode voltar a
alegar que as fixtures de gate são apenas "templates ilustrativos".
"""

from __future__ import annotations

from pathlib import Path

import pytest

# api/tests/agente/test_*.py → parents: [0]=agente [1]=tests [2]=api [3]=raiz do repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
_README = _REPO_ROOT / "api" / "evals" / "README.md"

# Alegação obsoleta que F2.2 removeu do README.
_ALEGACAO_OBSOLETA = "Esta sessão criou apenas templates ilustrativos"


def test_readme_nao_alega_templates_ilustrativos() -> None:
    """O README de evals não pode regredir à alegação obsoleta de "templates ilustrativos"."""
    texto = _README.read_text(encoding="utf-8")
    assert _ALEGACAO_OBSOLETA not in texto, (
        f"README ainda alega {_ALEGACAO_OBSOLETA!r} — o corpus já foi curado (F2.2)"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
