"""Recuo do cliente REABRE a negociação de preço (spec `.scratch/extracao-aceite-hibrido/`).

Os casos auditados em produção, pelo caminho de prod (harness fiel: `processar_turno` →
`enviar_turno`) com o GRAFO REAL e o chat do LLM substituído por um fake roteirizado —
determinístico e SEM consumir crédito (§0). O ponto de partida é sempre o estado que a auditoria
encontrou: preço cotado e `aceita_valor` JÁ marcado — e o teste afirma o que a negociação passa a
permitir depois do turno, não como o rebaixamento foi derivado.

  - #19 "Não" após "Podemos confirmar 18h ?" -> rebaixa (negativa correferenciada)
  - #20 "esperar começo do mês"              -> rebaixa (recuo autônomo)
  - #27 "Hoje não consigo"                   -> rebaixa
  - #34 "Perfeito, vou te avisando então"    -> PRESERVA (a armadilha do "te aviso")
  - #24 "Não conheço" respondendo "Campinas?" -> não rebaixa por si só
  - valor preservado                          -> o belief volta a apresentá-lo como cotado

DB real (TEST_DATABASE_URL), ROLLBACK no teardown. `needs_db`, SEM `needs_key`.
"""

import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from _chat_fake import ChatRoteirizado
from evals.harness import seedar
from evals.harness_fiel import rodar_turno_fiel
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.graph import build_graph
from barra.dominio.agenda.service import BRT
from barra.settings import get_settings

pytestmark = pytest.mark.needs_db

_AGORA = datetime(2026, 12, 1, 0, 30, tzinfo=BRT)
_VALOR = 800


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


@pytest.fixture(autouse=True)
def _sem_output_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """O output-guard chama o LLM-judge de AUP (crédito real, §0) e, sem chave, bloqueia+escala
    por default seguro — pausaria a IA e mataria os turnos seguintes."""
    monkeypatch.setattr(get_settings(), "output_guard_habilitado", False)


async def _cenario(
    conn: AsyncConnection[dict[str, Any]],
    *,
    historico: list[dict[str, str]] | None = None,
) -> Any:
    """Atendimento QUALIFICADO com o preço cotado e o aceite JÁ marcado — o estado em que os dez
    atendimentos auditados estavam quando o cliente recuou."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Lia"},
                "atendimento": {
                    "estado": "Qualificado",
                    "tipo_atendimento": "interno",
                    "cotacao_enviada": True,
                },
            },
            "historico": historico or [],
        },
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = %s, duracao_horas = 1, "
        "sinais_qualificacao = '{\"aceita_valor\": true}'::jsonb WHERE id = %s",
        (_VALOR, cen.atendimento_id),
    )
    return cen


async def _aceite_e_valor(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: Any
) -> tuple[Any, Any]:
    res = await conn.execute(
        "SELECT sinais_qualificacao->'aceita_valor' AS aceite, valor_acordado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row["aceite"], row["valor_acordado"]


def _chat(*falas: str) -> ChatRoteirizado:
    """Extrator MUDO sobre o aceite: nenhum roteiro repete o sinal no turno do recuo — é assim que
    o dado real se comporta (`limpar`: 2 usos em 531 extrações), e é o que o rebaixamento tem que
    atravessar."""
    return ChatRoteirizado(
        list(falas), [{"proxima_acao_esperada": "esperar ele decidir"} for _ in falas]
    )


async def _rodar(
    conn: AsyncConnection[dict[str, Any]], cen: Any, texto: str, chat: ChatRoteirizado
) -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, texto, graph=build_graph(), agora=_AGORA)


# --- rebaixam ---------------------------------------------------------------------------------


async def test_19_negativa_apos_pedido_de_confirmacao_rebaixa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#19: a IA pediu "Podemos confirmar 18h ?" e ele respondeu "Não" — e o atendimento seguiu com
    o preço marcado como aceito, o que faz o contexto mandar não re-cotar nem renegociar."""
    cen = await _cenario(
        conn,
        historico=[
            {"direcao": "cliente", "texto": "Hummm"},
            {"direcao": "ia", "texto": "Podemos confirmar 18h ?"},
        ],
    )

    await _rodar(conn, cen, "Não", _chat("Sem problema amor, me avisa 🥰"))

    aceite, valor = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is False
    assert valor == _VALOR  # o rebaixamento não toca o valor cotado


async def test_20_adiamento_para_o_comeco_do_mes_rebaixa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#20: "Quero muito ir mas... tenho que esperar começo do mês" — adiou, não aceitou."""
    cen = await _cenario(conn)

    await _rodar(
        conn,
        cen,
        "Quero muito ir mas... tenho que esperar começo do mês",
        _chat("Tranquilo amor, me chama quando puder 🥰"),
    )

    aceite, _ = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is False


async def test_27_hoje_nao_consigo_rebaixa(conn: AsyncConnection[dict[str, Any]]) -> None:
    """#27: "Hoje não consigo, te mando msg mais pra frente"."""
    cen = await _cenario(conn)

    await _rodar(
        conn, cen, "Hoje não consigo, te mando msg mais pra frente", _chat("Tranquilo amor 🥰")
    )

    aceite, _ = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is False


async def test_recuo_vence_o_aceite_marcado_no_mesmo_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Precedência: o extrator remarca o aceite no MESMO turno em que o cliente recua — e o recuo
    vence. Falso positivo do detector só reabre a escada do desconto; aceite falso trava a venda."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Tranquilo amor 🥰"],
        [
            {
                "sinais_qualificacao": {"aceita_valor": True},
                "proxima_acao_esperada": "esperar ele decidir",
            }
        ],
    )

    await _rodar(conn, cen, "hoje não consigo", chat)

    aceite, _ = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is False


# --- preservam --------------------------------------------------------------------------------


async def test_34_vou_te_avisando_preserva_o_aceite(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#34, o único aceite verdadeiro do corpus auditado: quem diz "vou te avisando" já quer, só
    não manda no relógio — horário e valor seguem de pé. É o teste que pega a armadilha."""
    cen = await _cenario(conn, historico=[{"direcao": "ia", "texto": "Posso confirmar às 18h ?"}])

    await _rodar(conn, cen, "Perfeito, vou te avisando então", _chat("Te espero amor 🥰"))

    aceite, _ = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is True


async def test_24_negativa_ambigua_nao_rebaixa(conn: AsyncConnection[dict[str, Any]]) -> None:
    """#24: "Não conheço" respondendo a "Campinas ?" — negativa sem correferência de fechamento,
    não rebaixa por si só."""
    cen = await _cenario(conn, historico=[{"direcao": "ia", "texto": "Campinas ?"}])

    await _rodar(conn, cen, "Não conheço", _chat("Fica no Cambuí amor 🥰"))

    aceite, _ = await _aceite_e_valor(conn, cen.atendimento_id)
    assert aceite is True


# --- o efeito na conversa ---------------------------------------------------------------------


async def test_depois_do_recuo_o_belief_volta_a_apresentar_o_valor_como_cotado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O efeito visível do rebaixamento: no turno seguinte o contexto deixa de dizer "valor já
    combinado: não re-cote nem renegocie" e volta a dizer que ele ainda não aceitou — que é o que
    mantém a escada do <desconto> disponível."""
    cen = await _cenario(
        conn,
        historico=[
            {"direcao": "cliente", "texto": "Hummm"},
            {"direcao": "ia", "texto": "Podemos confirmar 18h ?"},
        ],
    )
    chat = _chat("Sem problema amor 🥰", "Consigo 700 se você vier hoje 😊")

    await _rodar(conn, cen, "Não", chat)
    await _rodar(conn, cen, "tá caro pra mim", chat)

    contexto = chat.contexto_do_ultimo_turno()
    assert "<valor_cotado>" in contexto
    assert "<valor_fechado>" not in contexto
