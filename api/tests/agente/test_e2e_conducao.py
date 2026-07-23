"""Validacao offline do harness e2e (evals/e2e): o agente conduz Novo -> Aguardando_confirmacao
ao longo de varios turnos, contra um cliente roteirizado, com o LLM MOCKADO.

needs_db (DB real via TEST_DATABASE_URL, ROLLBACK sempre) mas NAO needs_key: o chat do agente e
um fake roteirizado, entao NAO gasta credito (§0). Prova o encanamento ponta-a-ponta: seed em
`Novo` -> loop multi-turn -> transicoes persistem no DB -> parada na linha de chegada -> veredito.

O fake conduz um caso interno: por turno o llm emite a bolha de texto (sem tool_call) e o no
`extrair` FORCA a registrar_extracao (a tool real escreve o estado). `_decidir_transicao` avanca
UM degrau por extracao (Novo->Triagem->Qualificado->Aguardando_confirmacao), por isso sao 3 turnos.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from evals.e2e.avaliacao import avaliar_e2e
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import rodar_e2e
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

pytestmark = pytest.mark.needs_db

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- conexao DB real (ROLLBACK sempre) -------------------------------------------------------


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


# --- chat fake roteirizado: conduz um caso interno, 1 extracao + 1 bolha por turno -----------


def _extracao(args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "tool_use"},
        tool_calls=[
            {"name": "registrar_extracao", "args": args, "id": uuid4().hex, "type": "tool_call"}
        ],
    )


def _bolha(texto: str) -> AIMessage:
    return AIMessage(
        content=texto,
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


class _BoundRoteirizado:
    def __init__(self, chat: _ChatRoteirizado) -> None:
        self._chat = chat

    async def ainvoke(self, _messages: Any) -> AIMessage:
        return self._chat._proxima()


class _ChatRoteirizado:
    """Por turno o agente consome 2 AIMessages da fila, na ordem: a BOLHA (chat #1, sem tool_call
    -> roteia ao no `extrair`) e a EXTRAÇÃO forcada (o `extrair` binda registrar_extracao com
    tool_choice e a executa inline). `bind_tools` (normal ou forcado) devolve o mesmo bound; a fila
    serve as duas chamadas na ordem."""

    model = "claude-test-e2e"

    def __init__(self, sequencia: list[AIMessage]) -> None:
        self._fila = list(sequencia)

    def _proxima(self) -> AIMessage:
        assert self._fila, "fila do chat fake esgotada (sequencia mais curta que os turnos rodados)"
        return self._fila.pop(0)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _BoundRoteirizado:
        return _BoundRoteirizado(self)


def _sequencia_interno() -> list[AIMessage]:
    amanha = date.today() + timedelta(days=1)
    base = {"proxima_acao_esperada": "conduzir o agendamento interno", "intencao": "agendamento"}
    so_tipo = {**base, "tipo_atendimento": "interno", "cotacao_apresentada": True}
    completa = {
        **so_tipo,
        "horario_desejado": "15:00",
        "data_desejada": amanha.isoformat(),
        "duracao_horas": 1,
    }
    # 3 turnos incrementais (espelham um cliente revelando aos poucos): intenção+cotação (Triagem)
    # -> tipo (Qualificado) -> horário (Aguardando_confirmacao + bloqueio). Prova que o multi-hop
    # NÃO pula etapas quando a info chega gradual e sobe os degraus na ordem; os dois últimos só
    # subiriam juntos se tipo+horário chegassem no MESMO turno. O runner para ao chegar em
    # Aguardando_confirmacao, então o 3o turno fecha a jornada.
    # Ordem por turno (02 §4): a BOLHA (chat #1, sem tool_call -> `extrair`) e depois a EXTRAÇÃO
    # (o `extrair` força registrar_extracao com tool_choice e a executa inline). Os args da extração
    # por turno não mudam — só o preenchedor mudou de posição.
    return [
        _bolha("oii amor, claro que atendo 😊 o encontro de 1h fica 400"),
        _extracao({**base, "cotacao_apresentada": True}),
        _bolha("aaa que delícia, você vem aqui então 🥰"),
        _extracao(so_tipo),
        _bolha("amanhã 15h fica perfeito pra mim"),
        _extracao(completa),
    ]


# --- teste -----------------------------------------------------------------------------------


async def test_conduz_interno_novo_ate_aguardando_confirmacao(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from barra.agente import graph as graph_mod

    chat_fake = _ChatRoteirizado(_sequencia_interno())
    # Caminhos de texto sao DeepSeek-only -> _criar_chat_principal/extracao chamam criar_chat_deepseek;
    # mocka o factory com o fake p/ o teste não escapar pra API real (§0).
    monkeypatch.setattr(graph_mod, "criar_chat_deepseek", lambda *a, **k: chat_fake)
    graph = graph_mod.build_graph()

    perfil = PerfilCaso(
        nome="interno_decidido",
        abertura="oi, vc atende? queria marcar um horario",
        modelo={
            "nome": "Manu",
            "tipo_atendimento_aceito": ["interno", "externo"],
            "programas": [{"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400}],
        },
        roteiro_cliente=["pode ser interno", "amanhã 15h, 1 hora"],
        tipo_esperado="interno",
        desfecho_real="convertido_provavel",
    )
    cliente = ClienteRoteirizado(perfil.roteiro_cliente)

    res = await rodar_e2e(conn, perfil, cliente, graph=graph, max_turnos=8)

    assert res.desfecho_conducao == "conduziu", (res.desfecho_conducao, res.trajetoria)
    assert res.estado_final == "Aguardando_confirmacao", res.trajetoria
    assert res.conduziu is True
    # multi-turn de verdade: passou por Triagem/Qualificado antes da confirmacao
    estados = [t.get("estado") for t in res.trajetoria]
    assert "Triagem" in estados and "Qualificado" in estados, estados

    vereditos = avaliar_e2e(res, perfil)
    assert vereditos.ok, vereditos.violacoes
    assert vereditos.bate_desfecho_real is True  # conduziu E o cliente real convergiu
    # Tokens 100% do fake (2 AIMessages x 3 turnos, _USAGE fixo) -> nenhuma chamada real a API (§0)
    assert sum(t.metricas.input_tokens for t in res.turnos) == 60
    assert sum(t.metricas.output_tokens for t in res.turnos) == 30
