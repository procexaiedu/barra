"""Conftest local de tests/agente: ao fim da sessao, despeja o relatorio de observabilidade do
gate de seguranca (se algum run foi registrado por test_gate_seguranca) E acrescenta uma linha ao
historico versionado (dashboard de regressao). No-op para a suite normal — `escrever` retorna None
quando o acumulador esta vazio."""

import subprocess
from datetime import UTC, datetime
from typing import Any

import pytest


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "?"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    from evals.relatorio import acrescentar_historico, escrever, resumo_texto

    destino = escrever("gate")
    if destino is None:
        return
    acrescentar_historico(git_sha=_git_sha(), ts=datetime.now(UTC).isoformat())
    writer: Any = session.config.pluginmanager.get_plugin("terminalreporter")
    msg = f"\n{resumo_texto()}\nrelatorio: {destino}\n"
    if writer is not None:
        writer.write_line(msg)
    else:
        print(msg)
