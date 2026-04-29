from fastapi.testclient import TestClient

from barra.main import app


def test_saude_v1() -> None:
    with TestClient(app) as cliente:
        r = cliente.get("/v1/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
