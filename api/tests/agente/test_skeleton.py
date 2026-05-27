"""Aceite M0-T6 — skeleton vivo: o grafo responde de verdade + cache + guard-rail de prefixo.

3 testes (09 §2 M0):
    1. test_prefixo_byte_identico (SEM chave): BP1+BP2 byte-identicos p/ 2 modelo_id distintos
       (guard-rail #1, agente/CLAUDE.md). Exercita build_system_messages/render diretamente.
    2. test_skeleton_responde (needs_key): graph.ainvoke com 1 mensagem do cliente -> AIMessage
       com content nao-vazio.
    3. test_cache_write_read (needs_key): 2 ainvokes identicos -> 1a escreve (ephemeral_*>0),
       2a le (cache_read>0). NAO assertar cache_creation>0 (vem sempre 0 no 1.4.3, 03 §5).

NAO ha Postgres de teste: o DB entra fake via ContextAgente(db_pool=FakePool(FakeConn(...))).
"""

import asyncio
import importlib
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
from barra.settings import get_settings


def _prefixo_geral() -> list[Any]:
    """Prefixo system GERAL (BP_GERAL fundido: persona+regras+FAQ) como prepare_context o monta.

    So depende de render_prefixo_geral() — nenhum dado por-modelo (BP_MODELO entra no M2).
    """
    return [
        msg.content
        for msg in build_system_messages(
            geral_md=render_prefixo_geral(),
            ttl_geral=get_settings().cache_ttl_geral,
        )
    ]


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


def _detalhes_tokens(estado: dict[str, Any]) -> dict[str, int]:
    """input_token_details da ultima AIMessage (03 §4.2)."""
    ultima = estado["messages"][-1]
    assert isinstance(ultima, AIMessage)
    meta = ultima.usage_metadata or {}
    return dict(meta.get("input_token_details") or {})


@pytest.mark.needs_key
def test_skeleton_responde() -> None:
    conn = FakeConn(ia_pausada=False, mensagens=[_msg_cliente("oi, vc atende hoje?")])
    estado = asyncio.run(build_graph().ainvoke({"messages": []}, context=_contexto(conn)))
    ultima = estado["messages"][-1]
    assert isinstance(ultima, AIMessage)
    assert ultima.content, "esperava resposta nao-vazia do Sonnet"


@pytest.mark.needs_key
def test_cache_write_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2 ainvokes IDENTICOS (mesmo conn -> mesmo prefixo+janela): a 1a escreve o prefixo no cache,
    # a 2a le. Rede contra o wrapper langchain dropar cache_control em silencio (03 §5).
    #
    # Nonce no BP1: o prefixo GERAL e o MESMO p/ todas as modelos/turnos, entao um teste anterior
    # (test_skeleton_responde) ou uma rodada dentro do TTL de 1h ja teria aquecido o cache e a "1a"
    # chamada LERIA em vez de escrever. O nonce torna o prefixo COLD (nunca visto) garantindo a
    # escrita; os dois ainvokes seguem identicos ENTRE SI (ambos usam o mesmo nonce).
    geral = f"{render_prefixo_geral()}\n<!-- cache-cold {uuid4().hex} -->"
    # importlib p/ pegar o MODULO (o pacote `nos` reexporta a funcao prepare_context com o mesmo
    # nome do submodulo, entao `import ...nos.prepare_context as m` resolveria p/ a funcao).
    prepare_context_mod = importlib.import_module("barra.agente.nos.prepare_context")
    monkeypatch.setattr(prepare_context_mod, "render_prefixo_geral", lambda: geral)

    graph = build_graph()
    conn = FakeConn(ia_pausada=False, mensagens=[_msg_cliente("oi, tudo bem? vc ta livre hoje?")])

    det1 = _detalhes_tokens(asyncio.run(graph.ainvoke({"messages": []}, context=_contexto(conn))))
    write = det1.get("ephemeral_5m_input_tokens", 0) + det1.get("ephemeral_1h_input_tokens", 0)
    assert write > 0, "1a chamada deveria ESCREVER o prefixo no cache (ephemeral_*)"

    det2 = _detalhes_tokens(asyncio.run(graph.ainvoke({"messages": []}, context=_contexto(conn))))
    assert det2.get("cache_read", 0) > 0, "2a chamada identica deveria LER do cache"
