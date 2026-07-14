"""Integração de DELETE /v1/atendimentos/{id} — exclusão de gestão do painel.

Verifica que a exclusão remove o bloqueio vinculado (senão sobraria avulso
travando a agenda), apaga o atendimento (CASCADE cuida do resto no banco real) e
limpa os objetos de mídia no MinIO. 404 quando o atendimento não existe.
"""

from typing import Any
from uuid import uuid4

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
    def __init__(
        self,
        *,
        atendimento: dict[str, Any] | None,
        media_keys: list[str] | None = None,
    ) -> None:
        self.atendimento = atendimento
        self.media_keys = media_keys or []
        self.queries: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append((query, params))

        if "SELECT id FROM barravips.atendimentos WHERE id" in query:
            return _Result([self.atendimento] if self.atendimento else [])
        if "SELECT media_object_key FROM barravips.atendimento_midias" in query:
            return _Result([{"media_object_key": k} for k in self.media_keys])
        return _Result([])


class FakeMinio:
    def __init__(self) -> None:
        self.objetos_removidos: list[tuple[str, str]] = []

    def remove_object(self, bucket: str, key: str) -> None:
        self.objetos_removidos.append((bucket, key))


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def test_excluir_atendimento_apaga_bloqueio_e_atendimento_e_limpa_minio() -> None:
    atendimento_id = uuid4()
    key = f"atendimentos/{atendimento_id}/midias/abc/foto.jpg"
    fake = FakeConn(atendimento={"id": atendimento_id}, media_keys=[key])
    minio = FakeMinio()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = minio
            try:
                response = client.delete(f"/v1/atendimentos/{atendimento_id}", headers=_token())
                bucket = app.state.settings.minio_bucket_media
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 204, response.text

        # Deleta o bloqueio vinculado ANTES do atendimento (agenda não fica travada).
        deletes = [q for q, _ in fake.queries if q.startswith("DELETE FROM")]
        assert any("DELETE FROM barravips.bloqueios WHERE atendimento_id" in q for q in deletes)
        assert any("DELETE FROM barravips.atendimentos WHERE id" in q for q in deletes)
        # Objeto de mídia foi removido do MinIO.
        assert minio.objetos_removidos == [(bucket, key)]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_excluir_atendimento_inexistente_retorna_404() -> None:
    atendimento_id = uuid4()
    fake = FakeConn(atendimento=None)

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            minio_anterior = getattr(app.state, "minio", None)
            app.state.minio = FakeMinio()
            try:
                response = client.delete(f"/v1/atendimentos/{atendimento_id}", headers=_token())
            finally:
                app.state.minio = minio_anterior
        assert response.status_code == 404
        # Nada foi deletado.
        assert not any(q.startswith("DELETE FROM") for q, _ in fake.queries)
    finally:
        app.dependency_overrides.pop(get_conn, None)
