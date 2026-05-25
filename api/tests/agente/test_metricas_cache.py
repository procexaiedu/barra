"""Aceite M2-T2 — instrumentação de tokens/cache + reminder anti-drift + TURNO_TRUNCADO.

DB-free e key-free: o nó `llm` roda com um fake chat que devolve um AIMessage com
`usage_metadata`/`response_metadata` mockados (sem HTTP). As métricas são lidas do REGISTRY do
prometheus_client; cada teste de token usa um label `modelo` único (nonce) p/ isolar a série.
"""

import asyncio
from typing import Any
from uuid import uuid4

from _fakes import FakeRuntime
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from prometheus_client import REGISTRY

from barra.agente.contexto import ContextAgente
from barra.agente.nos.llm import no_llm
from barra.agente.nos.prepare_context import (
    _injetar_reminder_se_necessario,
    _precisa_reminder,
)


class _FakeBound:
    """Resultado de bind_tools: ignora as mensagens e devolve o resp roteirizado."""

    def __init__(self, resp: BaseMessage) -> None:
        self._resp = resp

    async def ainvoke(self, messages: Any) -> BaseMessage:
        return self._resp


class _FakeChat:
    """ChatAnthropic falso: expõe `.model` (label das métricas) e `bind_tools`."""

    def __init__(self, resp: BaseMessage, *, model: str) -> None:
        self._resp = resp
        self.model = model

    def bind_tools(self, tools: Any) -> _FakeBound:
        return _FakeBound(self._resp)


def _runtime() -> FakeRuntime:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # o nó llm não toca no banco
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return FakeRuntime(ctx)


def _tokens(modelo: str, tipo: str) -> float | None:
    return REGISTRY.get_sample_value(
        "agente_turno_tokens_total", {"modelo": modelo, "tipo": tipo}
    )


# --- token: 4 séries, WRITE de ephemeral_* (não de cache_creation) -------------------------


def test_token_le_write_de_ephemeral_e_read_de_cache_read() -> None:
    modelo = f"test-sonnet-{uuid4().hex}"
    resp = AIMessage(
        content="oi amor",
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_token_details": {
                "cache_read": 4000,
                # cache_creation vem sempre 0 no 1.4.3; aqui sentinela 9999 p/ provar que o
                # write NÃO sai daqui (03 §4.2). Se o código lesse cache_creation, write=9999.
                "cache_creation": 9999,
                "ephemeral_5m_input_tokens": 1500,
                "ephemeral_1h_input_tokens": 500,
            },
        },
    )
    res = asyncio.run(no_llm(_FakeChat(resp, model=modelo), [])({"messages": []}, _runtime()))

    assert res.goto == "post_process"  # sem tool_calls → resposta final
    assert _tokens(modelo, "input") == 100
    assert _tokens(modelo, "output") == 50
    assert _tokens(modelo, "cache_read") == 4000
    # WRITE = ephemeral_5m + ephemeral_1h = 2000, NÃO o cache_creation (9999).
    assert _tokens(modelo, "cache_write") == 2000


def test_token_sem_usage_metadata_nao_quebra() -> None:
    modelo = f"test-sonnet-{uuid4().hex}"
    resp = AIMessage(content="oi")  # usage_metadata = None
    asyncio.run(no_llm(_FakeChat(resp, model=modelo), [])({"messages": []}, _runtime()))
    # nenhuma série criada para esse modelo (early return), e o turno não estoura.
    assert _tokens(modelo, "input") is None


# --- truncado: stop_reason=max_tokens incrementa TURNO_TRUNCADO -----------------------------


def test_max_tokens_incrementa_turno_truncado() -> None:
    resp = AIMessage(content="resp truncada", response_metadata={"stop_reason": "max_tokens"})
    antes = REGISTRY.get_sample_value("agente_turno_truncado_total") or 0.0
    asyncio.run(
        no_llm(_FakeChat(resp, model=f"test-{uuid4().hex}"), [])({"messages": []}, _runtime())
    )
    depois = REGISTRY.get_sample_value("agente_turno_truncado_total") or 0.0
    assert depois == antes + 1.0


def test_stop_reason_normal_nao_incrementa_truncado() -> None:
    resp = AIMessage(content="ok", response_metadata={"stop_reason": "end_turn"})
    antes = REGISTRY.get_sample_value("agente_turno_truncado_total") or 0.0
    asyncio.run(
        no_llm(_FakeChat(resp, model=f"test-{uuid4().hex}"), [])({"messages": []}, _runtime())
    )
    depois = REGISTRY.get_sample_value("agente_turno_truncado_total") or 0.0
    assert depois == antes


# --- reminder: limiar ≥8 AIMessages, só no último HumanMessage ------------------------------


def _janela(n_ai: int) -> list[BaseMessage]:
    """Janela com `n_ai` AIMessages intercaladas; termina num HumanMessage (a msg atual)."""
    msgs: list[BaseMessage] = []
    for i in range(n_ai):
        msgs.append(HumanMessage(content=f"cli {i}", id=f"h{i}"))
        msgs.append(AIMessage(content=f"ia {i}", id=f"a{i}"))
    msgs.append(HumanMessage(content="ultima do cliente", id="hlast"))
    return msgs


def test_precisa_reminder_limiar_8() -> None:
    assert _precisa_reminder(_janela(7)) is False  # 7 turnos da IA → não injeta
    assert _precisa_reminder(_janela(8)) is True  # 8 turnos da IA → injeta


def test_injetar_abaixo_do_limiar_nao_altera() -> None:
    hist = _janela(7)
    out = _injetar_reminder_se_necessario(hist, "Triagem")
    assert out is hist  # no-op retorna a mesma lista
    assert all("<lembrete_silencioso>" not in str(m.content) for m in out)


def test_injetar_acima_do_limiar_so_no_ultimo_human() -> None:
    out = _injetar_reminder_se_necessario(_janela(8), "Qualificado")
    humans = [m for m in out if m.type == "human"]
    ultimo = humans[-1]
    # tag prependada (lembrete → msg do cliente), com a fase do atendimento.
    assert str(ultimo.content).startswith("<lembrete_silencioso>")
    assert "Fase: Qualificado" in str(ultimo.content)
    assert str(ultimo.content).endswith("ultima do cliente")
    # só o último HumanMessage recebe a tag; os demais e as AIMessages ficam intactos.
    assert all("<lembrete_silencioso>" not in str(m.content) for m in humans[:-1])
    assert all("<lembrete_silencioso>" not in str(m.content) for m in out if m.type == "ai")
