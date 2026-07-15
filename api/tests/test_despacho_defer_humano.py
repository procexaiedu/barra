"""Defer 'humano' do enviar_turno (05 §4.1): sampler + despacho.

Sem DB e sem LLM: `amostrar_defer_humano_s` é função pura (settings + rng monkeypatchados) e
`despachar_humanizacao` só toca ctx['redis'].enqueue_job (AsyncMock). O defer é ARGUMENTO do
enqueue (_defer_by) — assert puro, nenhum sleep real. O fio fim-a-fim (processar_turno →
_defer_by no enviar_turno + judge alinhado) vive em tests/integracao/test_coordenador_basico.py.
"""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from barra.settings import Settings, get_settings
from barra.workers import coordenador, envio
from barra.workers.coordenador import despachar_humanizacao
from barra.workers.envio import amostrar_defer_humano_s, calcular_reading_delay_ms


def _settings_delay(**over: Any) -> Settings:
    base: dict[str, Any] = {"envio_delay_humano_habilitado": True}
    base.update(over)
    return get_settings().model_copy(update=base)


# --- sampler (amostrar_defer_humano_s) --------------------------------------------------------


def test_flag_off_devolve_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        envio,
        "get_settings",
        lambda: get_settings().model_copy(update={"envio_delay_humano_habilitado": False}),
    )
    assert amostrar_defer_humano_s(chars_inbound=0, elapsed_s=0.0) == 0


def test_desconta_elapsed_e_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(envio, "get_settings", _settings_delay)
    monkeypatch.setattr(envio.random, "lognormvariate", lambda mu, sigma: 50.0)
    reading_s = calcular_reading_delay_ms(100) / 1000
    esperado = round(50.0 - 10.0 - reading_s)
    assert amostrar_defer_humano_s(chars_inbound=100, elapsed_s=10.0) == esperado


def test_clampa_no_teto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        envio, "get_settings", lambda: _settings_delay(envio_delay_humano_teto_s=90)
    )
    monkeypatch.setattr(envio.random, "lognormvariate", lambda mu, sigma: 500.0)
    esperado = round(90 - calcular_reading_delay_ms(0) / 1000)
    assert amostrar_defer_humano_s(chars_inbound=0, elapsed_s=0.0) == esperado


def test_nunca_negativo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(envio, "get_settings", _settings_delay)
    monkeypatch.setattr(envio.random, "lognormvariate", lambda mu, sigma: 5.0)
    assert amostrar_defer_humano_s(chars_inbound=500, elapsed_s=60.0) == 0


def test_distribuicao_p25_p50(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estatístico seedado: a latência-alvo (defer + já-gasto) reproduz o corpus ±15%.

    Teto alto (300s) para não distorcer p25/p50; o já-gasto fixo (reading de inbound vazio,
    1,5s) é somado de volta para comparar com o alvo bruto p25≈14s / p50≈40s.
    """
    monkeypatch.setattr(
        envio, "get_settings", lambda: _settings_delay(envio_delay_humano_teto_s=300)
    )
    rng = random.Random(42)
    monkeypatch.setattr(envio.random, "lognormvariate", rng.lognormvariate)
    ja_gasto = calcular_reading_delay_ms(0) / 1000
    amostras = sorted(
        amostrar_defer_humano_s(chars_inbound=0, elapsed_s=0.0) + ja_gasto for _ in range(10_000)
    )
    p25 = amostras[2_500]
    p50 = amostras[5_000]
    assert 14 * 0.85 <= p25 <= 14 * 1.15, f"p25 fora do alvo humano: {p25:.1f}s"
    assert 40 * 0.85 <= p50 <= 40 * 1.15, f"p50 fora do alvo humano: {p50:.1f}s"


# --- despacho (despachar_humanizacao) ---------------------------------------------------------


def _despachar(
    monkeypatch: pytest.MonkeyPatch,
    defer: int,
    *,
    critico: bool = False,
    recebida_em: datetime | None = None,
) -> tuple[int, AsyncMock, list[dict[str, Any]]]:
    chamadas_sampler: list[dict[str, Any]] = []

    def _sampler_fake(*, chars_inbound: int, elapsed_s: float) -> int:
        chamadas_sampler.append({"chars_inbound": chars_inbound, "elapsed_s": elapsed_s})
        return defer

    monkeypatch.setattr(coordenador, "amostrar_defer_humano_s", _sampler_fake)
    redis = AsyncMock()
    ret = asyncio.run(
        despachar_humanizacao(
            {"redis": redis},
            "c1",
            "t1",
            ["oi amor"],
            [],
            [],
            7,
            critico,
            recebida_em=recebida_em,
        )
    )
    return ret, redis, chamadas_sampler


def test_defer_zero_enqueue_identico_ao_atual(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prova do deploy no-op: defer 0 (flag off) não adiciona _defer_by — kwargs de hoje."""
    ret, redis, _ = _despachar(monkeypatch, 0)
    assert ret == 0
    kwargs = redis.enqueue_job.call_args.kwargs
    assert "_defer_by" not in kwargs
    assert kwargs["_job_id"] == "turno_envio:t1"
    assert kwargs["chunks"] == ["oi amor"]


def test_defer_vira_argumento_do_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    ret, redis, _ = _despachar(monkeypatch, 33)
    assert ret == 33
    assert redis.enqueue_job.call_args.kwargs["_defer_by"] == 33


def test_critico_nunca_adia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Crítico pula o cancel-on-new-message no fire: deferi-lo criaria inversão de ordem."""
    ret, redis, chamadas = _despachar(monkeypatch, 99, critico=True)
    assert ret == 0
    assert "_defer_by" not in redis.enqueue_job.call_args.kwargs
    assert chamadas == []  # sampler nem é consultado


def test_recebida_em_vira_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    recebida = datetime.now(UTC) - timedelta(seconds=20)
    _, _, chamadas = _despachar(monkeypatch, 0, recebida_em=recebida)
    assert len(chamadas) == 1
    assert 19.0 <= chamadas[0]["elapsed_s"] <= 25.0
    assert chamadas[0]["chars_inbound"] == 7


def test_defer_humano_false_nao_adia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Canned de transcrição: cliente espera reação — nunca ganha o defer humano."""
    chamadas: list[int] = []
    monkeypatch.setattr(
        coordenador, "amostrar_defer_humano_s", lambda **_kw: chamadas.append(1) or 77
    )
    redis = AsyncMock()
    ret = asyncio.run(
        despachar_humanizacao(
            {"redis": redis}, "c1", "t1", ["canned"], [], [], 0, False, defer_humano=False
        )
    )
    assert ret == 0
    assert "_defer_by" not in redis.enqueue_job.call_args.kwargs
    assert chamadas == []


def test_dedupe_do_retry_devolve_teto(monkeypatch: pytest.MonkeyPatch) -> None:
    """enqueue dedupado (retry): a amostra fresca não vale — devolve o teto p/ o judge."""
    monkeypatch.setattr(coordenador, "amostrar_defer_humano_s", lambda **_kw: 3)
    monkeypatch.setattr(
        coordenador,
        "get_settings",
        lambda: get_settings().model_copy(
            update={"envio_delay_humano_habilitado": True, "envio_delay_humano_teto_s": 90}
        ),
    )
    redis = AsyncMock()
    redis.enqueue_job.return_value = None  # dedupe NX: job turno_envio: já existe
    ret = asyncio.run(despachar_humanizacao({"redis": redis}, "c1", "t1", ["oi"], [], [], 2, False))
    assert ret == 90
