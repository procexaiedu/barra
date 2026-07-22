"""post_process (M0): cinto-suspensorio de pausa concorrente.

Se a IA foi pausada por um pipeline sem lock (Pix/foto portaria) no meio do turno, o post_process
refaz o gate de pausa e ZERA as AIMessages geradas no turno -- o coordenador detecta a resposta
vazia e nao despacha a bolha ao cliente.

Regressao (AGENTE): zerava so `state["messages"][-1]`. Na reentrada pos-tools (extracao forcada /
resposta inline) a ultima mensagem e uma ToolMessage e a fala real e a AIMessage da 1a passagem ->
o `[-1]` deixava essa fala viva e o cliente recebia a bolha DEPOIS da pausa. Agora zera por
`mensagens_do_turno` (mesmo criterio do output_guard / do coordenador, agente/_texto_turno.py).
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente._canned import ESPERA_ESCALADA_CANNED
from barra.agente.contexto import ContextAgente
from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA

# nos/__init__ reexporta a funcao post_process, sombreando o submodulo; importlib pega o modulo
# real (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.post_process")


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    def __init__(self, ia_pausada: bool) -> None:
        self._ia_pausada = ia_pausada

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult({"ia_pausada": self._ia_pausada})


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(ia_pausada: bool) -> _Runtime:
    pool = _FakePool(_FakeConn(ia_pausada))
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _ai_turno(texto: str, _id: str) -> AIMessage:
    # usage_metadata marca a AIMessage como GERADA NESTE turno (mensagens_do_turno).
    return AIMessage(
        content=texto,
        id=_id,
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


async def test_pausa_concorrente_zera_aimessage_do_turno_nao_a_toolmessage() -> None:
    """Reentrada pos-tools: a ToolMessage e a ultima, mas quem vazaria e a AIMessage da 1a passagem.
    O post_process deve zerar a AIMessage do turno (a1), nunca a ToolMessage (t1)."""
    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            _ai_turno("ja te confirmo o horario amor", "a1"),  # fala real ao cliente
            ToolMessage(content="ok", id="t1", tool_call_id="tc1"),  # ultima msg, pos-tools
        ]
    }
    out = await mod.post_process(state, _runtime(ia_pausada=True))  # type: ignore[arg-type]
    zeradas = {m.id: m.content for m in out["messages"]}
    assert zeradas == {"a1": ""}  # so a AIMessage do turno, zerada; ToolMessage nao e tocada


async def test_pausa_concorrente_zera_todas_as_aimessages_do_turno() -> None:
    """Turno com texto na 1a E na 2a passagem: zerar so a ultima deixava a 1a fala viva."""
    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            _ai_turno("primeira parte", "a1"),
            _ai_turno("segunda parte", "a2"),
        ]
    }
    out = await mod.post_process(state, _runtime(ia_pausada=True))  # type: ignore[arg-type]
    zeradas = {m.id: m.content for m in out["messages"]}
    assert zeradas == {"a1": "", "a2": ""}


async def test_escalada_do_turno_preserva_bolha_de_espera_e_zera_o_pos_escalar() -> None:
    """Pausa do PROPRIO turno (escalar): a fala emitida ANTES do tool_call sai ao cliente (senao
    toda escalada vira silencio); o que a IA escrever DEPOIS segue descartado (04 §3.5)."""
    a1 = _ai_turno("Um momento amor", "a1")
    a1.tool_calls = [{"name": "escalar", "args": {}, "id": "tc1", "type": "tool_call"}]
    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            a1,
            ToolMessage(content="escalada aberta", id="t1", tool_call_id="tc1"),
            _ai_turno("ja te retorno", "a2"),  # desobediencia pos-escalar
        ]
    }
    out = await mod.post_process(state, _runtime(ia_pausada=True))  # type: ignore[arg-type]
    assert {m.id: m.content for m in out["messages"]} == {"a2": ""}


async def test_escalada_de_guarda_na_extracao_solta_bolha_de_espera() -> None:
    """Escalada silenciosa (análise prod 22/07, caso #10 1500/5h): a guarda do piso escala DENTRO
    do registrar_extracao (sem tool `escalar`, logo sem bolha de espera) e a pausa descartava o
    texto do turno — cliente no vácuo. O post_process zera as falas E solta uma canned de espera."""
    a1 = _ai_turno("Poxa amor, 5h não tenho pacote assim", "a1")
    a1.tool_calls = [{"name": "registrar_extracao", "args": {}, "id": "tc1", "type": "tool_call"}]
    msg_guard = next(iter(MENSAGENS_GUARD_ESCALADA))
    state = {
        "messages": [
            HumanMessage(content="faz 1500 as 5h?", id="h1"),
            a1,
            ToolMessage(content=msg_guard, id="t1", tool_call_id="tc1"),
            _ai_turno("consigo sim amor", "a2"),  # pós-guard, descartada
        ]
    }
    out = await mod.post_process(state, _runtime(ia_pausada=True))  # type: ignore[arg-type]
    espera = out["messages"][-1]
    # Falas do turno zeradas; a última mensagem é a bolha de espera canned, marcada como gerada
    # neste turno (usage_metadata) pro coordenador despachá-la.
    assert {m.id: m.content for m in out["messages"][:-1]} == {"a1": "", "a2": ""}
    assert espera.content in ESPERA_ESCALADA_CANNED
    assert espera.usage_metadata is not None


async def test_pausa_de_pipeline_externo_segue_silenciosa() -> None:
    """Pausa concorrente que NÃO nasce de guarda da extração (Pix/foto portaria): sem bolha de
    espera — o card/fluxo próprio cuida do cliente; o turno segue zerado como sempre."""
    state = {
        "messages": [
            HumanMessage(content="cheguei", id="h1"),
            _ai_turno("te espero amor", "a1"),
            ToolMessage(content="ok", id="t1", tool_call_id="tc1"),
        ]
    }
    out = await mod.post_process(state, _runtime(ia_pausada=True))  # type: ignore[arg-type]
    assert {m.id: m.content for m in out["messages"]} == {"a1": ""}


async def test_sem_pausa_nao_zera() -> None:
    """ia_pausada=false: turno segue normal, post_process e no-op (nao mexe nas mensagens)."""
    state = {"messages": [HumanMessage(content="oi", id="h1"), _ai_turno("resposta", "a1")]}
    out = await mod.post_process(state, _runtime(ia_pausada=False))  # type: ignore[arg-type]
    assert out == {}
