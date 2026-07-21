"""E2E da cadeia de `[quote]` — do texto bruto do LLM ao JSON HTTP que sai pra Evolution.

Os testes unitários cobrem cada estágio ISOLADO (`chunk_texto`, `_resolver_quotes`,
`_aplicar_saida_guard`, `EvolutionClient.enviar_texto`). Este arquivo costura os quatro no
fluxo REAL de saída — o mesmo que o coordenador dispara — e afirma o `quoted` de cada bolha
no corpo HTTP capturado por `respx`. Sem LLM, sem rede, sem prod: só a lógica de quote de ponta
a ponta.

Cadeia exercida: texto do LLM (com marker `[quote: trecho]`) → `chunk_texto` (extrai o alvo) →
`_resolver_quotes` (casa alvo↔msg do cliente) → `enviar_turno` (guard + despacho) →
`EvolutionClient.enviar_texto` real → body `{quoted: {messageId}}` (Evolution GO resolve a
citação pelo id guardado; não ecoa o texto como a v2).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
from fakeredis.aioredis import FakeRedis

from barra.core.evolution import EvolutionClient
from barra.settings import Settings
from barra.workers._chunking import chunk_texto
from barra.workers.coordenador import _resolver_quotes
from barra.workers.envio import enviar_turno

BASE = "http://evolution.test"
INST = "inst-1"


@pytest.fixture(autouse=True)
def _sem_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop)
    yield


# --- fakes de DB (só o que enviar_turno toca): destino + absorve INSERT/PII -------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        # marcar_cotacao_enviada_por_texto lê result.rowcount (o carimbo do ADR 0022 dispara
        # quando a bolha tem cara de cotação, ex. "800 1h no meu local"); o cursor real do
        # psycopg expõe rowcount, então o fake também precisa.
        self.rowcount = len(rows)

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
        return _Result([])  # INSERT em mensagens / PII inbound vazio

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


def _destino() -> dict[str, Any]:
    return {
        "evolution_instance_id": INST,
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": uuid4(),
        "ia_pausada": False,
    }


def _inbound(*msgs: tuple[str, str]) -> list[dict[str, Any]]:
    """Constrói o inbound do turno: (evolution_message_id, conteudo) em ordem cronológica."""
    return [{"evolution_message_id": mid, "conteudo": txt} for mid, txt in msgs]


def _mock_evolution() -> respx.Router:
    """Mocka os endpoints EvoGo que enviar_turno toca (resolução de token + markread + presença +
    send/text); /send/text devolve um id único por chamada."""
    router = respx.mock(base_url=BASE, assert_all_called=False)
    router.get("/instance/all").mock(
        return_value=httpx.Response(200, json={"data": [{"name": INST, "token": "tok"}]})
    )
    router.post("/message/markread").mock(
        return_value=httpx.Response(200, json={"message": "success"})
    )
    router.post("/message/presence").mock(
        return_value=httpx.Response(200, json={"message": "success"})
    )
    contador = {"n": 0}

    def _resposta(_req: httpx.Request) -> httpx.Response:
        contador["n"] += 1
        return httpx.Response(200, json={"id": f"MID-{contador['n']}"})

    router.post("/send/text").mock(side_effect=_resposta)
    return router


async def _rodar_cadeia(texto_llm: str, inbound: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roda a cadeia real e devolve os bodies dos POST /message/sendText, em ordem de envio."""
    chunks, quote_alvos = chunk_texto(texto_llm)
    quote_msg_ids, quote_textos = _resolver_quotes(quote_alvos, inbound)

    settings = Settings(evolution_base_url=BASE, evolution_api_key="k")
    ctx = {
        "redis": FakeRedis(),
        "db_pool": _FakePool(_FakeConn(_destino())),
        "evolution": EvolutionClient(settings),
        "minio": None,
    }
    conversa_id, turno_id = str(uuid4()), "turno-e2e"
    await ctx["redis"].set(f"turno_atual:{conversa_id}", turno_id)

    router = _mock_evolution()
    with router:
        await enviar_turno(
            ctx,
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=chunks,
            midias=[],
            msg_ids_cliente=[r["evolution_message_id"] for r in inbound],
            chars_inbound=sum(len(r["conteudo"]) for r in inbound),
            critico=False,
            quote_msg_ids=quote_msg_ids,
            quote_textos=quote_textos,
        )
        # Lê DENTRO do bloco: respx limpa o log de chamadas ao sair do contexto.
        return [
            json.loads(call.request.content)
            for call in router.calls
            if call.request.url.path.endswith("/send/text")
        ]


def _quoted(body: dict[str, Any]) -> dict[str, Any] | None:
    return body.get("quoted")


# --- cenários de ponta a ponta ---------------------------------------------------------------


async def test_quote_trecho_casa_pergunta_no_meio_do_burst() -> None:
    """[quote: trecho] aponta pra pergunta que ficou pra trás no burst, não pra última msg."""
    inbound = _inbound(
        ("evo-1", "oi gata tudo bem?"),
        ("evo-2", "vc faz oral sem?"),
        ("evo-3", "e o valor de 1h"),
    )
    texto = "oii tudo ótimo amor\n\n[quote: faz oral sem] faço sim vida\n\n800 1h no meu local"
    bodies = await _rodar_cadeia(texto, inbound)

    assert len(bodies) == 3
    # bolha 0: saudação, sem quote
    assert _quoted(bodies[0]) is None
    # bolha 1: cita a PERGUNTA (evo-2), com o texto real no conversation
    assert _quoted(bodies[1]) == {"messageId": "evo-2"}
    assert "[quote" not in bodies[1]["text"].lower()  # marker nunca vaza ao cliente
    # bolha 2: cotação, sem quote
    assert _quoted(bodies[2]) is None


async def test_quote_puro_pega_ultima_mensagem_do_cliente() -> None:
    """[quote] puro (sem trecho) cita a última msg do cliente do turno."""
    inbound = _inbound(("evo-1", "tá acordada?"), ("evo-2", "responde vai"))
    bodies = await _rodar_cadeia("[quote] tô sim amor", inbound)

    assert len(bodies) == 1
    assert _quoted(bodies[0]) == {"messageId": "evo-2"}


async def test_quote_trecho_miss_faz_fallback_para_ultima() -> None:
    """Trecho que não existe em nenhuma inbound → fallback gracioso para a última (nunca trava)."""
    inbound = _inbound(("evo-1", "oi"), ("evo-2", "quanto é 2h?"))
    bodies = await _rodar_cadeia("[quote: nao existe esse texto] oi amor", inbound)

    assert _quoted(bodies[0]) == {"messageId": "evo-2"}


async def test_quote_sobrevive_bolha_so_emoji_descartada_pelo_guard() -> None:
    """REGRESSÃO (o bug corrigido): uma bolha só-emoji ANTES da bolha com quote é descartada pelo
    guard de voz, encolhendo os chunks. O quote tem que seguir a bolha certa pela cadeia REAL —
    não sumir nem citar a mensagem errada."""
    inbound = _inbound(("evo-1", "vc faz oral sem?"), ("evo-2", "e quanto custa?"))
    # bolha 0 é só emoji fora do whitelist → descartada; bolha 1 cita a 1ª pergunta
    texto = "🔥🔥\n\n[quote: faz oral sem] faço sim amor\n\n[quote: quanto custa] 800 amor"
    bodies = await _rodar_cadeia(texto, inbound)

    assert len(bodies) == 2  # a bolha-emoji não saiu
    # a citação de CADA bolha seguiu o conteúdo certo, apesar do descarte deslocar os índices
    assert _quoted(bodies[0]) == {"messageId": "evo-1"}
    assert _quoted(bodies[1]) == {"messageId": "evo-2"}


async def test_sem_marker_nenhuma_bolha_cita() -> None:
    """Conversa fluida sem marker: nenhuma bolha sai com quoted (default limpo)."""
    inbound = _inbound(("evo-1", "oi sumida"))
    bodies = await _rodar_cadeia("oii amor\n\ntava com saudade", inbound)

    assert len(bodies) == 2
    assert all(_quoted(b) is None for b in bodies)
