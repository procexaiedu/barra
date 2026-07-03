"""Regressão dos bugs de agenda/tempo capturados no teste E2E ao vivo (grupo Lucia, 2026-06-05):

A) o contexto dinâmico injeta data E hora LOCAIS (America/Sao_Paulo), não só `current_date` em
   UTC — sem a hora a IA não resolve "daqui 1h" e chuta o horário do bloqueio;
B) a lista de bloqueios do contexto EXCLUI o bloqueio do próprio atendimento — senão, sem
   checkpointer, a IA vê a reserva que ela mesma criou como "ocupada" e recusa o próprio slot.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.conversas.modelos import DirecaoMensagem

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


class _FakeConnComAtendimento:
    """Devolve um atendimento interno com horário combinado; vazio no resto. `agora` vem do
    ctx.agora_utc (clock injection), então não há query de relógio."""

    def __init__(self, atendimento: dict[str, Any]) -> None:
        self.atendimento = atendimento

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "barravips.atendimentos" in sql and "numero_curto" in sql:
            return _Result([self.atendimento])
        return _Result([])


async def test_marcadores_de_tempo_e_horario_minimo_por_tipo() -> None:
    # Emenda ADR 0025 (2026-06-26): percepção de tempo na cauda + horario_minimo ~agora p/ interno.
    # agora = 2026-06-29 (2ª) 20:00 BRT (= 23:00 UTC), injetado via ctx.agora_utc.
    agora_utc = datetime(2026, 6, 29, 23, 0, tzinfo=UTC)
    conn = _FakeConnComAtendimento(
        {
            "numero_curto": 1,
            "estado": "Aguardando_confirmacao",
            "tipo_atendimento": "interno",
            "data_desejada": date(2026, 6, 29),
            "horario_desejado": time(20, 30),  # combinado p/ daqui 30 min
        }
    )
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=agora_utc,
    )
    # cliente falou às 19:55 BRT (= 22:55 UTC) -> faz 5 min.
    linhas = [
        {
            "direcao": DirecaoMensagem.cliente,
            "created_at": datetime(2026, 6, 29, 22, 55, tzinfo=UTC),
        }
    ]

    variaveis = await _resolver_variaveis(conn, ctx, linhas)  # type: ignore[arg-type]

    # E: marcadores de tempo na cauda.
    assert variaveis["min_desde_ultima_msg_cliente"] == 5
    assert variaveis["combinado_hora"] == "20:30"
    assert variaveis["min_para_combinado"] == 30
    # B: interno sem deslocamento + livre -> horario_minimo ancorado em ~agora (20:00), não +30.
    assert variaveis["horario_minimo"].astimezone(BRT).strftime("%H:%M") == "20:00"

    # O template renderiza os dois marcadores na cauda.
    saida = render_contexto_dinamico(**variaveis)
    assert "<relogio_do_encontro" in saida
    assert 'combinado="20:30"' in saida
    assert "faltam ~30 min" in saida
    assert "<tempo_desde_ultima_msg_cliente" in saida
    assert 'minutos="5"' in saida


async def test_relogio_do_encontro_so_com_horario_combinado_nao_desejado() -> None:
    # CONTEXT.md: desejado ≠ combinado. Em Qualificado o horário ainda está em negociação — o relógio
    # do encontro NÃO pode renderizar (senão a conduta de chegada trataria um horário só-desejado e
    # vencido como "é a hora"). Mesmos dados do teste acima, mas estado pré-confirmação.
    conn = _FakeConnComAtendimento(
        {
            "numero_curto": 1,
            "estado": "Qualificado",
            "tipo_atendimento": "interno",
            "data_desejada": date(2026, 6, 29),
            "horario_desejado": time(20, 30),
        }
    )
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 6, 29, 23, 0, tzinfo=UTC),
    )

    variaveis = await _resolver_variaveis(conn, ctx, [])  # type: ignore[arg-type]

    assert variaveis["combinado_hora"] is None
    assert variaveis["min_para_combinado"] is None
    assert "<relogio_do_encontro" not in render_contexto_dinamico(**variaveis)
