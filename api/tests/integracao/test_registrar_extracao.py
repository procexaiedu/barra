"""M3d — registrar_extracao_ia (dominio) + guarda do piso, contra o Postgres real.

`needs_db` (Postgres via TEST_DATABASE_URL). Espelha o padrao de test_tools_idempotencia /
test_coordenador_basico: autocommit=False, dict_row, prepare_threshold=None, `SELECT 1`/seeds
abrem a transacao externa (o conn.transaction() interno do helper/abrir_handoff vira SAVEPOINT),
ROLLBACK SEMPRE no teardown — nada commita no banco de prod self-hosted.

Cobre (09 §M3d): Novo->Triagem; interno+horario->Aguardando_confirmacao+bloqueio+enviar_pin;
valor abaixo do piso escala fora_de_oferta sem gravar; idempotencia por turno_id; ConflitoAgenda
em slot sobreposto; reagendamento pos-bloqueio escala sem sobrescrever (branch 12).
"""

import os
from collections.abc import AsyncIterator
from datetime import date, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas._idempotencia import _executar_idempotente
from barra.dominio.agenda.service import ConflitoAgenda
from barra.dominio.atendimentos.service import registrar_extracao_ia

# --- infra de DB real (ROLLBACK sempre) ------------------------------------------------------


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


# --- seeds (espelham test_coordenador_basico) ------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], aceita: list[str] | None = None) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            aceita if aceita is not None else ["interno", "externo"],
        ),
    )
    return modelo_id


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    conversa_id: UUID,
    cliente_id: UUID,
    modelo_id: UUID,
    *,
    estado: str = "Novo",
    tipo_atendimento: str | None = None,
    intencao: str | None = None,
    horario_desejado: time | None = None,
    data_desejada: date | None = None,
    duracao_horas: Decimal | None = None,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, intencao,
             horario_desejado, data_desejada, duracao_horas)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum, %s::barravips.intencao_enum, %s, %s, %s)
        """,
        (
            atendimento_id,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            tipo_atendimento,
            intencao,
            horario_desejado,
            data_desejada,
            duracao_horas,
        ),
    )
    return atendimento_id


async def _seed_programa(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, horas: Decimal, preco: Decimal
) -> None:
    """Programa de tabela da modelo numa duracao (`duracoes.horas`) — base do piso (ADR-0004)."""
    programa_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.programas (id, nome, categoria) VALUES (%s, %s, NULL)",
        (programa_id, f"Prog {uuid4().hex[:8]}"),
    )
    duracao_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.duracoes (id, nome, ordem, horas) VALUES (%s, %s, %s, %s)",
        (duracao_id, f"Dur {uuid4().hex[:8]}", 99, horas),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco)
        VALUES (%s, %s, %s, %s)
        """,
        (modelo_id, programa_id, duracao_id, preco),
    )


async def _seed_par(
    c: AsyncConnection[dict[str, Any]],
    aceita: list[str] | None = None,
    **atendimento_kwargs: Any,
) -> tuple[UUID, UUID]:
    """Modelo+cliente+conversa+atendimento. Retorna (modelo_id, atendimento_id)."""
    modelo_id = await _seed_modelo(c, aceita)
    cliente_id = await _seed_cliente(c)
    conversa_id = await _seed_conversa(c, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        c, conversa_id, cliente_id, modelo_id, **atendimento_kwargs
    )
    return modelo_id, atendimento_id


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_novo_para_triagem(conn: AsyncConnection[dict[str, Any]]) -> None:
    _, atendimento_id = await _seed_par(conn)  # estado Novo

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"intencao": "cotacao", "proxima_acao_esperada": "apresentar valores"},
    )

    assert resultado["novo_estado"] == "Triagem"
    res = await conn.execute(
        "SELECT estado::text AS estado, intencao::text AS intencao "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Triagem"
    assert a["intencao"] == "cotacao"


@pytest.mark.needs_db
async def test_interno_horario_cria_bloqueio_e_pin(conn: AsyncConnection[dict[str, Any]]) -> None:
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(14, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("2"),
    )

    resultado = await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar saida do cliente"}
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    assert resultado["enviar_pin"] is True

    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["bloqueio_id"] is not None

    # Bloqueio previo ligado ao atendimento, origem ia, estado bloqueado.
    res = await conn.execute(
        "SELECT origem::text AS origem, estado::text AS estado "
        "FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert len(bloqueios) == 1
    assert bloqueios[0]["origem"] == "ia"
    assert bloqueios[0]["estado"] == "bloqueado"


@pytest.mark.needs_db
async def test_valor_abaixo_do_piso_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="externo", intencao="agendamento"
    )
    # Preco de tabela 1000 na duracao de 2h; piso = 1000*(1-desconto_max_pct). valor_acordado=50
    # fica abaixo de qualquer piso para desconto_max_pct realista (<0.95).
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("1000"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "50",
            "duracao_horas": "2",
            "proxima_acao_esperada": "fechar com o cliente",
        },
    )

    assert resultado["novo_estado"] is None
    assert "enviar_pin" not in resultado

    # Valor NAO gravado; IA pausada com responsavel modelo; estado preservado.
    res = await conn.execute(
        "SELECT estado::text AS estado, valor_acordado, ia_pausada, "
        "responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is True
    assert a["responsavel_atual"] == "modelo"
    assert a["estado"] == "Qualificado"

    # Escalada fora_de_oferta para a modelo.
    res = await conn.execute(
        "SELECT responsavel::text AS responsavel, tipo::text AS tipo, observacao "
        "FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["responsavel"] == "modelo"
    assert esc["tipo"] == "fora_de_oferta"
    assert esc["observacao"] == "fora_de_oferta"


@pytest.mark.needs_db
async def test_tipo_nao_aceito_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    """CONTEXT.md "Atendimento interno vs externo": a IA nunca negocia tipo que a modelo nao
    realiza. Guarda determinística (mesmo padrao do piso ADR-0004): tipo fora de
    tipo_atendimento_aceito[] NAO e gravado e escala fora_de_oferta."""
    _, atendimento_id = await _seed_par(conn, aceita=["interno"], estado="Triagem")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "intencao": "agendamento",
            "tipo_atendimento": "externo",
            "proxima_acao_esperada": "combinar a saida",
        },
    )

    assert resultado["novo_estado"] is None

    # Tipo NAO gravado; IA pausada com responsavel modelo; estado preservado.
    res = await conn.execute(
        "SELECT estado::text AS estado, tipo_atendimento, ia_pausada, "
        "responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["tipo_atendimento"] is None
    assert a["ia_pausada"] is True
    assert a["responsavel_atual"] == "modelo"
    assert a["estado"] == "Triagem"

    # Escalada fora_de_oferta para a modelo.
    res = await conn.execute(
        "SELECT responsavel::text AS responsavel, tipo::text AS tipo "
        "FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["responsavel"] == "modelo"
    assert esc["tipo"] == "fora_de_oferta"


@pytest.mark.needs_db
async def test_tipo_aceito_ou_modelo_sem_cadastro_grava_normal(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Tipo dentro do array grava normal; array vazio (cadastro incompleto) nao trava a venda."""
    for aceita, tipo in ([["externo"], "externo"], [[], "interno"]):
        _, atendimento_id = await _seed_par(conn, aceita=aceita, estado="Triagem")
        await registrar_extracao_ia(
            conn,
            str(atendimento_id),
            {"tipo_atendimento": tipo, "proxima_acao_esperada": "seguir qualificando"},
        )
        res = await conn.execute(
            "SELECT tipo_atendimento::text AS tipo, ia_pausada "
            "FROM barravips.atendimentos WHERE id = %s",
            (atendimento_id,),
        )
        a = await res.fetchone()
        assert a is not None, (aceita, tipo)
        assert a["tipo"] == tipo, (aceita, tipo)
        assert a["ia_pausada"] is False, (aceita, tipo)


@pytest.mark.needs_db
async def test_idempotencia_mesmo_turno(conn: AsyncConnection[dict[str, Any]]) -> None:
    _, atendimento_id = await _seed_par(conn)  # estado Novo
    turno_id = str(uuid4())
    payload = {"intencao": "cotacao", "proxima_acao_esperada": "apresentar valores"}
    chamadas = 0

    async def executor(c: AsyncConnection[Any], p: dict[str, Any]) -> dict[str, Any]:
        nonlocal chamadas
        chamadas += 1
        return await registrar_extracao_ia(c, str(atendimento_id), p)

    r1 = await _executar_idempotente(conn, turno_id, "registrar_extracao", 0, payload, executor)
    r2 = await _executar_idempotente(conn, turno_id, "registrar_extracao", 0, payload, executor)

    assert chamadas == 1  # o efeito colateral nao foi reexecutado
    assert r2 == r1
    assert r1["novo_estado"] == "Triagem"


@pytest.mark.needs_db
async def test_conflito_de_agenda(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Duas conversas da MESMA modelo disputando o mesmo slot -> a 2a colide na EXCLUDE.
    modelo_id = await _seed_modelo(conn)
    horario, data, duracao = time(20, 0), date(2026, 12, 2), Decimal("1")
    pares: list[UUID] = []
    for _ in range(2):
        cliente_id = await _seed_cliente(conn)
        conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
        pares.append(
            await _seed_atendimento(
                conn,
                conversa_id,
                cliente_id,
                modelo_id,
                estado="Qualificado",
                tipo_atendimento="interno",
                intencao="agendamento",
                horario_desejado=horario,
                data_desejada=data,
                duracao_horas=duracao,
            )
        )

    payload = {"proxima_acao_esperada": "confirmar"}
    await registrar_extracao_ia(conn, str(pares[0]), payload)  # reserva o slot

    with pytest.raises(ConflitoAgenda):
        # SAVEPOINT: a ExclusionViolation aborta a tx; o rollback do savepoint limpa o estado.
        async with conn.transaction():
            await registrar_extracao_ia(conn, str(pares[1]), payload)

    res = await conn.execute(
        "SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (pares[1],)
    )
    a = await res.fetchone()
    assert a is not None
    assert a["bloqueio_id"] is None  # 2o atendimento NAO ficou com bloqueio


@pytest.mark.needs_db
async def test_reagendamento_pos_bloqueio_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Atendimento ja em Aguardando_confirmacao COM bloqueio: mudar o horario escala (branch 12).
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
    )
    # Leva a Aguardando_confirmacao + cria o bloqueio previo.
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "18:00:00", "proxima_acao_esperada": "remarcar horario"},
    )

    assert resultado["novo_estado"] is None
    # Horario NAO foi sobrescrito; escalada reagendamento para a modelo.
    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada, responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(15, 0)  # preservado
    assert a["ia_pausada"] is True
    assert a["responsavel_atual"] == "modelo"

    res = await conn.execute(
        "SELECT observacao FROM barravips.escaladas WHERE atendimento_id = %s "
        "ORDER BY aberta_em DESC LIMIT 1",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["observacao"] == "reagendamento_pos_bloqueio"
