"""Trilho determinístico do período longo (feedbacks 21-22/07): tabela sem pacote de 6h+
injeta <sem_periodo_longo> no contexto do turno — a IA fica proibida por dado, não só por
prosa, de prometer/precificar pernoite que não existe ("pernoite 12h, 2000" inventado)."""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Serve o atendimento e o MAX(horas) da tabela; vazio no resto."""

    def __init__(self, max_horas: float) -> None:
        self.max_horas = max_horas

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "barravips.atendimentos" in sql and "numero_curto" in sql:
            return _Result([{"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": None}])
        if "MAX(d.horas)" in sql:
            return _Result([{"max_horas": self.max_horas}])
        return _Result([])


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 22, 23, 0, tzinfo=UTC),
    )


async def test_tabela_so_curta_injeta_sem_periodo_longo() -> None:
    variaveis = await _resolver_variaveis(_FakeConn(1), _ctx())  # type: ignore[arg-type]
    assert variaveis["sem_periodo_longo"] is True
    saida = render_contexto_dinamico(**variaveis)
    assert "<sem_periodo_longo>" in saida
    assert "até 1h" in saida
    assert "fora_de_oferta" in saida


async def test_tabela_com_periodo_longo_nao_injeta() -> None:
    variaveis = await _resolver_variaveis(_FakeConn(12), _ctx())  # type: ignore[arg-type]
    assert variaveis["sem_periodo_longo"] is False
    assert "<sem_periodo_longo>" not in render_contexto_dinamico(**variaveis)


async def test_seis_horas_ja_conta_como_periodo_longo() -> None:
    variaveis = await _resolver_variaveis(_FakeConn(6), _ctx())  # type: ignore[arg-type]
    assert variaveis["sem_periodo_longo"] is False


async def test_cadastro_vazio_nao_injeta() -> None:
    # max 0 = modelo sem programas (estado anormal de cadastro) — não é "sem período longo".
    variaveis = await _resolver_variaveis(_FakeConn(0), _ctx())  # type: ignore[arg-type]
    assert variaveis["sem_periodo_longo"] is False
    assert "<sem_periodo_longo>" not in render_contexto_dinamico(**variaveis)
