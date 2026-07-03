"""Testes unit do judge pós-envio (workers/judge_pos_envio) — sem DB, sem DeepSeek real.

`FakePool`/`FakeConn` roteiam por substring do SQL; o `_julgar` é monkeypatchado nos testes de
fluxo (veredito canned) e testado à parte com um chat fake. Espelha o estilo de test_baixo_score.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from barra.settings import get_settings
from barra.workers import judge_pos_envio
from barra.workers.judge_pos_envio import VeredictoTurno, julgar_turno_pos_envio

CONVERSA = "22222222-2222-4222-8222-222222222222"
MODELO = "33333333-3333-4333-8333-333333333333"


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    """Roteia por substring do SQL; grava os INSERTs em `inserts`."""

    def __init__(
        self,
        *,
        ja_julgado: bool = False,
        contexto: list[dict[str, Any]] | None = None,
        tem_conversa: bool = True,
    ) -> None:
        self.ja_julgado = ja_julgado
        self.contexto = contexto or []
        self.tem_conversa = tem_conversa
        self.inserts: list[tuple[Any, ...]] = []

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        if "INSERT INTO barravips.julgamentos_turno" in sql:
            assert params is not None
            self.inserts.append(params)
            return _Result([])
        if "FROM barravips.julgamentos_turno" in sql:
            return _Result([{"ok": 1}] if self.ja_julgado else [])
        if "FROM barravips.conversas" in sql:
            return _Result([{"modelo_id": MODELO}] if self.tem_conversa else [])
        if "FROM barravips.mensagens" in sql:
            return _Result(self.contexto)
        raise AssertionError(f"SQL inesperado: {sql}")


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def connection(self) -> Any:
        conn = self._conn

        class _Ctx:
            async def __aenter__(self) -> FakeConn:
                return conn

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _Ctx()


def _ctx(conn: FakeConn, **over: Any) -> dict[str, Any]:
    settings = get_settings().model_copy(update={"judge_pos_envio_ativo": True, **over})
    return {"settings": settings, "db_pool": FakePool(conn)}


def _rodar(ctx: dict[str, Any], chunks: list[str], trace_id: str | None = None) -> int:
    return asyncio.run(
        julgar_turno_pos_envio(
            ctx, conversa_id=CONVERSA, turno_id="t1:0", chunks=chunks, trace_id=trace_id
        )
    )


def _veredito(**over: Any) -> VeredictoTurno:
    base: dict[str, Any] = {"rastro_llm": False, "voz": 4, "conduta": 5, "comentario": "ok"}
    base.update(over)
    return VeredictoTurno(**base)


def test_flag_off_nao_julga(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    ctx = {
        "settings": get_settings().model_copy(update={"judge_pos_envio_ativo": False}),
        "db_pool": FakePool(conn),
    }
    assert (
        asyncio.run(
            julgar_turno_pos_envio(ctx, conversa_id=CONVERSA, turno_id="t1:0", chunks=["oi"])
        )
        == 0
    )
    assert conn.inserts == []


def test_turno_vazio_nao_julga() -> None:
    conn = FakeConn()
    assert _rodar(_ctx(conn), ["", "  "]) == 0
    assert conn.inserts == []


def test_ja_julgado_pula_sem_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    chamado: list[Any] = []

    async def _julgar_espiao(*a: Any, **kw: Any) -> VeredictoTurno:
        chamado.append(a)
        return _veredito()

    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_espiao)
    conn = FakeConn(ja_julgado=True)
    assert _rodar(_ctx(conn), ["oi amor"]) == 0
    assert chamado == [] and conn.inserts == []


def test_fluxo_feliz_persiste_e_pontua_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[tuple[str, str]] = []

    async def _julgar_fake(contexto: str, turno: str, settings: Any) -> VeredictoTurno:
        prompts.append((contexto, turno))
        return _veredito()

    scores: list[tuple[str, str, float]] = []
    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_fake)
    monkeypatch.setattr(
        judge_pos_envio,
        "registrar_feedback_online",
        lambda trace_id, nome, score: scores.append((trace_id, nome, score)),
    )
    conn = FakeConn(
        contexto=[
            # mais novas primeiro (o módulo inverte p/ cronológico)
            {"direcao": "ia", "conteudo": "R$400 a hora"},
            {"direcao": "cliente", "conteudo": "quanto fica?"},
        ]
    )
    assert _rodar(_ctx(conn), ["consigo hoje sim", "que horas amor?"], trace_id="tr-1") == 1

    contexto, turno = prompts[0]
    # contexto em ordem cronológica, com rótulo em personagem (ia -> "ela")
    assert contexto == "cliente: quanto fica?\nela: R$400 a hora"
    assert turno == "consigo hoje sim\n\nque horas amor?"

    assert len(conn.inserts) == 1
    turno_id, conversa_id, modelo_id, rastro, voz, conduta, comentario = conn.inserts[0]
    assert (turno_id, conversa_id, modelo_id) == ("t1:0", CONVERSA, MODELO)
    assert (rastro, voz, conduta, comentario) == (False, 4, 5, "ok")

    # 3 eixos no MESMO trace do turno
    assert scores == [
        ("tr-1", "judge_rastro_llm", 1.0),
        ("tr-1", "judge_voz", 4 / 5),
        ("tr-1", "judge_conduta", 1.0),
    ]


def test_rastro_loga_nao_contido(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _julgar_fake(*a: Any, **kw: Any) -> VeredictoTurno:
        return _veredito(rastro_llm=True, voz=2, comentario="falou do cliente em 3a pessoa")

    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_fake)
    conn = FakeConn()
    with caplog.at_level("WARNING"):
        assert _rodar(_ctx(conn), ["o cliente quer saber o valor"]) == 1
    assert any("RASTRO NAO-CONTIDO" in r.message for r in caplog.records)
    # persistiu com rastro_llm=True — é a fonte do gatilho de rollback
    assert conn.inserts[0][3] is True


def test_judge_indisponivel_nao_persiste(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _julgar_quebrado(*a: Any, **kw: Any) -> VeredictoTurno:
        raise RuntimeError("deepseek 402")

    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_quebrado)
    conn = FakeConn()
    assert _rodar(_ctx(conn), ["oi"]) == 0
    assert conn.inserts == []


def test_sem_trace_id_nao_pontua_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _julgar_fake(*a: Any, **kw: Any) -> VeredictoTurno:
        return _veredito()

    scores: list[Any] = []
    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_fake)
    monkeypatch.setattr(judge_pos_envio, "registrar_feedback_online", lambda *a: scores.append(a))
    conn = FakeConn()
    assert _rodar(_ctx(conn), ["oi amor"], trace_id=None) == 1
    assert scores == [] and len(conn.inserts) == 1


class _FakeRedis:
    """smembers de `enviados:{turno_id}` (bytes, como o redis real sem decode_responses)."""

    def __init__(self, marcadores: set[str]) -> None:
        self._marcadores = marcadores

    async def smembers(self, chave: str) -> set[bytes]:
        return {m.encode() for m in self._marcadores}


def test_so_julga_chunks_realmente_enviados(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turno barrado pela rede final (sem marcador chunk:N) NÃO vira falso não-contido; envio
    parcial julga só o que saiu."""
    prompts: list[str] = []

    async def _julgar_fake(contexto: str, turno: str, settings: Any) -> VeredictoTurno:
        prompts.append(turno)
        return _veredito()

    monkeypatch.setattr(judge_pos_envio, "_julgar", _julgar_fake)

    # nada enviado (rede final barrou / cancelado): pula sem julgar nem persistir
    conn = FakeConn()
    ctx = _ctx(conn)
    ctx["redis"] = _FakeRedis({"read"})
    assert _rodar(ctx, ["bolha barrada"]) == 0
    assert prompts == [] and conn.inserts == []

    # envio parcial: só o chunk 0 saiu -> julga só ele
    conn2 = FakeConn()
    ctx2 = _ctx(conn2)
    ctx2["redis"] = _FakeRedis({"read", "chunk:0"})
    assert _rodar(ctx2, ["saiu", "nao saiu"]) == 1
    assert prompts == ["saiu"] and len(conn2.inserts) == 1


def test_julgar_unit_chat_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_julgar` de verdade com chat fake: monta system+user e devolve o parsed."""
    import barra.agente._instrumentar as instrumentar_mod
    import barra.core.llm as llm_mod

    chamadas: list[Any] = []

    class _FakeChain:
        async def ainvoke(self, mensagens: Any, config: Any = None) -> dict[str, Any]:
            chamadas.append(mensagens)
            return {"raw": None, "parsed": _veredito(voz=5), "parsing_error": None}

    class _FakeChat:
        def with_structured_output(self, *a: Any, **kw: Any) -> _FakeChain:
            return _FakeChain()

    monkeypatch.setattr(llm_mod, "criar_chat_deepseek", lambda settings, **kw: _FakeChat())
    monkeypatch.setattr(instrumentar_mod, "instrumentar_tokens", lambda *a, **kw: None)

    veredito = asyncio.run(judge_pos_envio._julgar("cliente: oi", "oi amor", get_settings()))
    assert veredito.voz == 5
    mensagens = chamadas[0]
    assert mensagens[0]["role"] == "system" and "rastro_llm" in mensagens[0]["content"]
    assert "TURNO ENVIADO" in mensagens[1]["content"] and "oi amor" in mensagens[1]["content"]
