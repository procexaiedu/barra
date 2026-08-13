"""Os CARIMBOS do turno espelham o que o template de fato renderizou — provado, não prometido.

`prepare_context` publica no State dois carimbos que viajam para FORA do grafo e são lidos quando a
fala já saiu: `valor_dele_no_prompt` (consumido por `workers/envio.py`, que grava o valor da venda)
e `local_endereco_no_prompt` (consumido pelo feedback literal da regen do `output_guard`).

Ambos são calculados por funções que **reimplementam à mão** a condição do template — porque um
carimbo é uma decisão congelada no instante do render, e reavaliá-lo depois da extração daria outra
resposta sobre uma fala que já foi ao cliente (`estado.py`, "carimbo, não predicado"). O padrão está
certo; o que faltava era a amarra. Duas cópias da mesma condição, em linguagens diferentes (Python e
Jinja), sem nada ligando uma à outra: mexer no `{% if %}` do template sem mexer na função faz o
write-time gravar o valor da venda sobre uma premissa que a IA nunca leu — e nada falha.

Estes testes não repetem a condição uma TERCEIRA vez. Eles renderizam o template de verdade e
afirmam a bicondicional: a tag apareceu no prompt ⟺ o carimbo saiu preenchido.
"""

import dataclasses as dc
from datetime import UTC, datetime
from typing import Any

import pytest

from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import (
    _ponto_de_encontro_no_prompt,
    _valor_dele_no_prompt,
)
from barra.agente.persona import render_contexto_dinamico

_AGORA = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)

# Preenchimento neutro dos 59 campos obrigatórios: o que interessa a cada caso entra por override.
# `False`/`None`/`0`/`[]` por tipo declarado é o bastante — nenhum bloco que estes testes olham
# depende de outro campo estar "ligado".
_NEUTRO: dict[str, Any] = {
    "agora": _AGORA,
    "data_atual": "2026-08-19",
    "hora_atual": "16:00",
    "escada_estado": "inteira",
    "estado": "Triagem",
}


def _contexto(**over: Any) -> ContextoDoTurno:
    valores: dict[str, Any] = {}
    for campo in dc.fields(ContextoDoTurno):
        if campo.default is not dc.MISSING or campo.default_factory is not dc.MISSING:
            continue
        if campo.name in _NEUTRO:
            valores[campo.name] = _NEUTRO[campo.name]
        elif campo.name in over:
            continue  # vem do override abaixo
        else:
            # `campo.type` é a CLASSE, não a string do annotation (a dataclass não usa
            # `from __future__ import annotations`). `bool` antes de `int`: bool é subclasse dele.
            tipo = campo.type
            valores[campo.name] = (
                False
                if tipo is bool
                else 0
                if tipo in (int, float)
                else []
                if getattr(tipo, "__origin__", None) is list
                else None
            )
    return ContextoDoTurno(**{**valores, **over})


def _render(ctx: ContextoDoTurno) -> str:
    return render_contexto_dinamico(**ctx.como_variaveis())


# --------------------------------------------------------------- <valor_dele_serve> ⟺ o carimbo
# A matriz cobre os eixos que a condição do template combina: escada esgotada, preço na mesa e o
# aceite em si. `n_contrapropostas` entra porque o template o testa com `is defined` — hoje sempre
# verdadeiro (o render vem de uma dataclass), e é justamente por isso que ninguém notaria se um dia
# deixasse de ser.
@pytest.mark.parametrize(
    "over",
    [
        pytest.param({}, id="nada_na_mesa"),
        pytest.param({"preco_na_mesa": True}, id="preco_sem_aceite"),
        pytest.param({"aceite_do_valor_dele": "300"}, id="aceite_sem_preco"),
        pytest.param({"preco_na_mesa": True, "aceite_do_valor_dele": "300"}, id="aceite_com_preco"),
        pytest.param(
            {
                "preco_na_mesa": True,
                "aceite_do_valor_dele": "300",
                "escada_estado": "esgotada",
            },
            id="aceite_com_escada_esgotada",
        ),
        pytest.param(
            {"preco_na_mesa": True, "aceite_do_valor_dele": "300", "n_contrapropostas": 2},
            id="aceite_apos_contrapropostas",
        ),
    ],
)
def test_valor_dele_no_prompt_espelha_a_tag(over: dict[str, Any]) -> None:
    ctx = _contexto(**over)
    renderizou = "<valor_dele_serve>" in _render(ctx)
    carimbou = _valor_dele_no_prompt(ctx) is not None

    assert renderizou == carimbou, (
        f"<valor_dele_serve> {'entrou' if renderizou else 'NAO entrou'} no prompt mas o carimbo "
        f"{'saiu' if carimbou else 'NAO saiu'}: o write-time vai gravar a venda sobre uma premissa "
        f"que a IA {'nunca leu' if carimbou else 'leu e ninguem registrou'}"
    )


def test_carimbo_do_valor_e_o_numero_que_a_tag_mostrou() -> None:
    """Não basta a tag existir: o número carimbado é o mesmo que foi parar na frente do modelo."""
    ctx = _contexto(preco_na_mesa=True, aceite_do_valor_dele="300")

    assert "300" in _render(ctx)
    assert _valor_dele_no_prompt(ctx) == 300


def test_aceite_ilegivel_e_o_unico_ponto_em_que_os_dois_podem_divergir() -> None:
    """A bicondicional acima tem UMA brecha, e ela depende de uma garantia de origem — este teste
    é quem a segura.

    Com um `aceite_do_valor_dele` que não seja número, o template renderiza a tag (ele só testa
    truthiness) e a função devolve `None` (o `Decimal(...)` levanta). A IA leria "aceite o valor
    dele" e o `envio.py` não gravaria a venda: encontro fechado sem valor no painel.

    Hoje isso é INALCANÇÁVEL — `_resolver_variaveis` preenche o campo com
    `_num_humano(aceite)` sobre o `Decimal` que `dominio/atendimentos:aceite_do_valor_dele`
    devolve, e essa função só retorna `Decimal | None`. O teste existe para que trocar a origem
    por algo que possa emitir texto livre falhe aqui, e não em produção com a venda perdida."""
    ctx = _contexto(preco_na_mesa=True, aceite_do_valor_dele="nao-e-numero")

    assert "<valor_dele_serve>" in _render(ctx)
    assert _valor_dele_no_prompt(ctx) is None


# ------------------------------------------------------------ <local_de_encontro> ⟺ o carimbo
@pytest.mark.parametrize(
    "over",
    [
        pytest.param({}, id="sem_endereco"),
        pytest.param({"local_endereco": "Rua Latino Coelho"}, id="so_rua"),
        pytest.param(
            {"local_endereco": "Rua Latino Coelho", "local_nome": "Hotel X"}, id="hotel_e_rua"
        ),
        pytest.param(
            {"local_endereco": "Rua Latino Coelho, 421", "numero_liberado": True},
            id="rua_com_numero",
        ),
    ],
)
def test_ponto_de_encontro_no_prompt_espelha_a_tag(over: dict[str, Any]) -> None:
    ctx = _contexto(**over)
    renderizou = "<local_de_encontro>" in _render(ctx)
    carimbou = _ponto_de_encontro_no_prompt(ctx) is not None

    assert renderizou == carimbou


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"local_endereco": "Rua Latino Coelho"}, id="so_rua"),
        pytest.param(
            {"local_endereco": "Rua Latino Coelho", "local_nome": "Hotel X"}, id="hotel_e_rua"
        ),
    ],
)
def test_carimbo_do_local_e_o_texto_que_a_tag_mostrou(over: dict[str, Any]) -> None:
    """O consumidor cola este texto LITERAL na regen. Se ele divergir do que o bloco apresentou,
    a regen devolve ao cliente um endereço com um degrau a mais do que o gate liberou."""
    ctx = _contexto(**over)
    carimbo = _ponto_de_encontro_no_prompt(ctx)
    render = _render(ctx)

    assert carimbo is not None
    for pedaco in carimbo.split(" — "):
        assert pedaco in render, f"{pedaco!r} carimbado mas ausente do <local_de_encontro>"
