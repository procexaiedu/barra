"""Tempo livre sinalizado por ele = alavanca de upsell no turno da PRIMEIRA cotação (13/08).

"to de folga hoje e a noite ta toda livre, quanto vc cobra ?" é o sinal de ticket mais forte que um
cliente dá — e a IA cotava 1h/400 e parava ali. Não por falta de conduta (regras:161 manda subir o
tempo antes de descer o preço), mas por falta de DADO: o `<pacote_maior_na_sua_tabela>` era gateado
por `preco_na_mesa`, que só liga DEPOIS de a cotação ter saído. No turno em que ele pergunta o
preço, o bloco não existia.

Duas metades: o detector determinístico (família fechada, direção resolvida pela gramática) e a
fiação, que abre o degrau já nesse turno e marca `tempo_que_ele_tem` como sabido — com o tempo dele
na mesa a jogada é oferecer o pacote maior, não sondar quanto tempo ele tem.

Sem DB, sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico, _tempo_livre_sinalizado
from barra.agente.persona import render_contexto_dinamico

# --- o DETECTOR ---------------------------------------------------------------------------------
# Falso-positivo aqui custa uma oferta de pacote maior no valor CHEIO da tabela (nunca um desconto);
# falso-negativo devolve o comportamento de hoje. Mesmo assim a DIREÇÃO é recorte duro: o tempo tem
# de ser DELE — "trabalho a noite toda" é o oposto do sinal, e "vc ta de folga ?" é pergunta sobre a
# agenda DELA.


@pytest.mark.parametrize(
    "fala",
    [
        "to de folga hoje e a noite ta toda livre, quanto vc cobra?",
        "tô de folga hoje",
        "hoje to de folga",
        "estou de férias essa semana",
        "to livre agora",
        "tenho a noite toda",
        "tenho o dia todo livre",
        "a noite ta toda livre",
        "to de bobeira aqui em casa",
        "tô à toa hoje",
        "sem pressa amor",
        "não tenho pressa hoje",
    ],
)
def test_tempo_livre_acende_no_sinal_dele(fala: str) -> None:
    assert _tempo_livre_sinalizado([HumanMessage(fala)]) is True


@pytest.mark.parametrize(
    "fala",
    [
        # DIREÇÃO invertida: o tempo é dele, não dela — e nenhum destes é sinal de ticket.
        "trabalho a noite toda",
        "vc ta de folga hoje?",
        "você tem a noite toda livre?",
        "você ta livre agora?",
        "tu ta de folga?",
        # conversa normal, sem sinal nenhum
        "quanto custa 1h?",
        "me manda o valor amor",
        "boa noite, tudo bem?",
        "pode ser hoje a noite",
    ],
)
def test_tempo_livre_nao_acende_fora_do_sinal(fala: str) -> None:
    assert _tempo_livre_sinalizado([HumanMessage(fala)]) is False


def test_a_fala_dela_nunca_e_sinal_dele() -> None:
    """Ela dizendo que está livre é agenda dela — o detector só lê o lado do cliente."""
    assert _tempo_livre_sinalizado([AIMessage("to de folga hoje amor")]) is False


def test_o_sinal_vale_pela_janela_inteira_nao_so_pelo_burst() -> None:
    """A folga que ele contou ao abrir continua valendo quando o preço entra dois turnos depois —
    mesma régua da `duracao_dita_na_janela`, que serve à mesma conduta."""
    janela: list[BaseMessage] = [
        HumanMessage("boa noite, to de folga hoje"),
        AIMessage("Oi amor 🥰"),
        HumanMessage("quanto vc cobra?"),
    ]

    assert _tempo_livre_sinalizado(janela) is True


# --- a FIAÇÃO: o degrau abre no turno da cotação -------------------------------------------------


class _FakeConnVazio:
    """Vazio em tudo: atendimento por kwarg, relógio injetado, sem query nenhuma respondendo."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


_TABELA = {1.0: [Decimal("400")], 2.0: [Decimal("700")]}
_CARDAPIO: dict[str, list[dict[str, Any]]] = {
    "programas": [
        {"nome": "Normal", "duracao_nome": "1 hora", "preco": Decimal("400")},
        {"nome": "Normal", "duracao_nome": "2 horas", "preco": Decimal("700")},
    ]
}


async def _contexto(mensagens: list[BaseMessage], **over: Any) -> Any:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 8, 13, 17, 30, tzinfo=UTC),
    )
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        ctx,
        mensagens,
        atendimento={"estado": "Qualificado", "n_contrapropostas": 0, **over},
        precos_por_horas=_TABELA,
        cardapio_rows=_CARDAPIO,
    )
    return contexto


async def test_tempo_livre_abre_o_pacote_maior_ja_na_primeira_cotacao() -> None:
    """O turno medido: nenhuma cotação saiu ainda (`preco_na_mesa` falso) e o degrau tem de estar
    lá — é ESTA a bolha em que o ticket sobe, e ela só acontece uma vez."""
    contexto = await _contexto(
        [HumanMessage("to de folga hoje e a noite ta toda livre, quanto vc cobra?")]
    )

    assert contexto.preco_na_mesa is False
    assert contexto.pacote_maior == {"horas": "2", "preco": "700"}
    assert contexto.tempo_dele_desconhecido is False


async def test_o_bloco_chega_ao_prompt_com_o_dado_do_tempo() -> None:
    """A bicondicional de sempre: o detector acendeu ⟺ a IA leu o degrau, com o `tempo_que_ele_tem`
    dizendo que não há o que sondar (a sondagem de tempo tem regra própria em regras:161)."""
    contexto = await _contexto([HumanMessage("to de folga hoje, a noite ta toda livre")])
    prompt = render_contexto_dinamico(**contexto.como_variaveis())

    assert '<pacote_maior_na_sua_tabela horas="2" preco="700"' in prompt
    assert "ele ainda não disse" not in prompt


async def test_sem_sinal_e_sem_cotacao_o_degrau_continua_fechado() -> None:
    """Contraprova do gate: a pergunta de preço seca não abre o upsell — o comportamento de antes."""
    contexto = await _contexto([HumanMessage("quanto vc cobra?")])

    assert contexto.pacote_maior is None


async def test_trabalhar_a_noite_toda_nao_abre_o_degrau() -> None:
    """A direção, ponta a ponta: o tempo dele estar TOMADO é o oposto do sinal."""
    contexto = await _contexto([HumanMessage("trabalho a noite toda, quanto vc cobra?")])

    assert contexto.pacote_maior is None


async def test_com_o_valor_ja_aceito_o_upsell_nao_reabre() -> None:
    """Venda feita não vira upsell: o degrau é a jogada ANTES do preço fechar, e reabrir preço
    depois do aceite é o modo de falha que o <valor_fechado> existe para calar."""
    contexto = await _contexto(
        [HumanMessage("to de folga hoje")],
        valor_acordado=Decimal("400"),
        duracao_horas=Decimal("1"),
        sinais_qualificacao={"aceita_valor": True},
    )

    assert contexto.pacote_maior is None


async def test_com_a_escada_aberta_o_gate_de_contraproposta_continua_valendo() -> None:
    """`n_contrapropostas >= 1` já desligava o degrau (a jogada é ANTERIOR à escada) e continua
    desligando — o sinal de tempo livre não fura esse gate."""
    contexto = await _contexto([HumanMessage("to de folga hoje")], n_contrapropostas=1)

    assert contexto.pacote_maior is None
