"""Mídia inbound da Evolution GO: o webhook dela não traz base64 nem URL baixável.

A EvoGo (whatsmeow) decifra a mídia e a sobe no MinIO com key
`evolution-go-medias/<evolution_message_id>.<ext>`; a `url` do payload aponta pro CDN cifrado do
WhatsApp e o campo nem chega ao parser (vem `URL`, PascalCase). Sem o fallback de bucket, toda
mídia recebida degradava para `tipo='texto'` vazio — em prod (24/07) dois áudios e um print do
cliente viraram mensagens vazias e a IA respondeu "não consegui ouvir teu áudio".
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from barra.main import app
from barra.webhook.parser import MensagemEvolution
from barra.webhook.routes import _buscar_midia_evogo, _ler_midia_evogo

_BUCKET = "evolution-go"
_PREFIXO = "evolution-go-medias/"
_MSG_ID = "3A43B4F0A79BB205132F"
_OGG = b"OggS\x00audio"

_MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENTE_ID = UUID("22222222-2222-2222-2222-222222222222")
_CONVERSA_ID = UUID("33333333-3333-3333-3333-333333333333")
_MENSAGEM_ID = UUID("44444444-4444-4444-4444-444444444444")


class _Objeto:
    def __init__(self, object_name: str, size: int | None) -> None:
        self.object_name = object_name
        self.size = size


class _Resposta:
    def __init__(self, dados: bytes, content_type: str) -> None:
        self._dados = dados
        self.headers = {"content-type": content_type}
        self.fechada = False

    def read(self, amt: int | None = None) -> bytes:
        return self._dados if amt is None else self._dados[:amt]

    def close(self) -> None:
        self.fechada = True

    def release_conn(self) -> None:
        return None


class FakeMinio:
    """MinIO fake: `objetos` mapeia key -> (bytes, content_type); registra puts e listagens."""

    def __init__(
        self, objetos: dict[str, tuple[bytes, str]] | None = None, *, sem_size: bool = False
    ) -> None:
        self.objetos = objetos or {}
        self.sem_size = sem_size
        self.listagens: list[str] = []
        self.puts: list[tuple[str, str, int, str]] = []
        self.respostas: list[_Resposta] = []

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False) -> list[_Objeto]:
        self.listagens.append(prefix)
        return [
            _Objeto(key, None if self.sem_size else len(dados))
            for key, (dados, _) in self.objetos.items()
            if key.startswith(prefix)
        ]

    def get_object(self, bucket: str, key: str) -> _Resposta:
        dados, ct = self.objetos[key]
        resp = _Resposta(dados, ct)
        self.respostas.append(resp)
        return resp

    def put_object(
        self, bucket: str, key: str, data: Any, length: int, content_type: str = ""
    ) -> None:
        self.puts.append((bucket, key, length, content_type))


def _msg(tipo: str = "audio", message_id: str = _MSG_ID) -> MensagemEvolution:
    return MensagemEvolution(
        evolution_message_id=message_id,
        instance_id="elitebaby01",
        remote_jid="5511999999999@s.whatsapp.net",
        sender_jid=None,
        from_me=False,
        texto="",
        tipo=tipo,  # type: ignore[arg-type]
        media_url=None,
        quoted_message_id=None,
    )


class _Settings:
    evogo_media_bucket = _BUCKET
    evogo_media_prefix = _PREFIXO
    midia_max_bytes = 25 * 1024 * 1024


def test_le_midia_do_bucket_resolvendo_a_extensao_por_prefixo() -> None:
    # A extensão varia (ogg/jpg/webp): resolvemos por prefixo em vez de adivinhar.
    minio = FakeMinio({f"{_PREFIXO}{_MSG_ID}.ogg": (_OGG, "audio/ogg; codecs=opus")})
    out = _ler_midia_evogo(minio, _BUCKET, _PREFIXO, _MSG_ID, 25 * 1024 * 1024)
    assert out == (_OGG, "audio/ogg")
    assert minio.respostas[0].fechada


def test_objeto_acima_do_teto_e_recusado() -> None:
    minio = FakeMinio({f"{_PREFIXO}{_MSG_ID}.ogg": (b"x" * 2048, "audio/ogg")})
    assert _ler_midia_evogo(minio, _BUCKET, _PREFIXO, _MSG_ID, 1024) is None


def test_objeto_sem_size_na_listagem_ainda_respeita_o_teto() -> None:
    # Sem `size` na listagem a 1ª barreira não vale: a leitura limitada (max_bytes+1) segura.
    minio = FakeMinio({f"{_PREFIXO}{_MSG_ID}.ogg": (b"x" * 2048, "audio/ogg")}, sem_size=True)
    assert _ler_midia_evogo(minio, _BUCKET, _PREFIXO, _MSG_ID, 1024) is None


def test_prefixo_de_outra_mensagem_nao_e_confundido() -> None:
    minio = FakeMinio({f"{_PREFIXO}OUTRO.ogg": (_OGG, "audio/ogg")})
    assert _ler_midia_evogo(minio, _BUCKET, _PREFIXO, _MSG_ID, 25 * 1024 * 1024) is None


@pytest.mark.asyncio
async def test_id_com_travessia_e_recusado_sem_tocar_o_bucket() -> None:
    # O id vem do remetente e entra no prefixo da listagem; ids reais são alfanuméricos.
    minio = FakeMinio()
    out = await _buscar_midia_evogo(minio, _Settings(), _msg(message_id="../outra/conversa"))
    assert out is None
    assert minio.listagens == []


@pytest.mark.asyncio
async def test_segunda_olhada_cobre_a_corrida_do_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    # O upload da EvoGo termina ~50ms antes do webhook: se a 1ª listagem vier vazia, olhamos de novo.
    monkeypatch.setattr("barra.webhook.routes._ESPERA_MIDIA_EVOGO_S", 0)
    minio = FakeMinio()

    listar_original = minio.list_objects

    def listar(bucket: str, prefix: str = "", recursive: bool = False) -> list[_Objeto]:
        if not minio.listagens:  # 1ª chamada: objeto ainda não subiu
            minio.listagens.append(prefix)
            return []
        minio.objetos[f"{_PREFIXO}{_MSG_ID}.ogg"] = (_OGG, "audio/ogg")
        return listar_original(bucket, prefix, recursive)

    monkeypatch.setattr(minio, "list_objects", listar)
    assert await _buscar_midia_evogo(minio, _Settings(), _msg()) == (_OGG, "audio/ogg")


@pytest.mark.asyncio
async def test_erro_do_minio_degrada_sem_estourar(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bucket/policy/MinIO fora não podem virar 500 no webhook (a Evolution reenviaria em loop).
    monkeypatch.setattr("barra.webhook.routes._ESPERA_MIDIA_EVOGO_S", 0)
    minio = FakeMinio()

    def explode(*args: Any, **kwargs: Any) -> list[_Objeto]:
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(minio, "list_objects", explode)
    assert await _buscar_midia_evogo(minio, _Settings(), _msg()) is None


@pytest.mark.asyncio
async def test_midia_ausente_nas_duas_tentativas_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("barra.webhook.routes._ESPERA_MIDIA_EVOGO_S", 0)
    minio = FakeMinio()
    assert await _buscar_midia_evogo(minio, _Settings(), _msg()) is None
    assert len(minio.listagens) == 2


# --- Integração: áudio EvoGo entra como 'audio' e dispara a transcrição ------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(self) -> None:
        self.binds: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.binds.append((query, params))
        if "SELECT 1 FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([])  # não persistida ainda
        if "SELECT id FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([{"id": _MENSAGEM_ID}])
        if "WHERE coordenacao_chat_id" in query:
            return _Result([])
        if "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"?column?": 1}])
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
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: Any, ex: Any = None) -> None:
        return None

    async def enqueue_job(self, name: str, **kwargs: Any) -> Any:
        self.enqueued.append((name, kwargs))
        return object()

    async def aclose(self) -> None:
        return None


def _payload_audio_go() -> dict[str, Any]:
    """Payload real da EvoGo: envelope CamelCase e `URL` (PascalCase) no audioMessage — por isso
    o parser não extrai `media_url` e não há base64 inline."""
    return {
        "event": "Message",
        "instanceName": "elitebaby01",
        "data": {
            "Info": {
                "ID": _MSG_ID,
                "Chat": "5511999999999@s.whatsapp.net",
                "Sender": "5511999999999@s.whatsapp.net",
                "IsFromMe": False,
            },
            "Message": {
                "audioMessage": {
                    "URL": "https://mmg.whatsapp.net/v/t62.7117-24/cifrado.enc",
                    "mimetype": "audio/ogg; codecs=opus",
                    "seconds": 13,
                }
            },
        },
    }


def test_audio_da_evogo_vira_mensagem_de_audio_e_enfileira_transcricao() -> None:
    settings = app.state.settings
    settings.evolution_grupo_coordenacao_jid = "outro-jid@g.us"
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evogo_media_bucket = _BUCKET
    settings.evogo_media_prefix = _PREFIXO

    conn = FakeConn()
    arq = FakeArq()
    minio = FakeMinio({f"{_PREFIXO}{_MSG_ID}.ogg": (_OGG, "audio/ogg; codecs=opus")})

    with TestClient(app) as client:
        minio_real = getattr(app.state, "minio", None)
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        app.state.minio = minio
        try:
            resp = client.post("/webhook/evolution", json=_payload_audio_go())
        finally:
            app.state.minio = minio_real  # estado global: não vaza o fake p/ os outros testes

    assert resp.status_code == 200
    assert resp.json() == {"status": "received"}

    insert = next(b for b in conn.binds if "INSERT INTO barravips.mensagens" in b[0])
    params = insert[1]
    assert params is not None
    # (conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
    assert params[3] == "audio"
    assert params[5] == f"conversas/{_CONVERSA_ID}/mensagens/{_MSG_ID}.ogg"
    assert minio.puts and minio.puts[0][2] == len(_OGG)
    assert [nome for nome, _ in arq.enqueued] == ["transcrever_audio", "processar_turno"]
