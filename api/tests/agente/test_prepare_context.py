"""Aceite M0-T4 — prepare_context: gate de pausa + system GERAL + janela deslizante.

ia_pausada=true -> Command(goto=END); senao messages = 2 SystemMessage + N HumanMessage/
AIMessage em ordem cronologica; modelo_manual vira AIMessage com prefixo. Fakes de pool/conn
(sem Postgres real, como o resto da suite); o grafo so e construido p/ provar que a pausa
encerra antes do llm (coordenacao graph.py <-> prepare_context).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from _fakes import FakeConn, FakePool, FakeRuntime
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.agente.nos.prepare_context import prepare_context, traduzir_mensagens


def _runtime(
    *,
    ia_pausada: bool = False,
    mensagens: list[dict[str, Any]] | None = None,
) -> FakeRuntime:
    conn = FakeConn(ia_pausada=ia_pausada, mensagens=mensagens or [])
    ctx = ContextAgente(
        db_pool=FakePool(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return FakeRuntime(ctx)


def _linhas_desc() -> list[dict[str, Any]]:
    """3 mensagens; ordem do DB e DESC (mais nova primeiro), o no reverte p/ cronologica."""
    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    nova_primeiro = [
        ("modelo_manual", "deixa que eu respondo", base + timedelta(minutes=2)),
        ("ia", "oi amor, tudo bem?", base + timedelta(minutes=1)),
        ("cliente", "ola", base),
    ]
    return [
        {
            "id": uuid4(),
            "direcao": direcao,
            "tipo": "texto",
            "conteudo": conteudo,
            "media_object_key": None,
            "created_at": ts,
        }
        for direcao, conteudo, ts in nova_primeiro
    ]


def test_ia_pausada_retorna_command_end() -> None:
    res = asyncio.run(prepare_context({"messages": []}, _runtime(ia_pausada=True)))
    assert isinstance(res, Command)
    assert res.goto == END


def test_caminho_normal_2_system_mais_janela_cronologica() -> None:
    res = asyncio.run(prepare_context({"messages": []}, _runtime(mensagens=_linhas_desc())))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    msgs = res.update["messages"]
    # 2 SystemMessage (BP_GERAL fundido + BP_MODELO por-modelo) + 3 da janela. BP_JANELA marca
    # cache na PENULTIMA da janela: msgs[3] (AIMessage "oi amor") vira content blocks; msgs[4]
    # (modelo_manual, ultima da janela) fica string volatil (sem cache).
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert len(msgs) == 5
    # msgs[2] = HumanMessage do cliente + contexto dinamico (ultimo HumanMessage da janela)
    assert isinstance(msgs[2], HumanMessage)
    assert msgs[2].content.startswith("ola")
    assert "<estado_atual>" in msgs[2].content
    # msgs[3] = penultima da janela = AIMessage "oi amor", agora COM cache_control (lista)
    assert isinstance(msgs[3], AIMessage)
    assert isinstance(msgs[3].content, list)
    assert msgs[3].content[0]["text"] == "oi amor, tudo bem?"  # type: ignore[index]
    assert msgs[3].content[0]["cache_control"]["type"] == "ephemeral"  # type: ignore[index]
    # msgs[4] = ultima da janela = modelo_manual, AIMessage com prefixo, content STRING (sem cache)
    assert isinstance(msgs[4], AIMessage)
    assert msgs[4].content == "[mensagem manual da modelo]: deixa que eu respondo"


def test_atendimento_id_none_pula_gate() -> None:
    rt = _runtime(mensagens=[])
    rt.context.atendimento_id = None  # type: ignore[assignment]
    res = asyncio.run(prepare_context({"messages": []}, rt))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    # 2 system (BP_GERAL + BP_MODELO) + 1 HumanMessage: janela vazia, contexto dinamico anexa
    # novo HumanMessage no fim. BP_MODELO carrega por modelo_id mesmo com atendimento_id None.
    # BP_JANELA no-op (janela so com 1 msg, sem penultima).
    msgs = res.update["messages"]
    assert len(msgs) == 3
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert isinstance(msgs[2], HumanMessage)
    assert "<estado_atual>" in msgs[2].content


def test_traduzir_audio_sem_transcricao_vira_placeholder() -> None:
    linhas = [
        {
            "id": uuid4(),
            "direcao": "cliente",
            "tipo": "audio",
            "conteudo": "",
            "media_object_key": "k",
            "created_at": None,
        },
        {
            "id": uuid4(),
            "direcao": "cliente",
            "tipo": "imagem",
            "conteudo": "",
            "media_object_key": "k",
            "created_at": None,
        },
    ]
    out = traduzir_mensagens(linhas)
    assert isinstance(out[0], HumanMessage)
    assert out[0].content == "[áudio que não consegui ouvir]"
    assert out[1].content == "[imagem]"


def test_traduzir_direcao_desconhecida_levanta() -> None:
    linhas = [
        {
            "id": uuid4(),
            "direcao": "sistema",
            "tipo": "texto",
            "conteudo": "x",
            "media_object_key": None,
            "created_at": None,
        },
    ]
    try:
        traduzir_mensagens(linhas)
    except ValueError as exc:
        assert "direcao desconhecida" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("esperava ValueError para direcao fora do enum")


@pytest.mark.needs_key  # build_graph() -> criar_chat_anthropic() exige ANTHROPIC_API_KEY
def test_grafo_pausa_encerra_antes_do_llm() -> None:
    # Prova a coordenacao graph.py <-> prepare_context: sem aresta estatica de saida, a pausa
    # (Command(goto=END)) encerra o turno sem fan-out p/ intercept_disclosure/llm (sem AIMessage).
    graph = build_graph()
    conn = FakeConn(ia_pausada=True, mensagens=[])
    ctx = ContextAgente(
        db_pool=FakePool(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    estado = asyncio.run(graph.ainvoke({"messages": []}, context=ctx))
    assert estado["messages"] == []
