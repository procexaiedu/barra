"""Integracao das rotas /v1/modelos."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.core.evolution import EvolutionClient
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _modelo_row(
    modelo_id: UUID,
    *,
    status: str = "ativa",
    evolution_instance_id: str | None = None,
    coordenacao_chat_id: str | None = None,
) -> dict[str, Any]:
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
        "evolution_instance_id": evolution_instance_id,
        "evolution_status": "conectado" if evolution_instance_id else "desconectado",
        "evolution_pareado_em": None,
        "coordenacao_chat_id": coordenacao_chat_id,
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


class FakeConnPausar:
    """Cobre o fluxo de pausa: SELECT do modelo, counts e UPDATEs."""

    def __init__(self, modelo_row: dict[str, Any]) -> None:
        self.modelo_row = modelo_row
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.modelos WHERE id" in query:
            return _Result([self.modelo_row])
        if "count(*)" in query:
            return _Result([{"count": 0}])
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


# --- Task 9597d79d: POST /v1/modelos/{id}/pausar ---


def test_pausar_modelo_sucesso_sem_evolution() -> None:
    modelo_id = uuid4()
    fake = FakeConnPausar(_modelo_row(modelo_id))

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post(f"/v1/modelos/{modelo_id}/pausar", json={}, headers=_token())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pausada"
        assert body["card_enviado"] is False
        pausou = any(
            "UPDATE barravips.modelos SET status = 'pausada'" in q for q, _ in fake.executes
        )
        assert pausou
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_modelo_ja_pausada_retorna_409() -> None:
    modelo_id = uuid4()
    fake = FakeConnPausar(_modelo_row(modelo_id, status="pausada"))

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post(f"/v1/modelos/{modelo_id}/pausar", json={}, headers=_token())
        assert response.status_code == 409, response.text
        # Mensagem clara do backend (o frontend exibe via error.message).
        assert response.json()["error"]["message"] == "Modelo nao esta ativa."
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_pausar_modelo_sucesso_mesmo_com_evolution_falhando(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modelo_id = uuid4()
    fake = FakeConnPausar(
        _modelo_row(
            modelo_id,
            evolution_instance_id="modelo-x",
            coordenacao_chat_id="120363000000000000@g.us",
        )
    )

    async def _override():
        yield fake

    async def _explode(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("Evolution offline")

    # Com base_url + instance + coordenacao configurados, _enviar_card_pausa tenta enviar.
    monkeypatch.setattr(app.state.settings, "evolution_base_url", "http://evolution.local")
    monkeypatch.setattr(EvolutionClient, "enviar_texto", _explode)

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.post(f"/v1/modelos/{modelo_id}/pausar", json={}, headers=_token())
        # A pausa nao pode falhar por causa de erro no envio do card.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pausada"
        assert body["card_enviado"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)
