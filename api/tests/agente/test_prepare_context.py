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


def test_caminho_normal_3_system_mais_janela_cronologica() -> None:
    res = asyncio.run(prepare_context({"messages": []}, _runtime(mensagens=_linhas_desc())))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    msgs = res.update["messages"]
    # 3 SystemMessage (BP1+BP2 gerais + BP3 por-modelo) + 3 da janela (contexto dinamico nao
    # cria msg nova: ha HumanMessage). BP3 emitido a partir do M2-T1.
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert isinstance(msgs[2], SystemMessage)
    assert len(msgs) == 6
    # ordem cronologica: cliente -> ia -> modelo_manual
    assert isinstance(msgs[3], HumanMessage)
    # contexto dinamico (02 §5) e concatenado no ULTIMO HumanMessage, depois da msg do cliente
    # (a verificacao rigorosa de que o prefixo cacheavel fica intacto vive em test_contexto_dinamico)
    assert msgs[3].content.startswith("ola")
    assert "# Estado atual do atendimento" in msgs[3].content
    assert isinstance(msgs[4], AIMessage)
    assert msgs[4].content == "oi amor, tudo bem?"
    # modelo_manual vira AIMessage COM PREFIXO
    assert isinstance(msgs[5], AIMessage)
    assert msgs[5].content == "[mensagem manual da modelo]: deixa que eu respondo"


def test_atendimento_id_none_pula_gate() -> None:
    rt = _runtime(mensagens=[])
    rt.context.atendimento_id = None  # type: ignore[assignment]
    res = asyncio.run(prepare_context({"messages": []}, rt))
    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    # 3 system (BP1+BP2+BP3) + 1 HumanMessage: janela vazia, entao o contexto dinamico (02 §5) e
    # anexado como novo HumanMessage no fim (defesa do _anexar_contexto_dinamico). BP3 carrega por
    # modelo_id, que existe mesmo com atendimento_id None. Gate pulado sem crashar.
    msgs = res.update["messages"]
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], SystemMessage)
    assert isinstance(msgs[2], SystemMessage)
    assert isinstance(msgs[3], HumanMessage)
    assert "# Estado atual do atendimento" in msgs[3].content


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
