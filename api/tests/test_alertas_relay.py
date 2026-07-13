"""Testes do relay Alertmanager→WhatsApp (api/alertas.py) — sem Evolution real."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import barra.api.alertas as alertas_mod
from barra.api.alertas import formatar_alertas, router
from barra.core.evolution import limpar_cache_tokens
from barra.settings import get_settings

BASE = "https://evo.exemplo"


def _payload(n: int = 1, status: str = "firing") -> dict[str, Any]:
    return {
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "PilotoGatilhoRollback",
                    "severity": "critical",
                    "gatilho": "nao_contidos",
                },
                "annotations": {"summary": "Gatilho de rollback do piloto disparado: nao_contidos"},
            }
        ]
        * n,
    }


def _client(monkeypatch: pytest.MonkeyPatch, **settings_over: Any) -> TestClient:
    base = {
        "alertas_webhook_token": "tok-teste",
        "alertas_whatsapp_jid": "5511999990000",
        "evolution_base_url": "https://evo.exemplo",
        "evolution_api_key": "k",
        "evolution_instancia": "lucia",
    }
    base.update(settings_over)
    settings = get_settings().model_copy(update=base)
    monkeypatch.setattr(alertas_mod, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router, prefix="/alertas")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cache_limpo() -> None:
    """O relay resolve o token da instância (`lucia`) via /instance/all — cache módulo-level,
    zerado por teste."""
    limpar_cache_tokens()


def _mock_instance_all() -> None:
    respx.get(f"{BASE}/instance/all").mock(
        return_value=httpx.Response(200, json={"data": [{"name": "lucia", "token": "tok-lucia"}]})
    )


def test_formatar_resumo_firing() -> None:
    texto = formatar_alertas(_payload())
    assert "🚨" in texto and "1 alerta(s) FIRING" in texto
    assert "*PilotoGatilhoRollback* [critical]" in texto
    assert "nao_contidos" in texto


def test_formatar_resolved_e_vazio() -> None:
    assert "✅" in formatar_alertas(_payload(status="resolved"))
    assert formatar_alertas({}) == ""
    assert formatar_alertas({"alerts": []}) == ""


@respx.mock
def test_token_errado_403_e_sem_token_configurado_403(monkeypatch: pytest.MonkeyPatch) -> None:
    send = respx.post(f"{BASE}/send/text").mock(return_value=httpx.Response(200, json={"id": "x"}))
    c = _client(monkeypatch)
    assert c.post("/alertas/alertmanager?token=errado", json=_payload()).status_code == 403
    # sem token configurado o endpoint fica DESLIGADO (mesmo com token vazio na query)
    c2 = _client(monkeypatch, alertas_webhook_token="")
    assert c2.post("/alertas/alertmanager?token=", json=_payload()).status_code == 403
    assert not send.called


@respx.mock
def test_entrega_no_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_instance_all()
    send = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-A"})
    )
    c = _client(monkeypatch)
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 200 and r.json() == {"ok": True, "entregue": True}
    req = send.calls.last.request
    body = json.loads(req.content)
    assert body["number"] == "5511999990000"
    assert "PilotoGatilhoRollback" in body["text"]
    # EvoGo escopa pela instância `lucia` via token no header apikey (não pela URL).
    assert req.headers["apikey"] == "tok-lucia"


@respx.mock
def test_sem_destino_aceita_e_nao_envia(monkeypatch: pytest.MonkeyPatch) -> None:
    send = respx.post(f"{BASE}/send/text").mock(return_value=httpx.Response(200, json={"id": "x"}))
    c = _client(monkeypatch, alertas_whatsapp_jid="")
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 200 and r.json()["entregue"] is False
    assert not send.called


@respx.mock
def test_falha_de_entrega_vira_502_para_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_instance_all()
    respx.post(f"{BASE}/send/text").mock(side_effect=httpx.ConnectError("evolution fora"))
    c = _client(monkeypatch)
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 502


def test_muitos_alertas_trunca(monkeypatch: pytest.MonkeyPatch) -> None:
    texto = formatar_alertas(_payload(n=15))
    assert "(+5 alertas no Grafana)" in texto
