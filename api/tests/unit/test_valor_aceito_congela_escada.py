"""A-D3.2 (campanha 13/08, eb04): valor ACEITO congela a escada de desconto.

O sintoma real: o cliente aceitou o valor (`sinais_qualificacao.aceita_valor` + `valor_acordado`
gravados) e, nos turnos seguintes, a cauda continuava renderizando bloco de escada com o número da
contraproposta na tela (`<ja_fez_contraproposta>`/`<escada_esgotada>`, grupo n>=1 do template, que
não olhava o aceite) — a IA reabria negociação de preço sobre valor já aceito e regalava desconto.

O congelamento tem DUAS pontas, testadas aqui:
  - compute (`_resolver_variaveis`): com o par completo do aceite, nenhum número de contraproposta
    é resolvido (a query da tabela nem roda);
  - render (`contexto_dinamico.md.j2`): o grupo n>=1 não sai quando `valor_aceito and
    valor_fechado` — exatamente a condição que põe o `<valor_fechado>` ("não re-cote nem
    renegocie") na tela: a supressão nunca deixa o turno sem conduta substituta.

Fail-closed pinado: aceite AMBÍGUO (só o sinal, sem `valor_acordado`; ou só a coluna, que o
painel/manual também escreve — #38) mantém o comportamento de sempre. Sem DB, sem crédito.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_AGORA_UTC = datetime(2026, 8, 11, 17, 30, tzinfo=UTC)
_OUTRO_DIA = date(2026, 8, 13)


class _FakeConnCatarina2h:
    """A 2h da Catarina: tabela 800 com piso absoluto 600 (degrau 700)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = (
            [{"programa_id": "p1", "preco": Decimal("800"), "preco_minimo": Decimal("600")}]
            if "modelo_programas" in sql
            else []
        )

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                return None

            async def fetchall(self) -> list[Any]:
                return linhas

        return _R()


async def _contexto(atendimento: dict[str, Any], conn: Any = None) -> ContextoDoTurno:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA_UTC,
    )
    return await _resolver_variaveis(
        conn or _FakeConnCatarina2h(),  # type: ignore[arg-type]
        ctx,
        atendimento=atendimento,
    )


def _pos_aceite(**over: Any) -> dict[str, Any]:
    """O belief do eb04 depois do aceite explícito: sinal + valor gravados, escada já usada."""
    return {
        "estado": "Qualificado",
        "n_contrapropostas": 1,
        "duracao_horas": Decimal("2"),
        "valor_acordado": Decimal("700"),
        "sinais_qualificacao": {"aceita_valor": True},
        "data_desejada": _OUTRO_DIA,
        **over,
    }


# --- compute ------------------------------------------------------------------------------------


async def test_aceite_completo_congela_o_numero_da_escada() -> None:
    """Sem o congelamento, n=1 em outro dia resolvia a última contraproposta (600) e ela ia parar
    no <ja_fez_contraproposta> de um valor já aceito."""
    contexto = await _contexto(_pos_aceite())

    assert contexto.valor_aceito is True
    assert contexto.contraproposta_disponivel is None
    assert contexto.aceite_do_valor_dele is None


async def test_sem_o_sinal_de_aceite_o_comportamento_antigo_fica_de_pe() -> None:
    """`valor_acordado` sozinho NÃO prova acordo (o painel/manual também o escreve, #38): a
    escada segue resolvendo o número da rodada que sobrou."""
    contexto = await _contexto(_pos_aceite(sinais_qualificacao={}))

    assert contexto.valor_aceito is False
    assert contexto.contraproposta_disponivel == "600"


async def test_sinal_sem_valor_gravado_e_aceite_ambiguo_fica_como_esta() -> None:
    """Fail-closed do par: `aceita_valor` sem `valor_acordado` não congela — sem o número da mesa
    o <valor_fechado> não renderiza e suprimir a escada deixaria o turno sem conduta nenhuma."""
    contexto = await _contexto(
        _pos_aceite(valor_acordado=None, cotacao_enviada_em=_AGORA_UTC),
    )

    assert contexto.valor_aceito is True
    assert contexto.contraproposta_disponivel == "600"


# --- render -------------------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_pos_aceite_suprime_o_grupo_da_escada() -> None:
    out = _render(
        n_contrapropostas=1,
        escada_estado="ultima",
        valor_aceito=True,
        valor_fechado="700",
        contraproposta_disponivel="600",
    )

    assert "<ja_fez_contraproposta" not in out
    assert "<escada_esgotada>" not in out
    assert "<escada_travada_sem_o_dia>" not in out
    # A conduta substituta está na tela no MESMO cruzamento que suprime a escada.
    assert "<valor_fechado>" in out
    assert "não re-cote nem renegocie" in out


def test_render_pos_aceite_suprime_tambem_a_escada_esgotada() -> None:
    out = _render(
        n_contrapropostas=2, escada_estado="esgotada", valor_aceito=True, valor_fechado="700"
    )

    assert "<escada_esgotada>" not in out
    assert "<valor_fechado>" in out


def test_render_aceite_sem_valor_fechado_mantem_o_bloco_da_rodada() -> None:
    """O espelho do fail-closed do compute: sem `valor_fechado` não há <valor_fechado> a exibir,
    então o grupo n>=1 continua saindo como sempre saiu."""
    out = _render(n_contrapropostas=1, escada_estado="ultima", valor_aceito=True)

    assert '<ja_fez_contraproposta n="1">' in out
