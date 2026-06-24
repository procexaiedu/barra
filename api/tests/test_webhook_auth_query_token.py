"""Auth do /webhook/evolution: token por header E por query string.

Com o webhook-router no meio (instancia -> router -> Barra) o header de auth NAO e repassado
e o modal do router so guarda Nome+URL (sem campo de header). Por isso o handler aceita o token
tambem via `?token=` na query — sem isso a entrega do router tomava 401 e a mensagem sumia
(sintoma real: `#reset` no grupo de teste sem resposta). Estes testes trancam os tres canais de
credencial aceitos e a rejeicao contra regressao.

Deterministico: o payload passa a auth e cai em 'ignored' (extrair_mensagem -> None) ANTES de
tocar o banco, entao isola a AUTH sem precisar de Postgres.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from barra.main import app

_TOKEN = "tok-teste-123"
# messages.upsert sem `data` util: sem key/message -> extrair_mensagem devolve None -> 'ignored'.
_PAYLOAD = {"event": "messages.upsert", "instance": "barra", "data": {}}


class _PoolDummy:
    """db_pool nao-nulo: o ramo 'ignored' retorna antes de abrir conexao, entao nunca e usado.
    So precisa do `close()` async que o lifespan chama no shutdown do TestClient."""

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _token_configurado() -> Iterator[None]:
    """Crava o token de webhook e restaura o original (isolamento entre testes)."""
    original = app.state.settings.evolution_webhook_token
    app.state.settings.evolution_webhook_token = _TOKEN
    yield
    app.state.settings.evolution_webhook_token = original


def test_sem_token_401() -> None:
    with TestClient(app) as client:
        app.state.db_pool = _PoolDummy()
        resp = client.post("/webhook/evolution", json=_PAYLOAD)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "WEBHOOK_NAO_AUTORIZADO"


def test_token_errado_401() -> None:
    with TestClient(app) as client:
        app.state.db_pool = _PoolDummy()
        resp = client.post(
            "/webhook/evolution", json=_PAYLOAD, headers={"X-Webhook-Token": "errado"}
        )
    assert resp.status_code == 401


def test_header_x_webhook_token_ok() -> None:
    with TestClient(app) as client:
        app.state.db_pool = _PoolDummy()
        resp = client.post("/webhook/evolution", json=_PAYLOAD, headers={"X-Webhook-Token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}


def test_header_authorization_bearer_ok() -> None:
    with TestClient(app) as client:
        app.state.db_pool = _PoolDummy()
        resp = client.post(
            "/webhook/evolution", json=_PAYLOAD, headers={"Authorization": f"Bearer {_TOKEN}"}
        )
    assert resp.json() == {"status": "ignored"}


def test_query_token_ok() -> None:
    """O caminho do webhook-router: token na query, sem nenhum header de auth."""
    with TestClient(app) as client:
        app.state.db_pool = _PoolDummy()
        resp = client.post(f"/webhook/evolution?token={_TOKEN}", json=_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
