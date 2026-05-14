"""Endpoints de inspeção do pipeline overnight.

Lê `.claude/state/overnight/runs.jsonl` (escrito pelos scripts
`overnight-loop.ps1` e `overnight-agente.ps1`) e devolve o último run.
Local-dev only: em produção esse arquivo não existe e a rota responde 404.
"""

import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends

from barra.api.deps import get_user
from barra.core.errors import ErroDominio

router = APIRouter(dependencies=[Depends(get_user)])


def _runs_path() -> Path:
    # api/src/barra/dominio/dev/routes.py -> 6 levels up para chegar à raiz do repo.
    return Path(__file__).resolve().parents[5] / ".claude" / "state" / "overnight" / "runs.jsonl"


@router.get("/overnight/ultimo")
async def overnight_ultimo() -> dict[str, Any]:
    """Devolve a última linha de `runs.jsonl` parseada como JSON.

    Filas `barra` e `agente` são misturadas; o cliente filtra pelo campo `fila`
    se quiser separar. Resposta inclui sempre `fila`, `stopReason`, totais e
    `commitsAheadOrigin` quando disponível.
    """
    path = _runs_path()
    if not path.exists():
        raise ErroDominio(
            "OVERNIGHT_INDISPONIVEL",
            "runs.jsonl não encontrado (ambiente sem overnight rodado).",
            status_code=404,
        )
    try:
        linhas = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        raise ErroDominio(
            "OVERNIGHT_LEITURA",
            f"Falha lendo runs.jsonl: {exc}",
            status_code=500,
        ) from exc
    if not linhas:
        raise ErroDominio(
            "OVERNIGHT_VAZIO",
            "runs.jsonl existe mas não tem registros.",
            status_code=404,
        )
    try:
        return cast(dict[str, Any], json.loads(linhas[-1]))
    except json.JSONDecodeError as exc:
        raise ErroDominio(
            "OVERNIGHT_CORROMPIDO",
            f"Última linha não é JSON válido: {exc}",
            status_code=500,
        ) from exc


@router.get("/overnight/historico")
async def overnight_historico(limite: int = 20) -> dict[str, Any]:
    """Últimas N execuções (mais recentes primeiro).

    Útil para gráfico de tendência: PASS vs rework, duração média, etc.
    `limite` clamped em [1, 200] para não devolver arquivo inteiro.
    """
    limite = max(1, min(200, limite))
    path = _runs_path()
    if not path.exists():
        raise ErroDominio(
            "OVERNIGHT_INDISPONIVEL",
            "runs.jsonl não encontrado.",
            status_code=404,
        )
    linhas = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    registros: list[dict[str, Any]] = []
    for ln in linhas[-limite:][::-1]:
        try:
            registros.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return {"total": len(linhas), "devolvidos": len(registros), "itens": registros}
