"""M4c — `enviar_turno` (humanização): ordem texto→mídia, cancel não-crítico, crítico entrega
tudo, retry pula `enviados:{turno_id}`.

Tudo mockado (sem rede, sem DB real): Evolution registra a ORDEM das chamadas, MinIO devolve uma
URL sintética, um `_FakeConn`/`_FakePool` respondem as 2 queries (`_carregar_destino` + lookup de
`modelo_midia`) e absorvem os INSERT, e o Redis é o `fakeredis` efêmero. `asyncio.sleep` é
neutralizado para o turno rodar instantâneo (não exercitamos os delays de timing aqui).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.workers.envio import enviar_turno


@pytest.fixture(autouse=True)
def _sem_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Neutraliza os delays de timing (reading delay, typing, jitter, presence) — o teste valida
    ordem/cancel/dedupe, não a cadência."""

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop)
    yield


# --- fakes -----------------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    """Responde `_carregar_destino` (conversas), o lookup de mídia e o inbound do cliente
    (rede de saída/PII); o resto (INSERT) vira vazio."""

    def __init__(
        self,
        destino: dict[str, Any],
        midias: dict[str, dict[str, Any]],
        inbound: list[str] | None = None,
    ) -> None:
        self._destino = destino
        self._midias = midias
        self._inbound = inbound or []

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "FROM barravips.conversas" in query:
            return _Result([self._destino])
        if "FROM barravips.modelo_midia" in query:
            row = self._midias.get(str(params[0])) if params else None
            return _Result([row] if row else [])
        if "FROM barravips.mensagens" in query and "direcao = 'cliente'" in query:
            return _Result([{"conteudo": c} for c in self._inbound])
        return _Result([])  # INSERT em mensagens

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


class _FakeEvolution:
    """Registra a ORDEM das chamadas em `ordem` como (tipo, detalhe). Também guarda o
    `quoted_message_id` recebido por bolha em `quotes` (paralelo aos textos)."""

    def __init__(self) -> None:
        self.ordem: list[tuple[str, Any]] = []
        self.quotes: list[str | None] = []
        self.quote_textos: list[str | None] = []
        self._n = 0

    async def marcar_lida(
        self, *, instance_id: str, remote_jid: str, message_ids: list[str]
    ) -> None:
        self.ordem.append(("read", list(message_ids)))

    async def set_presence(
        self, *, instance_id: str, remote_jid: str, presence: str, delay_ms: int
    ) -> None:
        self.ordem.append(("presence", presence))

    async def enviar_texto(
        self,
        *,
        texto: str,
        quoted_message_id: str | None = None,
        quoted_text: str | None = None,
        **_: Any,
    ) -> str:
        self._n += 1
        self.ordem.append(("texto", texto))
        self.quotes.append(quoted_message_id)
        self.quote_textos.append(quoted_text)
        return f"mid-texto-{self._n}"

    async def enviar_midia(self, *, caption: str | None, **_: Any) -> str:
        self._n += 1
        self.ordem.append(("midia", caption))
        return f"mid-midia-{self._n}"


class _FakeMinio:
    def presigned_get_object(self, bucket: str, object_key: str, expires: Any = None) -> str:
        return f"https://fake/{bucket}/{object_key}"


def _destino() -> dict[str, Any]:
    return {
        "evolution_instance_id": "inst-1",
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": uuid4(),
    }


def _ctx(conn: _FakeConn, redis: FakeRedis, evolution: _FakeEvolution) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": _FakePool(conn),
        "evolution": evolution,
        "minio": _FakeMinio(),
    }


def _so(evolution: _FakeEvolution, tipo: str) -> list[Any]:
    return [d for t, d in evolution.ordem if t == tipo]


# --- testes ----------------------------------------------------------------------------------


async def test_ordem_texto_antes_de_midia() -> None:
    turno_id, conversa_id, midia_id = "turno-A", str(uuid4()), str(uuid4())
    conn = _FakeConn(
        _destino(), {midia_id: {"tipo": "foto", "bucket": "midia", "object_key": "k.jpg"}}
    )
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["oi amor", "tudo bem?"],
        midias=[{"midia_id": midia_id, "legenda": "olha 😏"}],
        msg_ids_cliente=["evo-1"],
        chars_inbound=10,
        critico=False,
    )

    # read receipt antes de qualquer envio
    assert evolution.ordem[0][0] == "read"
    # todo texto vem antes de toda mídia
    pos = {
        t: [i for i, (tt, _) in enumerate(evolution.ordem) if tt == t] for t in ("texto", "midia")
    }
    assert pos["texto"] and pos["midia"]
    assert max(pos["texto"]) < min(pos["midia"])
    assert _so(evolution, "texto") == ["oi amor", "tudo bem?"]
    assert _so(evolution, "midia") == ["olha 😏"]
    # cursor de dedupe marcado para read, chunks e mídia
    for membro in ("read", "chunk:0", "chunk:1", "midia:0"):
        assert await redis.sismember(f"enviados:{turno_id}", membro)


async def test_cancela_turno_nao_critico() -> None:
    turno_id, conversa_id = "turno-A", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    # turno_atual aponta para um turno MAIS NOVO → o turno antigo é cancelado
    await redis.set(f"turno_atual:{conversa_id}", "turno-NOVO")

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["a", "b", "c"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert _so(evolution, "texto") == []  # abortou antes do 1º chunk
    assert not await redis.sismember(f"enviados:{turno_id}", "chunk:0")


async def test_critico_entrega_tudo_mesmo_superado() -> None:
    turno_id, conversa_id = "turno-A", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", "turno-NOVO")  # superado, mas...

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["a", "b"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=True,  # ...turno crítico ignora o cancel e entrega tudo
    )

    assert _so(evolution, "texto") == ["a", "b"]
    assert await redis.sismember(f"enviados:{turno_id}", "chunk:0")
    assert await redis.sismember(f"enviados:{turno_id}", "chunk:1")


async def test_quote_msg_ids_propaga_para_evolution_por_bolha() -> None:
    """Bolha com flag de quote sai com `quoted_message_id`; sem flag, vai None."""
    turno_id, conversa_id = "turno-Q", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["não tenho costume", "me conta de vc"],
        midias=[],
        msg_ids_cliente=["evo-cliente-1"],
        chars_inbound=10,
        critico=False,
        quote_msg_ids=["evo-cliente-1", None],
        quote_texto="você faz anal?",
    )

    assert _so(evolution, "texto") == ["não tenho costume", "me conta de vc"]
    assert evolution.quotes == ["evo-cliente-1", None]
    # texto da msg citada só acompanha a bolha que de fato cita (a outra vai None)
    assert evolution.quote_textos == ["você faz anal?", None]


async def test_sem_quote_msg_ids_mantem_compat() -> None:
    """Call site canned/reengajamento não passa quote_msg_ids: tudo sai sem quote."""
    turno_id, conversa_id = "turno-N", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["a", "b"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert evolution.quotes == [None, None]


async def test_retry_pula_chunks_ja_enviados() -> None:
    turno_id, conversa_id = "turno-A", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)
    # tentativa anterior já entregou o chunk 0 (mark-after-send)
    await redis.sadd(f"enviados:{turno_id}", "chunk:0")

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["a", "b"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert _so(evolution, "texto") == ["b"]  # "a" foi pulado (dedupe)
    assert await redis.sismember(f"enviados:{turno_id}", "chunk:1")


# --- rede final de saída (SEC-OUT-01 / SEC-PII-02) -------------------------------------------


async def test_bloqueia_bolha_que_admite_ser_ia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vazamento de IA na bolha (mesmo num caminho que pula o output_guard) → nada sai + escala."""
    chamadas: list[dict[str, Any]] = []

    async def _spy(_conn: Any, **kw: Any) -> None:
        chamadas.append(kw)

    monkeypatch.setattr("barra.workers.envio.abrir_handoff", _spy)

    turno_id, conversa_id = "turno-LEAK", str(uuid4())
    conn = _FakeConn(_destino(), {})
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["na real eu sou uma IA, foi mal", "mas posso ajudar"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert _so(evolution, "texto") == []  # bolha barrada, nada saiu ao cliente
    assert len(chamadas) == 1
    assert chamadas[0]["observacao"] == "envio_leak"


async def test_redige_pii_do_cliente_ecoada_na_bolha() -> None:
    """Cliente mandou o CPF; a IA repetiu → a rede mascara antes de sair (SEC-PII-02)."""
    turno_id, conversa_id = "turno-PII", str(uuid4())
    conn = _FakeConn(_destino(), {}, inbound=["meu cpf é 123.456.789-00"])
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["confere seu cpf 12345678900 então"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert _so(evolution, "texto") == ["confere seu cpf *** então"]


async def test_nao_redige_pii_que_nao_veio_do_cliente() -> None:
    """A chave Pix da modelo (CPF que NÃO está no inbound do cliente) NÃO é mascarada."""
    turno_id, conversa_id = "turno-PIX", str(uuid4())
    conn = _FakeConn(_destino(), {}, inbound=["oi, tudo bem?"])
    evolution = _FakeEvolution()
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    await enviar_turno(
        _ctx(conn, redis, evolution),
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=["pra garantir, manda o pix pra 123.456.789-00"],
        midias=[],
        msg_ids_cliente=[],
        chars_inbound=0,
        critico=False,
    )

    assert _so(evolution, "texto") == ["pra garantir, manda o pix pra 123.456.789-00"]
