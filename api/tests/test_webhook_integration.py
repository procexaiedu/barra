"""Integração do webhook Evolution: idempotência, outbound ignorado e webhook fino (M3c)."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from barra.main import app

_MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENTE_ID = UUID("22222222-2222-2222-2222-222222222222")
_CONVERSA_ID = UUID("33333333-3333-3333-3333-333333333333")


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """Conn fake que registra queries/binds e retorna respostas determinísticas."""

    def __init__(self, *, mensagem_existe: bool, envio_existe: bool) -> None:
        self.mensagem_existe = mensagem_existe
        self.envio_existe = envio_existe
        self.queries: list[str] = []
        self.binds: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        self.binds.append((query, params))
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.mensagem_existe else [])
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.envio_existe else [])
        if "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"?column?": 1}])  # _instance_cadastrada
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO_ID}])
        if "INSERT INTO barravips.clientes" in query:
            return _Result([{"id": _CLIENTE_ID}])
        if "INSERT INTO barravips.conversas" in query:
            return _Result([{"id": _CONVERSA_ID}])
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn

    async def close(self) -> None:
        return None


class FakeArq:
    """ArqRedis fake: registra set/enqueue_job; aclose é chamado no teardown do lifespan."""

    def __init__(self) -> None:
        self.sets: list[tuple[str, Any, Any]] = []
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: Any, ex: Any = None) -> None:
        self.sets.append((key, value, ex))

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.enqueued.append((name, kwargs))

    async def aclose(self) -> None:
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


def test_webhook_cliente_texto_persiste_orfa_e_enfileira_turno() -> None:
    """Webhook fino (M3c): texto do cliente → mensagem órfã + enqueue, sem atendimento eager."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = "grupo-diferente@g.us"  # força ramo cliente
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    arq = FakeArq()
    payload = {
        "instance": "barra",
        "data": {
            "key": {"id": "MSG-TXT-1", "remoteJid": "5521988887777@s.whatsapp.net"},
            "message": {"conversation": "oi, tudo bem?"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "received"}

    # Mensagem persistida como órfã: atendimento_id (2º bind) é NULL.
    insert_msg = [(q, p) for (q, p) in conn.binds if "INSERT INTO barravips.mensagens" in q]
    assert len(insert_msg) == 1
    _, params = insert_msg[0]
    assert params is not None
    assert params[0] == _CONVERSA_ID  # conversa_id
    assert params[1] is None  # atendimento_id NULL

    # Nenhum atendimento criado no caminho do cliente (criação é do coordenador).
    assert [q for q in conn.queries if "INSERT INTO barravips.atendimentos" in q] == []

    # Turno enfileirado uma única vez, com _job_id estático de coalescência.
    assert len(arq.enqueued) == 1
    nome, kwargs = arq.enqueued[0]
    assert nome == "processar_turno"
    assert kwargs["conversa_id"] == str(_CONVERSA_ID)
    assert kwargs["_job_id"] == f"turno:{_CONVERSA_ID}"
    # pending + debounce marcados em Redis.
    chaves = {chave for (chave, _v, _ex) in arq.sets}
    assert f"pending:conv:{_CONVERSA_ID}" in chaves
    assert f"debounce:conv:{_CONVERSA_ID}" in chaves


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
