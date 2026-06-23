"""Regressão do handoff silencioso (teste E2E ao vivo 2026-06-05, grupo Lucia): o cron de
reconciliação entrega cards de escalada órfãos — abertos (`fechada_em IS NULL`), sem
`card_message_id` — chamando `enviar_card` INLINE (idempotente), independente do enqueue ARQ.
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


async def test_reconciliar_entrega_cards_orfaos(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _Conn(
        [
            {"id": "e1", "tipo": "comportamento_atipico", "atendimento_id": "a1"},
            {"id": "e2", "tipo": "fora_de_oferta", "atendimento_id": "a2"},
        ]
    )
    ctx = {"db_pool": _Pool(conn), "evolution": object()}

    chamadas: list[tuple[str, str]] = []

    async def fake_enviar_card(_ctx: Any, *, tipo: str, **kw: Any) -> None:
        chamadas.append((tipo, kw["escalada_id"]))

    monkeypatch.setattr(recon, "enviar_card", fake_enviar_card)

    n = await recon.reconciliar_cards_escalada(ctx)

    assert n == 2
    assert chamadas == [("escalada", "e1"), ("escalada", "e2")]
    # Só escaladas abertas e ainda sem card (idempotência por owner no _card_escalada).
    assert conn.sql is not None
    assert "card_message_id IS NULL" in conn.sql
    assert "fechada_em IS NULL" in conn.sql
    # Roteamento por owner (UX §9.6): só órfãs que viram card no grupo entram na reconciliação —
    # owner=Fernando vai pro painel, então fica de fora (senão o _card_escalada no-op as relê
    # toda rodada, represando órfãs reais da modelo).
    assert "responsavel = 'modelo'" in conn.sql


async def test_reconciliar_tipo_proprio_usa_card_proprio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão (E2E ao vivo 2026-06-17, grupo Lucia): tipos com card PRÓPRIO não podem cair no
    card genérico `escalada` (🔔) — isso envenena a idempotência por owner e o card próprio nunca
    sai. Cada tipo é reconciliado com o SEU card: `foto_portaria` → 🚪 chegada (+foto),
    `cliente_busca` → 🤝 e `video_chamada` → 🎥 (go-time, ADR 0020/0021). O resto cai no `escalada`.
    """
    conn = _Conn(
        [
            {"id": "e1", "tipo": "foto_portaria", "atendimento_id": "a1"},
            {"id": "e2", "tipo": "cliente_busca", "atendimento_id": "a2"},
            {"id": "e3", "tipo": "video_chamada", "atendimento_id": "a3"},
            {"id": "e4", "tipo": "fora_de_oferta", "atendimento_id": "a4"},
        ]
    )
    ctx = {"db_pool": _Pool(conn), "evolution": object()}

    chamadas: list[tuple[str, str, str]] = []

    async def fake_enviar_card(_ctx: Any, *, tipo: str, **kw: Any) -> None:
        chamadas.append((tipo, kw["escalada_id"], kw["atendimento_id"]))

    monkeypatch.setattr(recon, "enviar_card", fake_enviar_card)

    n = await recon.reconciliar_cards_escalada(ctx)

    assert n == 4
    # Cada tipo com card próprio vai pro SEU card; só os sem card próprio caem no `escalada`.
    assert chamadas == [
        ("chegada", "e1", "a1"),
        ("cliente_busca", "e2", "a2"),
        ("video_chamada", "e3", "a3"),
        ("escalada", "e4", "a4"),
    ]


async def test_reconciliar_noop_sem_pool() -> None:
    assert await recon.reconciliar_cards_escalada({}) == 0
