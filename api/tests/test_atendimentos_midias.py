"""Integração de /v1/atendimentos/{id}/midias — anexo interno separado do histórico."""

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


class FakeConn:
    """Conn fake que registra todas as queries executadas e devolve linhas plausíveis."""

    def __init__(
        self,
        *,
        atendimento_id: UUID,
        midia_existente: dict[str, Any] | None = None,
    ) -> None:
        self.atendimento_id = atendimento_id
        self.midia_existente = midia_existente
        self.queries: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append((query, params))

        if "SELECT id FROM barravips.atendimentos WHERE id" in query:
            return _Result([{"id": self.atendimento_id}])

        if "INSERT INTO barravips.atendimento_midias" in query:
            assert isinstance(params, tuple)
            _atendimento_id, tipo, nome_arquivo, key, _user_id = params
            return _Result(
                [
                    {
                        "id": uuid4(),
                        "tipo": tipo,
                        "nome_arquivo": nome_arquivo,
                        "media_object_key": key,
                        "created_at": datetime.now(UTC),
                    }
                ]
            )

        if "SELECT media_object_key FROM barravips.atendimento_midias" in query:
            return _Result([self.midia_existente] if self.midia_existente else [])

        if "DELETE FROM barravips.atendimento_midias" in query:
            return _Result([])

        # Default: sem linhas.
        return _Result([])


class FakeMinio:
    def __init__(self) -> None:
        self.objetos_put: list[tuple[str, str]] = []
        self.objetos_removidos: list[tuple[str, str]] = []

    def put_object(
        self,
        bucket: str,
        key: str,
        data: Any,
        length: int,
        content_type: str | None = None,
    ) -> None:
        self.objetos_put.append((bucket, key))

    def remove_object(self, bucket: str, key: str) -> None:
        self.objetos_removidos.append((bucket, key))

    def presigned_get_object(self, bucket: str, key: str, expires: Any = None) -> str:
        return f"https://fake-minio/{bucket}/{key}"


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def test_upload_midia_grava_em_atendimento_midias_e_nao_em_mensagens() -> None:
    """Caso 1: POST imagem → linha em atendimento_midias; mensagens permanece intacta."""
    atendimento_id = uuid4()
    fake = FakeConn(atendimento_id=atendimento_id)
    minio = FakeMinio()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            # Sobrescreve após o lifespan inicializar app.state.minio.
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = minio
            try:
                response = client.post(
                    f"/v1/atendimentos/{atendimento_id}/midias",
                    files={"arquivo": ("foto.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
                    data={"tipo": "imagem"},
                    headers=_token(),
                )
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["tipo"] == "imagem"
        assert body["nome_arquivo"] == "foto.jpg"
        assert body["media_url"].startswith("https://fake-minio/")

        # Insert foi em atendimento_midias, não em mensagens.
        inserts_midias = [q for q, _ in fake.queries if "INSERT INTO barravips.atendimento_midias" in q]
        inserts_mensagens = [q for q, _ in fake.queries if "INSERT INTO barravips.mensagens" in q]
        assert len(inserts_midias) == 1
        assert inserts_mensagens == []

        # Objeto foi para o MinIO.
        assert len(minio.objetos_put) == 1
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_deletar_midia_remove_de_atendimento_midias_e_do_minio() -> None:
    """Caso 2: DELETE midia → linha some de atendimento_midias e objeto do MinIO."""
    atendimento_id = uuid4()
    midia_id = uuid4()
    key = f"atendimentos/{atendimento_id}/midias/abc/foto.jpg"
    fake = FakeConn(
        atendimento_id=atendimento_id,
        midia_existente={"media_object_key": key},
    )
    minio = FakeMinio()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = minio
            try:
                response = client.delete(
                    f"/v1/atendimentos/{atendimento_id}/midias/{midia_id}",
                    headers=_token(),
                )
                bucket = app.state.settings.minio_bucket_media
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 204, response.text

        deletes_midias = [q for q, _ in fake.queries if "DELETE FROM barravips.atendimento_midias" in q]
        deletes_mensagens = [q for q, _ in fake.queries if "DELETE FROM barravips.mensagens" in q]
        assert len(deletes_midias) == 1
        assert deletes_mensagens == []
        assert minio.objetos_removidos == [(bucket, key)]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_deletar_midia_inexistente_retorna_404() -> None:
    """DELETE de midia que não existe retorna 404 sem tocar em mensagens."""
    atendimento_id = uuid4()
    midia_id = uuid4()
    fake = FakeConn(atendimento_id=atendimento_id, midia_existente=None)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = FakeMinio()
            try:
                response = client.delete(
                    f"/v1/atendimentos/{atendimento_id}/midias/{midia_id}",
                    headers=_token(),
                )
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 404
        deletes_mensagens = [q for q, _ in fake.queries if "DELETE FROM barravips.mensagens" in q]
        assert deletes_mensagens == []
    finally:
        app.dependency_overrides.pop(get_conn, None)


class FakeConnObterAtendimento:
    """Devolve dados plausíveis para GET /v1/atendimentos/{id}, com mensagens e midias separadas."""

    def __init__(
        self,
        atendimento_id: UUID,
        *,
        mensagens: list[dict[str, Any]],
        midias_internas: list[dict[str, Any]],
    ) -> None:
        self.atendimento_id = atendimento_id
        self.mensagens = mensagens
        self.midias_internas = midias_internas
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.atendimentos a" in query and "JOIN barravips.clientes" in query:
            cliente_id = uuid4()
            modelo_id = uuid4()
            conversa_id = uuid4()
            return _Result(
                [
                    {
                        "id": self.atendimento_id,
                        "cliente_id": cliente_id,
                        "modelo_id": modelo_id,
                        "conversa_id": conversa_id,
                        "bloqueio_id": None,
                        "cliente_nome": "Cliente Teste",
                        "cliente_telefone": "5521999999999",
                        "modelo_nome": "Modelo Teste",
                        "percentual_repasse": None,
                        "bloqueio_inicio": None,
                        "bloqueio_fim": None,
                        "bloqueio_estado": None,
                        "conversa_recorrente": False,
                        "conversa_observacoes": None,
                        "conversa_ultimo_motivo_perda": None,
                    }
                ]
            )
        if "FROM barravips.mensagens" in query:
            return _Result(self.mensagens)
        if "FROM barravips.atendimento_midias" in query:
            return _Result(self.midias_internas)
        return _Result([])


def test_obter_atendimento_separa_mensagens_de_midias_internas() -> None:
    """Caso 3: mensagem direcao='cliente' tipo='imagem' (webhook) continua em mensagens;
    anexo interno aparece em midias_internas. Os dois conjuntos não se misturam."""
    atendimento_id = uuid4()
    mensagem_cliente = {
        "id": uuid4(),
        "atendimento_id": atendimento_id,
        "direcao": "cliente",
        "tipo": "imagem",
        "conteudo": "foto-portaria.jpg",
        "media_object_key": "evolution/cliente/abc.jpg",
        "evolution_message_id": "EVOLUTION-1",
        "created_at": datetime.now(UTC),
    }
    midia_interna = {
        "id": uuid4(),
        "tipo": "documento",
        "nome_arquivo": "contrato.pdf",
        "media_object_key": "atendimentos/x/midias/y/contrato.pdf",
        "created_at": datetime.now(UTC),
    }
    fake = FakeConnObterAtendimento(
        atendimento_id,
        mensagens=[mensagem_cliente],
        midias_internas=[midia_interna],
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = FakeMinio()
            try:
                response = client.get(f"/v1/atendimentos/{atendimento_id}", headers=_token())
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 200, response.text
        body = response.json()

        # Caso 3: mensagem do cliente continua em mensagens.
        assert len(body["mensagens"]) == 1
        assert body["mensagens"][0]["direcao"] == "cliente"
        assert body["mensagens"][0]["tipo"] == "imagem"

        # Anexo interno aparece em midias_internas, separado.
        assert "midias_internas" in body
        assert len(body["midias_internas"]) == 1
        assert body["midias_internas"][0]["tipo"] == "documento"
        assert body["midias_internas"][0]["nome_arquivo"] == "contrato.pdf"
        assert body["midias_internas"][0]["media_url"].startswith("https://fake-minio/")
    finally:
        app.dependency_overrides.pop(get_conn, None)
