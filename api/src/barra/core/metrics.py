"""Metricas Prometheus minimas."""

from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram
    from prometheus_client import generate_latest as _prometheus_generate_latest
except ModuleNotFoundError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    class _Metric:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def labels(self, *_: object) -> "_Metric":
            return self

        def inc(self, *_: object) -> None:
            return None

        def observe(self, *_: object) -> None:
            return None

    Counter = Histogram = _Metric  # type: ignore[misc,assignment]

    def _generate_latest() -> bytes:
        return b""
else:
    def _generate_latest() -> bytes:
        return _prometheus_generate_latest()

HTTP_REQUESTS = Counter("barra_http_requests_total", "Total de requests", ["route", "method", "status"])
HTTP_DURATION = Histogram("barra_http_request_duration_seconds", "Duracao por rota", ["route", "method"])
JOBS = Counter("barra_jobs_total", "Jobs executados", ["tipo", "resultado"])
COMANDOS_GRUPO = Counter("barra_comandos_grupo_total", "Comandos do grupo", ["resultado"])
PIX = Counter("barra_pix_total", "Decisoes Pix", ["resultado"])
ENVIOS_EVOLUTION = Counter("barra_envios_evolution_total", "Envios Evolution", ["resultado"])
WEBHOOK_ERRORS = Counter("barra_webhook_errors_total", "Erros de webhook", ["tipo"])
TIMEOUTS = Counter("barra_timeouts_total", "Timeouts aplicados", ["tipo"])

# Metricas do agente LangGraph (ver docs/agente/08-evals.md, 09-roteiro.md)
AGENTE_TURNO_DURACAO = Histogram(
    "agente_turno_duracao_seconds",
    "Duracao por turno (p50/p95/p99); split por tipo_turno p/ nao misturar texto e audio-Whisper (E5)",
    ["modelo", "tipo_turno"],
)
AGENTE_TURNO_RESULTADO = Counter(
    "agente_turno_resultado_total",
    "Resultado do turno: ok|escalado|exaustao|ia_pausada_skip|lock_busy|transcricao_timeout",
    ["resultado"],
)
# E3 (grilling 2026-05-23): dashboard de tendencia, NAO gate de qualidade.
# bucket=defesa (ataque ativo, desejavel; spike -> alerta) | capacidade (cego a
# alucinacao-sem-escalada, por isso nao gateia o cutover). mapa motivo->bucket vive
# em codigo (deterministico) e o enum de motivo aceito por `escalar` e restrito.
AGENTE_ESCALADA = Counter(
    "agente_escalada_total",
    "Escaladas por bucket/motivo (ver docs/agente/08-evals.md 3.2)",
    ["bucket", "motivo"],
)
AGENTE_TURNO_TOKENS = Counter(
    "agente_turno_tokens_total",
    "Tokens por turno por tipo: input|output|cache_read|cache_write. Rotulado por "
    "modelo p/ hit/write-rate por serie e tripwire de invalidador silencioso (03 §4.2)",
    ["modelo", "tipo"],
)
# E1 (grilling 2026-05-23): adiada pro P1 -- era para o gate de regressao nightly,
# que foi adiado (suite P0 = gate de cutover one-shot K=5, nao nightly com baseline).
AGENTE_EVAL_PASS_RATE = Histogram(
    "agente_eval_pass_rate",
    "Pass-rate de eval suite (P1; era pro nightly CI)",
    ["suite"],
)
AGENTE_CUSTO_TURNO_BRL = Histogram(
    "agente_custo_turno_brl",
    "Custo estimado por turno em BRL (Sonnet 4.6 com cache; meta <=0.12 BRL)",
    ["modelo"],
)
TURNO_TRUNCADO = Counter(
    "agente_turno_truncado_total",
    "Turnos com stop_reason=max_tokens (08 §3; valida a premissa de max_tokens~1024 nao "
    "truncar). No P0 so observa, nao escala (09 §4.2 / 03 §6.3); spike = revisar teto / mid-tool_use",
)
PERSONA_DRIFT_REMINDER = Counter(
    "agente_persona_reminder_injetado_total",
    "Reminder anti-drift injetado no ultimo HumanMessage (>=8 turnos da IA; 03 §10). Regra "
    "proativa -> proxy de volume de conversas longas, nao de drift detectado",
)
# 10 §9: deteccao heuristica de disclosure/jailbreak no intercept_disclosure (M3g).
DISCLOSURE_DETECTADO = Counter(
    "agente_disclosure_attempt_total",
    "Tentativas de disclosure detectadas",
    ["resultado"],  # negado | escalado | passou_silenciosamente
)
JAILBREAK_DETECTADO = Counter(
    "agente_jailbreak_attempt_total",
    "Tentativas de jailbreak detectadas",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(path, request.method, str(response.status_code)).inc()
        HTTP_DURATION.labels(path, request.method).observe(perf_counter() - start)
        return response


def prometheus_response() -> Response:
    return Response(_generate_latest(), media_type=CONTENT_TYPE_LATEST)
