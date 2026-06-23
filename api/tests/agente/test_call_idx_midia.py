"""#5 (bughunt): call_idx de `enviar_midia` e ordinal GLOBAL do turno (varre TODAS as AIMessages),
nao por-AIMessage.

A PK de idempotencia e `(turno_id, 'enviar_midia', call_idx)`. Se o ordinal reiniciasse a cada
AIMessage, duas `enviar_midia` em passagens ReAct distintas do MESMO turno colidiriam (ambas
call_idx=0) e o ON CONFLICT do `_executar_idempotente` descartaria a foto da 2a passagem em
silencio. O ordinal global mantem `call_idx` unico no turno. Funcao pura, sem DB.
"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente.nos.tools import _calcular_call_idx_midia


class _RT:
    def __init__(self, messages: list[Any]) -> None:
        self.state = {"messages": messages}


def _tc(call_id: str, name: str = "enviar_midia") -> dict[str, Any]:
    return {"id": call_id, "name": name, "args": {}, "type": "tool_call"}


def _ai(tool_calls: list[dict[str, Any]], **kw: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=tool_calls, **kw)


def test_uma_passagem_duas_midias_ordinais_0_e_1() -> None:
    """Duas `enviar_midia` na MESMA AIMessage -> ordinais 0 e 1."""
    ai = _ai([_tc("c0"), _tc("c1")])
    rt = _RT([HumanMessage(content="oi"), ai])
    assert _calcular_call_idx_midia(rt, "c0") == 0
    assert _calcular_call_idx_midia(rt, "c1") == 1


def test_global_entre_passagens_react_nao_reinicia() -> None:
    """`enviar_midia` em DUAS AIMessages (passagens ReAct distintas): a 2a NAO reinicia em 0 -- o
    ordinal e global (0 na 1a, 1 na 2a). Sem isso a 2a colidiria a PK e seria descartada."""
    p1 = _ai([_tc("c0")])
    tm = ToolMessage(content="Foto de 'apresentacao' anexada", tool_call_id="c0")
    p2 = _ai([_tc("c1")])
    rt = _RT([HumanMessage(content="oi"), p1, tm, p2])
    assert _calcular_call_idx_midia(rt, "c0") == 0
    assert _calcular_call_idx_midia(rt, "c1") == 1  # global, nao 0


def test_outras_tools_e_historicas_nao_contam() -> None:
    """`consultar_agenda` na mesma AIMessage nao incrementa; AIMessage historica re-injetada
    (so content+id, sem tool_calls) nao infla a contagem."""
    hist = AIMessage(content="oi de novo", id="hist")  # historica do prepare_context
    p1 = _ai([_tc("ca", name="consultar_agenda"), _tc("c0")])
    rt = _RT([hist, p1])
    assert _calcular_call_idx_midia(rt, "c0") == 0


def test_defesa_sem_state_ou_sem_mensagens() -> None:
    """Sem `state` / sem `messages` -> 0 (mesma defesa do codigo original)."""
    assert _calcular_call_idx_midia(object(), "x") == 0
    assert _calcular_call_idx_midia(_RT([]), "x") == 0


def test_id_nao_encontrado_devolve_contagem_corrente() -> None:
    """call_id ausente (nao deveria acontecer no fluxo real): devolve o total contado -- nunca
    colide com um ordinal ja atribuido."""
    rt = _RT([_ai([_tc("c0"), _tc("c1")])])
    assert _calcular_call_idx_midia(rt, "inexistente") == 2
