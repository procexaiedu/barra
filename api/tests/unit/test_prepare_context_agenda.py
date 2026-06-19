"""Regressão dos bugs de agenda/tempo capturados no teste E2E ao vivo (grupo Lucia, 2026-06-05):

A) o contexto dinâmico injeta data E hora LOCAIS (America/Sao_Paulo), não só `current_date` em
   UTC — sem a hora a IA não resolve "daqui 1h" e chuta o horário do bloqueio;
B) a lista de bloqueios do contexto EXCLUI o bloqueio do próprio atendimento — senão, sem
   checkpointer, a IA vê a reserva que ela mesma criou como "ocupada" e recusa o próprio slot.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

BRT = timezone(timedelta(hours=-3))


def test_render_contexto_inclui_hora_atual() -> None:
    saida = render_contexto_dinamico(
        data_atual=date(2026, 6, 5),
        hora_atual="22:30",
        bloqueios=[],
        pix_status="ainda não pedido",
    )
    assert 'hoje="2026-06-05"' in saida
    assert 'agora="22:30"' in saida


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Registra (sql, params); devolve a hora local fixa na query de relógio, vazio no resto."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        self.calls.append((sql, params))
        if "AT TIME ZONE" in sql:
            return _Result(
                [
                    {
                        "agora": datetime(2026, 6, 5, 22, 30),
                        "agora_tz": datetime(2026, 6, 5, 22, 30, tzinfo=BRT),
                    }
                ]
            )
        return _Result([])


async def test_resolver_variaveis_hora_local_e_exclui_bloqueio_atual() -> None:
    conn = _FakeConn()
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )

    variaveis = await _resolver_variaveis(conn, ctx)  # type: ignore[arg-type]

    # A: data + hora locais derivadas do timestamp em America/Sao_Paulo.
    assert variaveis["data_atual"] == date(2026, 6, 5)
    assert variaveis["hora_atual"] == "22:30"
    assert any("America/Sao_Paulo" in sql for sql, _ in conn.calls)

    # B: a query de bloqueios exclui o atendimento atual e passa o id como parâmetro.
    sql_bloq, params_bloq = next((sql, p) for sql, p in conn.calls if "barravips.bloqueios" in sql)
    assert "IS DISTINCT FROM" in sql_bloq
    assert ctx.atendimento_id in params_bloq
