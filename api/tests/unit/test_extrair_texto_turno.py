"""Coordenador — agregacao do texto do turno (regressao do `turno_sem_resposta`).

Puro (sem banco, sem chave). Cobre dois cenarios observados em prod (2026-05-27):
  1. ReAct: 1a AIMessage tem texto+tool_call, 2a vem com `content=[]` apos `ToolMessage` —
     pegar so a ultima daria "" e disparava `turno_sem_resposta`.
  2. Historica re-injetada pelo `prepare_context` (nos/prepare_context.py:188): AIMessage
     do banco SEM `usage_metadata` — agregar duplicava a resposta anterior na nova entrega.

Helpers `_ai_real(...)` e `_ai_historica(...)` espelham as duas fontes: o LLM real injeta
`usage_metadata`; o prepare_context constroi com so `content`+`id`.
"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from barra.workers.coordenador import _extrair_texto_do_turno


def _ai_real(content: Any, **kwargs: Any) -> AIMessage:
    """AIMessage como o LLM atual entrega — com `usage_metadata` (criterio do filtro)."""
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
        **kwargs,
    )


def _ai_historica(content: str, msg_id: str = "hist-1") -> AIMessage:
    """AIMessage como `prepare_context` re-injeta (nos/prepare_context.py:188) — sem metadata."""
    return AIMessage(content=content, id=msg_id)


def test_react_texto_primeira_passagem_seguido_de_vazia() -> None:
    """O caso real de prod: 1a AIMessage tem texto+tool_call, 2a vem vazia."""
    messages = [
        SystemMessage(content="persona"),
        HumanMessage(content="oi vc tem horário pra hoje?"),
        _ai_real(
            [
                {"type": "text", "text": "oi amor, tô sim! foi mal a demora"},
                {"type": "tool_use", "id": "toolu_1", "name": "registrar_extracao", "input": {}},
            ]
        ),
        ToolMessage(content="Extracao registrada.", tool_call_id="toolu_1"),
        _ai_real([]),  # 2a passagem vazia (LLM ja respondeu na 1a)
    ]
    assert _extrair_texto_do_turno(messages) == "oi amor, tô sim! foi mal a demora"


def test_historica_reinjetada_e_ignorada() -> None:
    """Regressao 2026-05-27: prepare_context injeta AIMessage previa no historico — sem
    usage_metadata. Antes do filtro, agregava com a resposta nova e duplicava o texto."""
    messages = [
        HumanMessage(content="oii"),
        # turno anterior re-injetado pelo prepare_context
        _ai_historica("oii amor, tudo bem? me conta, como descobriu meu número?"),
        HumanMessage(content="pelo barravips"),
        # turno atual (com usage_metadata)
        _ai_real("q legal amor, bem vindo 😊\n\nme conta, tava pensando em algo?"),
    ]
    assert (
        _extrair_texto_do_turno(messages)
        == "q legal amor, bem vindo 😊\n\nme conta, tava pensando em algo?"
    )


def test_apenas_uma_aimessage_com_string_simples() -> None:
    """Sem tool: content como str (formato simples)."""
    messages = [
        HumanMessage(content="oi"),
        _ai_real("oii amor, tudo bem?"),
    ]
    assert _extrair_texto_do_turno(messages) == "oii amor, tudo bem?"


def test_duas_aimessages_com_texto_concatenam_com_newline_duplo() -> None:
    """ReAct onde a 2a passagem tambem produz texto (elabora apos tool result)."""
    messages = [
        HumanMessage(content="quanto vc cobra?"),
        _ai_real(
            [
                {"type": "text", "text": "deixa eu ver"},
                {"type": "tool_use", "id": "toolu_1", "name": "buscar_programas", "input": {}},
            ]
        ),
        ToolMessage(content="1h=R$500", tool_call_id="toolu_1"),
        _ai_real("1h é 500, amor"),
    ]
    assert _extrair_texto_do_turno(messages) == "deixa eu ver\n\n1h é 500, amor"


def test_sem_aimessage_retorna_vazio() -> None:
    """Edge case: turno sem nenhuma AIMessage (nao deveria acontecer no fluxo real)."""
    messages = [HumanMessage(content="oi"), SystemMessage(content="persona")]
    assert _extrair_texto_do_turno(messages) == ""


def test_aimessage_com_blocos_misturados_pega_so_texto() -> None:
    """content com text + tool_use entremeados — agrega so os blocos type=text."""
    messages = [
        _ai_real(
            [
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
        _ai_real([]),
        _ai_real(""),
    ]
    assert _extrair_texto_do_turno(messages) == ""


def test_so_historicas_sem_atual_retorna_vazio() -> None:
    """Edge: turno sem nenhuma AIMessage do LLM atual (so historicas) -> "" (sem resposta nova)."""
    messages = [
        HumanMessage(content="oi"),
        _ai_historica("resposta de turno anterior"),
        HumanMessage(content="ainda ta ai?"),
        _ai_historica("outra resposta antiga"),
    ]
    assert _extrair_texto_do_turno(messages) == ""


def test_tool_com_erro_recuperavel_descarta_rascunho_da_passagem_re_tentada() -> None:
    """Bug 2026-06-03 (externo_pix): uma tool de escrita devolve "ERRO: ..." (recuperavel, string e
    nao excecao); o LLM RE-EMITE o texto e re-chama a tool na passagem seguinte. Antes do filtro, as
    duas passagens eram agregadas e o cliente via a fala DUPLICADA. So o texto da passagem BEM-SUCEDIDA
    deve sair; o rascunho da passagem cujo tool_call ERROU e descartado."""
    messages = [
        HumanMessage(content="me passa o pix do deslocamento"),
        # 1a passagem: texto + pedir_pix que vai FALHAR (horario ainda nao combinado)
        _ai_real(
            [
                {"type": "text", "text": "combinado, 22h então 😊"},
                {
                    "type": "tool_use",
                    "id": "toolu_err",
                    "name": "pedir_pix_deslocamento",
                    "input": {},
                },
            ]
        ),
        ToolMessage(
            content="ERRO: o horário ainda não está combinado — confirme primeiro.",
            tool_call_id="toolu_err",
        ),
        # 2a passagem (retentativa): texto re-emitido + pedir_pix que tem SUCESSO
        _ai_real(
            [
                {"type": "text", "text": "pra garantir teu horário amor, manda o pixzinho 🥰"},
                {
                    "type": "tool_use",
                    "id": "toolu_ok",
                    "name": "pedir_pix_deslocamento",
                    "input": {},
                },
            ]
        ),
        ToolMessage(content="Pix de R$ 100 solicitado e slot reservado.", tool_call_id="toolu_ok"),
        _ai_real([]),  # passagem final vazia
    ]
    assert _extrair_texto_do_turno(messages) == "pra garantir teu horário amor, manda o pixzinho 🥰"
