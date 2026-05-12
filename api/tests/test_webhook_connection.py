"""Webhook Evolution: eventos de instância (connection.update, qrcode.updated)."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi.testclient import TestClient

from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append((query, params))
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn

    async def close(self) -> None:
        return None


def _reset_settings() -> None:
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = None


def test_connection_update_open_promove_para_conectado() -> None:
    _reset_settings()
    conn = FakeConn()
    payload = {
        "event": "connection.update",
        "instance": "modelo-abc",
        "data": {"state": "open", "statusReason": 200},
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "connection_open"}
    updates = [(q, p) for (q, p) in conn.queries if "UPDATE barravips.modelos" in q]
    assert any("'conectado'" in q and "evolution_pareado_em = now()" in q for (q, _) in updates)
    assert any(p == ("modelo-abc",) for (_, p) in updates)


def test_connection_update_close_volta_para_desconectado() -> None:
    _reset_settings()
    conn = FakeConn()
    payload = {
        "event": "CONNECTION_UPDATE",  # também aceita forma com underscore
        "instance": "modelo-xyz",
        "data": {"state": "close"},
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "connection_close"}
    updates = [(q, p) for (q, p) in conn.queries if "UPDATE barravips.modelos" in q]
    assert any("'desconectado'" in q for (q, _) in updates)


def test_qrcode_updated_apenas_loga() -> None:
    _reset_settings()
    conn = FakeConn()
    payload = {
        "event": "qrcode.updated",
        "instance": "modelo-abc",
        "data": {"qrcode": {"base64": "data:image/png;base64,AAAA"}},
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "qrcode_logged"}
    assert all("UPDATE barravips.modelos" not in q for (q, _) in conn.queries)


def test_mensagem_de_instance_desconhecida_retorna_unknown() -> None:
    _reset_settings()
    conn = FakeConn()
    payload = {
        "instance": "modelo-nao-cadastrado",
        "data": {
            "key": {"id": "MSG-NEW", "remoteJid": "5521999999999@s.whatsapp.net"},
            "message": {"conversation": "oi"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "unknown_instance"}
    insert_msg = [q for (q, _) in conn.queries if "INSERT INTO barravips.mensagens" in q]
    assert insert_msg == []
