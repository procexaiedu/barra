"""Dados cadastrais da modelo (ADR 0007): validação de CPF, ranges e gravação."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def _modelo_row(modelo_id: UUID) -> dict[str, Any]:
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
        "tipo_fisico": None,
        "status": "ativa",
        "evolution_instance_id": None,
        "evolution_status": "desconectado",
        "evolution_pareado_em": None,
        "coordenacao_chat_id": None,
        "foto_perfil_object_key": None,
        "rg": "12.345.678-9",
        "cpf": "52998224725",
        "endereco_residencial_formatado": "Rua X, 100 - Rio de Janeiro",
        "place_id_residencial": "ChIJ_residencial",
        "cor_pele": "parda",
        "cor_cabelo": "castanho_escuro",
        "altura_cm": 170,
        "tamanho_pe": 37,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


class FakeConnCriar:
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


class _DupCPF(UniqueViolation):
    """UniqueViolation com constraint_name do índice de CPF (simula colisão)."""

    @property
    def diag(self) -> Any:  # type: ignore[override]
        class _D:
            constraint_name = "modelos_cpf_unique"

        return _D()


class FakeConnCpfDuplicado:
    def __init__(self) -> None:
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "INSERT INTO barravips.modelos" in query:
            raise _DupCPF("duplicate key value violates unique constraint")
        return _Result([])


class FakeConnEditar:
    def __init__(self, modelo_id: UUID) -> None:
        self.modelo_id = modelo_id
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))
        if "FROM barravips.modelos WHERE id" in query:
            return _Result([_modelo_row(self.modelo_id)])
        if "UPDATE barravips.modelos" in query:
            return _Result([_modelo_row(self.modelo_id)])
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _payload_base(**extra: Any) -> dict[str, Any]:
    base = {
        "nome": "Aurora",
        "idade": 26,
        "numero_whatsapp": "5521999990000",
        "valor_padrao": 0,
        "tipo_atendimento_aceito": ["interno"],
        "idiomas": ["pt-BR"],
    }
    base.update(extra)
    return base


def _override(fake: Any) -> None:
    async def _gen():
        yield fake

    app.dependency_overrides[get_conn] = _gen


def test_criar_modelo_com_dados_cadastrais_grava_no_insert() -> None:
    modelo_id = uuid4()
    fake = FakeConnCriar(modelo_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos",
                json=_payload_base(
                    rg="12.345.678-9",
                    cpf="529.982.247-25",
                    endereco_residencial_formatado="Rua X, 100 - Rio de Janeiro",
                    place_id_residencial="ChIJ_residencial",
                    cor_pele="parda",
                    cor_cabelo="castanho_escuro",
                    altura_cm=170,
                    tamanho_pe=37,
                ),
                headers=_token(),
            )
        assert response.status_code == 201, response.text
        insert_query, insert_params = next(
            (q, p) for q, p in fake.executes if "INSERT INTO barravips.modelos" in q
        )
        for coluna in (
            "rg",
            "cpf",
            "endereco_residencial_formatado",
            "place_id_residencial",
            "cor_pele",
            "cor_cabelo",
            "altura_cm",
            "tamanho_pe",
        ):
            assert coluna in insert_query
        params = tuple(insert_params)  # type: ignore[arg-type]
        # CPF normalizado para 11 dígitos (sem máscara).
        assert "52998224725" in params
        assert "parda" in params
        assert 170 in params
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_cpf_normaliza_mascara() -> None:
    modelo_id = uuid4()
    fake = FakeConnCriar(modelo_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos", json=_payload_base(cpf="529.982.247-25"), headers=_token()
            )
        assert response.status_code == 201, response.text
        _, insert_params = next(
            (q, p) for q, p in fake.executes if "INSERT INTO barravips.modelos" in q
        )
        assert "52998224725" in tuple(insert_params)  # type: ignore[arg-type]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_cpf_invalido_retorna_422() -> None:
    fake = FakeConnCriar(uuid4())
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos", json=_payload_base(cpf="529.982.247-20"), headers=_token()
            )
        assert response.status_code == 422, response.text
        assert not any("INSERT" in q for q, _ in fake.executes)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_cpf_repetido_retorna_422() -> None:
    fake = FakeConnCriar(uuid4())
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos", json=_payload_base(cpf="111.111.111-11"), headers=_token()
            )
        assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_altura_fora_do_range_retorna_422() -> None:
    fake = FakeConnCriar(uuid4())
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post("/v1/modelos", json=_payload_base(altura_cm=250), headers=_token())
        assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_tamanho_pe_fora_do_range_retorna_422() -> None:
    fake = FakeConnCriar(uuid4())
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post("/v1/modelos", json=_payload_base(tamanho_pe=60), headers=_token())
        assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_cor_invalida_retorna_422() -> None:
    fake = FakeConnCriar(uuid4())
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos", json=_payload_base(cor_pele="azul"), headers=_token()
            )
        assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_criar_modelo_cpf_duplicado_retorna_409() -> None:
    fake = FakeConnCpfDuplicado()
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/modelos", json=_payload_base(cpf="529.982.247-25"), headers=_token()
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CPF_DUPLICADO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_editar_modelo_aceita_dados_cadastrais() -> None:
    modelo_id = uuid4()
    fake = FakeConnEditar(modelo_id)
    _override(fake)
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/v1/modelos/{modelo_id}",
                json={"altura_cm": 168, "cor_cabelo": "ruivo", "cpf": "529.982.247-25"},
                headers=_token(),
            )
        assert response.status_code == 200, response.text
        update_query, update_params = next(
            (q, p) for q, p in fake.executes if "UPDATE barravips.modelos" in q
        )
        assert "altura_cm = %s" in update_query
        assert "cor_cabelo = %s" in update_query
        assert "cpf = %s" in update_query
        params = tuple(update_params)  # type: ignore[arg-type]
        assert "52998224725" in params
        assert 168 in params
    finally:
        app.dependency_overrides.pop(get_conn, None)
