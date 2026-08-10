"""Resiliencia do pipeline do turno: as tres janelas de perda silenciosa da auditoria.

Sem banco e sem LLM (grafo FAKE, `_FakeConn`/`_FakePool` no padrao de `test_custo_04_teto_turnos`,
Redis = fakeredis com `enqueue_job` AsyncMock) — roda no gate `-m "not needs_key and not needs_db"`.

1. `except Exception` generico do coordenador: escala `erro_interno` (card + IA pausada) ANTES de
   re-levantar, e nunca mascara a excecao original — nem quando a propria escalada falha.
2. TTLs do debounce: `TTL_PENDING`/`TTL_DEBOUNCE` >> janela do `_defer_by` do enqueue.
3. Gate de pendencia resiliente: sem `pending:conv`, quem diz se ha trabalho e o BANCO
   (mensagem do cliente posterior a ultima bolha da IA), com guard anti-double-texting.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid5

import pytest
from fakeredis.aioredis import FakeRedis
from langchain_core.messages import AIMessage

from barra.webhook.debounce import TTL_DEBOUNCE, TTL_PENDING
from barra.webhook.despacho import enfileirar_processar_turno
from barra.workers.coordenador import MAX_DRAIN, NS_TURNO, processar_turno

_ATEND_ID = UUID("00000000-0000-0000-0000-0000000000bb")
_MODELO_ID = UUID("00000000-0000-0000-0000-0000000000c1")
_CLIENTE_ID = UUID("00000000-0000-0000-0000-0000000000c2")
_CONV_ID = "00000000-0000-0000-0000-0000000000c3"

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- fakes de DB (sem Postgres) --------------------------------------------------------------


class _FakeResult:
    """`fetchone` devolve o atendimento aberto; `fetchall` devolve vazio.

    `tem_inbound` controla a resposta do fallback do gate (`SELECT 1 ... LIMIT 1`): quando False,
    a query de existencia nao acha linha nenhuma — mas as demais (`resolver_atendimento`, gate
    pos-turno) continuam devolvendo o atendimento, senao o turno nem comeca.
    """

    def __init__(self, *, e_consulta_de_inbound: bool, tem_inbound: bool) -> None:
        self._vazio = e_consulta_de_inbound and not tem_inbound

    async def fetchone(self) -> dict[str, Any] | None:
        if self._vazio:
            return None
        return {
            "id": _ATEND_ID,
            "ia_pausada": False,
            "estado": "Triagem",
            "modelo_id": _MODELO_ID,
            "cliente_id": _CLIENTE_ID,
            "conversa_id": UUID(_CONV_ID),
        }

    async def fetchall(self) -> list[dict[str, Any]]:
        return []


class _FakeConn:
    def __init__(self, *, tem_inbound: bool = True) -> None:
        self._tem_inbound = tem_inbound
        self.sqls: list[str] = []

    async def execute(self, sql: str = "", *_a: Any, **_k: Any) -> _FakeResult:
        self.sqls.append(sql)
        return _FakeResult(
            e_consulta_de_inbound="SELECT 1 FROM barravips.mensagens" in sql,
            tem_inbound=self._tem_inbound,
        )

    def transaction(self) -> _FakeConn:
        return self

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


class _FakePool:
    def __init__(self, *, tem_inbound: bool = True) -> None:
        self.conn = _FakeConn(tem_inbound=tem_inbound)

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self.conn


class _GrafoFake:
    def __init__(self) -> None:
        self.chamadas = 0

    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        self.chamadas += 1
        return {"messages": [AIMessage(content="oi amor", usage_metadata=_USAGE)]}


class _GrafoQueFalha:
    """ainvoke levanta um bug generico (nao 5xx de provider) — cai no `except Exception`."""

    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        raise RuntimeError("boom")


class _FakeSettings:
    deepseek_model_chat = "deepseek-test"
    usd_brl_cotacao = 5.5


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()
    return redis


def _ctx(
    redis: FakeRedis,
    graph: Any,
    pool: _FakePool | None = None,
    *,
    job_id: str = "job-resiliencia",
) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": pool if pool is not None else _FakePool(),
        "graph": graph,
        "settings": _FakeSettings(),
        "job_id": job_id,
        "score": 1_700_000_000_000,
    }


def _turno_id(job_id: str, loop_idx: int = 0) -> str:
    return str(uuid5(NS_TURNO, f"{job_id}:1700000000000:{loop_idx}"))


# --- 1. handoff no `except Exception` generico ------------------------------------------------


async def test_erro_generico_escala_antes_de_relevantar() -> None:
    """Bug no grafo: o ARQ nao retenta excecao comum, entao sem escalada o turno morria mudo —
    cliente sem resposta e ninguem avisado. Agora abre handoff `erro_interno` e RE-LEVANTA."""
    redis = _redis_fake()

    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()) as mock_escalar,
    ):
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        with pytest.raises(RuntimeError, match="boom"):
            await processar_turno(_ctx(redis, _GrafoQueFalha()), conversa_id=_CONV_ID)

    mock_escalar.assert_awaited_once()
    assert mock_escalar.await_args is not None
    assert mock_escalar.await_args.kwargs["motivo"] == "erro_interno"
    assert mock_escalar.await_args.args[1] == _ATEND_ID  # escalada no atendimento do turno


async def test_erro_generico_nao_manda_bolha_ao_cliente() -> None:
    """Escalada != resposta: o turno que quebrou nao despacha `enviar_turno`."""
    redis = _redis_fake()

    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()),
    ):
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        with pytest.raises(RuntimeError):
            await processar_turno(_ctx(redis, _GrafoQueFalha()), conversa_id=_CONV_ID)

    assert not [
        c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"
    ]


async def test_escalada_que_falha_nao_mascara_a_excecao_original() -> None:
    """Se a propria escalada estourar (banco fora, por ex.), ela vira log e o erro do grafo sobe
    intacto — nunca trocamos a causa raiz por um erro de handoff."""
    redis = _redis_fake()

    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch(
            "barra.workers.coordenador.escalar_por_exaustao",
            new=AsyncMock(side_effect=OSError("banco fora")),
        ),
    ):
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        with pytest.raises(RuntimeError, match="boom"):
            await processar_turno(_ctx(redis, _GrafoQueFalha()), conversa_id=_CONV_ID)


async def test_erro_generico_escala_idempotente_no_reprocessamento() -> None:
    """Idempotencia: o mesmo turno reprocessado (retry de shutdown do ARQ) reabre a escalada pela
    MESMA porta — `abrir_handoff` nao cria uma segunda com uma aberta (guard REL-02)."""
    redis = _redis_fake()

    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.dominio.escaladas.service.abrir_handoff", new=AsyncMock()) as mock_handoff,
        patch("barra.workers.coordenador.AGENTE_ESCALADA"),
    ):
        for _ in range(2):
            await redis.set(f"pending:conv:{_CONV_ID}", "1")
            with pytest.raises(RuntimeError):
                await processar_turno(_ctx(redis, _GrafoQueFalha()), conversa_id=_CONV_ID)

    # duas passadas, dois `abrir_handoff` com o MESMO atendimento e motivo: a deduplicacao mora la
    # dentro (INSERT ... WHERE NOT EXISTS), nao numa flag do coordenador.
    assert mock_handoff.await_count == 2
    for chamada in mock_handoff.await_args_list:
        assert chamada.kwargs["atendimento_id"] == _ATEND_ID
        assert chamada.kwargs["observacao"] == "erro_interno"


# --- 2. margem dos TTLs do debounce -----------------------------------------------------------


async def test_ttls_do_debounce_cobrem_a_janela_do_defer() -> None:
    """O job so roda `defer_s` depois do enqueue; o gate de pendencia precisa achar a chave viva
    la. Com 240s sobravam 60s — worker fora do ar por mais que isso descartava a fila em silencio.
    """
    capturado: list[dict[str, Any]] = []

    class _Arq:
        async def enqueue_job(self, _name: str, **kwargs: Any) -> Any:
            capturado.append(kwargs)
            return object()

    await enfileirar_processar_turno(_Arq(), _CONV_ID)
    defer_s = capturado[0]["_defer_by"].total_seconds()

    assert defer_s == 180  # janela de debounce real (nao os "~3-5s" que o doc dizia)
    assert TTL_PENDING >= 5 * defer_s
    assert TTL_DEBOUNCE >= 5 * defer_s
    assert TTL_PENDING >= TTL_DEBOUNCE  # `pending` e o unico dos dois que alguem LE


# --- 3. gate do turno resiliente a Redis ------------------------------------------------------


async def test_retry_pos_crash_com_pending_apagado_processa_pelo_banco() -> None:
    """O crash do worker deixa a janela sem dono: o `pending` ja foi apagado (o turno o limpa
    ANTES de processar) e o retry caia no `turno_sem_pendencia` -> cliente no vacuo. Agora o banco
    manda: ha mensagem do cliente posterior a ultima bolha da IA -> processa."""
    redis = _redis_fake()
    graph = _GrafoFake()
    ctx = _ctx(redis, graph)
    # marcador do turno que morreu: e DESTE job (mesmo job_id/score) -> retomada legitima.
    await redis.set(f"turno_atual:{_CONV_ID}", _turno_id("job-resiliencia"))

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await processar_turno(ctx, conversa_id=_CONV_ID)  # sem pending:conv

    assert graph.chamadas == 1
    assert [c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"]


async def test_retry_pos_crash_em_iteracao_de_drain_ainda_e_reconhecido() -> None:
    """O marcador pode ser de uma iteracao adiantada do drain (`loop_idx>0`) do MESMO job — segue
    sendo retomada nossa, nao turno alheio."""
    redis = _redis_fake()
    graph = _GrafoFake()
    await redis.set(f"turno_atual:{_CONV_ID}", _turno_id("job-resiliencia", MAX_DRAIN - 1))

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await processar_turno(_ctx(redis, graph), conversa_id=_CONV_ID)

    assert graph.chamadas == 1


async def test_sem_pending_e_sem_inbound_no_banco_retorna_como_antes() -> None:
    """A IA falou por ultimo: nada a fazer. O fallback nao pode virar desculpa p/ rodar o grafo em
    cima da propria fala (double-texting)."""
    redis = _redis_fake()
    graph = _GrafoFake()

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await processar_turno(
            _ctx(redis, graph, _FakePool(tem_inbound=False)), conversa_id=_CONV_ID
        )

    assert graph.chamadas == 0
    redis.enqueue_job.assert_not_awaited()


async def test_fallback_cede_para_turno_alheio_em_voo() -> None:
    """Guard anti-double-texting da resposta EM VOO: a varredura roda logo depois do turno
    primario, cuja bolha ainda esta deferida (`enviar_turno` com `_defer_by`) e por isso ainda nao
    virou linha em `mensagens`. O banco diria "inbound sem resposta"; o marcador de OUTRO turno
    diz que a resposta e dele."""
    redis = _redis_fake()
    graph = _GrafoFake()
    await redis.set(f"turno_atual:{_CONV_ID}", _turno_id("job-do-turno-primario"))

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await processar_turno(_ctx(redis, graph, job_id="job-da-varredura"), conversa_id=_CONV_ID)

    assert graph.chamadas == 0
    redis.enqueue_job.assert_not_awaited()


async def test_gate_normal_com_pending_nao_consulta_o_banco_a_toa() -> None:
    """Caminho quente inalterado: com `pending:conv` vivo o gate passa direto, sem a query de
    existencia (o fallback e excecao, nao custo fixo por turno)."""
    redis = _redis_fake()
    pool = _FakePool()

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        await processar_turno(_ctx(redis, _GrafoFake(), pool), conversa_id=_CONV_ID)

    assert not [s for s in pool.conn.sqls if "SELECT 1 FROM barravips.mensagens" in s]


async def test_fallback_nao_quebra_o_drain_nem_o_lock() -> None:
    """O fallback so decide ENTRAR no turno: o drain segue governado pelo `pending` (passo 8) e o
    lock continua sendo o mesmo — um turno recuperado nao vira loop infinito."""
    redis = _redis_fake()
    graph = _GrafoFake()
    locks: list[str] = []

    @asynccontextmanager
    async def _lock_espiao(_redis: Any, chave: str, **_k: Any) -> Any:
        locks.append(chave)
        yield None

    with patch("barra.workers.coordenador.adquirir_lock", _lock_espiao):
        await processar_turno(_ctx(redis, graph), conversa_id=_CONV_ID)

    assert locks == [f"lock:conv:{_CONV_ID}"]
    assert graph.chamadas == 1  # uma iteracao: o pending nao foi re-setado pelo grafo
