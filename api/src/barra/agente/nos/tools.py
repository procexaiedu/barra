"""No tools: executa as tool_calls do turno e devolve ao llm (loop ReAct).

M1: ToolNode do langgraph executando as tools de leitura registradas em TOOLS
    (P0: consultar_agenda). Loop tools<->llm ate o LLM parar de pedir tool_call
    (teto em recursion_limit, config de invocacao -- 03 §8, 09 §4.7).
M3: adiciona tools de escrita (registrar_extracao, pedir_pix_deslocamento, enviar_midia,
    escalar) com idempotencia via tabela barravips.tool_calls.
"""

from langgraph.prebuilt import ToolNode

from ..ferramentas import TOOLS

# ToolNode injeta automaticamente runtime: ToolRuntime[ContextAgente] nas tools que o declaram
# (04 §1.1) -- a partir do context= passado em graph.ainvoke. Constante de modulo: TOOLS ja esta
# populado (M1-T1). call_idx/midia_idx so importam p/ enviar_midia (M3); consultar_agenda e
# leitura pura, entao ToolNode cru basta aqui.
tools_node = ToolNode(TOOLS)
