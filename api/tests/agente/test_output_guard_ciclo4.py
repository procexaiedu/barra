"""Ciclo 4 da campanha 13/08 — tres ajustes no output_guard, todos com as falas dos dumps.

A1 — isencao `responde_pedido` cobre HORA re-perguntada (eb02:274203613901023 t8, o UNICO mudo
     do lote): o cliente re-pergunta "Que horas amanhã vc consegue ?", o modelo rascunha
     "Consigo às 10h, fecha ?" (mesma bolha do t5) e o detector de repeticao a matava; regen 2x
     vazia -> turno MUDO. Pedido de hora no burst (`contem_pedido_de_hora`, _foco_do_turno) +
     bolha com hora explicita (`contem_hora_explicita`, detector canonico de _disciplina) =
     resposta, nao papagaio. A isencao deixou de exigir bolha afirmativa: o criterio e "pergunta
     SEM o dado pedido" — o fecho interrogativo ("fecha ?") nao mata a entrega, e a pergunta seca
     repetida ("Seria hoje ?") continua flagrada por nao carregar o dado.

A2 — cauda passiva na ordem INVERTIDA (eb02:54181717110810 t4): "Tranquilo amor, quando tiver um
     tempo me chama 🥰" escapava de `_RE_DESPEDIDA_PASSIVA` (so casava "me chama quando X"; a
     inversao "quando X me chama" e o auxiliar nu "tiver" ficavam fora). A excecao de execucao
     virou lista de COMPOSTOS compartilhada pelas duas ordens ("estiver chegando" isenta;
     "tiver um tempo" nao).

A3 — pos-regen da despedida reincidente (residual do c4-rerun, 2 turnos): a regen devolvia OUTRA
     cauda passiva da familia ("Fico te esperando"/"Fico no aguardo amor") e o fallback era
     pass-through. Com irmas boas no turno, a cauda agora e CORTADA (drop granular da ultima
     bolha; label `cortada` no contador OUTPUT_DESPEDIDA_PASSIVA); bolha unica segue
     pass-through (drop = mudo, pior).

Unit tests sem DB/LLM (mesmo rig de test_output_guard_ciclo2.py): fakes de conn/pool/regen/judge.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END
from prometheus_client import REGISTRY

from barra.agente._disciplina import contem_hora_explicita
from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
foco = importlib.import_module("barra.agente.nos._foco_do_turno")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


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


def _state(
    texto: str, *, fala_cliente: str = "oi", historicas: list[str] | None = None
) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        # AIMessage SEM usage = historica re-injetada pelo prepare_context (_bolhas_historicas).
        *[AIMessage(content=h, id=f"hist{i}") for i, h in enumerate(historicas or [])],
        HumanMessage(content=fala_cliente, id="h1"),
        AIMessage(content=texto, id="a1", usage_metadata=_USAGE),
    ]
    return {
        "messages": msgs,
        "conversa_crua": [HumanMessage(content=fala_cliente, id="h1")],
    }


def _judge_ok(monkeypatch: Any) -> None:
    async def _ok(texto: str, settings: Any, **kwargs: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


class _FakeRegen:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
        self.chamadas.append(kwargs)
        if self.content is None:
            return None
        return AIMessage(content=self.content, id="regen1", usage_metadata=_USAGE)


def _msgs_update(res: Any) -> dict[str, str]:
    return {m.id: str(m.content) for m in (res.update or {}).get("messages", [])}


# --- A1: hora re-perguntada e resposta, nao papagaio ----------------------------------------------

# As falas REAIS do caso (eb02:274203613901023): a oferta do t5 e o rascunho do t8.
_OFERTA_T5 = "Consigo amanhã às 10h, fecha ?"
_RASCUNHO_T8 = "Consigo às 10h, fecha ?"
_BURST_T8 = "Que horas amanhã vc consegue ?"


@pytest.mark.parametrize(
    "fala",
    [
        _BURST_T8,
        "que horas você atende?",
        "A que horas vc pode?",
        "Qual horário amor?",
        "qual o horario",
    ],
)
def test_a1_detector_de_pedido_de_hora(fala: str) -> None:
    assert foco.contem_pedido_de_hora(fala) is True


@pytest.mark.parametrize("fala", ["quanto tempo você fica?", "Seria hoje?", "Qual valor amor"])
def test_a1_detector_nao_acende_sem_pedido_de_hora(fala: str) -> None:
    assert foco.contem_pedido_de_hora(fala) is False


def test_a1_rascunho_real_sobrevive_com_o_pedido_de_hora() -> None:
    """O rascunho do t8 TEM "?" ("fecha ?") e mesmo assim e entrega da hora re-pedida: a isencao
    deixou de exigir bolha afirmativa porque o predicado ja e fechado no DADO — pergunta sem a
    hora nao passa por ele. Sem o pedido no burst (predicado ausente), segue flagrado."""
    assert mod.bolhas_repetidas(_RASCUNHO_T8, [_OFERTA_T5]) == [_RASCUNHO_T8]
    assert (
        mod.bolhas_repetidas(_RASCUNHO_T8, [_OFERTA_T5], responde_pedido=contem_hora_explicita)
        == []
    )


def test_a1_pergunta_seca_repetida_continua_flagrada() -> None:
    # A fronteira do criterio novo: "Seria hoje ?" repetida nao carrega hora nenhuma — o predicado
    # a rejeita e o papagaio mais visivel segue flagrado, mesmo com o pedido de hora no burst.
    assert mod.bolhas_repetidas(
        "Seria hoje ?", ["Seria hoje ?"], responde_pedido=contem_hora_explicita
    ) == ["Seria hoje ?"]


def test_a1_bolha_sem_hora_nao_e_isenta() -> None:
    eco = "Sou bem tranquila, estilo namoradinha completa"
    assert mod.bolhas_repetidas(eco, [eco], responde_pedido=contem_hora_explicita) == [eco]


async def test_a1_fio_completo_o_t8_nao_regenera(monkeypatch: Any) -> None:
    """O caso real de ponta a ponta: oferta do t5 na janela historica, burst re-perguntando a
    hora, rascunho do t8 no turno — o guard nao arma gatilho nenhum e o texto sai como esta."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen(None)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_RASCUNHO_T8, fala_cliente=_BURST_T8, historicas=[_OFERTA_T5]), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas
    assert "a1" not in _msgs_update(res)  # nada reescrito: a bolha original segue viva


async def test_a1_fio_completo_pergunta_seca_ainda_dispara_repeticao(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo amanhã às 10h amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Seria hoje ?", fala_cliente=_BURST_T8, historicas=["Seria hoje ?"]), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
    assert _msgs_update(res)["regen1"] == "Consigo amanhã às 10h amor"


# --- A2: cauda passiva na ordem invertida ---------------------------------------------------------


def test_a2_fala_real_invertida_dispara() -> None:
    # A fala LITERAL do caso eb02:54181717110810 t4.
    fala = "Tranquilo amor, quando tiver um tempo me chama 🥰"
    assert mod.bolhas_despedida_passiva(fala) == [fala]


@pytest.mark.parametrize(
    "turno",
    [
        # excecao de execucao na ordem invertida + hora concreta (o negativo pedido no ciclo 4)
        "quando chegar me chama, te espero às 14h",
        # excecao de execucao SOZINHA, nas duas ordens
        "quando você chegar me avisa",
        "quando estiver chegando me avisa amor",
        # pins do ciclo 3 que tem de continuar valendo
        "te espero rs, me avisa quando sair",
        "Me chama quando você chegar",
    ],
)
def test_a2_execucao_do_encontro_nao_dispara(turno: str) -> None:
    assert mod.bolhas_despedida_passiva(turno) == []


def test_a2_auxiliar_nu_deixou_de_isentar_tambem_na_ordem_direta() -> None:
    # Harmonizacao: "tiver um tempo" e a vida do cliente, nao execucao do encontro — a mesma
    # fala do caso real na ordem direta agora tambem flagra (a excecao antiga isentava o "tiver"
    # nu e abria o buraco pelo qual o caso real passou).
    fala = "Me chama quando tiver um tempo"
    assert mod.bolhas_despedida_passiva(fala) == [fala]


# --- A3: pos-regen da despedida reincidente -------------------------------------------------------


def _cortadas() -> float:
    return (
        REGISTRY.get_sample_value("agente_output_despedida_passiva_total", {"acao": "cortada"})
        or 0.0
    )


async def test_a3_regen_reincidente_com_irmas_boas_corta_a_cauda(monkeypatch: Any) -> None:
    """Regen da `despedida` devolve outra cauda passiva da familia (o residual real do c4-rerun:
    "Fico no aguardo") junto de bolha boa -> a cauda e cortada (drop granular da ultima bolha),
    as irmas sobrevivem, e a acao nova e registrada como `cortada`."""
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Consigo te encaixar essa semana amor\n\nFico no aguardo")
    monkeypatch.setattr(mod, "_regenerar", regen)
    antes = _cortadas()

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tabom amor\n\nMe chama quando organizar"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "despedida"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""  # original zerada (despacho e a regen)
    assert msgs["regen1"] == "Consigo te encaixar essa semana amor"  # cauda cortada, irma viva
    assert _cortadas() == antes + 1


async def test_a3_regen_reincidente_bolha_unica_segue_pass_through(monkeypatch: Any) -> None:
    # Drop da bolha unica = turno MUDO, a pior saida medida no shadow: o pass-through de sempre.
    _judge_ok(monkeypatch)
    regen = _FakeRegen("Fico te esperando")  # o outro residual real, sozinho no turno
    monkeypatch.setattr(mod, "_regenerar", regen)
    antes = _cortadas()

    res = await mod.output_guard(_state("Fico no aguardo"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert _msgs_update(res)["regen1"] == "Fico te esperando"  # saiu como esta
    assert _cortadas() == antes
