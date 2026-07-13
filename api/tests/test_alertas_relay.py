"""Testes do relay Alertmanager→WhatsApp (api/alertas.py) — sem Evolution real."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import barra.api.alertas as alertas_mod
from barra.api.alertas import formatar_alertas, router
from barra.settings import get_settings


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


class _FakeAsyncClient:
    """Captura o POST do relay; classe-attr `chamadas` zerada por teste via fixture."""

    chamadas: ClassVar[list[dict[str, Any]]] = []
    falhar = False

    def __init__(self, **kw: Any) -> None: ...

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None: ...

    async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
        type(self).chamadas.append({"url": url, "json": json, "headers": headers})
        if type(self).falhar:
            raise httpx.ConnectError("evolution fora")

        class _Resp:
            def raise_for_status(self) -> None: ...

        return _Resp()


@pytest.fixture(autouse=True)
def _fake_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.chamadas = []
    _FakeAsyncClient.falhar = False
    monkeypatch.setattr(alertas_mod.httpx, "AsyncClient", _FakeAsyncClient)


def test_formatar_resumo_firing() -> None:
    texto = formatar_alertas(_payload())
    assert "🚨" in texto and "1 alerta(s) FIRING" in texto
    assert "*PilotoGatilhoRollback* [critical]" in texto
    assert "nao_contidos" in texto


def test_formatar_resolved_e_vazio() -> None:
    assert "✅" in formatar_alertas(_payload(status="resolved"))
    assert formatar_alertas({}) == ""
    assert formatar_alertas({"alerts": []}) == ""


def test_token_errado_403_e_sem_token_configurado_403(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch)
    assert c.post("/alertas/alertmanager?token=errado", json=_payload()).status_code == 403
    # sem token configurado o endpoint fica DESLIGADO (mesmo com token vazio na query)
    c2 = _client(monkeypatch, alertas_webhook_token="")
    assert c2.post("/alertas/alertmanager?token=", json=_payload()).status_code == 403
    assert _FakeAsyncClient.chamadas == []


def test_entrega_no_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch)
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 200 and r.json() == {"ok": True, "entregue": True}
    chamada = _FakeAsyncClient.chamadas[0]
    assert chamada["url"] == "https://evo.exemplo/message/sendText/lucia"
    assert chamada["json"]["number"] == "5511999990000"
    assert "PilotoGatilhoRollback" in chamada["json"]["text"]
    assert chamada["headers"]["apikey"] == "k"


def test_sem_destino_aceita_e_nao_envia(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(monkeypatch, alertas_whatsapp_jid="")
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 200 and r.json()["entregue"] is False
    assert _FakeAsyncClient.chamadas == []


def test_falha_de_entrega_vira_502_para_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.falhar = True
    c = _client(monkeypatch)
    r = c.post("/alertas/alertmanager?token=tok-teste", json=_payload())
    assert r.status_code == 502


def test_muitos_alertas_trunca(monkeypatch: pytest.MonkeyPatch) -> None:
    texto = formatar_alertas(_payload(n=15))
    assert "(+5 alertas no Grafana)" in texto
