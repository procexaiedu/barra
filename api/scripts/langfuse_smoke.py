"""Smoke de avaliação do Langfuse (LangSmith vs Langfuse) — CUSTO ZERO, sem Anthropic.

Monta um mini-LangGraph de 2 nós usando um LLM FAKE (FakeListChatModel) e o traça no Langfuse
pelo CallbackHandler oficial. Prova, sem gastar crédito:
  - ingestão (o trace chega ao projeto),
  - legibilidade (conteúdo não-mascarado, ao contrário do prod LangSmith),
  - fidelidade LangGraph-nativa (a árvore do trace reflete os nós do grafo).

NÃO é código de produção e NÃO toca o agente real (`barra.agente`). Descartável: apaga depois da
avaliação. Lê as chaves do ambiente (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST);
sem elas, só valida que a fiação importa e sai.

Uso:
    LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-... \
    LANGFUSE_HOST=https://cloud.langfuse.com \
    uv run python scripts/langfuse_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Annotated, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class _Estado(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# Falas roteirizadas (sintéticas, sem PII) — o fake só ecoa estas, na ordem.
_TRIAGEM = FakeListChatModel(responses=["Oi! Que programa você procura e pra quando?"])
_COTACAO = FakeListChatModel(responses=["Pernoite fica R$X. Quer que eu reserve?"])


async def _no_triagem(estado: _Estado) -> _Estado:
    resp = await _TRIAGEM.ainvoke(estado["messages"])
    return {"messages": [resp]}


async def _no_cotacao(estado: _Estado) -> _Estado:
    resp = await _COTACAO.ainvoke(estado["messages"])
    return {"messages": [resp]}


def _build() -> object:
    g = StateGraph(_Estado)
    g.add_node("triagem", _no_triagem)
    g.add_node("cotacao", _no_cotacao)
    g.add_edge(START, "triagem")
    g.add_edge("triagem", "cotacao")
    g.add_edge("cotacao", END)
    return g.compile()


async def _rodar() -> None:
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler

    # get_client lê LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST do ambiente e instancia o singleton.
    client = get_client()
    if not client.auth_check():
        print("ERRO: auth_check falhou — confira as 3 chaves/host.", file=sys.stderr)
        sys.exit(1)

    handler = CallbackHandler()
    grafo = _build()
    entrada = {"messages": [HumanMessage(content="oi, tudo bem? queria saber dos seus valores")]}
    resultado = await grafo.ainvoke(
        entrada,
        config={
            "callbacks": [handler],
            "metadata": {
                "langfuse_session_id": "smoke-eval",
                "modelo_id": "smoke-modelo",
                "atendimento_id": "smoke-atendimento",
            },
            "tags": ["smoke", "langsmith-vs-langfuse"],
            "run_name": "smoke_minigrafo",
        },
    )
    client.flush()  # garante o envio antes do processo morrer
    msgs = [m for m in resultado["messages"] if isinstance(m, AIMessage)]
    print(f"OK — grafo rodou, {len(msgs)} respostas da IA. Trace enviado ao Langfuse.")
    print(f"Veja em: {os.environ['LANGFUSE_HOST']} (projeto) — filtre pela tag 'smoke'.")


def main() -> None:
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        print(
            "Sem LANGFUSE_PUBLIC_KEY no ambiente — fiação importa OK, mas nada a enviar.\n"
            "Rode com as 3 chaves no env (ver docstring).",
        )
        return
    asyncio.run(_rodar())


if __name__ == "__main__":
    main()
