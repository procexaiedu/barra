"""Regressão do incidente 24-27/07: a desculpa do Cancelamento automático do piloto (ADR-0033)
evaporou porque a Evolution ficou 3 dias fora e o envio crítico esgota `MAX_TRIES_ENVIO` em ~30s.
O cliente ficou esperando um encontro que o sistema já tinha cancelado — exatamente o que o
ADR-0033 existe pra evitar. O backstop reenfileira enquanto a desculpa não saiu.
"""

from typing import Any

import pytest

import barra.workers.reconciliacao as recon


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Conn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.sql: str | None = None
        self.params: tuple[Any, ...] = ()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        self.sql = sql
        self.params = params
        return _Result(self.rows)


class _PoolCtx:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def connection(self) -> _PoolCtx:
        return _PoolCtx(self._conn)


class _Redis:
    def __init__(self) -> None:
        self.sets: list[tuple[str, str]] = []
        self.jobs: list[dict[str, Any]] = []

    async def set(self, chave: str, valor: str, ex: int | None = None) -> None:
        self.sets.append((chave, valor))

    async def enqueue_job(self, nome: str, **kwargs: Any) -> None:
        self.jobs.append({"nome": nome, **kwargs})


async def test_reenfileira_desculpa_que_nao_saiu() -> None:
    conn = _Conn([{"atendimento_id": "a1", "conversa_id": "c1"}])
    redis = _Redis()

    n = await recon.reconciliar_desculpa_piloto({"db_pool": _Pool(conn), "redis": redis})

    assert n == 1
    (job,) = redis.jobs
    assert job["nome"] == "enviar_turno"
    assert job["conversa_id"] == "c1"
    # `critico=True` como no caminho original: a desculpa não pode ser barrada pela IA pausada
    # (o cancelamento pausou) nem pelo cancel-on-new-message.
    assert job["critico"] is True
    assert job["chunks"] and job["chunks"][0]
    # O `turno_id` é o MESMO do envio original (uuid5 determinístico por atendimento): é ele que
    # segura a idempotência por chunk, então uma corrida entre o job original e o backstop não
    # duplica a bolha.
    assert job["turno_id"] == recon._turno_id_cancelamento("a1")
    assert ("turno_atual:c1", job["turno_id"]) in redis.sets


async def test_sem_pendencia_nao_enfileira_nada() -> None:
    redis = _Redis()

    n = await recon.reconciliar_desculpa_piloto({"db_pool": _Pool(_Conn([])), "redis": redis})

    assert n == 0
    assert redis.jobs == []


async def test_varredura_filtra_por_janela_instancia_e_desculpa_ja_entregue() -> None:
    conn = _Conn([])

    await recon.reconciliar_desculpa_piloto({"db_pool": _Pool(conn), "redis": _Redis()})

    assert conn.sql is not None
    sql = " ".join(conn.sql.split())
    # Só reentrega enquanto a desculpa ainda faz sentido...
    assert "piloto_cancelado_em > now() - make_interval" in sql
    # ...só se nenhuma fala da IA saiu depois do cancelamento (o texto é sorteado, então a prova
    # de entrega é a mensagem gravada, não o conteúdo)...
    assert "NOT EXISTS" in sql and "direcao = 'ia'" in sql
    # ...e só com a instância de pé, senão o backstop queima tentativa contra uma Evolution morta.
    assert "evolution_status = 'conectado'" in sql
    assert conn.params[0] == recon._DESCULPA_PILOTO_JANELA_HORAS


async def test_falha_de_um_nao_derruba_a_varredura(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _Conn(
        [
            {"atendimento_id": "a1", "conversa_id": "c1"},
            {"atendimento_id": "a2", "conversa_id": "c2"},
        ]
    )

    class _RedisQuebrado(_Redis):
        async def enqueue_job(self, nome: str, **kwargs: Any) -> None:
            if kwargs.get("conversa_id") == "c1":
                raise RuntimeError("redis fora")
            await super().enqueue_job(nome, **kwargs)

    redis = _RedisQuebrado()
    n = await recon.reconciliar_desculpa_piloto({"db_pool": _Pool(conn), "redis": redis})

    assert n == 1
    assert [j["conversa_id"] for j in redis.jobs] == ["c2"]


async def test_ctx_incompleto_e_no_op() -> None:
    assert await recon.reconciliar_desculpa_piloto({}) == 0
