"""Agregacao das AIMessages GERADAS NO TURNO (criterio: usage_metadata is not None).

Fonte unica do criterio "o que o LLM gerou agora" vs historico re-injetado pelo
prepare_context (AIMessages do banco, sem usage_metadata). Compartilhado pelo coordenador
(extrai o texto que vai ao cliente) e pelo output_guard (escaneia/zera EXATAMENTE o mesmo
texto antes do envio) — duplicar o filtro nos dois lados ja divergiu uma vez (o guard so via
a ultima AIMessage enquanto o coordenador despachava o agregado do turno).
"""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def mensagens_do_turno(messages: Sequence[BaseMessage]) -> list[AIMessage]:
    """AIMessages geradas NESTE turno (com usage_metadata; exclui historicas re-injetadas)."""
    return [m for m in messages if isinstance(m, AIMessage) and m.usage_metadata is not None]


def _extrair_texto(msg: AIMessage) -> str:
    """Texto plano de uma AIMessage. content pode ser str ou lista de blocos (1.x)."""
    if isinstance(msg.content, str):
        return msg.content
    partes = [
        bloco.get("text", "")
        for bloco in msg.content
        if isinstance(bloco, dict) and bloco.get("type") == "text"
    ]
    return "".join(partes)


def _tool_use_ids(msg: AIMessage) -> set[str]:
    """IDs dos tool_calls de uma AIMessage -- de `.tool_calls` (LLM real) e dos blocos `tool_use`
    do content (cobre mensagens cruas/testes onde `.tool_calls` nao foi populado)."""
    ids: set[str] = set()
    for tc in msg.tool_calls or []:
        tid = tc.get("id")
        if tid:
            ids.add(tid)
    if isinstance(msg.content, list):
        for b in msg.content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
                ids.add(b["id"])
    return ids


def extrair_texto_do_turno(messages: Sequence[BaseMessage]) -> str:
    """Agrega texto das AIMessages GERADAS pelo LLM neste turno, separadas por \\n\\n.

    No padrao ReAct, o LLM e chamado de novo depois de cada ToolMessage; quando ja respondeu
    o cliente na 1a passagem (texto + tool_call), a 2a passagem volta com `content=[]` —
    pegar so a ultima AIMessage daria "" e disparava `turno_sem_resposta`.

    O `prepare_context` re-injeta AIMessages historicas (mensagens previas da IA do banco)
    no input do LLM (`nos/prepare_context.py:188`); essas vem SEM `usage_metadata`. Filtrar
    por `usage_metadata` mantem so o que o LLM gerou agora — agregar historicas duplicaria
    a resposta anterior junto com a nova (bug observado em prod 2026-05-27).

    Erro recuperavel + retry (2026-06-03): quando uma tool falha de forma recuperavel, o LLM
    RE-EMITE o texto e re-chama a tool na passagem seguinte. O texto da passagem cujo tool_call
    ERROU e um rascunho SUPERADO pela retentativa -- agrega-lo duplicaria a fala ao cliente (bug
    externo_pix). Descartamos o texto das AIMessages cujo tool_call resultou em ToolMessage de
    erro: `status == "error"` cobre ToolException com handle_tool_error (ferramentas/, prefixo
    "ERRO:") E erro de args do ToolNode (ToolInvocationError, ex. data invalida pos-tipagem
    `date` -- sem o prefixo); o startswith fica de cinto de seguranca p/ ToolMessage construida
    a mao com status default.
    """
    ids_com_erro = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage)
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
        and m.tool_call_id
    }
    partes: list[str] = []
    for m in mensagens_do_turno(messages):
        if ids_com_erro and (_tool_use_ids(m) & ids_com_erro):
            # rascunho superado por retentativa de tool-com-erro recuperavel. Premissa: no maximo
            # UMA tool de escrita com erro recuperavel por passagem -- as tools de mídia (fan-out
            # multi-call por turno) NAO retornam "ERRO:" agregavel a texto, entao nao acionam isto.
            continue
        texto = _extrair_texto(m)
        if texto:
            partes.append(texto)
    return "\n\n".join(partes)
