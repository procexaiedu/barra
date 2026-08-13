"""`agente_contexto_bloco_total{bloco,desfecho}` — os quatro fail-closed do contexto do turno.

O `prepare_context` tem quatro pontos que devolvem None e apagam um bloco INTEIRO do prompt:
o endereço do degrau sem número, a base do pacote no patamar, o `<pacote_em_pauta>` e o salto na
mesa. Todos são a decisão certa (número errado no prompt é pior que bloco nenhum), e todos eram
MUDOS: nada distinguia "este turno não pedia o bloco" de "o cadastro/detector quebrou e o bloco
sumiu" — e um bloco que some em silêncio não vira erro, vira venda perdida sem explicação.

Aqui forçamos os quatro caminhos e afirmamos os DOIS lados do contador, porque é a razão
ausente/(ausente+presente) que tem leitura: contar só a ausência mede tráfego, não quebra.
Afirmamos também o terceiro caso — o "não se aplica", que não pode contar de lado nenhum, senão a
razão afoga no ruído.

Sem DB e sem crédito. Reusa os fakes/builders de `test_oferta_condicionada_ao_dia` (mesmo alvo).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from prometheus_client import REGISTRY
from tests.unit.test_oferta_condicionada_ao_dia import (
    _CARDAPIO,
    _contexto,
    _FakeConnCatarina,
)

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import (
    _base_no_patamar,
    _endereco_do_degrau_sem_numero,
    _resolver_variaveis,
    _salto_na_mesa,
)

_METRICA = "agente_contexto_bloco_total"


def _lido(bloco: str, desfecho: str) -> float:
    # Gotcha do repo: `get_sample_value` NAO duplica o sufixo `_total` — o nome da amostra de um
    # Counter("agente_contexto_bloco_total") é exatamente esse (ver test_judge_conduta_metrica).
    return REGISTRY.get_sample_value(_METRICA, {"bloco": bloco, "desfecho": desfecho}) or 0.0


class _Delta:
    """Os dois lados de um bloco, medidos como DELTA: o registry é global ao processo e outros
    testes do mesmo arquivo (e da mesma suíte) já mexeram nas séries."""

    def __init__(self, bloco: str) -> None:
        self.bloco = bloco
        self._antes = (_lido(bloco, "presente"), _lido(bloco, "ausente"))

    def __call__(self) -> tuple[float, float]:
        return (
            _lido(self.bloco, "presente") - self._antes[0],
            _lido(self.bloco, "ausente") - self._antes[1],
        )


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 8, 12, 17, 30, tzinfo=UTC),
    )


# --- 1. <local_de_encontro>: o endereço do degrau sem número --------------------------------------


def test_endereco_do_degrau_conta_os_dois_lados() -> None:
    """Ausente = cadastro fora do formato do Google (texto livre legado, sem vírgula): a remoção
    não reconhece o número, o fail-closed apaga o bloco e a IA cai em "só a região". É a série que
    diz que existe cadastro estragado — antes disso, indistinguível de "esta modelo não tem local"."""
    delta = _Delta("local_de_encontro")

    assert (
        _endereco_do_degrau_sem_numero("Av. Aquidabã, 130 - Centro, Campinas")
        == "Av. Aquidabã - Centro, Campinas"
    )
    assert delta() == (1.0, 0.0)

    assert _endereco_do_degrau_sem_numero("Rua das Flores 291 Cambuí Campinas") is None
    assert delta() == (1.0, 1.0)


def test_endereco_ausente_no_cadastro_nao_conta_de_lado_nenhum() -> None:
    """Sem endereço cadastrado o bloco não foi TENTADO — o `<local_de_encontro>` não sairia de
    qualquer jeito. Contar isso como "ausente" faria a razão medir cadastro incompleto (comum e
    legítimo) em vez de cadastro quebrado, e nenhum alerta em cima dela significaria nada."""
    delta = _Delta("local_de_encontro")

    assert _endereco_do_degrau_sem_numero(None) is None
    assert _endereco_do_degrau_sem_numero("") == ""

    assert delta() == (0.0, 0.0)


# --- 2. a base do pacote no patamar ---------------------------------------------------------------


async def test_base_no_patamar_conta_os_dois_lados() -> None:
    """Presente = uma linha presencial na duração. Ausente = duração sem linha (ou com duas, o
    pacote ambíguo): o total "pacote no patamar + extra no mesmo patamar" some e a IA volta para a
    tabela cheia do `<fetiches>`, cotando o fetiche pelo preço de tabela numa negociação já
    descida."""
    delta = _Delta("base_no_patamar")

    assert await _base_no_patamar(_FakeConnCatarina(), "m1", Decimal("1"), "piso") is not None  # type: ignore[arg-type]
    assert delta() == (1.0, 0.0)

    assert await _base_no_patamar(_FakeConnCatarina(), "m1", Decimal("3"), "piso") is None  # type: ignore[arg-type]
    assert delta() == (1.0, 1.0)


async def test_base_no_patamar_fora_de_escopo_nao_conta() -> None:
    """Patamar cheio (a tabela estática JÁ é esse número) e belief sem duração são "não se aplica",
    e saem antes até da query. Ficam fora dos dois lados."""
    delta = _Delta("base_no_patamar")

    assert await _base_no_patamar(_FakeConnCatarina(), "m1", Decimal("1"), "cheio") is None  # type: ignore[arg-type]
    assert await _base_no_patamar(_FakeConnCatarina(), "m1", None, "piso") is None  # type: ignore[arg-type]

    assert delta() == (0.0, 0.0)


# --- 3. <pacote_em_pauta> -------------------------------------------------------------------------


async def _pacote(**atendimento: Any) -> Any:
    precos = atendimento.pop("precos_por_horas", None)
    contexto = await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"estado": "Triagem", **atendimento},
        precos_por_horas=precos,
    )
    return contexto.pacote_em_pauta


async def test_pacote_em_pauta_conta_os_dois_lados() -> None:
    """Ausente = a duração do belief não tem UM preço na tabela dela (cadastro ambíguo ou vazio):
    o `<pacote_em_pauta>` some do foco justamente no turno em que ele discute aquela duração."""
    delta = _Delta("pacote_em_pauta")

    assert await _pacote(duracao_horas=Decimal("1"), precos_por_horas={1.0: [Decimal("400")]}) == {
        "horas": "1",
        "preco": "400",
    }
    assert delta() == (1.0, 0.0)

    assert (
        await _pacote(
            duracao_horas=Decimal("1"),
            precos_por_horas={1.0: [Decimal("400"), Decimal("800")]},
        )
        is None
    )
    assert delta() == (1.0, 1.0)


async def test_pacote_em_pauta_fora_de_escopo_nao_conta() -> None:
    """Sem duração em discussão, ou com valor já cotado (quem ancora o número passa a ser o
    `<valor_cotado>`), o bloco não se aplica — nenhum dos dois lados."""
    delta = _Delta("pacote_em_pauta")

    assert await _pacote(precos_por_horas={1.0: [Decimal("400")]}) is None
    assert (
        await _pacote(
            duracao_horas=Decimal("1"),
            valor_acordado=Decimal("400"),
            precos_por_horas={1.0: [Decimal("400")]},
        )
        is None
    )

    assert delta() == (0.0, 0.0)


# --- 4. o salto na mesa (oferta condicionada ao dia) ----------------------------------------------


def test_salto_na_mesa_conta_os_dois_lados() -> None:
    """O chamador só chega aqui no cruzamento em que a oferta condicionada É a jogada do turno
    (preço na mesa, escada intacta, dia desconhecido) — então a chamada já é o "bloco tentado" e
    os dois desfechos contam. Ausente subindo = a IA voltando a interrogar ("seria hoje ?") onde
    deveria embutir a condição na oferta."""
    delta = _Delta("salto_na_mesa")

    assert _salto_na_mesa(_contexto(composicao_em_pauta=True), _CARDAPIO, Decimal("1"), None)
    assert delta() == (1.0, 0.0)

    # Primeira cotação limpa: não há salto a condicionar — a ausência LEGÍTIMA, que é maioria.
    assert _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), None) is None
    assert delta() == (1.0, 1.0)


# --- a razão, que é o que o alerta lê -------------------------------------------------------------


def test_a_razao_por_bloco_e_calculavel_das_series() -> None:
    """O contrato com `infra/monitoring/alert.rules.yml`: a regra divide o lado `ausente` pela soma
    dos dois desfechos DO MESMO nome de série. Com dois counters separados essa divisão viraria
    vetor vazio enquanto um dos lados não tivesse amostra nenhuma — é por isso que a forma é um
    counter com label de desfecho."""
    delta = _Delta("salto_na_mesa")

    _salto_na_mesa(_contexto(composicao_em_pauta=True), _CARDAPIO, Decimal("1"), None)
    _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), None)
    _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), None)

    presente, ausente = delta()
    assert ausente / (ausente + presente) == 2 / 3
