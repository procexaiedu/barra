"""Bancada offline: a reconstrução da entrada e a trajetória, contra o Postgres real.

Duas afirmações que só o banco sustenta:

  - reconstrução — dado um Atendimento com histórico conhecido, o replay dos payloads reproduz a
    tripla que o extrator leu em cada turno (conversa até o instante, snapshot no instante, agora),
    e o snapshot vem dos payloads em ordem, NUNCA do estado atual do Atendimento;
  - trajetória — o extrator rodado turno a turno move o Atendimento pela FSM de verdade
    (`registrar_extracao_ia`), e a sequência de estados é o que se compara com a rotulada.

DB real (TEST_DATABASE_URL), ROLLBACK no teardown. `needs_db`, SEM `needs_key` (o extrator é fake).
"""

import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from evals.extracao.extrator import VARIANTES, ExtratorGravado, ExtratorRoteirizado
from evals.extracao.golden import Fala, ItemGolden, carregar_golden
from evals.extracao.janela import CAMPOS_SNAPSHOT, aplicar_payload, detectores_do_turno
from evals.extracao.replay import reconstruir_turnos, rodar_trajetoria
from evals.harness import seedar
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.agenda.service import BRT
from barra.dominio.atendimentos.service import registrar_extracao_ia

pytestmark = pytest.mark.needs_db

_T0 = datetime(2026, 12, 1, 14, 0, tzinfo=BRT)


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


async def _msg(
    conn: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    direcao: str,
    texto: str,
    quando: datetime,
) -> None:
    """Mensagem com `created_at` EXPLÍCITO: o corte por instante é o que separa os turnos (todas as
    linhas de uma mesma transação empatam no `now()` default)."""
    await conn.execute(
        "INSERT INTO barravips.mensagens (conversa_id, direcao, tipo, conteudo, "
        "evolution_message_id, created_at) VALUES (%s, %s::barravips.direcao_mensagem_enum, "
        "'texto', %s, %s, %s)",
        (conversa_id, direcao, texto, f"test-evo-{quando.isoformat()}", quando),
    )


async def _extracao(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
    payload: dict[str, Any],
    quando: datetime,
) -> None:
    """Evento `extracao_registrada` como o domínio o grava — é a fonte do replay."""

    await conn.execute(
        "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload, created_at) "
        "VALUES (%s, 'extracao_registrada', 'agente', 'IA', %s::jsonb, %s)",
        (atendimento_id, json.dumps(payload), quando),
    )


async def test_reconstrucao_reproduz_a_entrada_de_cada_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    cen = await seedar(
        conn,
        {
            "cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Novo"}},
            "historico": [],
        },
    )
    await _msg(
        conn, cen.conversa_id, "cliente", "Você tem horário amanhã?", _T0 - timedelta(minutes=1)
    )
    await _extracao(conn, cen.atendimento_id, {"intencao": "cotacao"}, _T0)
    await _msg(conn, cen.conversa_id, "ia", "Consigo às 17:30", _T0 + timedelta(minutes=1))
    await _msg(
        conn, cen.conversa_id, "cliente", "Perfeito, pode ser 18h", _T0 + timedelta(minutes=5)
    )
    await _extracao(
        conn,
        cen.atendimento_id,
        {"intencao": "agendamento", "tipo_atendimento": "interno", "horario_desejado": "18:00"},
        _T0 + timedelta(minutes=6),
    )
    await _msg(conn, cen.conversa_id, "ia", "Fechado", _T0 + timedelta(minutes=7))
    # 3ª extração: reenvia o que já estava gravado, sem nada novo na conversa (o eco do piloto).
    await _extracao(
        conn, cen.atendimento_id, {"tipo_atendimento": "interno"}, _T0 + timedelta(minutes=10)
    )

    turnos = await reconstruir_turnos(conn, cen.atendimento_id)

    assert [t.ordem for t in turnos] == [1, 2, 3]
    # 1º turno: só a fala do cliente que já existia; snapshot vazio; relógio = o instante do turno.
    assert [(f.de, f.texto) for f in turnos[0].conversa] == [
        ("cliente", "Você tem horário amanhã?")
    ]
    assert turnos[0].registrado == {}
    assert turnos[0].agora == _T0
    # 2º turno: a conversa até ali (a fala da IA do 1º turno já entrou) e o snapshot INTERMEDIÁRIO,
    # vindo do payload anterior — não do estado final.
    assert [f.de for f in turnos[1].conversa] == ["cliente", "ia", "cliente"]
    assert turnos[1].registrado == {"intencao": "cotacao"}
    assert turnos[1].gravado["horario_desejado"] == "18:00"
    # 3º turno: o snapshot já carrega o que o 2º gravou, com a marca de evidência do horário.
    assert turnos[2].registrado["tipo_atendimento"] == "interno"
    assert turnos[2].registrado["horario_desejado"] == "18:00"
    assert turnos[2].registrado["horario_evidenciado"] is True
    # decisivo = um campo apareceu ou mudou; o eco não é decisivo.
    assert [t.decisivo for t in turnos] == [True, True, False]

    # E o Atendimento em si nunca foi tocado: a reconstrução lê histórico, não o estado atual.
    res = await conn.execute(
        "SELECT estado::text AS estado, intencao::text AS intencao FROM barravips.atendimentos "
        "WHERE id = %s",
        (cen.atendimento_id,),
    )
    linha = await res.fetchone()
    assert linha is not None and linha["estado"] == "Novo" and linha["intencao"] is None


async def test_snapshot_reconstruido_bate_com_o_que_o_dominio_grava(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O snapshot do replay é um ESPELHO do UPSERT do domínio — este teste é o que o amarra.

    Sem ele o espelho envelhece em silêncio e a bancada passa a medir o extrator contra um bloco
    `<ja_registrado>` que produção nunca mostrou. Os três turnos cobrem o que já divergiu: aceite
    explícito, recuo rebaixando o aceite e a promoção da intenção por evidência de horário.
    """
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {
                    "nome": "Lia",
                    "programas": [
                        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400}
                    ],
                },
                "atendimento": {"estado": "Novo", "cotacao_enviada": True},
            },
            "historico": [],
        },
    )
    turnos: list[tuple[list[Fala], dict[str, Any]]] = [
        (
            [Fala("cliente", "fechou, pode ser")],
            {
                "intencao": "cotacao",
                "tipo_atendimento": "interno",
                "valor_acordado": "400",
                "duracao_horas": "1",
                "sinais_qualificacao": {"aceita_valor": True},
            },
        ),
        ([Fala("cliente", "Hoje não consigo, te mando msg mais pra frente")], {}),
        (
            [Fala("ia", "Posso confirmar às 18h"), Fala("cliente", "Perfeito")],
            {"data_desejada": "2026-12-01", "horario_desejado": "18:00"},
        ),
    ]

    snapshot: dict[str, Any] = {}
    for ordem, (conversa, payload) in enumerate(turnos, start=1):
        item = ItemGolden(
            id=f"t{ordem}",
            atendimento=0,
            descricao="",
            agora=_T0,
            conversa=conversa,
            registrado=snapshot,
            gravado=payload,
            rotulo={},
        )
        evidenciado, recuo = detectores_do_turno(item)
        snapshot = aplicar_payload(snapshot, payload, horario_evidenciado=evidenciado, recuo=recuo)
        async with conn.transaction():
            await registrar_extracao_ia(
                conn,
                str(cen.atendimento_id),
                dict(payload),
                agora=_T0,
                horario_evidenciado=evidenciado,
                recuo_detectado=recuo,
            )
        assert _comparavel(await _atendimento(conn, cen.atendimento_id)) == _comparavel(snapshot), (
            f"snapshot divergiu do domínio no turno {ordem}"
        )

    # E o replay chegou onde a rotulagem espera: aceite rebaixado pelo recuo, intenção promovida.
    assert snapshot["aceita_valor"] is False
    assert snapshot["horario_evidenciado"] is True
    assert snapshot["intencao"] == "agendamento"


async def _atendimento(
    conn: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT intencao::text AS intencao, urgencia::text AS urgencia, "
        "tipo_atendimento::text AS tipo_atendimento, data_desejada, horario_desejado, "
        "horario_evidenciado, endereco, bairro, valor_acordado, duracao_horas, "
        "sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    linha = await res.fetchone()
    assert linha is not None
    return {
        **dict(linha),
        "aceita_valor": bool((linha["sinais_qualificacao"] or {}).get("aceita_valor")),
    }


def _comparavel(origem: dict[str, Any]) -> dict[str, str | None]:
    """Os campos do bloco `<ja_registrado>` na mesma forma dos dois lados: o banco devolve
    date/time/Decimal, o snapshot devolve as strings do payload."""

    def _norm(campo: str, valor: Any) -> str | None:
        if campo in ("horario_evidenciado", "aceita_valor"):
            return str(bool(valor))  # ausente no snapshot = false no banco (default da coluna)
        if valor is None or valor == "":
            return None
        if campo in ("valor_acordado", "duracao_horas"):
            return format(Decimal(str(valor)).normalize(), "f")
        if campo == "horario_desejado":
            return str(valor)[:5]  # "18:00:00" (banco) e "18:00" (payload) são o mesmo horário
        return str(valor)

    return {campo: _norm(campo, origem.get(campo)) for campo in CAMPOS_SNAPSHOT}


async def test_trajetoria_mede_o_funil_pela_fsm_de_verdade(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Com o payload que a rotulagem espera, o Atendimento percorre a trajetória rotulada."""
    trajetoria = carregar_golden().trajetorias[0]

    resultado = await rodar_trajetoria(
        conn, trajetoria, ExtratorGravado(), variante=VARIANTES["base"]
    )

    assert resultado.prevista == ["Triagem", "Aguardando_confirmacao"]
    assert resultado.rotulada == trajetoria.estados
    assert resultado.igual and resultado.estado_final_igual


async def test_trajetoria_divergente_quando_falta_campo_no_payload(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Campo certo que não faz o funil andar é exatamente o que o nível trajetória pega: sem o
    tipo do encontro, a mesma conversa deixa o Atendimento parado em Triagem."""
    trajetoria = carregar_golden().trajetorias[0]
    sem_tipo = ExtratorRoteirizado(
        {
            "34-funil-t1": {"intencao": "cotacao"},
            "34-funil-t2": {"intencao": "agendamento", "horario_desejado": "18:00"},
        }
    )

    resultado = await rodar_trajetoria(conn, trajetoria, sem_tipo, variante=VARIANTES["base"])

    assert resultado.prevista == ["Triagem", "Triagem"]
    assert not resultado.igual
    assert resultado.prefixo_comum == 1
    assert not resultado.estado_final_igual
