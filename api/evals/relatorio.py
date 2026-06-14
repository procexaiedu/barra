"""Relatorio de observabilidade do gate: agrega verdito + metricas por fixture/run num JSON e
num resumo legivel. Acumulador em memoria (o teste/runner registra cada run); `escrever` despeja
em `api/evals/relatorios/` e `resumo_texto` imprime o panorama (pass-rate, custo, p95, write-rate).

Complementa — nao substitui — o Prometheus (que o no llm ja alimenta durante o ainvoke) e o
trace Langfuse (anexado por turno em `harness.rodar_turno`). Aqui e a visao consolidada do gate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .harness import Metricas, ResultadoTurno

_RELATORIOS = Path(__file__).resolve().parent / "relatorios"


@dataclass
class Entrada:
    fixture_id: str
    categoria: str
    run: int
    passou: bool
    falhas: list[str]
    nodes: list[str]
    tool_calls: list[str]
    texto: str
    metricas: dict[str, Any]


_ACUMULADOR: list[Entrada] = []


def registrar(
    *,
    fixture_id: str,
    categoria: str,
    run: int,
    falhas: list[str],
    resultado: ResultadoTurno,
) -> None:
    """Registra um run no acumulador da sessao (chamado pelo gate apos cada `rodar_turno`)."""
    _ACUMULADOR.append(
        Entrada(
            fixture_id=fixture_id,
            categoria=categoria,
            run=run,
            passou=not falhas,
            falhas=falhas,
            nodes=resultado.nodes,
            tool_calls=resultado.tool_calls,
            texto=resultado.texto[:500],
            metricas=resultado.metricas.como_dict(),
        )
    )


def limpar() -> None:
    _ACUMULADOR.clear()


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenado = sorted(valores)
    k = min(len(ordenado) - 1, round((p / 100) * (len(ordenado) - 1)))
    return ordenado[k]


@dataclass
class Sumario:
    n_runs: int = 0
    n_fixtures: int = 0
    fixtures_verdes: int = 0  # passaram em TODOS os runs (pass^K)
    runs_verdes: int = 0
    custo_total_brl: float = 0.0
    tokens_total: int = 0
    cache_write_total: int = 0
    cache_read_total: int = 0
    latencia_p50_s: float = 0.0
    latencia_p95_s: float = 0.0
    write_rate_medio: float = 0.0
    por_categoria: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def write_rate_global(self) -> float:
        base = self.cache_read_total + self.cache_write_total
        return self.cache_write_total / base if base else 0.0


def _sumarizar(entradas: list[Entrada]) -> Sumario:
    s = Sumario(n_runs=len(entradas))
    por_fixture: dict[str, list[bool]] = {}
    latencias: list[float] = []
    write_rates: list[float] = []
    for e in entradas:
        por_fixture.setdefault(e.fixture_id, []).append(e.passou)
        s.custo_total_brl += float(e.metricas.get("custo_brl", 0.0))
        s.tokens_total += int(e.metricas.get("total_tokens", 0))
        s.cache_write_total += int(e.metricas.get("cache_write", 0))
        s.cache_read_total += int(e.metricas.get("cache_read", 0))
        latencias.append(float(e.metricas.get("latencia_s", 0.0)))
        write_rates.append(float(e.metricas.get("write_rate", 0.0)))
        if e.passou:
            s.runs_verdes += 1
        cat = s.por_categoria.setdefault(e.categoria, {"runs": 0, "verdes": 0})
        cat["runs"] += 1
        cat["verdes"] += int(e.passou)
    s.n_fixtures = len(por_fixture)
    s.fixtures_verdes = sum(1 for runs in por_fixture.values() if all(runs))
    s.latencia_p50_s = round(_percentil(latencias, 50), 3)
    s.latencia_p95_s = round(_percentil(latencias, 95), 3)
    s.write_rate_medio = round(sum(write_rates) / len(write_rates), 3) if write_rates else 0.0
    s.custo_total_brl = round(s.custo_total_brl, 6)
    return s


def escrever(nome: str = "gate") -> Path | None:
    """Despeja o acumulado em `api/evals/relatorios/<nome>.json`. None se nada foi registrado."""
    if not _ACUMULADOR:
        return None
    _RELATORIOS.mkdir(exist_ok=True)
    sumario = _sumarizar(_ACUMULADOR)
    destino = _RELATORIOS / f"{nome}.json"
    destino.write_text(
        json.dumps(
            {
                "sumario": {
                    **asdict(sumario),
                    "write_rate_global": round(sumario.write_rate_global, 3),
                },
                "entradas": [asdict(e) for e in _ACUMULADOR],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destino


def resumo_texto() -> str:
    """Panorama legivel para o terminal (impresso ao fim do gate)."""
    if not _ACUMULADOR:
        return "gate: nenhum run registrado."
    s = _sumarizar(_ACUMULADOR)
    linhas = [
        "── Relatorio do gate de seguranca ──",
        f"fixtures verdes (pass^K): {s.fixtures_verdes}/{s.n_fixtures}  |  runs verdes: {s.runs_verdes}/{s.n_runs}",
        f"custo total: R$ {s.custo_total_brl:.4f}  |  tokens: {s.tokens_total}  |  write-rate: {s.write_rate_global:.1%}",
        f"latencia p50/p95: {s.latencia_p50_s}s / {s.latencia_p95_s}s",
    ]
    for cat, d in sorted(s.por_categoria.items()):
        linhas.append(f"  · {cat}: {d['verdes']}/{d['runs']} runs verdes")
    return "\n".join(linhas)


def metricas_vazias() -> Metricas:
    """Conveniencia p/ entradas sem turno real (ex.: fixture pulada)."""
    return Metricas()


# --- dashboard: historico versionado por execucao (regressao entre versoes de prompt) ---------

_HISTORICO = _RELATORIOS / "historico.jsonl"


def acrescentar_historico(*, git_sha: str, ts: str) -> dict[str, Any] | None:
    """Acrescenta UMA linha ao historico (append-only) com o sumario desta execucao do gate.

    Permite acompanhar regressao entre versoes de prompt/grafo: cada `make evals` carimba
    git_sha + timestamp + pass-rate + custo + write-rate + p95. None se nada foi registrado.
    `ts`/`git_sha` vem de fora (o relatorio nao tem acesso a Date.now/git por design)."""
    if not _ACUMULADOR:
        return None
    _RELATORIOS.mkdir(exist_ok=True)
    s = _sumarizar(_ACUMULADOR)
    linha = {
        "ts": ts,
        "git_sha": git_sha,
        "fixtures_verdes": s.fixtures_verdes,
        "n_fixtures": s.n_fixtures,
        "runs_verdes": s.runs_verdes,
        "n_runs": s.n_runs,
        "custo_total_brl": s.custo_total_brl,
        "tokens_total": s.tokens_total,
        "write_rate_global": round(s.write_rate_global, 3),
        "latencia_p95_s": s.latencia_p95_s,
    }
    with _HISTORICO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha


def tendencia_texto() -> str:
    """Le o historico e devolve a serie (1 linha por execucao) — `make evals-tendencia`."""
    if not _HISTORICO.exists():
        return "sem historico do gate ainda (rode `make evals`)."
    linhas = [
        "── Tendencia do gate (execucoes) ──",
        f"{'data/hora':19}  {'sha':8}  {'verde':>7}  {'R$':>8}  {'wr':>5}  {'p95':>6}",
    ]
    for raw in _HISTORICO.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        d = json.loads(raw)
        verde = f"{d['fixtures_verdes']}/{d['n_fixtures']}"
        linhas.append(
            f"{d['ts'][:19]:19}  {str(d['git_sha'])[:8]:8}  {verde:>7}  "
            f"{d['custo_total_brl']:>8.4f}  {d['write_rate_global']:>5.1%}  {d['latencia_p95_s']:>6.2f}"
        )
    return "\n".join(linhas)


if __name__ == "__main__":  # `uv run python -m evals.relatorio` -> tendencia
    print(tendencia_texto())
