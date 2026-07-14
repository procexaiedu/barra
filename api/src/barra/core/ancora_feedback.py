"""Âncora do rig de feedback — skill `/processar-feedbacks` (issues #90/#91).

Função pura que casa um feedback cru do Fernando ao trace do turno que ele critica.
Recebe os traces candidatos JÁ buscados do Langfuse (o fetch via MCP mora na skill, fora
daqui), o texto do agente extraído do print (vision nativa) e o timestamp do feedback; devolve
o trace escolhido ou sinaliza ambiguidade — **nunca escolhe um turno em silêncio** (spec #90:
a âncora não chuta; empate/nada-plausível vira desambiguação humana).

`escolher_trace_candidato` é sem I/O, sem MCP, sem rede: é o Seam 1 do spec, testável de mesa.
`escolher_de_payload`/`_main` são o adaptador JSON→JSON que a skill chama via `python -m` — glue
de integração, deixa a função-seam pura. A ancoragem é contra o Langfuse (append-only) e não o
banco operacional porque o `#reset` do rig apaga conversas/mensagens/atendimentos entre sessões.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

# Janela: horizonte típico entre o turno criticado e o feedback do Fernando (parametrizável pelo
# chamador, que a expõe via `janela_min` no payload). Os demais limiares governam confiança e
# empate do match textual — constantes: nenhum caller precisou ajustá-los (CLAUDE.md §2).
JANELA_PADRAO = timedelta(minutes=30)
TOLERANCIA_FUTURA = timedelta(minutes=2)  # folga p/ skew de relógio (turno "depois" do feedback)
LIMIAR_MATCH = 0.6  # abaixo disso, nenhum candidato é confiável o bastante p/ escolher
MARGEM_EMPATE = 0.08  # dois candidatos plausíveis dentro dessa margem = empate → ambíguo


@dataclass(frozen=True)
class TraceCandidato:
    """Um turno do agente no Langfuse, reduzido ao que a âncora precisa.

    `timestamp` deve ser tz-aware (as timestamps do Langfuse são ISO com timezone); comparar
    com o `ts_feedback` naive levantaria TypeError — falha alto, não silenciosa.
    """

    trace_id: str
    saida_agente: str  # o texto que o agente respondeu naquele turno
    timestamp: datetime


@dataclass(frozen=True)
class ResultadoAncora:
    """Desfecho da âncora. `ambiguo=True` ⇒ `trace_id is None` e a skill pede desambiguação."""

    trace_id: str | None
    ambiguo: bool
    motivo: str  # "match" | "nenhum_match" | "empate" | "sem_candidato_na_janela"
    score: float  # similaridade do escolhido (ou do topo, quando ambíguo por empate)
    candidatos: tuple[str, ...]  # trace_ids em disputa (vazio fora de empate)


def _normalizar(texto: str) -> str:
    """NFKD + drop de diacríticos + casefold + colapso de espaços — match acento/caixa-insensível.

    Mesmo dobramento do `workers/coordenador._normalizar`: a vision recorta a fala do agente e
    costuma perder acentos do PT-BR ("horario" por "horário"), então normalizar evita erro de
    match espúrio por diacrítico.
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.split()).casefold()


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def escolher_trace_candidato(
    traces: Sequence[TraceCandidato],
    texto_agente_print: str,
    ts_feedback: datetime,
    *,
    janela: timedelta = JANELA_PADRAO,
) -> ResultadoAncora:
    """Escolhe o trace do turno criticado, ou sinaliza ambiguidade.

    Passos: (1) restringe à janela de tempo ao redor do feedback; (2) pontua cada candidato pela
    similaridade textual com a fala extraída do print; (3) ordena por (score, timestamp, trace_id)
    — total e determinístico; (4) o topo abaixo do limiar vira `nenhum_match`; (5) um segundo
    candidato plausível dentro da `MARGEM_EMPATE` vira `empate`; (6) senão, escolhe o topo.
    """
    na_janela = [t for t in traces if -janela <= (t.timestamp - ts_feedback) <= TOLERANCIA_FUTURA]
    if not na_janela:
        return ResultadoAncora(None, True, "sem_candidato_na_janela", 0.0, ())

    # Ordem total determinística: score desc, depois turno mais recente, depois trace_id.
    pontuados = sorted(
        ((_similaridade(texto_agente_print, t.saida_agente), t) for t in na_janela),
        key=lambda par: (-par[0], -par[1].timestamp.timestamp(), par[1].trace_id),
    )
    melhor_score, melhor = pontuados[0]

    if melhor_score < LIMIAR_MATCH:
        return ResultadoAncora(None, True, "nenhum_match", melhor_score, ())

    # Empate: outros candidatos acima do limiar e dentro da margem do topo. Não desempata sozinho.
    empatados = [
        t.trace_id
        for score, t in pontuados
        if score >= LIMIAR_MATCH and (melhor_score - score) <= MARGEM_EMPATE
    ]
    if len(empatados) > 1:
        return ResultadoAncora(None, True, "empate", melhor_score, tuple(sorted(empatados)))

    return ResultadoAncora(melhor.trace_id, False, "match", melhor_score, ())


def escolher_de_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Adaptador JSON→JSON para a skill: mantém `escolher_trace_candidato` livre de parsing.

    A skill despeja os traces do MCP langfuse-traces num JSON e chama
    `python -m barra.core.ancora_feedback`; este adaptador faz o parse (`timestamp`/`ts_feedback`
    em ISO 8601, tz-aware) e serializa o `ResultadoAncora`. `janela_min` é opcional (minutos) e
    sobrepõe a `JANELA_PADRAO`.
    """
    traces = [
        TraceCandidato(
            trace_id=t["trace_id"],
            saida_agente=t["saida_agente"],
            timestamp=datetime.fromisoformat(t["timestamp"]),
        )
        for t in payload["traces"]
    ]
    kwargs: dict[str, Any] = {}
    if payload.get("janela_min") is not None:
        kwargs["janela"] = timedelta(minutes=payload["janela_min"])
    r = escolher_trace_candidato(
        traces,
        payload["texto_agente_print"],
        datetime.fromisoformat(payload["ts_feedback"]),
        **kwargs,
    )
    return {
        "trace_id": r.trace_id,
        "ambiguo": r.ambiguo,
        "motivo": r.motivo,
        "score": round(r.score, 4),
        "candidatos": list(r.candidatos),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Âncora de feedback: escolhe o trace do turno criticado (ou sinaliza ambiguidade)."
    )
    parser.add_argument("payload", nargs="?", help="Arquivo JSON com o payload; omitido = stdin.")
    args = parser.parse_args(argv)
    if args.payload:
        with open(args.payload, encoding="utf-8") as fh:
            bruto = fh.read()
    else:
        bruto = sys.stdin.read()
    print(json.dumps(escolher_de_payload(json.loads(bruto)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
