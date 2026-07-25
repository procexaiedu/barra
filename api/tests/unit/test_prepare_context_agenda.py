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
    """Vazio em todas as queries: o atendimento agora chega por kwarg em _resolver_variaveis (lido
    uma vez pelo gate em prepare_context), não por query. `agora` vem do ctx.agora_utc (clock
    injection), então também não há query de relógio."""

    def __init__(self, atendimento: dict[str, Any]) -> None:
        self.atendimento = atendimento

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
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

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, linhas, atendimento=conn.atendimento
    )

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


class _FakeConnAgenda:
    """Roteia por SQL: devolve as regras de Disponibilidade e os bloqueios; vazio no resto."""

    def __init__(
        self,
        regras: list[dict[str, Any]],
        bloqueios: list[dict[str, Any]],
        atendimento: dict[str, Any],
    ) -> None:
        self.regras = regras
        self.bloqueios = bloqueios
        self.atendimento = atendimento

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "modelo_disponibilidade" in sql:
            return _Result(self.regras)
        if "barravips.bloqueios" in sql:
            return _Result(self.bloqueios)
        return _Result([])


def _ctx_em(agora_utc: datetime) -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=agora_utc,
    )


# Cadastro real do #41: expediente 10:00-04:00 todos os dias.
def _regras_10_as_04() -> list[dict[str, Any]]:
    return [
        {
            "data_inicio": date(2026, 7, 21),
            "data_fim": None,
            "dia_semana": dow,
            "hora_inicio": time(10, 0),
            "hora_fim": time(4, 0),
        }
        for dow in range(7)
    ]


def _bloqueio(inicio_h: int, fim_h: int) -> dict[str, Any]:
    """Bloqueio do dia 24/07 em horas UTC (BRT = UTC-3)."""
    return {
        "inicio": datetime(2026, 7, 24, inicio_h, 0, tzinfo=UTC),
        "fim": datetime(2026, 7, 24, fim_h, 0, tzinfo=UTC),
    }


async def test_proximo_horario_ancora_quando_horario_minimo_some() -> None:
    # Atendimento #41 (24/07): cliente chegou às 05:10 BRT, expediente 10:00-04:00 -> `agora` está
    # FORA, `horario_minimo` vira None e a tag some. Antes do fix, o único horário concreto que
    # sobrava no <agenda> era o `proximo_livre` do bloqueio das 16:00-17:00 (= 17:30) — e a IA o
    # vendeu como "17:30 é o horário que tenho livre hoje", com o dia livre desde as 10h.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[_bloqueio(19, 20)],  # 16:00-17:00 BRT
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": None},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 8, 10, tzinfo=UTC))  # 05:10 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["horario_minimo"] is None  # o silêncio que causou o bug
    proximo = variaveis["proximo_horario"]
    assert proximo is not None
    assert proximo.astimezone(BRT).strftime("%d/%m %H:%M") == "24/07 10:00"

    saida = render_contexto_dinamico(**variaveis)
    assert 'inicio="Fri 24/07 10:00"' in saida
    assert "é o seu primeiro" in saida
    # O 17:30 do bloqueio segue no contexto (a IA precisa saber que a tarde tem um buraco) — mas
    # agora ele não é mais o único horário concreto do <agenda>.
    assert 'proximo_livre="Fri 24/07 17:30"' in saida


async def test_proximo_horario_respeita_bloqueio_em_cima_da_abertura() -> None:
    # A abertura crua (10:00) está OCUPADA: anunciá-la ofereceria um horário já vendido. O valor
    # passa pela mesma aritmética do `horario_minimo` (bloqueio + buffer de 30min) -> 12:30.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[_bloqueio(13, 15)],  # 10:00-12:00 BRT, bem em cima da abertura
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": None},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 8, 10, tzinfo=UTC))  # 05:10 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    proximo = variaveis["proximo_horario"]
    assert proximo is not None
    assert proximo.astimezone(BRT).strftime("%d/%m %H:%M") == "24/07 12:30"


async def test_proximo_horario_cobre_o_fim_do_periodo_de_trabalho() -> None:
    # Zona morta: 03:50 numa janela 10:00-04:00 é `agora` COBERTO (transbordo do dia anterior), mas
    # sem nenhum slot até o encerramento das 04:00 -> `horario_minimo` é None do mesmo jeito. Se o
    # gate fosse "está fora do período de trabalho", este caso ficaria sem sinal — o mesmo silêncio
    # do #41, uma hora antes de o cliente dele chegar.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[],
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": "interno"},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 6, 50, tzinfo=UTC))  # 03:50 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["horario_minimo"] is None
    proximo = variaveis["proximo_horario"]
    assert proximo is not None
    assert proximo.astimezone(BRT).strftime("%d/%m %H:%M") == "24/07 10:00"


async def test_proximo_horario_ausente_quando_ha_horario_minimo() -> None:
    # Dentro da janela e com slot (15:00 BRT): a tag não aparece — quem ancora é o <horario_minimo>.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[],
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": "interno"},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 18, 0, tzinfo=UTC))  # 15:00 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["horario_minimo"] is not None
    assert variaveis["proximo_horario"] is None
    assert "<proximo_horario" not in render_contexto_dinamico(**variaveis)


async def test_proximo_horario_ausente_sem_disponibilidade_cadastrada() -> None:
    # Modelo sem regra é reservável SEMPRE (CONTEXT.md "Disponibilidade"): `horario_minimo` nunca
    # falta, então a tag não nasce. Guarda contra um cadastro vazio virar "não tenho horário".
    conn = _FakeConnAgenda(
        regras=[],
        bloqueios=[],
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": "interno"},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 8, 10, tzinfo=UTC))  # 05:10 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["horario_minimo"] is not None
    assert variaveis["proximo_horario"] is None
    assert "<proximo_horario" not in render_contexto_dinamico(**variaveis)


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

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["combinado_hora"] is None
    assert variaveis["min_para_combinado"] is None
    assert "<relogio_do_encontro" not in render_contexto_dinamico(**variaveis)


async def test_janelas_livres_expoem_a_manha_vaga_do_41() -> None:
    # O POSITIVO que faltava: mesmo cenário do #41 (dia vago, um bloqueio 16-17). Antes, "quando
    # estou livre" era uma subtração que a IA tinha de fazer sobre a lista de ocupados — e ela
    # errou, anunciando o 17:30 como o horário do dia. Agora a manhã inteira sai escrita.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[_bloqueio(19, 20)],  # 16:00-17:00 BRT
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": None},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 8, 10, tzinfo=UTC))  # 05:10 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    janelas = [
        (i.astimezone(BRT).strftime("%d/%m %H:%M"), f.astimezone(BRT).strftime("%d/%m %H:%M"))
        for i, f in variaveis["janelas_livres"]
    ]
    assert janelas[0] == ("24/07 10:00", "24/07 15:30")
    assert janelas[1] == ("24/07 17:30", "25/07 04:00")

    saida = render_contexto_dinamico(**variaveis)
    assert '<janela_livre de="Fri 24/07 10:00" ate="Fri 24/07 15:30"/>' in saida


async def test_janelas_livres_nao_comecam_antes_da_antecedencia() -> None:
    # Externo (com deslocamento) às 15:00 BRT: a 1ª janela não pode abrir antes do que o
    # `horario_minimo` já permite — senão a lista ofereceria um horário que a reserva recusa.
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[],
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": "externo"},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 18, 0, tzinfo=UTC))  # 15:00 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    primeira_janela = variaveis["janelas_livres"][0][0]
    assert primeira_janela == variaveis["horario_minimo"]
    assert primeira_janela.astimezone(BRT).strftime("%H:%M") == "15:30"


async def test_sem_janela_livre_a_tag_some() -> None:
    # Agenda inteira tomada nas 48h: nenhuma janela a anunciar (e nada de tag vazia no prompt).
    conn = _FakeConnAgenda(
        regras=_regras_10_as_04(),
        bloqueios=[
            {
                "inicio": datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
                "fim": datetime(2026, 7, 27, 0, 0, tzinfo=UTC),
            }
        ],
        atendimento={"numero_curto": 41, "estado": "Triagem", "tipo_atendimento": "interno"},
    )
    ctx = _ctx_em(datetime(2026, 7, 24, 18, 0, tzinfo=UTC))  # 15:00 BRT

    variaveis = await _resolver_variaveis(  # type: ignore[arg-type]
        conn, ctx, [], atendimento=conn.atendimento
    )

    assert variaveis["janelas_livres"] == []
    assert "<janela_livre" not in render_contexto_dinamico(**variaveis)
