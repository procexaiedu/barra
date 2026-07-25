"""M5a — `transcrever_audio` contra o Postgres real (06 §1.3).

Exercita o job inteiro: le `mensagens.media_object_key` do banco, baixa do MinIO (mockado em
memoria), transcreve (OpenRouter mockado por classe fake), faz `UPDATE mensagens.conteudo` e
sinaliza o canal Redis `transcricao:{conversa_id}`. Tambem cobre o coordenador (`aguardar_transcricoes`):
ok=true vs timeout vs ok=false.

`needs_db` (Postgres self-hosted; ROLLBACK no teardown). OpenRouter/MinIO/Redis sao fakes.
"""

import base64
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.coordenador import aguardar_transcricoes
from barra.workers.media import transcrever_audio

pytestmark = pytest.mark.needs_db


# --- fakes -----------------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt_tokens: int = 400, completion_tokens: int = 12) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeChatResponse:
    """Mimic do chat completions do OpenRouter: .choices[0].message.content + .usage."""

    def __init__(self, texto: str) -> None:
        mensagem = type("_Msg", (), {"content": texto})()
        self.choices = [type("_Escolha", (), {"message": mensagem})()]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, parent: "_FakeOpenRouter") -> None:
        self._parent = parent

    async def create(self, **kwargs: Any) -> _FakeChatResponse:
        self._parent.chamadas.append(kwargs)
        return self._parent.resposta


class _FakeChat:
    def __init__(self, parent: "_FakeOpenRouter") -> None:
        self.completions = _FakeCompletions(parent)


class _FakeOpenRouter:
    """Stand-in para AsyncOpenAI apontado ao OpenRouter: expoe `.chat.completions.create(...)`."""

    def __init__(self, resposta: _FakeChatResponse) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []
        self.chat = _FakeChat(self)


class _FakeMinioResponse:
    def __init__(self, dados: bytes) -> None:
        self._dados = dados

    def read(self) -> bytes:
        return self._dados

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _FakeMinio:
    def __init__(self, dados_por_key: dict[str, bytes]) -> None:
        self._dados = dados_por_key

    def get_object(self, bucket: str, object_key: str) -> _FakeMinioResponse:
        return _FakeMinioResponse(self._dados[object_key])


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: seed + job + asserts na MESMA transacao -> rollback final."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


# --- DB real --------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


async def _seed_par_completo(
    connection: AsyncConnection[dict[str, Any]],
) -> tuple[UUID, UUID, UUID, UUID]:
    """Cria modelo+cliente+conversa+mensagem(audio, sem conteudo). Devolve (modelo, cliente, conversa, mensagem)."""
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "M Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["externo"]),
    )
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "C Teste"),
    )
    conversa_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    mensagem_id = uuid4()
    # Webhook persiste audio com conteudo='' (msg.texto vazia se nao houver caption — parser.py:41).
    await connection.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'audio', %s, %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            "",
            f"conversas/{conversa_id}/mensagens/test-{uuid4().hex}.ogg",
            f"test-evo-{uuid4().hex}",
        ),
    )
    return modelo_id, cliente_id, conversa_id, mensagem_id


async def _conteudo_de(
    connection: AsyncConnection[dict[str, Any]], mensagem_id: UUID
) -> str | None:
    res = await connection.execute(
        "SELECT conteudo FROM barravips.mensagens WHERE id = %s", (mensagem_id,)
    )
    row = await res.fetchone()
    assert row is not None
    return row["conteudo"]


async def _object_key_de(connection: AsyncConnection[dict[str, Any]], mensagem_id: UUID) -> str:
    res = await connection.execute(
        "SELECT media_object_key FROM barravips.mensagens WHERE id = %s", (mensagem_id,)
    )
    row = await res.fetchone()
    assert row is not None
    return row["media_object_key"]


# --- helpers ---------------------------------------------------------------------------------


def _settings_fake() -> Any:
    """Settings minimo para o job: bucket + chave + modelo."""

    class _S:
        minio_bucket_media = "media"
        openrouter_api_key = "sk-fake"
        openrouter_model_audio_transcribe = "google/gemini-2.5-flash"
        usd_brl_cotacao = 5.50

    return _S()


# --- testes ----------------------------------------------------------------------------------


async def test_transcricao_ok_atualiza_conteudo_e_sinaliza_canal(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    _, _, conversa_id, mensagem_id = await _seed_par_completo(conn)
    object_key = await _object_key_de(conn, mensagem_id)
    pool = _PoolDeUmaConexao(conn)
    redis: Any = FakeRedis()
    minio = _FakeMinio({object_key: b"fake-ogg-bytes"})
    openrouter = _FakeOpenRouter(_FakeChatResponse(texto="oi amor, tudo bem?"))

    ctx: dict[str, Any] = {
        "db_pool": pool,
        "redis": redis,
        "minio": minio,
        "settings": _settings_fake(),
        "audio_client": openrouter,
    }

    await transcrever_audio(
        ctx,
        mensagem_id=str(mensagem_id),
        evolution_message_id="test-evo-id",
    )

    # 1. conteudo atualizado com transcricao + nota
    conteudo = await _conteudo_de(conn, mensagem_id)
    assert conteudo is not None
    assert "oi amor, tudo bem?" in conteudo
    assert "originalmente audio" in conteudo

    # 2. canal sinalizado com ok=true
    chave = f"transcricao:{conversa_id}"
    payload_raw = await redis.lpop(chave)
    assert payload_raw is not None
    if isinstance(payload_raw, (bytes, bytearray)):
        payload_raw = payload_raw.decode("utf-8")
    payload = json.loads(payload_raw)
    assert payload["ok"] is True
    assert payload["mensagem_id"] == str(mensagem_id)

    # 3. o STT foi chamado com o modelo configurado e o audio como content part `input_audio`
    assert len(openrouter.chamadas) == 1
    chamada = openrouter.chamadas[0]
    assert chamada["model"] == "google/gemini-2.5-flash"
    partes = chamada["messages"][0]["content"]
    audio = next(p for p in partes if p["type"] == "input_audio")
    assert audio["input_audio"]["format"] == "ogg"  # extensao do object_key
    assert base64.standard_b64decode(audio["input_audio"]["data"]) == b"fake-ogg-bytes"


async def test_aguardar_transcricoes_le_sinal_ok(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O coordenador acorda do BLPOP quando o worker sinaliza ok=true."""
    _, _, conversa_id, _ = await _seed_par_completo(conn)
    redis: Any = FakeRedis()
    chave = f"transcricao:{conversa_id}"
    await redis.lpush(chave, json.dumps({"mensagem_id": "irrelevante", "ok": True}))

    ok = await aguardar_transcricoes(redis, str(conversa_id), orcamento_s=2)
    assert ok is True


async def test_aguardar_transcricoes_timeout(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem nada no canal, retorna False dentro do orcamento (coordenador despacha canned)."""
    _, _, conversa_id, _ = await _seed_par_completo(conn)
    redis: Any = FakeRedis()

    ok = await aguardar_transcricoes(redis, str(conversa_id), orcamento_s=1)
    assert ok is False


async def test_aguardar_transcricoes_falha_definitiva_do_worker(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Worker sinalizou ok=false (esgotou retry) -> coordenador deve cair em canned."""
    _, _, conversa_id, _ = await _seed_par_completo(conn)
    redis: Any = FakeRedis()
    chave = f"transcricao:{conversa_id}"
    await redis.lpush(chave, json.dumps({"mensagem_id": "x", "ok": False}))

    ok = await aguardar_transcricoes(redis, str(conversa_id), orcamento_s=2)
    assert ok is False


async def test_transcricao_sem_provider_marca_falha_definitiva(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem cliente/chave do OpenRouter, grava placeholder e sinaliza ok=false (06 §1.5)."""
    _, _, conversa_id, mensagem_id = await _seed_par_completo(conn)
    pool = _PoolDeUmaConexao(conn)
    redis: Any = FakeRedis()

    ctx: dict[str, Any] = {
        "db_pool": pool,
        "redis": redis,
        "minio": _FakeMinio({}),
        "settings": _settings_fake(),
        "audio_client": None,  # provider ausente
    }

    await transcrever_audio(
        ctx,
        mensagem_id=str(mensagem_id),
        evolution_message_id="test-evo-id",
    )

    conteudo = await _conteudo_de(conn, mensagem_id)
    assert conteudo == "[audio que nao consegui ouvir]"

    chave = f"transcricao:{conversa_id}"
    payload_raw = await redis.lpop(chave)
    assert payload_raw is not None
    if isinstance(payload_raw, (bytes, bytearray)):
        payload_raw = payload_raw.decode("utf-8")
    assert json.loads(payload_raw)["ok"] is False
