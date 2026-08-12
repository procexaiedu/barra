"""O sinal de transcricao tem de sobreviver ate o turno DEFERIDO acordar (06 §1.4).

Bug de producao (auditoria pre-estreia): `transcrever_audio` fazia LPUSH + `EXPIRE 30` no canal
`transcricao:{conversa_id}`, mas quem le o canal e o `processar_turno` enfileirado com
`_defer_by=180s` (9728a25, 22/07, subiu o defer de 12s -> 180s e deixou o TTL parado). O sinal
morria ~150s antes do leitor: o BLPOP achava fila vazia, `aguardar_transcricoes` devolvia False e
TODO audio — inclusive o transcrito com perfeicao — recebia a canned "nao consegui ouvir, me
manda por escrito".

Estes testes exercitam a RELACAO defer x TTL (nao a constante): o defer sai do `_defer_by` real
do enqueue, o orcamento sai da assinatura real do consumidor e o TTL sai do `expire` real do
produtor. Mudar qualquer um dos tres sem mover os outros derruba o teste.

Sem DB, sem rede, sem LLM: roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from barra.webhook.despacho import (
    DEFER_TURNO_S,
    enfileirar_processar_turno,
    ttl_sinal_transcricao_s,
)
from barra.workers.coordenador import aguardar_transcricoes
from barra.workers.media import transcrever_audio

_CONV_ID = str(uuid4())
_MSG_ID = str(uuid4())
_OBJECT_KEY = f"conversas/{_CONV_ID}/audio.ogg"


# --- fakes ------------------------------------------------------------------------------------


class _RedisRelogio:
    """Redis fake com RELOGIO VIRTUAL, so o necessario para o canal (lpush/expire/blpop).

    `fakeredis` nao viaja no tempo e o bug so aparece quando o consumidor acorda MINUTOS depois
    do produtor — sem relogio virtual o teste teria de dormir 180s de verdade.
    """

    def __init__(self) -> None:
        self.agora = 0.0
        self.expires: list[tuple[str, int]] = []
        self._listas: dict[str, list[str]] = {}
        self._deadlines: dict[str, float] = {}

    def avancar(self, segundos: float) -> None:
        self.agora += segundos
        self._expirar()

    def _expirar(self) -> None:
        for chave, deadline in list(self._deadlines.items()):
            if deadline <= self.agora:
                self._listas.pop(chave, None)
                self._deadlines.pop(chave, None)

    async def lpush(self, chave: str, valor: str) -> int:
        self._expirar()
        self._listas.setdefault(chave, []).insert(0, valor)
        return len(self._listas[chave])

    async def expire(self, chave: str, ttl: int) -> bool:
        self._expirar()
        self.expires.append((chave, int(ttl)))
        if chave not in self._listas:
            return False
        self._deadlines[chave] = self.agora + int(ttl)
        return True

    # ASYNC109: `timeout` e o nome do kwarg do redis-py real — `aguardar_transcricoes` chama
    # `redis.blpop(chave, timeout=...)`; renomear quebraria o fake.
    async def blpop(
        self,
        chave: str,
        timeout: int = 0,  # noqa: ASYNC109
    ) -> tuple[str, str] | None:
        self._expirar()
        fila = self._listas.get(chave)
        if fila:
            return (chave, fila.pop(0))  # LPUSH+BLPOP operam na mesma ponta (LIFO), como o real
        # Fila vazia: o consumidor real dormiria `timeout`s no syscall. Aqui so anda o relogio.
        self.avancar(timeout)
        return None

    async def enqueue_job(self, _name: str, **_kwargs: Any) -> Any:  # pragma: no cover
        return object()


class _FakeResultado:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """SELECT devolve a mensagem de audio; UPDATE so registra (sem Postgres)."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _FakeResultado:
        if sql.strip().upper().startswith("SELECT"):
            return _FakeResultado({"conversa_id": _CONV_ID, "media_object_key": _OBJECT_KEY})
        self.updates.append((sql, params))
        return _FakeResultado(None)


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


class _FakeMinioResponse:
    def read(self) -> bytes:
        return b"fake-ogg-bytes"

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _FakeMinio:
    def get_object(self, _bucket: str, _key: str) -> _FakeMinioResponse:
        return _FakeMinioResponse()


class _FakeOpenRouter:
    """Stand-in do AsyncOpenAI: `.chat.completions.create(...)` devolve a transcricao."""

    def __init__(self, texto: str) -> None:
        self._texto = texto
        parent = self

        class _Completions:
            async def create(self, **_kwargs: Any) -> Any:
                mensagem = type("_Msg", (), {"content": parent._texto})()
                return type(
                    "_Resp",
                    (),
                    {
                        "choices": [type("_Escolha", (), {"message": mensagem})()],
                        "usage": type(
                            "_Usage", (), {"prompt_tokens": 400, "completion_tokens": 12}
                        )(),
                    },
                )()

        self.chat = type("_Chat", (), {"completions": _Completions()})()


class _SettingsFake:
    openrouter_api_key = "sk-fake"
    openrouter_model_audio_transcribe = "google/gemini-3.1-flash-lite"
    minio_bucket_media = "media"
    usd_brl_cotacao = 5.50


def _ctx(
    redis: _RedisRelogio, conn: _FakeConn, *, texto: str = "oi amor, tudo bem?"
) -> dict[str, Any]:
    return {
        "db_pool": _FakePool(conn),
        "redis": redis,
        "minio": _FakeMinio(),
        "settings": _SettingsFake(),
        "audio_client": _FakeOpenRouter(texto),
    }


# --- medidas do sistema real (nada hardcoded) ---------------------------------------------------


async def _defer_real_do_turno() -> float:
    """Maior `_defer_by` que o enqueue do turno usa hoje — direto do helper de producao."""
    capturado: list[dict[str, Any]] = []

    class _ArqNulo:
        async def enqueue_job(self, _name: str, **kwargs: Any) -> Any:
            capturado.append(kwargs)
            return None  # forca tambem o ramo da varredura (defer_s + 2)

    await enfileirar_processar_turno(_ArqNulo(), _CONV_ID, aguardar_transcricao=True)
    return max(k["_defer_by"].total_seconds() for k in capturado)


def _orcamento_real_do_blpop() -> int:
    """Orcamento do BLPOP direto da assinatura de `aguardar_transcricoes` (coordenador)."""
    default = inspect.signature(aguardar_transcricoes).parameters["orcamento_s"].default
    return int(default)


async def _ttl_real_do_sinal(redis: _RedisRelogio, conn: _FakeConn) -> int:
    """TTL que o PRODUTOR de verdade aplica no canal (roda `transcrever_audio` inteiro)."""
    await transcrever_audio(_ctx(redis, conn), mensagem_id=_MSG_ID, evolution_message_id="evo-1")
    canal = f"transcricao:{_CONV_ID}"
    ttls = [ttl for chave, ttl in redis.expires if chave == canal]
    assert ttls, "o produtor nao aplicou TTL nenhum no canal"
    return ttls[-1]


# --- testes -------------------------------------------------------------------------------------


async def test_ttl_do_sinal_cobre_a_janela_do_defer_do_turno() -> None:
    """O contrato: TTL do sinal >= defer do turno + orcamento do BLPOP.

    Antes do fix: TTL=30 vs defer=182 + 8 -> falha (era o apagao do audio em prod).
    """
    redis = _RedisRelogio()
    ttl = await _ttl_real_do_sinal(redis, _FakeConn())
    defer = await _defer_real_do_turno()
    orcamento = _orcamento_real_do_blpop()

    assert ttl >= defer + orcamento, (
        f"sinal de transcricao expira em {ttl}s mas o turno so acorda em {defer}s "
        f"(+{orcamento}s de BLPOP): todo audio cairia na canned"
    )


def test_ttl_acompanha_um_defer_maior_sem_novo_ajuste_manual() -> None:
    """Se alguem subir o defer de novo, o TTL sobe junto — a derivacao e a protecao."""
    orcamento = _orcamento_real_do_blpop()
    for defer in (DEFER_TURNO_S, 600, 1800, 3600):
        assert ttl_sinal_transcricao_s(defer) >= defer + orcamento


async def test_audio_transcrito_nao_vira_canned_quando_o_turno_acorda_apos_o_defer() -> None:
    """Ponta a ponta com relogio virtual: STT em 2s, coordenador so acorda no fim do defer."""
    redis = _RedisRelogio()
    conn = _FakeConn()

    redis.avancar(2)  # o job de STT roda ~2s depois do audio chegar
    await transcrever_audio(_ctx(redis, conn), mensagem_id=_MSG_ID, evolution_message_id="evo-1")
    assert conn.updates, "a transcricao deveria ter sido persistida em mensagens.conteudo"

    defer = await _defer_real_do_turno()
    redis.avancar(defer)  # o `processar_turno` deferido finalmente acorda

    assert await aguardar_transcricoes(redis, _CONV_ID) is True


async def test_transcricao_que_falha_de_verdade_continua_caindo_na_canned() -> None:
    """Guard do fix: sinal duravel nao pode mascarar falha real (ok=false chega intacto)."""
    redis = _RedisRelogio()
    conn = _FakeConn()

    ctx = _ctx(redis, conn)
    ctx["audio_client"] = None  # provider ausente -> _falha_definitiva (ok=false)
    await transcrever_audio(ctx, mensagem_id=_MSG_ID, evolution_message_id="evo-1")

    redis.avancar(await _defer_real_do_turno())
    assert await aguardar_transcricoes(redis, _CONV_ID) is False


async def test_stt_mais_lento_que_o_defer_ainda_cai_na_canned() -> None:
    """Sinal nenhum quando o turno acorda -> canned (o turno nao pode ficar esperando)."""
    redis = _RedisRelogio()
    redis.avancar(await _defer_real_do_turno())  # turno acorda; STT ainda rodando

    assert await aguardar_transcricoes(redis, _CONV_ID) is False


async def test_dois_audios_na_mesma_janela_sao_drenados_pelo_turno_unico() -> None:
    """Burst de audio coalesce num turno so; os dois sinais tem de sobreviver ate la."""
    redis = _RedisRelogio()
    conn = _FakeConn()

    await transcrever_audio(_ctx(redis, conn), mensagem_id=_MSG_ID, evolution_message_id="evo-1")
    redis.avancar(20)
    await transcrever_audio(_ctx(redis, conn), mensagem_id=_MSG_ID, evolution_message_id="evo-2")

    redis.avancar(await _defer_real_do_turno())
    assert await aguardar_transcricoes(redis, _CONV_ID) is True

    # e um ok=false no meio do burst derruba o conjunto (canned), como antes.
    redis2 = _RedisRelogio()
    conn2 = _FakeConn()
    await transcrever_audio(_ctx(redis2, conn2), mensagem_id=_MSG_ID, evolution_message_id="evo-1")
    ctx_falho = _ctx(redis2, conn2)
    ctx_falho["audio_client"] = None
    await transcrever_audio(ctx_falho, mensagem_id=_MSG_ID, evolution_message_id="evo-2")

    redis2.avancar(await _defer_real_do_turno())
    assert await aguardar_transcricoes(redis2, _CONV_ID) is False


async def test_payload_do_sinal_segue_o_contrato_do_consumidor() -> None:
    """O canal continua carregando `{mensagem_id, ok}` — o fix mexe no prazo, nao no formato."""
    redis = _RedisRelogio()
    await transcrever_audio(
        _ctx(redis, _FakeConn()), mensagem_id=_MSG_ID, evolution_message_id="evo-1"
    )
    res = await redis.blpop(f"transcricao:{_CONV_ID}", timeout=1)
    assert res is not None
    payload = json.loads(res[1])
    assert payload == {"mensagem_id": _MSG_ID, "ok": True}
