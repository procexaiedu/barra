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
