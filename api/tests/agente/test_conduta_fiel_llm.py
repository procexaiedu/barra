"""Conduta ponta-a-ponta com o LLM REAL pelo caminho fiel (a prova final do epico harness fiel).

Os outros testes do harness fiel injetam um graph FAKE — provam o encanamento (lock/drain/envio/
clock), nao a IA. Aqui rodamos `rodar_turno_fiel` SEM graph: ele constroi o `build_graph()` real,
que chama o DeepSeek V4 Flash de prod. Junta tudo o que so o caminho de prod exercita: prepare_
context (janela + clock injetado) -> graph real -> enviar_turno (output-guard + grava a bolha da IA).

Como a temp e 1.3 (mantida de proposito, fidelidade por judge), o TEXTO varia entre execucoes —
entao asserimos CONDUTA/MECANICA estavel, nunca uma frase: a IA respondeu, a resposta saiu pelo
caminho real e foi persistida (anti-amnesia), e a temperatura efetiva e a de prod.

⚠️ §0: gasta credito LLM real (DeepSeek). needs_key (opt-in RUN_LLM_TESTS) + needs_db
(TEST_DATABASE_URL; seed + ROLLBACK, nada commita).
"""

import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from evals.harness import seedar
from evals.harness_fiel import rodar_turno_fiel
from psycopg import AsyncConnection
from psycopg.rows import dict_row

pytestmark = [pytest.mark.needs_db, pytest.mark.needs_key]

_BRT = ZoneInfo("America/Sao_Paulo")


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


async def test_agente_real_responde_pelo_caminho_fiel(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O agente REAL conduz um primeiro contato pelo MESMO caminho do WhatsApp: o DeepSeek responde,
    a bolha sai pelo spy (passou por processar_turno + enviar_turno) e e gravada como direcao='ia'
    (fecha o loop multi-turno). Clock injetado -> determinismo de agenda. Conduta, nao frase."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )
    agora = datetime(2026, 3, 16, 15, 0, tzinfo=_BRT)  # segunda 15h, dentro de qualquer expediente

    res = await rodar_turno_fiel(conn, cen, "oi, tudo bem? vc ta atendendo hoje?", agora=agora)

    # a IA respondeu de fato (texto nao vazio) e saiu UMA entrega pelo caminho real
    assert res.resposta.strip(), "a IA real nao produziu texto"
    assert res.n_jobs_envio >= 1
    assert "composing" in res.presencas  # enviar_turno rodou (humanizacao), nao foi pulado
    # nao vazou andaime interno (spotlight/cerca de DADO) pro cliente
    assert "DADO do cliente" not in res.resposta
    # a temperatura efetiva e a de prod (1.3), nao foi achatada pra determinismo
    assert res.flags["chat_temperature"] == 1.3

    # resposta persistida como direcao='ia' — sem isso o proximo turno correria amnesico
    r = await conn.execute(
        "SELECT conteudo FROM barravips.mensagens "
        "WHERE conversa_id = %s AND direcao = 'ia' ORDER BY created_at DESC LIMIT 1",
        (cen.conversa_id,),
    )
    ia = await r.fetchone()
    assert ia is not None and ia["conteudo"].strip()
    # o que saiu no spy e o que foi gravado sao a MESMA resposta (caminho unico)
    assert ia["conteudo"] in res.resposta
