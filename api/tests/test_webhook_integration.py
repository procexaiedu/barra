"""Integração do webhook Evolution: idempotência e outbound do backend ignorado."""

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
    """Conn fake que registra queries e retorna respostas determinísticas."""

    def __init__(self, *, mensagem_existe: bool, envio_existe: bool) -> None:
        self.mensagem_existe = mensagem_existe
        self.envio_existe = envio_existe
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.mensagem_existe else [])
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.envio_existe else [])
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn

    async def close(self) -> None:
        return None


def _payload_grupo(message_id: str = "MSG-1", from_me: bool = True) -> dict[str, Any]:
    return {
        "instance": "barra",
        "data": {
            "key": {
                "id": message_id,
                "remoteJid": "120363000000000000@g.us",
                "fromMe": from_me,
            },
            "message": {"conversation": "finalizado 1000 #12"},
        },
    }


def _configurar_grupo() -> None:
    settings = app.state.settings
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None


def test_webhook_idempotente_nao_duplica_mensagem() -> None:
    _configurar_grupo()
    settings = app.state.settings
    settings.evolution_grupo_coordenacao_jid = "outro-jid@g.us"  # força ramo cliente
    conn = FakeConn(mensagem_existe=True, envio_existe=False)
    payload = {
        "instance": "barra",
        "data": {
            "key": {"id": "MSG-DUPL", "remoteJid": "5521999999999@s.whatsapp.net"},
            "message": {"conversation": "oi"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "duplicate"}
    insert_msg = [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q]
    assert insert_msg == []


def test_webhook_outbound_do_backend_e_ignorado_no_grupo() -> None:
    _configurar_grupo()
    conn = FakeConn(mensagem_existe=False, envio_existe=True)
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=_payload_grupo("OUTBOUND-1"))
    assert response.status_code == 200
    assert response.json() == {"status": "outbound_ignored"}
    update_atendimento = [q for q in conn.queries if "UPDATE barravips.atendimentos" in q]
    assert update_atendimento == []


def test_webhook_token_invalido_retorna_401() -> None:
    settings = app.state.settings
    settings.evolution_webhook_token = "secreto"
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    try:
        with TestClient(app) as client:
            app.state.db_pool = FakePool(conn)
            response = client.post(
                "/webhook/evolution",
                json=_payload_grupo("X"),
                headers={"X-Webhook-Token": "errado"},
            )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "WEBHOOK_NAO_AUTORIZADO"
    finally:
        settings.evolution_webhook_token = ""
