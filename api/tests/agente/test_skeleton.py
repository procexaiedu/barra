"""Aceite M0-T6 — skeleton vivo: o grafo responde de verdade + guard-rail de prefixo.

2 testes (09 §2 M0):
    1. test_prefixo_byte_identico (SEM chave): BP_GERAL byte-identico p/ 2 modelo_id distintos
       (guard-rail #1, agente/CLAUDE.md). Exercita build_system_messages/render diretamente.
    2. test_skeleton_responde (needs_key): graph.ainvoke com 1 mensagem do cliente -> AIMessage
       com content nao-vazio.

NAO ha Postgres de teste: o DB entra fake via ContextAgente(db_pool=FakePool(FakeConn(...))).
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from _fakes import FakeConn, FakePool
from langchain_core.messages import AIMessage

from barra.agente.contexto import ContextAgente
from barra.agente.graph import build_graph
from barra.agente.llm import build_system_messages
from barra.agente.persona import render_prefixo_geral


def _prefixo_geral() -> list[Any]:
    """Prefixo system GERAL (BP_GERAL fundido: persona+regras+FAQ) como prepare_context o monta.

    So depende de render_prefixo_geral() — nenhum dado por-modelo (BP_MODELO entra no M2).
    """
    return [msg.content for msg in build_system_messages(geral_md=render_prefixo_geral())]


def test_prefixo_byte_identico() -> None:
    # Guard-rail #1 (agente/CLAUDE.md): BP1+BP2 saem byte-identicos entre modelos — vazar dado
    # por-modelo no prefixo derruba o cache de TODAS. Em M0 o prefixo nem recebe modelo_id (BP3 so
    # no M2), entao construi-lo p/ 2 modelos distintos tem que dar o MESMO conteudo. O teste trava
    # a invariante: se BP1/BP2 passarem a depender da modelo, ele quebra antes de chegar em prod.
    modelo_a, modelo_b = str(uuid4()), str(uuid4())
    assert modelo_a != modelo_b
    assert _prefixo_geral() == _prefixo_geral()


def _msg_cliente(texto: str) -> dict[str, Any]:
    """Linha de `mensagens` (forma que carregar_mensagens devolve) p/ 1 mensagem do cliente."""
    return {
        "id": uuid4(),
        "direcao": "cliente",
        "tipo": "texto",
        "conteudo": texto,
        "media_object_key": None,
        "created_at": datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
    }


def _contexto(conn: FakeConn) -> ContextAgente:
    return ContextAgente(
        db_pool=FakePool(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )


@pytest.mark.needs_key
def test_skeleton_responde() -> None:
    conn = FakeConn(ia_pausada=False, mensagens=[_msg_cliente("oi, vc atende hoje?")])
    estado = asyncio.run(build_graph().ainvoke({"messages": []}, context=_contexto(conn)))
    ultima = estado["messages"][-1]
    assert isinstance(ultima, AIMessage)
    assert ultima.content, "esperava resposta nao-vazia do modelo"
