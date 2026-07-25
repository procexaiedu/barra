"""Proveniência do horário: o Atendimento distingue horário que o cliente sustentou de palpite
do sistema (spec `.scratch/extracao-proveniencia-horario/spec.md`).

Casos REAIS do piloto, pelo caminho de produção (harness fiel: `processar_turno` → `enviar_turno`)
com o GRAFO REAL e o chat do LLM substituído por um fake roteirizado — determinístico e SEM
consumir crédito (§0). O teste afirma o que o Atendimento passa a valer depois do turno, nunca a
mecânica interna:

  - #34 "Tipo 18h, 18h15" + "Perfeito"      -> evidenciado
  - #24 "Umas 16 horas"                     -> evidenciado
  - #35 sondagem "seria agora ?" aceita     -> evidenciado, mesmo com o número vindo do fallback
  - #25 sondagem ignorada                   -> NÃO evidenciado, com o horário mesmo assim gravado
  - promoção tardia (a partir do #25)       -> "pode ser 2h então" sobe a marca sem o valor mudar

DB real (TEST_DATABASE_URL), ROLLBACK no teardown. `needs_db`, SEM `needs_key`.
"""

import os
from collections.abc import AsyncIterator
from datetime import datetime, time
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

# Relógio do turno (clock injection): 00:30, com o dia inteiro livre à frente — TODOS os horários
# dos cenários (02:00, 16:00, 18:00) caem no futuro, então a reserva do slot não esbarra em
# antecedência mínima nem em bloqueio (a modelo seedada não tem regra de Disponibilidade).
_AGORA = datetime(2026, 12, 1, 0, 30, tzinfo=BRT)
_HOJE = "2026-12-01"


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
    por default seguro — pausaria a IA e mataria os turnos seguintes. Fora do escopo deste teste,
    que afirma o estado do Atendimento depois da extração."""
    monkeypatch.setattr(get_settings(), "output_guard_habilitado", False)


async def _marca(conn: AsyncConnection[dict[str, Any]], atendimento_id: Any) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT horario_desejado, horario_evidenciado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _cenario(conn: AsyncConnection[dict[str, Any]], **atendimento: Any) -> Any:
    return await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Lia"},
                "atendimento": {
                    "estado": "Qualificado",
                    "tipo_atendimento": "interno",
                    # Cotação já apresentada: sem ela a extração recusa cravar horário (ADR 0022,
                    # "não pode combinar o horário sem ter dito o preço") e o turno cai na reoferta.
                    "cotacao_enviada": True,
                }
                | atendimento,
            }
        },
    )


# --- casos de produção -----------------------------------------------------------------------


async def test_34_hora_explicita_e_confirmacao_evidenciam(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#34: o cliente dá a hora ("Tipo 18h, 18h15"), a IA confirma e ele fecha ("Perfeito") — o
    horário é dele do começo ao fim e a marca não cai no turno da confirmação."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Posso confirmar às 18h amor 🥰", "Perfeito, te espero 🥰"],
        [
            {
                "intencao": "agendamento",
                "horario_desejado": "18:00",
                "data_desejada": _HOJE,
                "proxima_acao_esperada": "confirmar o horario",
            },
            {"proxima_acao_esperada": "esperar ele chegar"},
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        graph = build_graph()
        await rodar_turno_fiel(conn, cen, "Tipo 18h, 18h15", graph=graph, agora=_AGORA)
        depois_da_hora = await _marca(conn, cen.atendimento_id)
        await rodar_turno_fiel(conn, cen, "Perfeito", graph=graph, agora=_AGORA)

    assert depois_da_hora["horario_evidenciado"] is True
    final = await _marca(conn, cen.atendimento_id)
    assert final["horario_desejado"] == time(18, 0)
    assert final["horario_evidenciado"] is True


async def test_24_hora_explicita_do_cliente_evidencia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#24: "Umas 16 horas" — hora explícita numa fala do cliente."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Fechou amor, 16h 🥰"],
        [
            {
                "intencao": "agendamento",
                "horario_desejado": "16:00",
                "data_desejada": _HOJE,
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "Umas 16 horas", graph=build_graph(), agora=_AGORA)

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] == time(16, 0)
    assert marca["horario_evidenciado"] is True


async def test_35_sondagem_aceita_evidencia_horario_sintetico(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#35: o número vem do fallback de tempo imediato (`horario_minimo`), mas a intenção é dele —
    a IA sondou "Seria agora ?" e ele respondeu "sim". Evidenciado apesar do número sintético."""
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
            "historico": [
                {"direcao": "cliente", "texto": "oi, tudo bem?"},
                {"direcao": "ia", "texto": "Oii amor 🥰 Seria agora ?"},
            ],
        },
    )
    chat = ChatRoteirizado(
        ["Que delícia, te espero 🥰"],
        [
            {
                "intencao": "agendamento",
                "urgencia": "imediato",
                "proxima_acao_esperada": "confirmar a saida dele",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "sim", graph=build_graph(), agora=_AGORA)

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] is not None  # fallback gravou o horario_minimo
    assert marca["horario_evidenciado"] is True


async def test_25_sondagem_ignorada_grava_horario_sem_evidencia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#25 (23/07): a IA sondou "Seria agora ?", o cliente ignorou e mudou de assunto. O fallback
    grava o horário (a agenda precisa de um número), mas ele NÃO é evidenciado — era exatamente
    este palpite que a IA passou a exibir como "pedido dele"."""
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
            "historico": [
                {"direcao": "cliente", "texto": "oi"},
                {"direcao": "ia", "texto": "Oii amor 🥰 Seria agora ?"},
            ],
        },
    )
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [
            {
                "intencao": "agendamento",
                "urgencia": "imediato",
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(
            conn, cen, "vc faz oral sem camisinha?", graph=build_graph(), agora=_AGORA
        )

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] is not None  # o horário é gravado do mesmo jeito
    assert marca["horario_evidenciado"] is False


async def test_promocao_tardia_sobe_a_marca_sem_o_valor_mudar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Partindo do estado do #25 (02:00 gravado, sem evidência): o cliente confirma depois o
    palpite do sistema — "pode ser 2h então" — e a marca sobe COM O MESMO VALOR. É o caso que a
    versão ingênua ("sticky por valor") perderia."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos "
        "SET horario_desejado = %s, data_desejada = %s, horario_evidenciado = false WHERE id = %s",
        (time(2, 0), _AGORA.date(), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Combinado então amor 🥰"],
        [
            {
                "intencao": "agendamento",
                "horario_desejado": "02:00",
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "pode ser 2h então", graph=build_graph(), agora=_AGORA)

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] == time(2, 0)  # valor inalterado
    assert marca["horario_evidenciado"] is True


async def test_eco_do_belief_nao_derruba_nem_valida_a_marca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O eco (o extrator relê o horário do belief e o devolve como observação nova) regrava o MESMO
    valor num turno sem fala de hora: regravar o mesmo número não é mudança, então a marca fica
    como está — nem cai (o valor não mudou) nem sobe (o eco não se auto-valida)."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos "
        "SET horario_desejado = %s, data_desejada = %s, horario_evidenciado = true WHERE id = %s",
        (time(16, 0), _AGORA.date(), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [
            {
                "intencao": "agendamento",
                "horario_desejado": "16:00",  # eco do belief, não observação nova
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "vc faz massagem?", graph=build_graph(), agora=_AGORA)

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] == time(16, 0)
    assert marca["horario_evidenciado"] is True  # preservada: o valor não mudou


async def test_valor_novo_sem_evidencia_derruba_a_marca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Outro ramo da transição: o horário MUDA num turno sem fala do cliente que o sustente (aqui,
    o extrator troca o número sozinho) — a marca cai, porque a evidência antiga era do valor
    antigo."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos "
        "SET horario_desejado = %s, data_desejada = %s, horario_evidenciado = true WHERE id = %s",
        (time(16, 0), _AGORA.date(), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Te espero 🥰"],
        [
            {
                "intencao": "agendamento",
                "horario_desejado": "20:00",  # número novo, sem ninguém ter pedido
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "vc faz massagem?", graph=build_graph(), agora=_AGORA)

    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] == time(20, 0)
    assert marca["horario_evidenciado"] is False


async def test_horario_editado_no_painel_nasce_evidenciado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Operador é fonte forte (ele combinou por fora): o PATCH /dados do painel deixa o atendimento
    com o horário dele E evidenciado, mesmo partindo de um palpite do sistema. Editar OUTRO campo
    não carimba nada — validaria um palpite que ninguém confirmou."""
    from fastapi.testclient import TestClient

    from barra.api.deps import get_conn
    from barra.main import app

    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_desejado = %s, horario_evidenciado = false "
        "WHERE id = %s",
        (time(2, 0), cen.atendimento_id),
    )

    async def _conn_de_teste() -> Any:
        yield conn

    def _editar(client: TestClient, corpo: dict[str, Any]) -> None:
        resp = client.patch(
            f"/v1/atendimentos/{cen.atendimento_id}/dados",
            json=corpo,
            headers={
                "Authorization": "Bearer test:00000000-0000-0000-0000-000000000001:fernando:true"
            },
        )
        assert resp.status_code == 200, resp.text

    app.dependency_overrides[get_conn] = _conn_de_teste
    try:
        with TestClient(app) as client:
            _editar(client, {"bairro": "Cambuí"})
            marca_outro_campo = await _marca(conn, cen.atendimento_id)
            _editar(client, {"horario_desejado": "18:00:00"})
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert marca_outro_campo["horario_evidenciado"] is False  # editar bairro não valida horário
    marca = await _marca(conn, cen.atendimento_id)
    assert marca["horario_desejado"] == time(18, 0)
    assert marca["horario_evidenciado"] is True
