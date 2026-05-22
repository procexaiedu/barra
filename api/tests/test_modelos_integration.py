"""Integracao das rotas /v1/modelos."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _modelo_row(modelo_id: UUID, *, status: str = "ativa") -> dict[str, Any]:
    return {
        "id": modelo_id,
        "nome": "Aurora",
        "idade": 26,
        "numero_whatsapp": "5521999990000",
        "valor_padrao": 0,
        "percentual_repasse": None,
        "chave_pix": None,
        "titular_chave": None,
        "idiomas": ["pt-BR"],
        "localizacao_operacional": None,
        "endereco_formatado": None,
        "latitude": None,
        "longitude": None,
        "place_id": None,
        "tipo_atendimento_aceito": ["interno"],
        "status": status,
        "evolution_instance_id": None,
        "evolution_status": "desconectado",
        "evolution_pareado_em": None,
        "coordenacao_chat_id": None,
        "foto_perfil_object_key": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


class FakeConnCriar:
    """INSERT em barravips.modelos retorna o row criado (RETURNING *)."""

    def __init__(self, modelo_id: UUID) -> None:
        self.modelo_id = modelo_id
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.modelos" in query:
            return _Result([_modelo_row(self.modelo_id)])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


# --- Task 8619826c: POST /v1/modelos nao deve usar _serializar_servico ---


def test_criar_modelo_retorna_201_com_modelo_serializado() -> None:
    modelo_id = uuid4()
    fake = FakeConnCriar(modelo_id)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos",
                json={
                    "nome": "Aurora",
                    "idade": 26,
                    "numero_whatsapp": "5521999990000",
                    "valor_padrao": 0,
                    "tipo_atendimento_aceito": ["interno"],
                    "idiomas": ["pt-BR"],
                },
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        body = response.json()
        # _modelo_com_foto serializa o row de modelo (nao o de modelo_servicos).
        assert body["id"] == str(modelo_id)
        assert body["nome"] == "Aurora"
        assert body["numero_whatsapp"] == "5521999990000"
        assert body["tipo_atendimento_aceito"] == ["interno"]
        assert body["foto_perfil_url"] is None
    finally:
        app.dependency_overrides.pop(get_conn, None)
