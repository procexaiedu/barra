"""F1.2 — trava os invariantes de cadência/ritmo da humanização (05 §4, eixo 5/UX).

O gate de `test_enviar_turno.py` **neutraliza** `asyncio.sleep` para validar ordem/cancel/dedupe
sem cadência — então a ordem `read→digitando→bolha`, a proporção do reading delay à fala do
cliente, o presence por bolha e o jitter ficavam **sem rede**: qualquer regressão (mandar a bolha
antes do "digitando", achatar o reading delay, dropar o presence ou o jitter) passava batido.

Esta suíte fecha esse buraco. Em vez de neutralizar o sleep, **grava** cada `asyncio.sleep` numa
linha do tempo unificada junto das chamadas do Evolution (read/presence/texto) — sem dormir de
verdade, então roda instantâneo, mas asserta sobre as durações *pedidas* e sobre a ordem real.

Invariantes travados:
- **ordem read→digitando→bolha**: read receipt primeiro; cada bolha precedida do seu `composing`.
- **atraso proporcional à fala**: o reading delay (antes do 1º composing) cresce com `chars_inbound`
  e segue a fórmula com piso 1500ms / teto 9000ms (05 §4.1, recalibrado 2026-06-17) — o único delay
  proporcional por design (o typing é plano de propósito, 05 §4.1).
- **presence por bolha**: um `composing` por chunk de texto, sempre antes do envio.
- **jitter**: pausa entre bolhas (800-2800ms) e typing (800-2000ms) presentes e dentro da faixa —
  não neutralizados.

Puro (sem rede, sem DB real): Evolution/MinIO/Conn/Pool são fakes; Redis é `fakeredis`. NÃO mexe no
conftest compartilhado nem neutraliza o sleep globalmente para os outros testes (cada turno
restaura o `asyncio.sleep` original no finally).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fakeredis.aioredis import FakeRedis

import barra.workers.envio as envio
from barra.workers.envio import (
    calcular_pausa_ms,
    calcular_reading_delay_ms,
    calcular_typing_ms,
    enviar_turno,
)

# --- linha do tempo + fakes ------------------------------------------------------------------
#
# A timeline intercala as chamadas observáveis do Evolution (read/presence/texto/midia) com os
# sleeps pedidos. Classificamos cada sleep pelo evento NÃO-sleep imediatamente anterior:
#   prev == "read"     → reading delay   (lê antes de digitar)
#   prev == "presence" → typing delay    (digitando, antes da bolha)
#   prev == "texto"    → jitter          (pausa entre bolhas)
# Isso reconstrói o papel de cada delay sem instrumentar o código de produção.


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, destino: dict[str, Any]) -> None:
        self._destino = destino

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "FROM barravips.conversas" in query:
            return _Result([self._destino])
        if "FROM barravips.mensagens" in query and "direcao = 'cliente'" in query:
            return _Result([])  # sem inbound → rede de saída/PII não interfere na cadência
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
    """Anexa cada chamada observável à `timeline` partilhada como (kind, detalhe)."""

    def __init__(self, timeline: list[tuple[str, Any]]) -> None:
        self.timeline = timeline
        self._n = 0

    async def marcar_lida(
        self, *, instance_id: str, remote_jid: str, message_ids: list[str]
    ) -> None:
        self.timeline.append(("read", list(message_ids)))

    async def set_presence(
        self, *, instance_id: str, remote_jid: str, presence: str, delay_ms: int
    ) -> None:
        self.timeline.append(("presence", presence))

    async def enviar_texto(self, *, texto: str, **_: Any) -> str:
        self._n += 1
        self.timeline.append(("texto", texto))
        return f"mid-{self._n}"

    async def enviar_midia(self, *, caption: str | None, **_: Any) -> str:
        self._n += 1
        self.timeline.append(("midia", caption))
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


async def _roda_turno(
    *, chunks: list[str], chars_inbound: int, msg_ids_cliente: list[str]
) -> list[tuple[str, Any]]:
    """Roda `enviar_turno` gravando a timeline (ações + sleeps pedidos). Grava o sleep SEM dormir
    (roda instantâneo) e restaura o `asyncio.sleep` original no finally — não vaza para outros
    testes."""
    timeline: list[tuple[str, Any]] = []

    async def _rec(secs: float = 0, *_a: Any, **_k: Any) -> None:
        timeline.append(("sleep", secs))

    conversa_id, turno_id = str(uuid4()), "turno-CAD"
    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)
    ctx = {
        "redis": redis,
        "db_pool": _FakePool(_FakeConn(_destino())),
        "evolution": _FakeEvolution(timeline),
        "minio": _FakeMinio(),
    }

    orig = envio.asyncio.sleep
    envio.asyncio.sleep = _rec  # type: ignore[assignment]
    try:
        await enviar_turno(
            ctx,
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=chunks,
            midias=[],
            msg_ids_cliente=msg_ids_cliente,
            chars_inbound=chars_inbound,
            critico=False,
        )
    finally:
        envio.asyncio.sleep = orig  # type: ignore[assignment]
    return timeline


def _acoes(timeline: list[tuple[str, Any]]) -> list[str]:
    """Subsequência só das ações observáveis (descarta sleeps): read/presence/texto/midia."""
    return [k for k, _ in timeline if k != "sleep"]


def _sleeps_por_papel(timeline: list[tuple[str, Any]]) -> dict[str, list[float]]:
    """Classifica cada sleep pelo evento não-sleep imediatamente anterior."""
    papel = {"read": "reading", "presence": "typing", "texto": "jitter"}
    out: dict[str, list[float]] = {"reading": [], "typing": [], "jitter": []}
    prev: str | None = None
    for kind, det in timeline:
        if kind == "sleep":
            if prev in papel:
                out[papel[prev]].append(det)
        else:
            prev = kind
    return out


# --- ordem read→digitando→bolha + presence por bolha -----------------------------------------


async def test_ordem_read_digitando_bolha_e_presence_por_bolha() -> None:
    """A subsequência de ações é exatamente read, depois (presence, texto) por bolha — nessa ordem.
    Trava de uma vez: read antes de tudo, um composing ANTES de cada bolha (presence por bolha) e
    nenhuma bolha antes do seu digitando."""
    timeline = await _roda_turno(
        chunks=["oi amor", "tudo bem?", "me conta de vc"],
        chars_inbound=10,
        msg_ids_cliente=["evo-1"],
    )
    assert _acoes(timeline) == [
        "read",
        "presence",
        "texto",
        "presence",
        "texto",
        "presence",
        "texto",
    ]


async def test_reading_delay_entre_o_read_e_o_primeiro_composing() -> None:
    """O reading delay (lê → digita) cai DEPOIS do read e ANTES do primeiro presence."""
    timeline = await _roda_turno(chunks=["a", "b"], chars_inbound=10, msg_ids_cliente=["evo-1"])
    kinds = [k for k, _ in timeline]
    i_read = kinds.index("read")
    i_sleep = kinds.index("sleep")  # primeiro sleep
    i_presence = kinds.index("presence")
    assert i_read < i_sleep < i_presence


# --- atraso proporcional à fala (reading delay) ----------------------------------------------


async def test_reading_delay_cresce_com_a_fala_do_cliente() -> None:
    """Reading delay maior para um inbound maior — proporcional à fala (05 §4.1).
    Dente direto: se alguém achatar `calcular_reading_delay_ms` para constante, curto==longo e a
    desigualdade quebra."""
    curto = _sleeps_por_papel(
        await _roda_turno(chunks=["a"], chars_inbound=5, msg_ids_cliente=["evo-1"])
    )["reading"]
    longo = _sleeps_por_papel(
        await _roda_turno(chunks=["a"], chars_inbound=200, msg_ids_cliente=["evo-1"])
    )["reading"]
    assert len(curto) == 1 and len(longo) == 1
    assert longo[0] > curto[0]


async def test_reading_delay_segue_a_formula_com_piso_e_teto() -> None:
    """O sleep de reading no fluxo bate exatamente `calcular_reading_delay_ms(chars)/1000`."""
    timeline = await _roda_turno(chunks=["a"], chars_inbound=80, msg_ids_cliente=["evo-1"])
    reading = _sleeps_por_papel(timeline)["reading"]
    assert reading == [calcular_reading_delay_ms(80) / 1000]


def test_calcular_reading_delay_proporcional_piso_teto() -> None:
    """Invariante puro da fórmula: piso 1500ms, teto 9000ms, monotônico e estritamente crescente
    na faixa entre piso e teto (proporção à fala). Recalibrado com o corpus (2026-06-17)."""
    assert calcular_reading_delay_ms(0) == 1500  # piso
    assert calcular_reading_delay_ms(10_000) == 9000  # teto
    # estritamente crescente enquanto não saturou o teto
    seq = [calcular_reading_delay_ms(n) for n in (0, 20, 60, 120)]
    assert seq == sorted(seq)
    assert calcular_reading_delay_ms(120) > calcular_reading_delay_ms(0)
    # monotônico não-decrescente em toda a faixa (inclui a saturação no teto)
    largo = [calcular_reading_delay_ms(n) for n in range(0, 400, 7)]
    assert largo == sorted(largo)
    assert max(largo) <= 9000


# --- jitter + typing presentes e dentro da faixa (não neutralizados) -------------------------


async def test_typing_e_jitter_presentes_e_na_faixa() -> None:
    """Um typing antes de cada bolha (800-2000ms) e um jitter depois de cada bolha (800-2800ms).
    Dente: dropar o sleep de jitter (passo 7) zera a contagem; achatar a faixa estoura o bound."""
    papeis = _sleeps_por_papel(
        await _roda_turno(chunks=["a", "b", "c"], chars_inbound=10, msg_ids_cliente=["evo-1"])
    )
    assert len(papeis["typing"]) == 3
    assert len(papeis["jitter"]) == 3
    assert all(0.8 <= s <= 2.0 for s in papeis["typing"])
    assert all(0.8 <= s <= 2.8 for s in papeis["jitter"])


def test_typing_e_pausa_dentro_da_faixa_da_spec() -> None:
    """Faixas planas da spec (05 §4.1, jitter recalibrado 2026-06-17): typing 0.8-2.0s, jitter 0.8-2.8s."""
    typings = [calcular_typing_ms("qualquer fala") for _ in range(200)]
    pausas = [calcular_pausa_ms() for _ in range(200)]
    assert all(800 <= t <= 2000 for t in typings)
    assert all(800 <= p <= 2800 for p in pausas)
