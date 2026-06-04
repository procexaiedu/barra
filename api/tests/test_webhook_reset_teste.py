"""Comando de TESTE `#reset` no webhook: zera o estado da modelo, com gate por instância.

Espelha os fakes de `test_webhook_integration.py` (FakeConn/FakePool/FakeArq), adicionando
`rowcount` ao result (o `resetar_modelo` lê `cur.rowcount`).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from barra.main import app
from barra.webhook.parser import MensagemEvolution
from barra.webhook.reset_teste import resetar_modelo
from barra.webhook.routes import _eh_reset_teste

_MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
_CONVERSA_ID = UUID("33333333-3333-3333-3333-333333333333")


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self, *, modelo_existe: bool = True) -> None:
        self.modelo_existe = modelo_existe
        self.queries: list[str] = []
        self.binds: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        self.binds.append((query, params))
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([])  # nunca duplicada
        if "WHERE coordenacao_chat_id" in query:
            return _Result([])  # não é grupo de coordenação
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO_ID}] if self.modelo_existe else [])
        if "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"?column?": 1}])
        if "SELECT id FROM barravips.conversas WHERE modelo_id" in query:
            return _Result([{"id": _CONVERSA_ID}])
        if "INSERT INTO barravips.clientes" in query:
            return _Result([{"id": UUID("22222222-2222-2222-2222-222222222222")}])
        if "INSERT INTO barravips.conversas" in query:
            return _Result([{"id": _CONVERSA_ID}])
        if query.lstrip().upper().startswith("DELETE"):
            return _Result([], rowcount=1)
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self.conn

    async def close(self) -> None:
        return None


class FakeArq:
    def __init__(self) -> None:
        self.sets: list[tuple[str, Any, Any]] = []
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: Any, ex: Any = None) -> None:
        self.sets.append((key, value, ex))

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.enqueued.append((name, kwargs))

    async def aclose(self) -> None:
        return None


def _payload_reset(texto: str = "#reset") -> dict[str, Any]:
    return {
        "instance": "barra",
        "data": {
            "key": {"id": "MSG-RESET-1", "remoteJid": "120363000000000000@g.us"},
            "message": {"conversation": texto},
        },
    }


def _configurar(reset_instances: list[str]) -> None:
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = "grupo-diferente@g.us"  # força ramo cliente
    settings.reset_teste_instances = reset_instances
    settings.evolution_base_url = ""  # confirmação vira no-op (best-effort)


def _msg(texto: str, instance: str = "barra") -> MensagemEvolution:
    return MensagemEvolution(
        evolution_message_id="X",
        instance_id=instance,
        remote_jid="120363000000000000@g.us",
        sender_jid=None,
        from_me=False,
        texto=texto,
        tipo="texto",
        media_url=None,
        quoted_message_id=None,
    )


def test_eh_reset_teste_respeita_gate_e_texto() -> None:
    cfg = SimpleNamespace(reset_teste_instances=["barra"])
    assert _eh_reset_teste(_msg("#reset"), cfg) is True
    assert _eh_reset_teste(_msg("  #RESET  "), cfg) is True  # trim + case-insensitive
    assert _eh_reset_teste(_msg("#reset agora"), cfg) is False  # só o token exato
    assert _eh_reset_teste(_msg("oi"), cfg) is False
    # Gate: instância fora da allowlist não reseta.
    assert _eh_reset_teste(_msg("#reset", instance="outra"), cfg) is False
    assert _eh_reset_teste(_msg("#reset"), SimpleNamespace(reset_teste_instances=[])) is False


def test_webhook_reset_zera_estado_e_nao_persiste_mensagem() -> None:
    _configurar(reset_instances=["barra"])
    conn = FakeConn()
    arq = FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=_payload_reset())

    assert response.status_code == 200
    assert response.json() == {"status": "reset"}
    # Rodou o wipe (pelo menos o DELETE de conversas).
    assert any("DELETE FROM barravips.conversas WHERE modelo_id" in q for q in conn.queries)
    # Não tratou como mensagem de cliente: sem INSERT de mensagem e sem turno enfileirado.
    assert [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q] == []
    assert arq.enqueued == []


def test_webhook_reset_com_gate_desligado_e_mensagem_normal() -> None:
    """Sem a instância na allowlist, `#reset` segue como texto de cliente comum (prova o gate)."""
    _configurar(reset_instances=[])  # gate desligado
    conn = FakeConn()
    arq = FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=_payload_reset())

    assert response.status_code == 200
    assert response.json() == {"status": "received"}
    # Caiu no ramo cliente: persistiu a mensagem e enfileirou o turno; nenhum DELETE.
    assert any("INSERT INTO barravips.mensagens" in q for q in conn.queries)
    assert [q for q in conn.queries if q.lstrip().upper().startswith("DELETE")] == []
    assert len(arq.enqueued) == 1


@pytest.mark.asyncio
async def test_resetar_modelo_instancia_desconhecida_retorna_none() -> None:
    conn = FakeConn(modelo_existe=False)
    assert await resetar_modelo(conn, "inexistente") is None  # type: ignore[arg-type]
    # Não tentou apagar nada.
    assert [q for q in conn.queries if q.lstrip().upper().startswith("DELETE")] == []
