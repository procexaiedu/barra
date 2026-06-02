"""Regressao CUSTO-01: a LINHA individual de receita (listar_receitas) calcula o repasse sobre o
VALOR DO SERVICO (liquido de taxa), nao sobre o bruto inflado pela taxa (ADR 0013) — senao a
linha/CSV divergiria do somatorio do periodo (achado do domain-isolation-reviewer). FakeConn,
sem DB real.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from barra.core.janela import Janela
from barra.dominio.financeiro.repo import listar_receitas


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_: Any, **__: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _linha(taxa: float | None) -> dict[str, Any]:
    # cartao 10%: cliente pagou 1100 bruto p/ um servico de 1000. Repasse 30% = 300 (do servico),
    # NUNCA 330 (do bruto).
    return {
        "atendimento_id": uuid4(),
        "numero_curto": 1,
        "fechado_em": datetime(2026, 6, 1, tzinfo=UTC),
        "modelo_id": uuid4(),
        "modelo_nome": "M",
        "cliente_id": uuid4(),
        "cliente_nome": "C",
        "forma_pagamento": "cartao",
        "valor_final": 1100.0,
        "taxa_cartao_snapshot": taxa,
        "percentual_repasse_snapshot": 30.0,
    }


async def test_repasse_da_linha_usa_valor_servico_com_taxa() -> None:
    janela = Janela(
        de=datetime(2026, 6, 1, tzinfo=UTC).date(),
        ate=datetime(2026, 6, 30, tzinfo=UTC).date(),
        inicio=datetime(2026, 6, 1, tzinfo=UTC),
        fim=datetime(2026, 6, 30, tzinfo=UTC),
    )
    conn = _FakeConn([_linha(taxa=10.0)])
    items, _ = await listar_receitas(conn, janela, None, None, limit=10, cursor=None)  # type: ignore[arg-type]
    assert items[0].valor_repasse_calculado == pytest.approx(300.0)  # 1000 * 30%, nao 330


async def test_repasse_da_linha_sem_taxa_e_no_op() -> None:
    janela = Janela(
        de=datetime(2026, 6, 1, tzinfo=UTC).date(),
        ate=datetime(2026, 6, 30, tzinfo=UTC).date(),
        inicio=datetime(2026, 6, 1, tzinfo=UTC),
        fim=datetime(2026, 6, 30, tzinfo=UTC),
    )
    conn = _FakeConn([_linha(taxa=None)])
    items, _ = await listar_receitas(conn, janela, None, None, limit=10, cursor=None)  # type: ignore[arg-type]
    assert items[0].valor_repasse_calculado == pytest.approx(330.0)  # sem taxa, servico == bruto
