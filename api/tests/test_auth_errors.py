from uuid import uuid4

from fastapi.testclient import TestClient

from barra.main import app


def _token(papel: str = "fernando", ativo: bool = True) -> str:
    return f"test:{uuid4()}:{papel}:{str(ativo).lower()}"


def test_health_publico() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_v1_exige_auth() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/saude")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NAO_AUTENTICADO"


def test_v1_rejeita_token_invalido() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/saude", headers={"Authorization": "Bearer invalido"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NAO_AUTENTICADO"


def test_v1_rejeita_sem_permissao() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/v1/saude",
            headers={"Authorization": f"Bearer {_token('vendedor_read_only')}"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SEM_PERMISSAO"


def test_v1_aceita_fernando_ativo() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/saude", headers={"Authorization": f"Bearer {_token()}"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
