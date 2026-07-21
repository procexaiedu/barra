"""Contador determinístico de contrapropostas (padrão A2, agente/CLAUDE.md).

A disciplina "desconto é até DUAS contrapropostas na conversa inteira — degrau, depois teto"
(regras.md.j2 <desconto> 3/4, ADR-0031) dependia da janela de 20 msgs: contraproposta fora da
janela → LLM podia ofertar de novo. `_contar_contrapropostas` conta quantas falas da IA batem na
forma canônica ("Consigo 500 se você vier hoje") sobre TODAS as falas da IA do atendimento; o
template injeta a tag instrutiva certa pra cada rodada (nenhuma, 1ª ou 2ª/última). Puro, sem DB.
"""

from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _contar_contrapropostas, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

# --- detector puro ------------------------------------------------------------------------------


def test_conta_contrapropostas_canonicas() -> None:
    assert _contar_contrapropostas(["Consigo 500 se você vier hoje 😊"]) == 1
    assert _contar_contrapropostas(["Poxa amor\n\nConsigo 450 se fechar agora"]) == 1
    # acento/caixa não escondem ("CONSIGO", "consigo R$ 400")
    assert _contar_contrapropostas(["CONSIGO 400 amor"]) == 1
    assert _contar_contrapropostas(["consigo r$ 400 pra hoje"]) == 1


def test_conta_ate_duas_contrapropostas_no_mesmo_atendimento() -> None:
    historico = [
        "Oii",
        "600 1h no meu local",
        "Consigo 500 se você vier hoje 😊",
        "Poxa amor não consigo",
        "Consigo 450 se fechar agora 😊",
    ]
    assert _contar_contrapropostas(historico) == 2


def test_nao_flaga_recusa_nem_horario_nem_cotacao() -> None:
    # recusa da escada ("não consigo") não é contraproposta
    assert _contar_contrapropostas(["Poxa amor não consigo"]) == 0
    # hora não é preço: 1-2 dígitos + h ficam fora do \d{3,}
    assert _contar_contrapropostas(["Consigo às 22h amor", "consigo 14h sim"]) == 0
    # confirmação sem número e cotação de tabela (sem "consigo") ficam fora
    assert _contar_contrapropostas(["Consigo sim amor", "600 1h no meu local"]) == 0
    assert _contar_contrapropostas([]) == 0


# --- reset em atendimento novo (recorrência) -----------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConnMensagensPorAtendimento:
    """Falas da IA indexadas por atendimento_id — simula recorrência: cada atendimento novo tem
    sua própria lista, sem vazamento das contrapropostas de um atendimento anterior do mesmo par."""

    def __init__(self, mensagens_por_atendimento: dict[str, list[str]]) -> None:
        self._mensagens = mensagens_por_atendimento

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        if "barravips.mensagens" in sql:
            conteudos = self._mensagens.get(params[0], [])
            return _Result([{"conteudo": c} for c in conteudos])
        return _Result([])


async def test_contador_reseta_em_atendimento_novo_do_mesmo_par() -> None:
    conn = _FakeConnMensagensPorAtendimento(
        {
            "atendimento-antigo": [
                "Consigo 500 se você vier hoje 😊",
                "Consigo 450 se fechar agora 😊",
            ],
            "atendimento-novo": [],
        }
    )
    base: dict[str, Any] = dict(
        db_pool=None,
        redis=None,
        modelo_id="11111111-1111-1111-1111-111111111111",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )

    variaveis_antigo = await _resolver_variaveis(
        conn,  # type: ignore[arg-type]
        ContextAgente(atendimento_id="atendimento-antigo", **base),
    )
    variaveis_novo = await _resolver_variaveis(
        conn,  # type: ignore[arg-type]
        ContextAgente(atendimento_id="atendimento-novo", **base),
    )

    assert variaveis_antigo["n_contrapropostas"] == 2
    assert variaveis_novo["n_contrapropostas"] == 0


# --- render do template -------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_sem_contraproposta_nao_injeta_tag() -> None:
    assert "<ja_fez_contraproposta" not in _render(n_contrapropostas=0)
    assert "<ja_fez_contraproposta" not in _render()


def test_render_primeira_contraproposta_permite_segunda_rodada() -> None:
    out = _render(n_contrapropostas=1)
    assert '<ja_fez_contraproposta n="1">' in out
    assert "segunda" in out.lower() or "última" in out.lower()


def test_render_segunda_contraproposta_esgota_desconto() -> None:
    out = _render(n_contrapropostas=2)
    assert '<ja_fez_contraproposta n="2">' in out
    assert "fora_de_oferta" in out


def test_render_terceira_insistencia_trata_como_esgotado() -> None:
    # defesa: contagem >2 (não deveria acontecer, mas não pode reabrir oferta) segue como esgotado.
    out = _render(n_contrapropostas=3)
    assert '<ja_fez_contraproposta n="2">' in out
