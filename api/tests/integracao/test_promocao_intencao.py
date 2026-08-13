"""Promoção Triagem → Qualificado por EVIDÊNCIA, não por julgamento do extrator
(spec `.scratch/extracao-promocao-intencao/spec.md`).

Casos REAIS do piloto, pelo caminho de produção (harness fiel: `processar_turno` → `enviar_turno`)
com o GRAFO REAL e o chat do LLM substituído por um fake roteirizado — determinístico e SEM
consumir crédito (§0). Em TODOS os cenários o extrator julga a intenção ABAIXO de agendamento
(`cotacao`), que é o erro sistemático medido em produção; quem decide é o horário evidenciado.

O teste afirma em que ESTADO o Atendimento fica e o que a IA passa a ter no contexto — nunca como
a intenção foi derivada:

  - #34 "Tipo 18h, 18h15"            -> promove, e o ponto de encontro entra no contexto seguinte
  - #24 "Umas 16 horas"              -> promove
  - #35 sondagem "seria agora ?" aceita -> promove, apesar de o número vir do fallback
  - marca já persistida (painel)     -> promove no turno seguinte, sem fala nova de hora
  - #25 sondagem ignorada            -> permanece em Triagem, com o horário gravado
  - #19 "Não" após "Podemos confirmar 18h ?" -> permanece em Triagem
  - cascata externa                  -> Aguardando_confirmacao + Pix pedido UMA vez
  - cascata sem cotação              -> barrada pelo guard, sem reserva nem Pix

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

# Relógio do turno (clock injection): 00:30, com o dia inteiro livre à frente — todos os horários
# dos cenários (16:00, 18:00) caem no futuro, então a reserva do slot não esbarra em antecedência
# mínima nem em bloqueio (a modelo seedada não tem regra de Disponibilidade).
_AGORA = datetime(2026, 12, 1, 0, 30, tzinfo=BRT)
_HOJE = "2026-12-01"
_ENDERECO = "Hotel Boutique Aurora, Rua das Palmeiras"


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


async def _cenario(
    conn: AsyncConnection[dict[str, Any]],
    *,
    historico: list[dict[str, str]] | None = None,
    **atendimento: Any,
) -> Any:
    """Atendimento em TRIAGEM (o estado de onde a promoção parte), com a cotação já apresentada —
    sem ela o guard de cotação ausente barra a reserva antes de a cascata chegar ao fim."""
    return await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Lia", "endereco_formatado": _ENDERECO},
                "atendimento": {
                    "estado": "Triagem",
                    "tipo_atendimento": "interno",
                    "cotacao_enviada": True,
                }
                | atendimento,
            },
            "historico": historico or [],
        },
        # MESMO relogio dos turnos: sem isto o historico nasce no `now()` do banco enquanto o turno
        # "acontece" em `_AGORA`, e o agente le a diferenca como tempo decorrido (acima de 6h, como
        # uma marca de pausa no meio de uma conversa que nunca parou).
        agora=_AGORA,
    )


async def _estado(conn: AsyncConnection[dict[str, Any]], atendimento_id: Any) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT estado::text AS estado, intencao::text AS intencao, horario_desejado, "
        "horario_evidenciado, bloqueio_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _n_eventos(conn: AsyncConnection[dict[str, Any]], atendimento_id: Any, tipo: str) -> int:
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s",
        (atendimento_id, tipo),
    )
    row = await res.fetchone()
    assert row is not None
    return int(row["n"])


# --- promovem ---------------------------------------------------------------------------------


async def test_34_horario_combinado_promove_e_libera_o_ponto_de_encontro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#34 é o retrato do defeito: tipo interno, 18:00 combinado, aceite real — e ficou em Triagem
    porque a intenção permaneceu `cotacao`. Com a promoção por evidência ele sai de Triagem, e o
    ponto de encontro (liberado a partir de Qualificado) entra no contexto do turno seguinte — é o
    dado que faltava quando a IA respondeu "onde é?" com um bairro inventado (#27)."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Posso confirmar às 18h amor 🥰", "Te mando o endereço amor 🥰"],
        [
            {
                "intencao": "cotacao",  # o extrator errando para baixo, como em produção
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
        depois = await _estado(conn, cen.atendimento_id)
        await rodar_turno_fiel(conn, cen, "onde você fica?", graph=graph, agora=_AGORA)

    assert depois["estado"] != "Triagem"
    assert depois["intencao"] == "agendamento"
    assert depois["bloqueio_id"] is not None  # o slot foi reservado
    contexto = chat.contexto_do_ultimo_turno()
    assert "<local_de_encontro>" in contexto
    assert _ENDERECO in contexto


async def test_24_hora_explicita_promove(conn: AsyncConnection[dict[str, Any]]) -> None:
    """#24: "Umas 16 horas" — hora explícita do cliente, intenção julgada `cotacao`."""
    cen = await _cenario(conn)
    chat = ChatRoteirizado(
        ["Fechou amor, 16h 🥰"],
        [
            {
                "intencao": "cotacao",
                "horario_desejado": "16:00",
                "data_desejada": _HOJE,
                "proxima_acao_esperada": "confirmar o horario",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "Umas 16 horas", graph=build_graph(), agora=_AGORA)

    depois = await _estado(conn, cen.atendimento_id)
    assert depois["estado"] != "Triagem"
    assert depois["intencao"] == "agendamento"


async def test_35_sondagem_de_imediatismo_aceita_promove(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#35: a IA sondou "Seria agora ?" e ele respondeu "sim". O número vem do fallback de tempo
    imediato, mas a evidência é dele — este é o caso que o piso pontual do nó `extrair` cobria
    sozinho e que agora entra pela mesma porta de todos os outros."""
    cen = await _cenario(
        conn,
        historico=[
            {"direcao": "cliente", "texto": "oi, tudo bem?"},
            {"direcao": "ia", "texto": "Oii amor 🥰 Seria agora ?"},
        ],
    )
    chat = ChatRoteirizado(
        ["Que delícia, te espero 🥰"],
        [
            {
                "intencao": "cotacao",
                "urgencia": "imediato",
                "proxima_acao_esperada": "confirmar a saida dele",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "sim", graph=build_graph(), agora=_AGORA)

    depois = await _estado(conn, cen.atendimento_id)
    assert depois["horario_desejado"] is not None  # fallback gravou o horario_minimo
    assert depois["estado"] != "Triagem"
    assert depois["intencao"] == "agendamento"


async def test_marca_ja_persistida_promove_no_turno_seguinte(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A evidência não precisa ser deste turno: o predicado lê a MARCA. Aqui ela veio de fora da
    conversa — o operador editou o horário no painel, que carimba evidência (fonte forte) — e o
    Atendimento seguia em Triagem. O turno seguinte, sem nenhuma fala de hora, já promove."""
    cen = await _cenario(conn)
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_desejado = %s, horario_evidenciado = true "
        "WHERE id = %s",
        (time(18, 0), cen.atendimento_id),
    )
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [{"intencao": "cotacao", "data_desejada": _HOJE, "proxima_acao_esperada": "esperar ele"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "vc faz massagem?", graph=build_graph(), agora=_AGORA)

    depois = await _estado(conn, cen.atendimento_id)
    assert depois["horario_desejado"] == time(18, 0)
    assert depois["estado"] != "Triagem"
    assert depois["intencao"] == "agendamento"


# --- permanecem em Triagem --------------------------------------------------------------------


async def test_25_horario_sem_evidencia_permanece_em_triagem(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#25: a IA sondou "Seria agora ?", o cliente ignorou e mudou de assunto. O fallback grava o
    horário (a agenda precisa de um número), mas ninguém o sustentou — sem a marca de evidência a
    promoção não ocorre e o palpite do sistema NÃO vira reserva."""
    cen = await _cenario(
        conn,
        historico=[
            {"direcao": "cliente", "texto": "oi"},
            {"direcao": "ia", "texto": "Oii amor 🥰 Seria agora ?"},
        ],
    )
    chat = ChatRoteirizado(
        ["Faço sim amor 🥰"],
        [
            {
                "intencao": "cotacao",
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

    depois = await _estado(conn, cen.atendimento_id)
    assert depois["horario_desejado"] is not None  # o horário é gravado do mesmo jeito
    assert depois["horario_evidenciado"] is False
    assert depois["estado"] == "Triagem"
    assert depois["bloqueio_id"] is None  # nenhuma reserva sobre um palpite


async def test_19_recuo_sem_horario_permanece_em_triagem(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#19: a IA pediu "Podemos confirmar 18h ?" e ele respondeu "Não". Uma negativa não é
    confirmação curta: não há evidência, não há horário e o Atendimento não avança."""
    cen = await _cenario(
        conn,
        historico=[
            {"direcao": "cliente", "texto": "Hummm"},
            {"direcao": "ia", "texto": "Podemos confirmar 18h ?"},
        ],
    )
    chat = ChatRoteirizado(
        ["Sem problema amor, me avisa 🥰"],
        [{"intencao": "cotacao", "proxima_acao_esperada": "esperar ele decidir"}],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        await rodar_turno_fiel(conn, cen, "Não", graph=build_graph(), agora=_AGORA)

    depois = await _estado(conn, cen.atendimento_id)
    assert depois["estado"] == "Triagem"
    assert depois["horario_desejado"] is None
    assert depois["horario_evidenciado"] is False


# --- cascata do externo (o efeito assumido: dinheiro pedido mais cedo) -------------------------


async def test_cascata_externa_pede_pix_uma_unica_vez(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Externo com cotação enviada, horário evidenciado e tipo percorre Triagem → Qualificado →
    Aguardando_confirmacao no mesmo turno e dispara a solicitação determinística de Pix de
    deslocamento. O turno seguinte NÃO re-pede: o guard `pix_status='nao_solicitado'` mantém a
    cobrança única."""
    cen = await _cenario(conn, tipo_atendimento="externo")
    chat = ChatRoteirizado(
        ["Fechou amor, 16h 🥰", "Te espero 🥰"],
        [
            {
                "intencao": "cotacao",
                "horario_desejado": "16:00",
                "data_desejada": _HOJE,
                "proxima_acao_esperada": "aguardar o pix",
            },
            {"proxima_acao_esperada": "aguardar o pix"},
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        graph = build_graph()
        primeiro = await rodar_turno_fiel(conn, cen, "Umas 16 horas", graph=graph, agora=_AGORA)
        await rodar_turno_fiel(conn, cen, "beleza", graph=graph, agora=_AGORA)

    assert primeiro.estado == "Aguardando_confirmacao"
    assert primeiro.pix_status == "aguardando"
    depois = await _estado(conn, cen.atendimento_id)
    assert depois["bloqueio_id"] is not None
    assert await _n_eventos(conn, cen.atendimento_id, "pix_solicitado") == 1


async def test_cascata_sem_cotacao_continua_barrada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesma cascata sem o preço nunca dito: o guard de cotação ausente barra a reserva (a
    transação reverte), então não há bloqueio, não há Pix e o estado não avança. A promoção por
    evidência não abre caminho novo para combinar encontro sem cotar."""
    cen = await _cenario(conn, tipo_atendimento="externo", cotacao_enviada=False)
    chat = ChatRoteirizado(
        ["Fechou amor, 16h 🥰"],
        [
            {
                "intencao": "cotacao",
                "horario_desejado": "16:00",
                "data_desejada": _HOJE,
                "proxima_acao_esperada": "aguardar o pix",
            }
        ],
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("barra.agente.graph.criar_chat_deepseek", lambda settings, **_kw: chat)
        resultado = await rodar_turno_fiel(
            conn, cen, "Umas 16 horas", graph=build_graph(), agora=_AGORA
        )

    assert resultado.estado == "Triagem"
    assert resultado.pix_status == "nao_solicitado"
    depois = await _estado(conn, cen.atendimento_id)
    assert depois["bloqueio_id"] is None
    assert await _n_eventos(conn, cen.atendimento_id, "pix_solicitado") == 0
