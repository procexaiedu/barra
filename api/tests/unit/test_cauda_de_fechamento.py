"""M4d (campanha 13/08): as duas mortes da cauda de fechamento viram bloco condicional.

(a) `<janela_futura_vaga>`: cliente adia sem data ("semana que vem te falo") com preço já na mesa
    e a IA respondia passiva ("me avisa quando souber") — a conversa morria ali. Detector de
    CO-OCORRÊNCIA (token de tempo vago + fala de adiamento na mesma bolha), gate de preço na mesa.
(b) `<desistencia_por_item_fora_do_cardapio>`: cliente desiste por item que a modelo não oferece e
    a IA enterrava a venda ("tranquilo, qualquer coisa me chama"). Detector de desistência dita no
    burst + família da JANELA resolvida como "fora" contra o cadastro (closed-world), sem fluxo de
    parceira em pauta.

Detectores puros em `_foco_do_turno.py`; a fiação (gates com belief/cardápio) em
`_anexar_contexto_dinamico`; o render em `contexto_dinamico.md.j2`. Sem DB, sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos._foco_do_turno import desistencia_no_burst, janela_futura_vaga_no_burst
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico
from barra.agente.persona import render_contexto_dinamico

# --- detector: janela futura vaga ----------------------------------------------------------------


def _burst(*falas: str) -> list[BaseMessage]:
    return [HumanMessage(f) for f in falas]


@pytest.mark.parametrize(
    "fala",
    [
        "semana que vem te falo",
        "qualquer dia desses eu apareço aí",
        "quando der te chamo amor",
        "te aviso depois",
        "depois a gente combina",
        "assim que der eu te falo",
        "qualquer coisa te chamo",
    ],
)
def test_janela_vaga_acende_no_adiamento_sem_data(fala: str) -> None:
    assert janela_futura_vaga_no_burst(_burst(fala)) is True


@pytest.mark.parametrize(
    "fala",
    [
        # aviso de CHEGADA não é janela vaga — é o encontro de hoje andando.
        "to chegando, te aviso",
        "chegando lá te aviso",
        # proposta de agenda (ainda que vaga) sem fala de adiamento: ele está marcando, não fugindo.
        "pode ser semana que vem?",
        # adiamento sem token de tempo: curto demais pra afirmar a janela.
        "te falo",
        "beleza, fechou 21h então",
    ],
)
def test_janela_vaga_nao_acende_fora_do_adiamento(fala: str) -> None:
    assert janela_futura_vaga_no_burst(_burst(fala)) is False


# --- detector: desistência dita ------------------------------------------------------------------


@pytest.mark.parametrize(
    "fala",
    [
        "então deixa",
        "deixa pra lá",
        "deixa pra próxima",
        "sem anal não rola",
        "não rola então",
        "vou procurar outra",
        "desisto",
    ],
)
def test_desistencia_acende_na_despedida_de_compra(fala: str) -> None:
    assert desistencia_no_burst(_burst(fala)) is True


@pytest.mark.parametrize(
    "fala",
    [
        "então deixa eu ver aqui com meu chefe",
        "deixa que eu resolvo",
        "sem problema, não dá hoje",
        "beleza amor",
        # fechar venda GANHA também usa "então" — não pode virar resgate.
        "valeu então, te vejo às 21h",
    ],
)
def test_desistencia_nao_acende_em_conversa_viva(fala: str) -> None:
    assert desistencia_no_burst(_burst(fala)) is False


# --- fiação: gates em _anexar_contexto_dinamico --------------------------------------------------


class _FakeConnVazio:
    """Vazio em tudo: atendimento por kwarg, relógio injetado, sem parceria autorizada."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


_SEM_COMPLETO: dict[str, list[dict[str, Any]]] = {
    "fetiches": [{"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False}],
    "programas": [{"nome": "Normal", "duracao_nome": "1 hora", "preco": Decimal("400")}],
}


async def _contexto(
    mensagens: list[BaseMessage],
    *,
    cardapio: dict[str, list[dict[str, Any]]] | None = None,
    **over: Any,
) -> Any:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 8, 13, 17, 30, tzinfo=UTC),
    )
    atendimento: dict[str, Any] = {"estado": "Qualificado", "n_contrapropostas": 0, **over}
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        ctx,
        mensagens,
        atendimento=atendimento,
        cardapio_rows=cardapio if cardapio is not None else _SEM_COMPLETO,
    )
    return contexto


async def test_adiamento_com_preco_na_mesa_acende_a_janela_vaga() -> None:
    contexto = await _contexto(
        _burst("semana que vem te falo"),
        cotacao_enviada_em=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert contexto.janela_futura_vaga is True


async def test_adiamento_pos_aceite_tambem_acende() -> None:
    """Adiar depois do aceite adia igual: `valor_acordado` na mesa é preço na mesa."""
    contexto = await _contexto(
        _burst("qualquer dia desses te aviso"), valor_acordado=Decimal("400")
    )

    assert contexto.janela_futura_vaga is True


async def test_adiamento_sem_preco_na_mesa_nao_acende() -> None:
    """Sem cotação não há fechamento a salvar — o adiamento é matéria da conversa normal."""
    contexto = await _contexto(_burst("semana que vem te falo"))

    assert contexto.janela_futura_vaga is False


async def test_desistencia_por_item_fora_acende_com_a_recusa_na_janela() -> None:
    """O turno do eb02: "faz anal?" turnos atrás (modelo sem Anal e sem Completo → status "fora")
    e o burst atual é só a despedida — a janela cobre o item que o burst não repete."""
    contexto = await _contexto(
        [
            HumanMessage("vc faz anal?"),
            AIMessage("Isso não faço amor"),
            HumanMessage("então deixa"),
        ]
    )

    assert contexto.desistencia_fora_do_cardapio is True


async def test_desistencia_sem_item_fora_nao_acende() -> None:
    """Desistência seca (sem item negado na janela) não é perda de cardápio — pode ser preço,
    agenda, qualquer coisa: o bloco não afirma o que o detector não sabe."""
    contexto = await _contexto(_burst("então deixa"))

    assert contexto.desistencia_fora_do_cardapio is False


async def test_item_no_cardapio_nao_e_desistencia_de_cardapio() -> None:
    com_anal = {
        "fetiches": [{"nome": "Anal", "preco": Decimal("300"), "cobra_por_pessoa": False}],
        "programas": _SEM_COMPLETO["programas"],
    }
    contexto = await _contexto(
        [HumanMessage("vc faz anal?"), AIMessage("Faço sim amor"), HumanMessage("então deixa")],
        cardapio=com_anal,
    )

    assert contexto.desistencia_fora_do_cardapio is False


async def test_item_com_rota_no_completo_fica_fora_do_gate() -> None:
    """Fail-closed deliberado: com Completo na tabela o item TEM rota (status "no_completo") e a
    desistência costuma ser de preço — o bloco de cardápio não fala por ela."""
    com_completo = {
        "fetiches": _SEM_COMPLETO["fetiches"],
        "programas": [
            *_SEM_COMPLETO["programas"],
            {"nome": "Completo", "duracao_nome": "1 hora", "preco": Decimal("800")},
        ],
    }
    contexto = await _contexto(
        [
            HumanMessage("faz anal?"),
            AIMessage("Isso é do completo amor"),
            HumanMessage("deixa pra lá"),
        ],
        cardapio=com_completo,
    )

    assert contexto.desistencia_fora_do_cardapio is False


# --- render --------------------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_janela_vaga_proibe_a_saida_passiva_e_manda_agenda() -> None:
    out = _render(janela_futura_vaga=True, livre_agora="livre hoje a partir de 21:00")

    assert "<janela_futura_vaga>" in out
    # negação ativa: o comportamento proibido nomeado + a conduta substituta no mesmo bloco.
    assert "NÃO termine o seu turno devolvendo a iniciativa" in out
    assert "livre hoje a partir de 21:00" in out


def test_render_desistencia_proibe_a_despedida_passiva_e_pivota() -> None:
    out = _render(desistencia_fora_do_cardapio=True)

    assert "<desistencia_por_item_fora_do_cardapio>" in out
    assert "qualquer coisa me chama" in out  # a despedida proibida, nomeada
    assert "pivotar pro que EXISTE" in out


def test_render_sem_gatilho_nenhum_bloco_novo_sai() -> None:
    out = _render()

    assert "<janela_futura_vaga>" not in out
    assert "<desistencia_por_item_fora_do_cardapio>" not in out
