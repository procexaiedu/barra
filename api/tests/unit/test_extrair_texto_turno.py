"""Coordenador — agregacao do texto do turno (regressao do `turno_sem_resposta`).

Puro (sem banco, sem chave). Cobre o caso real observado em prod (2026-05-27): no padrao
ReAct, o LLM e chamado de novo depois de cada ToolMessage; quando ja respondeu na 1a
passagem (texto + tool_call), a 2a passagem volta com `content=[]` — pegar so a ultima
AIMessage daria "" e disparava `turno_sem_resposta` no coordenador.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from barra.workers.coordenador import _extrair_texto_do_turno


def test_react_texto_primeira_passagem_seguido_de_vazia() -> None:
    """O caso real de prod: 1a AIMessage tem texto+tool_call, 2a vem vazia."""
    messages = [
        SystemMessage(content="persona"),
        HumanMessage(content="oi vc tem horário pra hoje?"),
        AIMessage(
            content=[
                {"type": "text", "text": "oi amor, tô sim! foi mal a demora"},
                {"type": "tool_use", "id": "toolu_1", "name": "registrar_extracao", "input": {}},
            ]
        ),
        ToolMessage(content="Extracao registrada.", tool_call_id="toolu_1"),
        AIMessage(content=[]),  # 2a passagem vazia (LLM ja respondeu na 1a)
    ]
    assert _extrair_texto_do_turno(messages) == "oi amor, tô sim! foi mal a demora"


def test_apenas_uma_aimessage_com_string_simples() -> None:
    """Sem tool: content como str (formato simples)."""
    messages = [
        HumanMessage(content="oi"),
        AIMessage(content="oii amor, tudo bem?"),
    ]
    assert _extrair_texto_do_turno(messages) == "oii amor, tudo bem?"


def test_duas_aimessages_com_texto_concatenam_com_newline_duplo() -> None:
    """ReAct onde a 2a passagem tambem produz texto (elabora apos tool result)."""
    messages = [
        HumanMessage(content="quanto vc cobra?"),
        AIMessage(
            content=[
                {"type": "text", "text": "deixa eu ver"},
                {"type": "tool_use", "id": "toolu_1", "name": "buscar_programas", "input": {}},
            ]
        ),
        ToolMessage(content="1h=R$500", tool_call_id="toolu_1"),
        AIMessage(content="1h é 500, amor"),
    ]
    assert _extrair_texto_do_turno(messages) == "deixa eu ver\n\n1h é 500, amor"


def test_sem_aimessage_retorna_vazio() -> None:
    """Edge case: turno sem nenhuma AIMessage (nao deveria acontecer no fluxo real)."""
    messages = [HumanMessage(content="oi"), SystemMessage(content="persona")]
    assert _extrair_texto_do_turno(messages) == ""


def test_aimessage_com_blocos_misturados_pega_so_texto() -> None:
    """content com text + tool_use entremeados — agrega so os blocos type=text."""
    messages = [
        AIMessage(
            content=[
                {"type": "text", "text": "primeira parte"},
                {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
                {"type": "text", "text": " segunda parte"},
            ]
        ),
    ]
    assert _extrair_texto_do_turno(messages) == "primeira parte segunda parte"


def test_todas_aimessages_vazias_retorna_vazio() -> None:
    """Caso degenerado: todas vazias -> string vazia (coordenador loga turno_sem_resposta)."""
    messages = [
        HumanMessage(content="oi"),
        AIMessage(content=[]),
        AIMessage(content=""),
    ]
    assert _extrair_texto_do_turno(messages) == ""
