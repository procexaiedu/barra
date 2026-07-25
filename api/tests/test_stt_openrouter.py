"""STT via OpenRouter (06 §1.3): modelo, formato do áudio e o caso 'sem fala'.

Offline (sem banco, sem provider): pool/Redis/MinIO/cliente são fakes. Os `needs_db` do job
inteiro vivem em `tests/integracao/test_transcrever_audio.py`; aqui ficam os invariantes que
não precisam de Postgres — incluindo a regressão do `model` vazio, que só aparece contra o
provider real (HTTP 400 'No models provided').
"""

import base64
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis

from barra.workers.media import _AUDIO_PLACEHOLDER, _MODELO_STT_PADRAO, transcrever_audio

_OBJECT_KEY = "conversas/abc/mensagens/MSG1.ogg"


class _Usage:
    prompt_tokens = 400
    completion_tokens = 10


class _RespostaFake:
    def __init__(self, texto: str) -> None:
        mensagem = type("_Msg", (), {"content": texto})()
        self.choices = [type("_Escolha", (), {"message": mensagem})()]
        self.usage = _Usage()


class _ClienteFake:
    def __init__(self, texto: str = "oi amor") -> None:
        self.chamadas: list[dict[str, Any]] = []
        cliente = self

        class _Completions:
            async def create(self, **kwargs: Any) -> _RespostaFake:
                cliente.chamadas.append(kwargs)
                return _RespostaFake(texto)

        self.chat = type("_Chat", (), {"completions": _Completions()})()


class _MinioFake:
    def get_object(self, bucket: str, key: str) -> Any:
        class _Resp:
            def read(self, amt: int | None = None) -> bytes:
                return b"ogg-bytes"

            def close(self) -> None: ...

            def release_conn(self) -> None: ...

        return _Resp()


class _ConnFake:
    def __init__(self, object_key: str) -> None:
        self.object_key = object_key
        self.conteudo: str | None = None

    async def execute(self, query: str, params: Any = None) -> Any:
        conn = self

        class _Result:
            async def fetchone(self) -> dict[str, Any] | None:
                if "SELECT conversa_id" in query:
                    return {"conversa_id": "conv-1", "media_object_key": conn.object_key}
                return None

        if "UPDATE" in query and params:
            self.conteudo = params[0]
        return _Result()


class _PoolFake:
    def __init__(self, conn: _ConnFake) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self.conn


def _ctx(cliente: _ClienteFake, *, modelo: str | None, object_key: str = _OBJECT_KEY) -> Any:
    class _S:
        minio_bucket_media = "media"
        openrouter_api_key = "sk-fake"
        openrouter_model_audio_transcribe = modelo
        usd_brl_cotacao = 5.50

    conn = _ConnFake(object_key)
    return {
        "db_pool": _PoolFake(conn),
        "redis": FakeRedis(),
        "minio": _MinioFake(),
        "settings": _S(),
        "audio_client": cliente,
    }, conn


@pytest.mark.asyncio
async def test_modelo_vazio_no_env_cai_no_padrao() -> None:
    """O compose repassa OPENROUTER_MODEL_AUDIO_TRANSCRIBE e ela chega VAZIA quando o Portainer
    não a define — sem o fallback, a chamada sai com `model=''` e o OpenRouter devolve 400."""
    cliente = _ClienteFake()
    ctx, _ = _ctx(cliente, modelo="")
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    assert cliente.chamadas[0]["model"] == _MODELO_STT_PADRAO


@pytest.mark.asyncio
async def test_modelo_do_env_vence_o_padrao() -> None:
    cliente = _ClienteFake()
    ctx, _ = _ctx(cliente, modelo="google/gemini-2.5-flash")
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    assert cliente.chamadas[0]["model"] == "google/gemini-2.5-flash"


@pytest.mark.asyncio
async def test_audio_vai_como_input_audio_com_formato_da_extensao() -> None:
    cliente = _ClienteFake()
    ctx, _ = _ctx(cliente, modelo=None, object_key="conversas/abc/mensagens/MSG1.mp3")
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    partes = cliente.chamadas[0]["messages"][0]["content"]
    audio = next(p for p in partes if p["type"] == "input_audio")
    assert audio["input_audio"]["format"] == "mp3"
    assert base64.standard_b64decode(audio["input_audio"]["data"]) == b"ogg-bytes"


@pytest.mark.asyncio
async def test_extensao_desconhecida_assume_ogg() -> None:
    cliente = _ClienteFake()
    ctx, _ = _ctx(cliente, modelo=None, object_key="conversas/abc/mensagens/MSG1")
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    partes = cliente.chamadas[0]["messages"][0]["content"]
    audio = next(p for p in partes if p["type"] == "input_audio")
    assert audio["input_audio"]["format"] == "ogg"


@pytest.mark.asyncio
async def test_audio_sem_fala_vira_falha_definitiva() -> None:
    # Áudio mudo: grava o placeholder e sinaliza ok=false (o cliente ouve o canned honesto),
    # em vez de deixar o modelo inventar fala.
    cliente = _ClienteFake(texto="(sem fala)")
    ctx, conn = _ctx(cliente, modelo=None)
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    assert conn.conteudo == _AUDIO_PLACEHOLDER
    sinal = await ctx["redis"].lpop("transcricao:conv-1")
    assert b'"ok": false' in sinal


@pytest.mark.asyncio
async def test_resposta_vazia_do_modelo_vira_falha_definitiva() -> None:
    cliente = _ClienteFake(texto="   ")
    ctx, conn = _ctx(cliente, modelo=None)
    await transcrever_audio(ctx, mensagem_id="MSG1", evolution_message_id="MSG1")
    assert conn.conteudo == _AUDIO_PLACEHOLDER
