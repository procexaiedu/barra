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
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas._idempotencia import _executar_idempotente
from barra.dominio.agenda.service import BRT, ConflitoAgenda
from barra.dominio.atendimentos.service import (
    CotacaoAusente,
    ParPrecoDuracaoInvalido,
    _abaixo_do_piso,
    registrar_extracao_ia,
)
from barra.settings import get_settings

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
    cotou: bool = True,
) -> UUID:
    # cotou=True por padrao: quem combina horario (reach Aguardando_confirmacao) ja ouviu o preco —
    # e a precondicao real do guard CotacaoAusente (finding onda 1 A). Testes que exercitam o guard
    # passam cotou=False.
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, intencao,
             horario_desejado, data_desejada, duracao_horas, cotacao_enviada_em)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum, %s::barravips.intencao_enum, %s, %s, %s,
                CASE WHEN %s THEN now() ELSE NULL END)
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
            cotou,
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
        "SELECT estado::text AS estado, bloqueio_id, pix_status::text AS pix_status "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["bloqueio_id"] is not None
    assert a["pix_status"] == "nao_solicitado"  # interno nao pede Pix de deslocamento

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
async def test_combinar_horario_sem_cotacao_barra_e_reverte(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Guard onda 1 A: combinar horario com cotacao_enviada_em NULL e sem cotar neste turno barra a
    transicao (CotacaoAusente) e reverte tudo — o cliente marcaria o encontro sem saber o preco."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(14, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("2"),
        cotou=False,
    )
    with pytest.raises(CotacaoAusente):
        async with conn.transaction():
            await registrar_extracao_ia(
                conn, str(atendimento_id), {"proxima_acao_esperada": "combinar horario"}
            )
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Qualificado"  # reverteu, nao avancou sem cotar
    assert a["bloqueio_id"] is None


@pytest.mark.needs_db
async def test_cotar_e_combinar_no_mesmo_turno_avanca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Caso abencoado pelo <funil> ("diga o valor junto da confirmacao"): sem cotacao previa mas com
    cotacao_apresentada=True no mesmo turno, a transicao passa e o preco fica carimbado."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(14, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("2"),
        cotou=False,
    )
    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"proxima_acao_esperada": "confirmar", "cotacao_apresentada": True},
    )
    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    res = await conn.execute(
        "SELECT estado::text AS estado, cotacao_enviada_em "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["cotacao_enviada_em"] is not None  # carimbado no mesmo turno


@pytest.mark.needs_db
async def test_multihop_triagem_ate_aguardando_no_mesmo_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Bug B: quando intencao+tipo+horario chegam no MESMO turno, a FSM multi-hop leva
    Triagem -> Qualificado -> Aguardando_confirmacao numa unica extracao e cria o bloqueio previo
    ali — sem a janela de um turno do antigo single-hop (que deixava o slot sem reserva ate o turno
    seguinte, p.ex. o Aviso de saida)."""
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="cotacao")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "intencao": "agendamento",
            "tipo_atendimento": "interno",
            "horario_desejado": "22:00:00",
            "data_desejada": "2026-12-01",
            "duracao_horas": "1",
            "proxima_acao_esperada": "confirmar saida do cliente",
        },
    )

    # Promoveu ate Aguardando_confirmacao + bloqueio + pin, tudo no mesmo turno.
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

    # Auditoria: os DOIS hops foram registrados (passou por Qualificado), provando o multi-hop.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'transicao_estado' "
        "ORDER BY created_at",
        (atendimento_id,),
    )
    transicoes = [e["payload"]["para"] for e in await res.fetchall()]
    assert transicoes == ["Qualificado", "Aguardando_confirmacao"]


@pytest.mark.needs_db
async def test_remoto_horario_cria_bloqueio_sem_pin(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Remoto (video chamada, ADR 0021) promove como o interno: so pelo horario, cria o bloqueio
    previo, mas SEM enviar_pin (nao ha endereco). Sem valor_acordado tambem NAO solicita o Pix
    antecipado (ADR 0029: sem valor nao ha o que pedir — pix_status segue nao_solicitado)."""
    _, atendimento_id = await _seed_par(
        conn,
        aceita=["remoto"],
        estado="Qualificado",
        tipo_atendimento="remoto",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("1"),
    )

    resultado = await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "lembrar do horario da chamada"}
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    assert "enviar_pin" not in resultado

    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, pix_status::text AS pix_status "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["bloqueio_id"] is not None
    assert a["pix_status"] == "nao_solicitado"

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert len(bloqueios) == 1
    assert bloqueios[0]["estado"] == "bloqueado"


@pytest.mark.needs_db
async def test_remoto_com_valor_solicita_pix_antecipado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Remoto com valor acordado (ADR 0029): promove pelo horario E solicita o Pix antecipado
    do VALOR DA CHAMADA (valor_acordado), nao o fixo de deslocamento — mesmo trilho do
    externo-Uber (pix_status='aguardando', evento pix_solicitado, pix_valor no resultado p/ o
    coordenador anexar a chave). O comprovante nao gateia (coberto em test_operacional)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        aceita=["remoto"],
        estado="Qualificado",
        tipo_atendimento="remoto",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("1"),
    )
    # Programa de tabela para o guard do piso achar o preco: o payload do commit remoto so traz o
    # `valor_acordado`, sem reenviar a duracao (ja persistida na cotacao). O COALESCE de duracao em
    # `_abaixo_do_piso` pega a duracao persistida (1h) -> preco 300 -> valor 300 nao esta abaixo do
    # piso (300*0.85). Sem o COALESCE, duracao=None -> preco=None -> escala fora_de_oferta (Finding E).
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("300"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": 300, "proxima_acao_esperada": "pedir o pix da chamada"},
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    assert resultado["pix_solicitado"] is True
    assert Decimal(resultado["pix_valor"]) == Decimal("300")
    # guard-rail: nem a chave nem o titular vazam pelo resultado da extracao.
    assert "chave" not in resultado
    assert "titular" not in resultado

    res = await conn.execute(
        "SELECT pix_status::text AS pix_status, bloqueio_id "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["pix_status"] == "aguardando"
    assert a["bloqueio_id"] is not None

    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'pix_solicitado'",
        (atendimento_id,),
    )
    ev = await res.fetchall()
    assert len(ev) == 1
    assert Decimal(ev[0]["payload"]["valor"]) == Decimal("300")


@pytest.mark.needs_db
async def test_imediato_sem_horario_assume_horario_minimo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#4: urgencia=imediato SEM horario_desejado, em remoto (sem-deslocamento), assume o
    `horario_minimo` (cedo agenda-coerente) e promove a Aguardando_confirmacao + bloqueio — em vez
    de ficar preso em Qualificado -> Perdido. `agora`/`horario_minimo` fixos -> determinístico."""
    _, atendimento_id = await _seed_par(
        conn,
        aceita=["remoto"],
        estado="Qualificado",
        tipo_atendimento="remoto",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    agora = datetime(2026, 12, 1, 9, 0, tzinfo=BRT)
    horario_minimo = datetime(2026, 12, 1, 9, 30, tzinfo=BRT)

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"urgencia": "imediato", "proxima_acao_esperada": "reservar a chamada"},
        agora=agora,
        horario_minimo=horario_minimo,
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    res = await conn.execute(
        "SELECT estado::text AS estado, horario_desejado, bloqueio_id "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["horario_desejado"] == time(9, 30)  # assumiu o horario_minimo, não o now cru
    assert a["bloqueio_id"] is not None


@pytest.mark.needs_db
async def test_imediato_externo_uber_nao_auto_reserva(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#4 gate (c): externo-Uber (a modelo se desloca) com imediato SEM horario NÃO auto-crava —
    fica sem reserva (trilha reoferta->confirma->Pix), pra não disparar uma cobrança de Pix a partir
    de um 'imediato' que veio de condicional ('agora mesmo se der')."""
    _, atendimento_id = await _seed_par(
        conn,
        aceita=["externo"],
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    agora = datetime(2026, 12, 1, 9, 0, tzinfo=BRT)
    horario_minimo = datetime(2026, 12, 1, 9, 30, tzinfo=BRT)

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"urgencia": "imediato", "proxima_acao_esperada": "x"},
        agora=agora,
        horario_minimo=horario_minimo,
    )

    assert resultado["novo_estado"] is None  # gate sem-deslocamento: não preencheu horário
    res = await conn.execute(
        "SELECT estado::text AS estado, horario_desejado, bloqueio_id "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Qualificado"
    assert a["horario_desejado"] is None
    assert a["bloqueio_id"] is None


@pytest.mark.needs_db
async def test_valor_abaixo_do_piso_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="externo", intencao="agendamento"
    )
    # Preco de tabela 1000 na duracao de 2h; piso = 1000*(1-desconto_teto_pct). valor_acordado=50
    # fica abaixo de qualquer piso para desconto_teto_pct realista (<0.95).
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
async def test_valor_no_piso_sem_duracao_no_payload_nao_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Abrangencia do fix do Finding E: o commit que registra so o `valor_acordado` (sem reenviar a
    duracao ja persistida na cotacao) NAO pode ser tratado como abaixo do piso. Vale para todo
    trilho — aqui externo (happy-path de desconto), nao so o remoto. `_abaixo_do_piso` faz COALESCE
    da duracao com a persistida (2h) e acha o preco 400 -> valor 400 esta acima do piso (400*0.85)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("2"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("400"))

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "400", "proxima_acao_esperada": "combinar a saida"},
    )

    # Nao escalou: o valor foi gravado e a IA segue conduzindo (sem handoff fora_de_oferta).
    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("400")
    assert a["ia_pausada"] is False
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["n"] == 0


@pytest.mark.needs_db
async def test_lowball_sem_duracao_no_payload_ainda_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O COALESCE de duracao NAO enfraquece a deteccao de lowball: mesmo sem a duracao no payload,
    o guard usa a persistida (2h, preco 1000, piso 850) e um valor_acordado=50 segue abaixo do piso
    -> escala fora_de_oferta e nao grava o valor."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("2"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("1000"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "50", "proxima_acao_esperada": "fechar com o cliente"},
    )

    assert resultado["novo_estado"] is None
    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada, responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is True
    assert a["responsavel_atual"] == "modelo"
    res = await conn.execute(
        "SELECT tipo::text AS tipo FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["tipo"] == "fora_de_oferta"


# --- guarda do par preco x duracao (feedback piloto 21/07 — "3h 800" com tabela so de 1h) ----


@pytest.mark.needs_db
async def test_duracao_muda_sem_valor_par_abaixo_do_piso_erro_recuperavel(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A IA estica a duracao (1h -> 3h) sem re-cotar: o valor persistido (800, da 1h) fica abaixo
    do piso pra duracao nova (sem programa de 3h na tabela -> abaixo por definicao). O registro
    NAO grava e levanta ParPrecoDuracaoInvalido (erro recuperavel: a tool instrui a re-cotacao)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("800"))
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 800 WHERE id = %s",
        (atendimento_id,),
    )

    with pytest.raises(ParPrecoDuracaoInvalido):
        await registrar_extracao_ia(
            conn,
            str(atendimento_id),
            {"duracao_horas": "3", "proxima_acao_esperada": "fechar 3h com o cliente"},
        )

    # Nada gravado: duracao segue a da cotacao original.
    res = await conn.execute(
        "SELECT duracao_horas, valor_acordado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["duracao_horas"] == Decimal("1")
    assert a["valor_acordado"] == Decimal("800")


@pytest.mark.needs_db
async def test_duracao_muda_com_par_valido_grava_normal(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mudar a duracao com o valor persistido AINDA acima do piso da duracao nova nao dispara:
    valor 1000 (preco cheio da 2h) cobre o piso da tabela de 2h."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("600"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("1000"))
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 1000 WHERE id = %s",
        (atendimento_id,),
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"duracao_horas": "2", "proxima_acao_esperada": "combinar o horario"},
    )

    res = await conn.execute(
        "SELECT duracao_horas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["duracao_horas"] == Decimal("2")


@pytest.mark.needs_db
async def test_duracao_muda_sem_valor_persistido_nao_dispara(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem valor_acordado persistido nao ha par a conferir: registrar duracao nova segue livre
    (a cotacao do periodo vem depois, pelo trilho normal)."""
    _modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Triagem",
        tipo_atendimento="interno",
        intencao="cotacao",
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"duracao_horas": "3", "proxima_acao_esperada": "cotar o periodo pedido"},
    )

    res = await conn.execute(
        "SELECT duracao_horas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["duracao_horas"] == Decimal("3")


# --- _abaixo_do_piso contra desconto_teto_pct (ADR-0031 — dois degraus) ----------------------


@pytest.mark.needs_db
async def test_abaixo_do_piso_dentro_do_teto_grava_normal(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valor dentro do teto (desconto_teto_pct) NAO esta abaixo do piso -> grava normalmente."""
    monkeypatch.setattr(get_settings(), "desconto_teto_pct", 0.3)
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("2"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("1000"))
    # piso = 1000 * (1 - 0.3) = 700; 750 esta acima do piso.
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "750"}) is False


@pytest.mark.needs_db
async def test_abaixo_do_piso_abaixo_do_teto_escala(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valor abaixo do teto (desconto_teto_pct) escala (fora_de_oferta)."""
    monkeypatch.setattr(get_settings(), "desconto_teto_pct", 0.3)
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("2"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("1000"))
    # piso = 1000 * (1 - 0.3) = 700; 650 esta abaixo do piso.
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "650"}) is True


@pytest.mark.needs_db
async def test_abaixo_do_piso_sem_programa_correspondente_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem programa cadastrado na duracao do atendimento, `_preco_tabela_min` nao acha preco de
    tabela -> trata como abaixo do piso (escala), mesmo com um valor_acordado alto."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("3"),
    )
    # Nenhum _seed_programa nessa duracao (3h) -> preco_tabela None.
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "10000"}) is True


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


@pytest.mark.needs_db
async def test_limpar_horario_pos_bloqueio_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Recuo do cliente ("nao sei o dia ainda") com bloqueio previo ativo: zerar o snapshot em
    silencio deixaria o bloqueio orfao travando a agenda — cai na mesma branch 12."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"limpar": ["data_desejada", "horario_desejado"]},
    )

    assert resultado["novo_estado"] is None
    res = await conn.execute(
        "SELECT horario_desejado, bloqueio_id, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(15, 0)  # nao zerou sem tratar o bloqueio
    assert a["bloqueio_id"] is not None
    assert a["ia_pausada"] is True


@pytest.mark.needs_db
async def test_reagendamento_drift_dentro_da_tolerancia_nao_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Re-derivacao do horario relativo ("daqui 1h" recalculado do `agora` do turno seguinte)
    # chega com minutos de diferenca do reservado: NAO e pedido de mudanca (branch 12 ignora).
    # Preserva o horario do bloqueio, nao escala, e o resto do payload segue gravando.
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

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "data_desejada": "2026-12-03",
            "horario_desejado": "15:02:00",
            "proxima_acao_esperada": "aguardando comprovante",
        },
    )

    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada, proxima_acao_esperada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(15, 0)  # preservado (drift descartado)
    assert a["ia_pausada"] is False
    assert a["proxima_acao_esperada"] == "aguardando comprovante"  # upsert seguiu normal

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["n"] == 0  # sem escalada para drift


# --- externo-Uber ------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_externo_uber_promove_e_solicita_pix(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Externo-Uber (invariante 01 §6.1) agora promove na PROPRIA extracao:
    # Aguardando_confirmacao + bloqueio previo + pix_status='aguardando' + evento pix_solicitado, e o
    # resultado sinaliza pix_solicitado/pix_valor (p/ o coordenador anexar a bolha da chave). A chave
    # NUNCA entra no resultado/evento (guard-rail de dado sensivel).
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        horario_desejado=time(16, 0),
        data_desejada=date(2026, 12, 4),
        duracao_horas=Decimal("12"),
    )
    resultado = await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "pedir o pix"}
    )

    valor = str(get_settings().pix_deslocamento_valor)
    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    assert resultado["pix_solicitado"] is True
    assert resultado["pix_valor"] == valor
    # guard-rail: nem a chave nem o titular vazam pelo resultado da extracao.
    assert "chave" not in resultado
    assert "titular" not in resultado

    res = await conn.execute(
        "SELECT estado::text AS estado, pix_status::text AS pix_status, bloqueio_id "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["pix_status"] == "aguardando"
    assert a["bloqueio_id"] is not None  # bloqueio previo reservou o slot

    # bloqueio previo: 1, origem ia, estado bloqueado.
    res = await conn.execute(
        "SELECT origem::text AS origem, estado::text AS estado "
        "FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert len(bloqueios) == 1
    assert bloqueios[0]["origem"] == "ia"
    assert bloqueios[0]["estado"] == "bloqueado"

    # evento de auditoria pix_solicitado com SO o valor.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'pix_solicitado'",
        (atendimento_id,),
    )
    ev = await res.fetchall()
    assert len(ev) == 1
    assert ev[0]["payload"] == {"valor": valor}


@pytest.mark.needs_db
async def test_externo_uber_slot_tomado_reverte(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Externo-Uber cujo slot foi tomado entre turnos: criar_bloqueio_previo (no bloco de Pix)
    # levanta ConflitoAgenda, a transacao reverte tudo (estado, pix_status, bloqueio) — paridade
    # com a antiga tool. A casca da tool (extracao.py) converte em erro recuperavel; aqui testamos
    # a propagacao + reversao na funcao nucleo.
    modelo_id = await _seed_modelo(conn)
    horario, data, duracao = time(20, 0), date(2026, 12, 6), Decimal("1")
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        conversa_id,
        cliente_id,
        modelo_id,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        horario_desejado=horario,
        data_desejada=data,
        duracao_horas=duracao,
    )
    # Bloqueio avulso de outra origem ja ocupa o slot da modelo.
    inicio = datetime.combine(data, horario, tzinfo=BRT)
    await conn.execute(
        "INSERT INTO barravips.bloqueios (modelo_id, inicio, fim, origem, estado) "
        "VALUES (%s, %s, %s, 'manual', 'bloqueado')",
        (modelo_id, inicio, inicio + timedelta(hours=float(duracao))),
    )

    with pytest.raises(ConflitoAgenda):
        async with conn.transaction():
            await registrar_extracao_ia(
                conn, str(atendimento_id), {"proxima_acao_esperada": "pedir o pix"}
            )

    res = await conn.execute(
        "SELECT estado::text AS estado, pix_status::text AS pix_status, bloqueio_id "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Qualificado"  # reverteu
    assert a["pix_status"] == "nao_solicitado"
    assert a["bloqueio_id"] is None


# --- cotacao apresentada (ADR 0022) -----------------------------------------------------------


@pytest.mark.needs_db
async def test_cotacao_apresentada_carimba_uma_vez(conn: AsyncConnection[dict[str, Any]]) -> None:
    # ADR 0022: cotacao_apresentada=True carimba cotacao_enviada_em (first-write-wins, ancora do
    # reengajamento). 2a chamada com o flag de novo NAO move o carimbo (preserva a 1a cotacao).
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="cotacao")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"cotacao_apresentada": True, "proxima_acao_esperada": "aguardar resposta ao preco"},
    )
    assert resultado["novo_estado"] is None  # cotar nao transiciona estado

    res = await conn.execute(
        "SELECT cotacao_enviada_em FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None
    assert a["cotacao_enviada_em"] is not None
    primeiro = a["cotacao_enviada_em"]

    # Reenviar o flag num turno seguinte nao re-carimba (guard IS NULL).
    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"cotacao_apresentada": True, "proxima_acao_esperada": "reforcar o valor"},
    )
    res = await conn.execute(
        "SELECT cotacao_enviada_em FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a2 = await res.fetchone()
    assert a2 is not None
    assert a2["cotacao_enviada_em"] == primeiro


@pytest.mark.needs_db
async def test_sem_cotacao_apresentada_nao_carimba(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Sem o flag (so registra intencao/sondagem), cotacao_enviada_em permanece NULL.
    _, atendimento_id = await _seed_par(conn, cotou=False)  # estado Novo, sem cotacao previa
    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"intencao": "cotacao", "proxima_acao_esperada": "apresentar valores"},
    )
    res = await conn.execute(
        "SELECT cotacao_enviada_em FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None
    assert a["cotacao_enviada_em"] is None
