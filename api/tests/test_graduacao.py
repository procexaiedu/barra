"""Testes unit do relatorio de graduacao (dominio/graduacao) -- sem DB.

FakeConn devolve agregados canned roteando por substring do SQL (mesmo padrao de
`test_rollback_watch` / `test_digest_semanal`). O que se afirma aqui e a LEITURA dos criterios do
ADR-0034: quando cada um atende, quando REPROVA, e quando fica indeterminado -- a distincao que
o relatorio existe para nao perder.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from barra.dominio.graduacao import repo, service
from barra.dominio.graduacao.relatorio import renderizar
from barra.dominio.graduacao.schemas import RelatorioGraduacao, SemanaGate

INICIO = datetime(2026, 7, 1, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    """Roteia por substring do SQL. Cada branch casa a tabela-ALVO da consulta."""

    def __init__(
        self,
        *,
        inicio: datetime | None = INICIO,
        completas: int = 120,
        com_atendimento: int = 130,
        incidentes: tuple[int, int, int] = (0, 0, 0),  # total, abertos, triados
        turnos_julgados: int = 900,
        semanas: list[dict[str, Any]] | None = None,
        fechados: int = 45,
        terminais: int = 100,
        baseline: dict[str, Any] | None = None,
        baseline_existe: bool = True,
    ) -> None:
        self.inicio = inicio
        self.completas = completas
        self.com_atendimento = com_atendimento
        self.incidentes = incidentes
        self.turnos_julgados = turnos_julgados
        self.semanas = semanas if semanas is not None else _serie([2, 2, 1])
        self.fechados = fechados
        self.terminais = terminais
        self.baseline = baseline
        self.baseline_existe = baseline_existe
        self.sqls: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _Result:
        self.sqls.append(sql)
        if "min(m.created_at)" in sql:
            return _Result([{"inicio": self.inicio}])
        if "to_regclass" in sql:
            return _Result([{"existe": self.baseline_existe}])
        if "FROM barravips.graduacao_baseline" in sql:
            return _Result([self.baseline] if self.baseline else [])
        if "bool_or(a.estado" in sql:
            return _Result([{"com_atendimento": self.com_atendimento, "completas": self.completas}])
        if "j.rastro_llm" in sql:
            total, abertos, triados = self.incidentes
            return _Result([{"total": total, "abertos": abertos, "triados": triados}])
        if "WITH aborts AS" in sql:
            return _Result(self.semanas)
        if "FROM barravips.julgamentos_turno" in sql:
            return _Result([{"n": self.turnos_julgados}])
        if "FROM barravips.atendimentos a" in sql:
            return _Result([{"terminais": self.terminais, "fechados": self.fechados}])
        raise AssertionError(f"SQL inesperado: {sql}")


def _serie(aborts: list[int], julgados: int = 200) -> list[dict[str, Any]]:
    """Uma semana por elemento de `aborts`, com denominador fixo."""
    return [
        {"semana": date(2026, 7, 6 + 7 * i), "aborts": n, "julgados": julgados}
        for i, n in enumerate(aborts)
    ]


BASELINE = {
    "conversao_pct": 50.0,
    "amostra_n": 320,
    "fonte": "corpus do vendedor 2026-05/06",
    "registrado_em": datetime(2026, 8, 1, tzinfo=UTC),
}


def _gerar(**kw: Any) -> RelatorioGraduacao:
    return asyncio.run(service.gerar_relatorio(FakeConn(**kw)))  # type: ignore[arg-type]


# --- recorte de cliente real ---------------------------------------------------------------


def test_todo_sql_recorta_cliente_real() -> None:
    """O rig de teste (`...@g.us`) e o harness e2e nao podem inflar nenhum dos 4 criterios."""
    conn = FakeConn(baseline=BASELINE)
    asyncio.run(service.gerar_relatorio(conn))  # type: ignore[arg-type]
    consultas = [s for s in conn.sqls if "barravips.conversas" in s]
    assert len(consultas) >= 5
    for sql in consultas:
        assert "@g.us" in sql, f"SQL sem recorte do rig: {sql}"
        assert "c.origem = 'prod'" in sql, f"SQL sem recorte do harness e2e: {sql}"


def test_predicado_de_abort_espelha_o_rollback_watch() -> None:
    """A definicao de abort do gate e a MESMA do gatilho de rollback.

    `dominio/` nao pode importar `workers/` (direcao das dependencias), entao o predicado e
    copiado -- este teste e a costura que impede a copia de derivar em silencio.
    """
    from barra.workers import rollback_watch

    assert repo.PREDICADO_ABORT_GATE in rollback_watch._SQL_GATE_ABORTS


# --- criterio 1: conversas ------------------------------------------------------------------


def test_conversas_atende_a_partir_de_100_completas() -> None:
    rel = _gerar(completas=100, com_atendimento=112, baseline=BASELINE)
    assert rel.conversas.atende is True
    assert rel.conversas.completas == 100
    assert rel.conversas.em_curso == 12


def test_conversas_em_curso_nao_contam_para_o_limiar() -> None:
    """99 completas + 40 em curso continua NAO atendendo: o limiar e de ciclo fechado."""
    rel = _gerar(completas=99, com_atendimento=139, baseline=BASELINE)
    assert rel.conversas.atende is False
    assert rel.apto is False


# --- criterio 2: incidentes -----------------------------------------------------------------


def test_incidente_triado_ainda_reprova() -> None:
    """O gatilho de rollback perdoa o triado (mede risco ABERTO); a graduacao pede zero HISTORICO."""
    rel = _gerar(incidentes=(1, 0, 1), baseline=BASELINE)
    assert rel.incidentes.atende is False
    assert (rel.incidentes.abertos, rel.incidentes.triados) == (0, 1)


def test_zero_incidente_sem_amostra_do_judge_e_indeterminado() -> None:
    """Zero sem nenhum turno julgado e ausencia de medida -- nao pode passar de graca."""
    rel = _gerar(incidentes=(0, 0, 0), turnos_julgados=0, baseline=BASELINE)
    assert rel.incidentes.atende is None
    assert rel.apto is False
    assert any("ausencia de medida" in g for g in rel.gaps)


# --- criterio 3: taxa do gate ---------------------------------------------------------------


def test_taxa_do_gate_caindo_atende() -> None:
    rel = _gerar(semanas=_serie([20, 12, 4]), baseline=BASELINE)
    assert rel.taxa_gate.tendencia == "caindo"
    assert rel.taxa_gate.atende is True
    assert rel.taxa_gate.inclinacao_pp_semana is not None
    assert rel.taxa_gate.inclinacao_pp_semana < 0


def test_taxa_do_gate_subindo_reprova() -> None:
    rel = _gerar(semanas=_serie([2, 14, 30]), baseline=BASELINE)
    assert rel.taxa_gate.tendencia == "subindo"
    assert rel.taxa_gate.atende is False


def test_ruido_pequeno_conta_como_estavel() -> None:
    """Oscilacao dentro da tolerancia nao vira 'subindo' -- serie curta ruidosa nao reprova."""
    rel = _gerar(semanas=_serie([4, 5, 4, 5]), baseline=BASELINE)
    assert rel.taxa_gate.tendencia == "estavel"
    assert rel.taxa_gate.atende is True


def test_semana_sem_trafego_sai_da_serie() -> None:
    """0 abort em 0 turno nao e gate saudavel: e semana parada, e puxaria a tendencia."""
    semanas = _serie([10, 5])
    semanas.append({"semana": date(2026, 7, 27), "aborts": 0, "julgados": 0})
    rel = _gerar(semanas=semanas, baseline=BASELINE)
    assert [s.semana for s in rel.taxa_gate.semanas] == [date(2026, 7, 6), date(2026, 7, 13)]


def test_uma_semana_so_nao_tem_tendencia() -> None:
    rel = _gerar(semanas=_serie([5]), baseline=BASELINE)
    assert rel.taxa_gate.tendencia == "indeterminada"
    assert rel.taxa_gate.atende is None
    assert any("duas leituras" in g for g in rel.gaps)


def test_universo_soma_aborts_e_julgados() -> None:
    """Abort nao vira julgamento (o turno nao saiu): os dois somam, um nao contem o outro."""
    rel = _gerar(semanas=_serie([50, 50], julgados=150), baseline=BASELINE)
    assert rel.taxa_gate.semanas[0] == SemanaGate(
        semana=date(2026, 7, 6), aborts=50, julgados=150, universo=200, taxa=0.25
    )


# --- criterio 4: conversao ------------------------------------------------------------------


def test_conversao_acima_de_80pct_do_baseline_atende() -> None:
    rel = _gerar(fechados=45, terminais=100, baseline=BASELINE)  # 45% vs baseline 50% -> 0.90
    assert rel.conversao.conversao_pct == 45.0
    assert rel.conversao.razao == 0.90
    assert rel.conversao.atende is True


def test_conversao_abaixo_de_80pct_do_baseline_reprova() -> None:
    rel = _gerar(fechados=39, terminais=100, baseline=BASELINE)  # 0.78
    assert rel.conversao.atende is False


def test_sem_baseline_o_criterio_fica_indeterminado_e_vira_gap() -> None:
    """Sem denominador o 4o criterio nao e computavel -- e isso precisa aparecer, nao virar 0."""
    rel = _gerar(baseline=None)
    assert rel.conversao.atende is None
    assert rel.conversao.conversao_pct == 45.0
    assert rel.conversao.baseline_pct is None
    assert rel.apto is False
    assert any("graduacao_baseline" in g for g in rel.gaps)


def test_tabela_de_baseline_ausente_nao_quebra_o_relatorio() -> None:
    """O relatorio roda ANTES da migration chegar no ambiente -- e serve para mostrar que falta."""
    rel = _gerar(baseline_existe=False, baseline=BASELINE)
    assert rel.conversao.baseline_pct is None
    assert rel.conversao.atende is None


def test_sem_atendimento_terminal_a_conversao_nao_e_zero() -> None:
    rel = _gerar(fechados=0, terminais=0, baseline=BASELINE)
    assert rel.conversao.conversao_pct is None
    assert rel.conversao.atende is None
    assert any("sem denominador" in g for g in rel.gaps)


# --- veredito e porta fechada ---------------------------------------------------------------


def test_apto_exige_os_quatro_criterios() -> None:
    rel = _gerar(baseline=BASELINE)
    assert (
        rel.conversas.atende,
        rel.incidentes.atende,
        rel.taxa_gate.atende,
        rel.conversao.atende,
    ) == (True, True, True, True)
    assert rel.apto is True


def test_indeterminado_nunca_gradua() -> None:
    """`apto` exige `True` nos quatro: indeterminado nao e aprovacao silenciosa."""
    rel = _gerar(baseline=None)
    assert rel.apto is False


def test_porta_fechada_deixa_tudo_indeterminado() -> None:
    """Sem turno da IA para cliente real, zero e AUSENCIA DE SINAL (ADR-0034), nao saude."""
    rel = _gerar(inicio=None)
    assert rel.piloto_inicio_origem == "ausente"
    assert rel.piloto_inicio_em is None
    assert [c.atende for c in (rel.conversas, rel.incidentes, rel.taxa_gate, rel.conversao)] == [
        None,
        None,
        None,
        None,
    ]
    assert rel.apto is False
    assert any("porta ainda esta fechada" in g for g in rel.gaps)


def test_desde_explicito_vence_a_derivacao() -> None:
    conn = FakeConn(baseline=BASELINE)
    rel = asyncio.run(service.gerar_relatorio(conn, desde=datetime(2026, 8, 1, tzinfo=UTC)))  # type: ignore[arg-type]
    assert rel.piloto_inicio_origem == "informado"
    assert rel.piloto_inicio_em == datetime(2026, 8, 1, tzinfo=UTC)
    assert not any("min(m.created_at)" in s for s in conn.sqls)


def test_gaps_estruturais_sempre_presentes() -> None:
    """Mesmo com os 4 criterios verdes, o relatorio diz o que os numeros nao cobrem."""
    rel = _gerar(baseline=BASELINE)
    assert rel.apto is True
    assert any("SUBCONTADA" in g for g in rel.gaps)
    assert any("turnos julgados" in g for g in rel.gaps)


# --- render ---------------------------------------------------------------------------------


def test_render_marca_indeterminado_diferente_de_falha() -> None:
    texto = renderizar(_gerar(completas=10, baseline=None))
    assert "[FALHA]" in texto  # criterio 1 reprovou de verdade
    assert "[ ?  ]" in texto  # criterio 4 e indeterminado
    assert "NAO REGISTRADO" in texto
    assert "a decisao de graduar continua humana" in texto


def test_render_da_porta_fechada_nao_quebra() -> None:
    texto = renderizar(_gerar(inicio=None))
    assert "AUSENTE" in texto
    assert "NAO APTO" in texto
