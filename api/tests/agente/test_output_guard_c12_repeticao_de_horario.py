"""c12cen_v2 (14/08), cenario `segunda_venda_cotado`: a isencao do PRECO engolia o papagaio.

Falas REAIS da corrida (sessao Langfuse 5182ff46/e1e9fe45, t3 e t4):

    t3  ele: "e 2h quanto fica?"
        ela: "700 2h amor" / "Consigo hoje a partir das 15h, fecha ?"
    t4  ele: "quanto era mesmo a 1h?"
        ela: "700 2h amor, aproveitar melhor rs" / "Consigo hoje a partir das 15h, fecha ?"

A segunda bolha do t4 e BYTE-IDENTICA a do t3 e mesmo assim saiu ao cliente: o burst do t4 e
pedido de preco (`contem_pedido_de_preco`), e a isencao `responde_pedido` do `bolhas_repetidas`
liberava qualquer bolha com DIGITO — "15h" e digito. O predicado passa a mascarar relogio/duracao
(`carrega_valor_pedido`), o que devolve a bolha de horario ao detector sem tocar na isencao que a
criou (campanha 13/08, eb02:26311003246742: "e 400 a 1h no meu local" respondendo "E o
investimento?" continua isenta).

Unit tests sem DB/LLM — mesmo rig de test_output_guard_ciclo4.py.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos._foco_do_turno import contem_pedido_de_preco

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo.
mod = importlib.import_module("barra.agente.nos.output_guard")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

# As duas falas do caso, literais.
_BURST_T4 = "quanto era mesmo a 1h?"
_HORARIO_T3 = "Consigo hoje a partir das 15h, fecha ?"
_T4 = "700 2h amor, aproveitar melhor rs\n\nConsigo hoje a partir das 15h, fecha ?"
# A isencao que o predicado tem de PRESERVAR (campanha 13/08, eb02:26311003246742).
_COTACAO_REPETIDA = "e 400 a 1h no meu local"


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult([])


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConn()


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime() -> _Runtime:
    ctx = ContextAgente(
        db_pool=_FakePool(),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _state(texto: str, *, fala_cliente: str, historicas: list[str]) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        # AIMessage SEM usage = historica re-injetada pelo prepare_context (_bolhas_historicas).
        *[AIMessage(content=h, id=f"hist{i}") for i, h in enumerate(historicas)],
        HumanMessage(content=fala_cliente, id="h1"),
        AIMessage(content=texto, id="a1", usage_metadata=_USAGE),
    ]
    return {"messages": msgs, "conversa_crua": [HumanMessage(content=fala_cliente, id="h1")]}


class _FakeRegen:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
        self.chamadas.append(kwargs)
        return None if self.content is None else AIMessage(content=self.content, id="regen1")


def _judge_ok(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any, **kwargs: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


def test_o_burst_do_t4_e_pedido_de_preco() -> None:
    # Sem isto o caso nao existe: e o pedido de preco que abre a isencao.
    assert contem_pedido_de_preco(_BURST_T4) is True


@pytest.mark.parametrize(
    ("bolha", "carrega"),
    [
        (_HORARIO_T3, False),  # so relogio -> nao e o dado de um pedido de preco
        ("Consigo às 15h30, fecha ?", False),  # hora com minutos colados
        ("Consigo amanhã às 10 horas", False),  # hora por extenso
        ("Seria hoje ?", False),  # sonda seca, sem numero
        (_COTACAO_REPETIDA, True),  # a isencao de 13/08 segue de pe
        ("400 1h no meu local", True),  # preco + duracao
        ("250 30minutos amor", True),  # pacote curto: o numero do preco sobrevive a mascara
    ],
)
def test_predicado_do_preco_mascara_relogio_e_duracao(bolha: str, carrega: bool) -> None:
    assert mod.carrega_valor_pedido(bolha) is carrega


def test_bolha_de_horario_verbatim_volta_a_ser_flagrada() -> None:
    """O nucleo do bug: com o predicado antigo (qualquer digito) a bolha do t3 reenviada no t4
    saia isenta; com a mascara ela volta ao detector, e a bolha que traz o preco segue isenta."""
    assert mod.bolhas_repetidas(
        _HORARIO_T3, [_HORARIO_T3], responde_pedido=mod.carrega_valor_pedido
    ) == [_HORARIO_T3]
    # o contrafactual do bug (predicado "qualquer digito"): a mesma bolha passava batido
    assert (
        mod.bolhas_repetidas(
            _HORARIO_T3, [_HORARIO_T3], responde_pedido=lambda b: bool(mod._RE_DIGITOS.search(b))
        )
        == []
    )
    # e a isencao original continua isentando
    assert (
        mod.bolhas_repetidas(
            _COTACAO_REPETIDA, [_COTACAO_REPETIDA], responde_pedido=mod.carrega_valor_pedido
        )
        == []
    )


async def test_fio_completo_o_t4_dispara_repeticao(monkeypatch: Any) -> None:
    """De ponta a ponta pelo no: burst de preco + a bolha de horario identica a do turno anterior
    -> gatilho `repeticao` (antes do fix o guard nao armava nada e o papagaio saia)."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_T4, fala_cliente=_BURST_T4, historicas=["700 2h amor", _HORARIO_T3]), _runtime()
    )

    assert res is not None
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
