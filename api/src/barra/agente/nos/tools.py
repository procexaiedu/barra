"""No tools: executa as tool_calls do turno e devolve ao llm (loop ReAct).

M1: ToolNode do langgraph executando as tools de leitura registradas em TOOLS
    (P0: consultar_agenda). Loop tools<->llm ate o LLM parar de pedir tool_call
    (teto em recursion_limit, config de invocacao -- 03 §8, 09 §4.7).
M3: adiciona tools de escrita (registrar_extracao, escalar) com idempotencia via tabela
    barravips.tool_calls. (O Pix de deslocamento virou side-effect deterministico da extracao,
    nao tool -- ver dominio/atendimentos/service.py:_solicitar_pix_deslocamento_se_aplicavel.)
M5e: registra `enviar_midia`. Como ela pode ser chamada VARIAS vezes no mesmo turno (ex.:
    2 fotos da mesma tag) e a idempotencia depende da PK `(turno_id, tool_name, call_idx)`,
    `_ToolNodeComMidiaIdx` injeta `call_idx` ordinal no `_inject_tool_args` (NUNCA no `args`
    cru do tool_call: o ToolNode default STRIPA InjectedToolArg vindos de `tool_call["args"]`
    como defesa contra LLM forjar -- doc oficial em langgraph 1.x). `runtime.tool_call_id`
    muda no replay (quebraria a PK) e `runtime.state["midia_idx"]` carrega o MESMO valor
    p/ todas as chamadas do turno (o State so consolida no fim do no), entao o indice por
    ordem de aparicao das `enviar_midia` em TODAS as AIMessages do turno e a unica fonte
    deterministica (04 §3.3 nota; ordinal GLOBAL p/ nao colidir entre passagens ReAct).
"""

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode

from ..ferramentas import TOOLS


class _ToolNodeComMidiaIdx(ToolNode):
    """Injeta `call_idx` ordinal nas chamadas de `enviar_midia`.

    Por que aqui e nao via `tool_call["args"]`: o ToolNode default (`_inject_tool_args`)
    deliberadamente STRIPA qualquer valor de `InjectedToolArg` que tenha sido colocado em
    `tool_call_copy["args"]` antes de chamar a tool, para impedir que o LLM forge valores
    secretos (`call_idx`, `tool_call_id`, etc.). A injecao tem de entrar em `injected_args`
    (valores "trusted"), exatamente no mesmo ponto onde state/store/runtime sao injetados.

    Calcula `call_idx` pela posicao ordinal GLOBAL da chamada entre TODAS as `enviar_midia`
    do turno (varrendo as AIMessages do State em ordem) -- determinismo total, sem estado
    mutavel compartilhado, replay-safe: no replay o State nasce do zero, as mesmas AIMessages
    produzem os mesmos `call_idx` 0..N-1 e o ON CONFLICT do `_executar_idempotente` deduplica.
    O ordinal e GLOBAL (nao por-AIMessage) p/ nao colidir quando `enviar_midia` reaparece em
    passagens ReAct distintas do mesmo turno (ver `_calcular_call_idx_midia`).

    "Unordered" no doc oficial e sobre EXECUCAO paralela (asyncio.gather no `_afunc`) --
    nao sobre posicao no array `tool_calls`, que e estavel (04 §3.3 nota).
    """

    def _inject_tool_args(
        self,
        tool_call: Any,
        tool_runtime: Any,
        tool: BaseTool | None = None,
    ) -> Any:
        result = super()._inject_tool_args(tool_call, tool_runtime, tool)
        if tool_call["name"] == "enviar_midia":
            result["args"]["call_idx"] = _calcular_call_idx_midia(tool_runtime, tool_call["id"])
        return result


def _calcular_call_idx_midia(tool_runtime: Any, this_call_id: str) -> int:
    """Posicao ordinal GLOBAL desta chamada de `enviar_midia` entre TODAS as `enviar_midia`
    geradas no turno -- varre as AIMessages do State em ordem, nao so a ultima. Determinismo:
    depende so do conteudo do State (replay-safe). Sem estado mutavel compartilhado (compativel
    com `asyncio.gather` do `_afunc`).

    Por que GLOBAL e nao por-AIMessage: no ReAct `enviar_midia` pode reaparecer em PASSAGENS
    distintas do MESMO turno (AIMessages distintas) -- ex.: manda 1 foto, ve o resultado, decide
    mandar outra. Um ordinal local a cada AIMessage reiniciaria em 0 na 2a passagem e colidiria a
    PK `(turno_id, 'enviar_midia', call_idx)`: o ON CONFLICT do `_executar_idempotente` descartaria
    a foto da 2a passagem em silencio. O ordinal global mantem `call_idx` unico no turno. AIMessages
    historicas re-injetadas pelo prepare_context nao carregam tool_calls (so content+id), entao nao
    inflam a contagem -- varrer todas e seguro.
    """
    state = getattr(tool_runtime, "state", None)
    if state is None:
        return 0
    mensagens = (
        state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    )
    if not mensagens:
        return 0
    idx = 0
    for m in mensagens:
        if not isinstance(m, AIMessage):
            continue
        for tc in m.tool_calls or []:
            if tc.get("id") == this_call_id:
                return idx
            if tc.get("name") == "enviar_midia":
                idx += 1
    return idx


# Constante de modulo: TOOLS ja esta populado. A subclass injeta `call_idx` ordinal nas
# chamadas de `enviar_midia`; as demais tools nao tem esse param.
tools_node = _ToolNodeComMidiaIdx(TOOLS)
