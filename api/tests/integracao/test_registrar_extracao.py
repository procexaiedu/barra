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
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas._idempotencia import _executar_idempotente
from barra.dominio.agenda.service import BRT, ConflitoAgenda
from barra.dominio.atendimentos.service import (
    MENSAGENS_GUARD_ESCALADA,
    CotacaoAusente,
    ParPrecoDuracaoInvalido,
    _abaixo_do_piso,
    carimbar_cotacao_por_texto_enviado,
    registrar_extracao_ia,
    retirar_horario_palpite,
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
    valor_acordado: Decimal | None = None,
    cotou: bool = True,
    horario_evidenciado: bool = False,
    n_contrapropostas: int = 0,
) -> UUID:
    # cotou=True por padrao: quem combina horario (reach Aguardando_confirmacao) ja ouviu o preco —
    # e a precondicao real do guard CotacaoAusente (finding onda 1 A). Testes que exercitam o guard
    # passam cotou=False.
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, intencao,
             horario_desejado, data_desejada, duracao_horas, valor_acordado, cotacao_enviada_em,
             horario_evidenciado, n_contrapropostas)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum, %s::barravips.intencao_enum, %s, %s, %s, %s,
                CASE WHEN %s THEN now() ELSE NULL END, %s, %s)
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
            valor_acordado,
            cotou,
            horario_evidenciado,
            n_contrapropostas,
        ),
    )
    return atendimento_id


async def _seed_programa(
    c: AsyncConnection[dict[str, Any]],
    modelo_id: UUID,
    *,
    horas: Decimal,
    preco: Decimal,
    preco_minimo: Decimal | None = None,
    nome: str | None = None,
) -> tuple[UUID, UUID]:
    """Programa de tabela da modelo numa duracao (`duracoes.horas`) — base do piso (ADR-0004).
    `preco_minimo` e o piso ABSOLUTO da linha, que clampa a escada percentual (11/08/2026).
    Devolve `(programa_id, duracao_id)` p/ quem precisa amarrar o servico VENDIDO ao pacote.

    `nome` importa para UMA leitura: `core.catalogo.e_video_chamada` separa a linha REMOTA das
    presenciais pelo nome (ADR-0021). O default aleatorio nunca casa — quem precisa da chamada
    pede `nome="Vídeo chamada"`."""
    programa_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.programas (id, nome, categoria) VALUES (%s, %s, NULL)",
        (programa_id, nome or f"Prog {uuid4().hex[:8]}"),
    )
    duracao_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.duracoes (id, nome, ordem, horas) VALUES (%s, %s, %s, %s)",
        (duracao_id, f"Dur {uuid4().hex[:8]}", 99, horas),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_programas
               (modelo_id, programa_id, duracao_id, preco, preco_minimo)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (modelo_id, programa_id, duracao_id, preco, preco_minimo),
    )
    return programa_id, duracao_id


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
        horario_evidenciado=True,  # a hora e DELE: e ela que autoriza a reserva do slot
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
        horario_evidenciado=True,  # a hora e DELE; o que falta e o preco
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
        horario_evidenciado=True,  # a hora e DELE; o preco chega no mesmo turno
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
        horario_evidenciado=True,  # a hora saiu da boca DELE neste turno
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
    # ORDER BY ctid, nao created_at: os dois hops saem da MESMA chamada na MESMA transacao —
    # `now()` empata byte a byte e uuidv7 no mesmo ms tem sufixo aleatorio; so a ordem fisica
    # de insercao discrimina.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'transicao_estado' "
        "ORDER BY ctid",
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
        horario_evidenciado=True,  # a hora da chamada e DELE
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
        horario_evidenciado=True,  # a hora da chamada e DELE
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
    de ficar preso em Qualificado -> Perdido. `agora`/`horario_minimo` fixos -> determinístico.

    O NUMERO vem do fallback, a EVIDENCIA vem dele (#35 da spec de proveniencia: a IA sondou
    "Seria agora ?" e ele respondeu "sim"). Sem o carimbo do detector do turno o fallback e
    palpite e nao reserva nada — caso #25, coberto em test_promocao_intencao.py."""
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
        horario_evidenciado=True,  # ele aceitou a sondagem de imediatismo
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
    # `n_contrapropostas=1` = a IA JA jogou uma rodada da escada e ele voltou pedindo menos: isto e
    # INSISTENCIA, que e a pre-condicao da escalada desde a r3 (loop-massa, achado 2c). Com a escada
    # intacta o mesmo valor vira descarte silencioso — ver o teste irmao logo abaixo.
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        n_contrapropostas=1,
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
async def test_valor_abaixo_do_piso_na_rodada_zero_descarta_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """loop-massa r3, achado 2c: com a escada INTACTA (`n_contrapropostas == 0`) o pedido baixo e o
    PRIMEIRO lance dele, nao insistencia — e escalar ali pre-empta a jogada que o proprio contexto
    acabou de mandar fazer (em `negociacao_dura_a` t6 a contraproposta CERTA de 300 morreu zerada
    pelo `post_process` sobre um pedido de 200).

    O valor continua NAO sendo gravado; o que muda e que ninguem e acordado, a IA nao e pausada e a
    escada segue viva. A escalada e o DEPOIS da escada (ADR-0031, degrau 6 do `regras.md.j2`)."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="externo", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "200",
            "duracao_horas": "1",
            "proxima_acao_esperada": "contrapor pela escada",
        },
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada, n_contrapropostas "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None  # o numero abaixo do piso nunca e gravado
    assert a["ia_pausada"] is False  # e a IA segue conduzindo, com a contraproposta na mao
    assert a["n_contrapropostas"] == 0  # a rodada continua disponivel

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None
    assert esc["n"] == 0


# --- guarda do VALOR FANTASMA (validacao ao vivo 11/08, escada_val2) --------------------------
#
# Cenario vivo: tabela 400/1h; o cliente insistiu "vai amor, 300 e fecho agora", a IA RECUSOU
# ("nao consigo por 300 nao") e a extracao gravou valor_acordado=300 + aceita_valor. O piso NAO
# pega: 300 e exatamente o teto de 25% sobre 400 (ADR-0031). No turno seguinte o belief mostrou
# "aceito por ele 300" e a IA capitulou. Aqui o campo tem que ser DESCARTADO (nao escalado).


async def _seed_fala_da_ia(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID, texto: str
) -> None:
    """Fala PERSISTIDA da IA na conversa do atendimento — a fonte (c) do conjunto legitimo."""
    res = await c.execute(
        "SELECT conversa_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    await c.execute(
        """
        INSERT INTO barravips.mensagens (conversa_id, atendimento_id, direcao, tipo, conteudo,
                                         evolution_message_id)
        VALUES (%s, %s, 'ia', 'texto', %s, %s)
        """,
        (row["conversa_id"], atendimento_id, texto, f"test-msg-{uuid4().hex}"),
    )


def _valor_fantasma_total() -> float:
    # Gotcha: `get_sample_value` NAO duplica o sufixo `_total` do Counter.
    return REGISTRY.get_sample_value("agente_extracao_valor_fantasma_total") or 0.0


def _descartes(tipo: str) -> float:
    """`agente_extracao_tipo_fora_de_oferta_total{tipo}` — o descarte que era so `logger.info`."""
    return (
        REGISTRY.get_sample_value("agente_extracao_tipo_fora_de_oferta_total", {"tipo": tipo})
        or 0.0
    )


def _incoerente(modo: str) -> float:
    """`agente_cadastro_remoto_incoerente_total{modo}` — os dois interruptores da video chamada
    divergindo (`programa_sem_checkbox` | `checkbox_sem_programa`)."""
    return (
        REGISTRY.get_sample_value("agente_cadastro_remoto_incoerente_total", {"modo": modo}) or 0.0
    )


@pytest.mark.needs_db
async def test_valor_que_a_ia_nunca_ofertou_e_descartado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O bug vivo: 300 e do CLIENTE, passa do piso e nunca saiu da boca da IA -> campo descartado,
    `aceita_valor` do mesmo payload cai junto, o RESTO do payload e aplicado e o retorno ensina o
    caminho certo. Nao escala: nao ha nada para a modelo decidir."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_fala_da_ia(conn, atendimento_id, "Fica 400 1h no meu local amor")
    antes = _valor_fantasma_total()

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "300",
            "duracao_horas": "1",
            "bairro": "Meireles",
            "sinais_qualificacao": {"aceita_valor": True, "responde_objetivamente": True},
            "proxima_acao_esperada": "combinar o horario",
        },
    )

    assert "descartado" in resultado["mensagem"].lower()
    assert "300" in resultado["mensagem"]
    assert _valor_fantasma_total() == antes + 1

    res = await conn.execute(
        "SELECT valor_acordado, duracao_horas, bairro, sinais_qualificacao, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    # O resto do payload seguiu gravando; so o aceite (inferido do mesmo evento falso) caiu.
    assert a["duracao_horas"] == Decimal("1")
    assert a["bairro"] == "Meireles"
    assert a["sinais_qualificacao"].get("aceita_valor") is not True
    assert a["sinais_qualificacao"]["responde_objetivamente"] is True
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0

    # Auditoria no evento, igual ao drift/tipo descartados.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s",
        (atendimento_id, "extracao_registrada"),
    )
    ev = await res.fetchone()
    assert ev is not None
    assert ev["payload"]["valor_descartado"]["proposto"] == 300


@pytest.mark.needs_db
async def test_valor_que_a_ia_ofertou_grava_normal(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O degrau que a IA OFERTOU num turno anterior e legitimo — a escada de desconto (ADR-0031)
    tem que continuar fechando venda."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_fala_da_ia(conn, atendimento_id, "consigo 350 se vier hoje amor")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "350",
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "combinar o horario",
        },
    )

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("350")
    assert a["sinais_qualificacao"]["aceita_valor"] is True


@pytest.mark.needs_db
async def test_valor_ofertado_na_fala_deste_turno_grava_normal(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`valor_acordado` e gravado JA NA COTACAO: o total com extra de fetiche (400 do pacote + 400
    do extra, ADR-0030) nao esta na tabela nem no historico — so na bolha deste turno."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "800",
            "duracao_horas": "1",
            "proxima_acao_esperada": "combinar o horario",
        },
        fala_da_ia_no_turno="com o extra fica 800 amor, na 1h",
    )

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["valor_acordado"] == Decimal("800")


@pytest.mark.needs_db
@pytest.mark.parametrize(
    "fala_do_aceite",
    [
        "Fechado 700 amor",
        "Tabom, 700 entao / Te espero as 22h amor",
        "Combinado 700 amor, consigo as 21h ?",
        "Faco 700 sim amor",
        "700 fechado entao / Seria que horas ?",
        "Consigo 700 sim amor",
    ],
)
async def test_aceite_do_valor_dele_grava_a_venda_em_forma_natural(
    conn: AsyncConnection[dict[str, Any]], fala_do_aceite: str
) -> None:
    """ADR-0040 ponta a ponta: 2h da Catarina (800, piso absoluto 600), o cliente propos 700 e a IA
    aceitou NO NUMERO DELE. O 700 nao esta na tabela e nunca foi ofertado por ela antes -- so a
    fala DESTE turno o legitima.

    A fala VARIA de propriedade nesta parametrizacao. A saida barata para esta guarda era prescrever
    no prompt UMA frase canonica que o scanner ja lesse ("Consigo 700 sim amor"): foi recusada pelo
    dono do produto, porque conduta prescrita como frase vira tique e uma frase com CARGA FUNCIONAL
    puniria a IA por dizer a mesma coisa com outras palavras -- toda venda sairia com a mesma bolha.
    Quem alargou foi o detector (`_RE_PRECO_CITADO`, ramo de fechamento), e este teste e a prova de
    que o registro nao depende de nenhuma fala especifica.

    Tem que passar por DUAS guardas na ordem: `_abaixo_do_piso` (700 >= 600, nao escala) e o valor
    fantasma (700 saiu da boca dela neste turno, nao e descartado)."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(
        conn, modelo_id, horas=Decimal("2"), preco=Decimal("800"), preco_minimo=Decimal("600")
    )
    antes = _valor_fantasma_total()

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "700",
            "duracao_horas": "2",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "combinar o horario",
        },
        fala_da_ia_no_turno=fala_do_aceite,
    )

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("700")
    assert a["sinais_qualificacao"]["aceita_valor"] is True
    assert _valor_fantasma_total() == antes

    # E nenhuma escalada: 700 esta acima do piso absoluto da linha, entao nao ha `fora_de_oferta`.
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_aceite_sem_o_numero_na_fala_continua_descartado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O contrapeso do teste acima, e a razao pela qual o bloco do prompt exige que o numero
    APARECA na bolha: "Tabom entao" sem numero nao prova aceite nenhum. Relaxar a guarda para
    "qualquer numero do cliente acima do piso" reabriria o bug de 11/08 -- a IA RECUSOU 300 e o
    extrator gravou 300, e 300 estava acima do piso. "Acima do piso" nunca foi prova de aceite."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(
        conn, modelo_id, horas=Decimal("2"), preco=Decimal("800"), preco_minimo=Decimal("600")
    )
    antes = _valor_fantasma_total()

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "700",
            "duracao_horas": "2",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "combinar o horario",
        },
        fala_da_ia_no_turno="Tabom entao amor / Te espero as 22h",
    )

    assert "descartado" in resultado["mensagem"].lower()
    assert _valor_fantasma_total() == antes + 1

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["sinais_qualificacao"].get("aceita_valor") is not True


@pytest.mark.needs_db
async def test_recusa_no_historico_nao_legitima_o_valor(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A fala que RECUSA o numero cita o numero — sem a leitura de negacao, a recusa do turno 3
    legitimaria o mesmo 300 no turno 4 (foi exatamente assim que a IA capitulou ao vivo)."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", tipo_atendimento="interno", intencao="cotacao"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_fala_da_ia(conn, atendimento_id, "Poxa amor, nao consigo por 300 nao")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "300", "duracao_horas": "1", "proxima_acao_esperada": "seguir"},
    )

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["valor_acordado"] is None


@pytest.mark.needs_db
async def test_payload_sem_valor_passa_intocado(conn: AsyncConnection[dict[str, Any]]) -> None:
    """A guarda so olha payload que REGISTRA valor: sem `valor_acordado` nada muda (nem a
    mensagem de retorno, que o post_process compara por igualdade)."""
    modelo_id, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="cotacao")
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    antes = _valor_fantasma_total()

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"bairro": "Aldeota", "proxima_acao_esperada": "perguntar o horario"},
    )

    assert resultado["mensagem"] == "Extracao registrada."
    assert _valor_fantasma_total() == antes


@pytest.mark.needs_db
async def test_valor_ja_acordado_reregistrado_preserva_valor_e_aceite(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Bug de 14/08 (corrida `c12cen_v2_20260814`, cenarios `remarcacao_para_outro_dia` e
    `ainda_ta_de_pe`): o atendimento ja tinha 350 acordado — negociado abaixo da tabela de 400/700
    —, o cliente voltou dias depois, a extracao RE-registrou o mesmo 350 e a guarda o tratava como
    fantasma (`proposto=350 legitimos=[400, 700]`), porque a janela de falas ja nao alcancava a
    bolha em que ela ofertou o desconto. Com `total_anunciado=False`, o `aceita_valor` do MESMO
    payload caia junto: o aceite do turno perdido por causa de um numero que ja estava no banco.

    Mordia toda retomada de conversa com desconto concedido — justamente as que estavam ganhas."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
        valor_acordado=Decimal("350"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("700"))
    antes = _valor_fantasma_total()

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "350",
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True, "informa_local": True},
            "proxima_acao_esperada": "confirmar o horario",
        },
        fala_da_ia_no_turno="Perfeito amor, te espero as 21h entao",
    )

    assert _valor_fantasma_total() == antes

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("350")
    assert a["sinais_qualificacao"]["aceita_valor"] is True  # o aceite do turno SOBREVIVE
    assert a["sinais_qualificacao"]["informa_local"] is True


@pytest.mark.needs_db
async def test_valor_perto_do_acordado_mas_nunca_ofertado_continua_fantasma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """CONTROLE NEGATIVO do teste acima, no caminho real: 380 nao esta na tabela, nao saiu da boca
    dela nesta conversa e NAO e o valor acordado (350) — segue descartado, e segue derrubando o
    `aceita_valor` do mesmo payload. A correcao alarga o conjunto por UM numero, o ja acordado, e
    nao por 'qualquer numero perto dele' (ADR-0040 rejeitou explicitamente relaxar por faixa)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
        valor_acordado=Decimal("350"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("700"))
    antes = _valor_fantasma_total()

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "380",
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True, "informa_local": True},
            "proxima_acao_esperada": "confirmar o horario",
        },
        fala_da_ia_no_turno="Perfeito amor, te espero as 21h entao",
    )

    assert "descartado" in resultado["mensagem"].lower()
    assert _valor_fantasma_total() == antes + 1

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("350")  # o 380 nao entrou; o acordado segue de pe
    assert a["sinais_qualificacao"].get("aceita_valor") is not True
    assert a["sinais_qualificacao"]["informa_local"] is True


@pytest.mark.needs_db
async def test_valor_abaixo_do_piso_ainda_escala_em_vez_de_descartar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ordem das guardas: abaixo do piso continua ESCALANDO **com a escada ja jogada** (ADR-0004 —
    o cliente INSISTINDO num numero baixo merece a modelo decidir; a premissa sempre esteve no
    comentario, o gate e que passou a checa-la na r3). So o que PASSA do piso e nunca saiu da boca
    dela cai no descarte silencioso do valor fantasma."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        n_contrapropostas=1,
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    antes = _valor_fantasma_total()

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "50", "duracao_horas": "1", "proxima_acao_esperada": "fechar"},
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA
    assert _valor_fantasma_total() == antes


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
    -> escala fora_de_oferta e nao grava o valor. (`n_contrapropostas=1`: a escalada exige
    insistencia desde a r3 — o que este teste isola e o COALESCE da duracao, nao o gate novo.)"""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        duracao_horas=Decimal("2"),
        n_contrapropostas=1,
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


# --- piso sem duracao NENHUMA (ciclo 7 da campanha) -------------------------------------------
#
# Caso vivo: a IA cotou "400 1h" na bolha dela, o cliente fechou em 300 (exatamente o piso de 25%)
# e a extracao gravou `valor_acordado` SEM `duracao_horas` — ela nao ve a fala da IA por contrato.
# Sem duracao dos dois lados (payload e snapshot), `_linhas_da_duracao` volta vazia,
# `_piso_do_pacote` devolve `(None, ...)` e o `abaixo = piso is None` escalava `fora_de_oferta` no
# TURNO DO FECHAMENTO. A cotacao dela e que identifica a linha; nao identificando, o fail-closed
# fica — mas descartando o valor, nunca pausando a IA.


def _piso_pacote_total(origem: str, resultado: str) -> float:
    # Gotcha: `get_sample_value` NAO duplica o sufixo `_total` do Counter.
    return (
        REGISTRY.get_sample_value(
            "agente_piso_pacote_total", {"origem": origem, "resultado": resultado}
        )
        or 0.0
    )


@pytest.mark.needs_db
async def test_piso_sem_duracao_usa_a_linha_que_a_ia_cotou(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O caso do ciclo 7: 300 e o piso LEGITIMO da linha de 1h/400 que a propria IA cotou. Com a
    duracao ausente dos dois lados, quem desambigua a linha e a cotacao dela — e o valor passa,
    grava e ninguem e acordado."""
    monkeypatch.setattr(get_settings(), "desconto_teto_pct", 0.25)
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    antes = _piso_pacote_total("linha_cotada", "aceito")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "300",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "combinar o horario",
        },
        # Os dois numeros saem da boca DELA: o 400 identifica a linha (piso 300) e o 300 e o degrau
        # que ela ofertou — sem ele o valor passaria no piso e cairia no valor fantasma, que e outra
        # guarda.
        fala_da_ia_no_turno="Fica 400 1h no meu local amor / consigo 300 se vier hoje",
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, duracao_horas, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("300")
    assert a["duracao_horas"] is None  # a duracao continua faltando; o piso e que soube se virar
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0
    # A serie nova: `linha_cotada` e o que mede se a cotacao esta salvando o julgamento.
    assert _piso_pacote_total("linha_cotada", "aceito") == antes + 1


@pytest.mark.needs_db
async def test_piso_sem_duracao_com_a_linha_cotada_ainda_barra_o_lowball(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O contrapeso: resolver a linha pela cotacao NAO e um salvo-conduto. Mesma cotacao (400 na
    1h, piso 300), valor 250 e a escada ja jogada — segue escalando `fora_de_oferta` como sempre."""
    monkeypatch.setattr(get_settings(), "desconto_teto_pct", 0.25)
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        n_contrapropostas=1,  # a escada JA foi jogada: pedir menos agora e insistencia
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "250", "proxima_acao_esperada": "fechar com o cliente"},
        fala_da_ia_no_turno="Fica 400 1h no meu local amor",
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is True

    res = await conn.execute(
        "SELECT tipo::text AS tipo FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["tipo"] == "fora_de_oferta"


@pytest.mark.needs_db
async def test_piso_sem_duracao_com_duas_cotacoes_resolve_pela_faixa_da_linha(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """DUAS cotacoes na mesma conversa e o caso frequente (2 de 9 conversas reais): a IA cota a 1h,
    ele pergunta a 2h, ela cota as duas — e ai o desempate por piso igual/preco cheio nao resolve
    nada. Sem o segundo degrau (a FAIXA vendavel de cada linha cotada), todo fechamento depois de
    duas cotacoes caia no fail-closed e o encontro era marcado SEM preco.

    300 e venda possivel na 1h (faixa [300, 400]) e impossivel na 2h (faixa [525, 700]): uma linha
    so contem o numero, entao e ela que julga — e o 300 passa como o piso legitimo que e."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("700"))
    antes = _piso_pacote_total("linha_cotada", "aceito")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "300",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "combinar o horario",
        },
        fala_da_ia_no_turno="Fica 400 1h no meu local amor / a 2h fica 700 / consigo 300 se vier hoje",
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("300")
    assert a["ia_pausada"] is False
    assert _piso_pacote_total("linha_cotada", "aceito") == antes + 1


@pytest.mark.needs_db
async def test_piso_sem_duracao_com_valor_em_duas_faixas_continua_fail_closed(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O contrapeso do degrau da faixa: ele elimina as linhas onde o numero seria impossivel, nao
    escolhe entre as possiveis. Cotadas 400 (faixa [300, 400]) e 500 (faixa [375, 500]), o valor 390
    cabe nas DUAS com pisos diferentes — ambiguidade de verdade, entao o piso nao resolve e o valor
    e descartado (sem pausar, que e a outra metade da regra)."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("500"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "390", "proxima_acao_esperada": "combinar o horario"},
        fala_da_ia_no_turno="Fica 400 1h no meu local amor / a 2h fica 500",
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["valor_descartado"] for e in eventos if "valor_descartado" in e["payload"]
    ]
    assert descartes == [{"proposto": "390", "motivo": "piso_sem_duracao"}]


@pytest.mark.needs_db
async def test_piso_indecidivel_sem_duracao_no_fechamento_descarta_sem_pausar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ambiguidade nao vira palpite — mas tambem nao vira handoff. Sem duracao e sem cotacao que
    identifique uma linha, o piso continua indecidivel (fail-closed, o valor NAO e gravado); com a
    cotacao ja enviada, porem, este turno e o do FECHAMENTO, e pausar a IA ali por cadastro
    incompleto e o modo de falha que o ciclo 7 mediu — nao a protecao.

    O `aceita_valor` sobrevive, ao contrario do descarte por piso: ninguem RECUSOU o numero, o
    sistema so nao teve como julga-lo. Vale para a PRIMEIRA ocorrencia — a segunda escala (ver
    `test_piso_sem_duracao_na_insistencia_escala`)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        n_contrapropostas=1,  # com insistencia: hoje isto bastaria para escalar
        cotou=True,  # explicito: e a cotacao enviada que rebaixa a escalada a descarte
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    antes = _piso_pacote_total("duracao_desconhecida", "descartado")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "300",
            "sinais_qualificacao": {"aceita_valor": True, "informa_local": True},
            "proxima_acao_esperada": "combinar o horario",
        },
        # Nenhuma fala da IA na conversa: sem preco cotado, a linha nao tem como ser identificada.
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None  # fail-closed: o numero indecidivel nao entra
    assert a["ia_pausada"] is False  # mas o turno do fechamento segue com a IA no comando
    assert a["sinais_qualificacao"]["aceita_valor"] is True  # o "fechou" dele aconteceu
    assert a["sinais_qualificacao"]["informa_local"] is True

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0

    # Descarte AUDITAVEL (mesmo canal do valor fantasma), com o motivo que o distingue do lowball.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["valor_descartado"] for e in eventos if "valor_descartado" in e["payload"]
    ]
    assert descartes == [{"proposto": "300", "motivo": "piso_sem_duracao"}]
    assert _piso_pacote_total("duracao_desconhecida", "descartado") == antes + 1


@pytest.mark.needs_db
async def test_descarte_por_piso_sem_duracao_com_o_valor_sozinho_no_payload_e_auditavel(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O turno em que o `valor_acordado` chega SOZINHO (o formato que o extrator produz no aceite):
    descartado o numero, nao sobra campo nenhum para o UPSERT e a funcao sai pelo ramo "Nenhum campo
    novo para registrar". Sem o insert de auditoria ali, um numero FINANCEIRO sumiria deixando so um
    `logger.warning` — e, pior, o proximo descarte igual nao teria como saber que houve um primeiro
    (e a escalada por insistencia nunca chegaria)."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento", cotou=True
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(conn, str(atendimento_id), {"valor_acordado": "300"})

    assert resultado["mensagem"] == "Nenhum campo novo para registrar."
    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["valor_descartado"] for e in eventos if "valor_descartado" in e["payload"]
    ]
    assert descartes == [{"proposto": "300", "motivo": "piso_sem_duracao"}]


@pytest.mark.needs_db
async def test_piso_sem_duracao_na_insistencia_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Anti-leilao (ADR-0031): o rebaixamento da escalada e UM turno de paciencia, nao licenca.

    Sem duracao o piso nunca resolve — entao, se o descarte silencioso valesse para sempre, o
    cliente poderia baixar o numero turno apos turno com o sistema calado e a modelo nunca acordada.
    A `contraproposta_da_escada` tambem cala na duracao irresolvivel, entao `n_contrapropostas` pode
    ficar em 0 eternamente: quem conta a insistencia aqui e o rastro do PROPRIO descarte no audit
    log, e o gatilho e o numero DIMINUIR (ADR-0031, "cada vez menos")."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento", cotou=True
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    primeiro = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "300", "proxima_acao_esperada": "combinar o horario"},
    )
    assert primeiro["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    # Ele volta pedindo menos ainda, no mesmo cenario indecidivel: agora a modelo decide.
    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "280", "proxima_acao_esperada": "fechar com o cliente"},
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA
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
    assert esc is not None and esc["tipo"] == "fora_de_oferta"


@pytest.mark.needs_db
async def test_piso_sem_duracao_com_o_mesmo_valor_reemitido_nao_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O outro lado do comparador (refutacao do verificador, 13/08): o descarte nao persiste nada e
    o `<ja_registrado>` manda o extrator RE-EMITIR o que esta na janela, entao o MESMO 300 volta no
    payload do turno seguinte sem o cliente ter aberto a boca. Contar isso como leilao daria um
    handoff indevido por artefato do proprio sistema — o numero precisa DIMINUIR.

    Descarta de novo, auditavel (dois eventos), com a IA no comando."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento", cotou=True
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    for _ in range(2):
        resultado = await registrar_extracao_ia(
            conn,
            str(atendimento_id),
            {"valor_acordado": "300", "proxima_acao_esperada": "combinar o horario"},
        )
        assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0

    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["valor_descartado"] for e in eventos if "valor_descartado" in e["payload"]
    ]
    assert descartes == [
        {"proposto": "300", "motivo": "piso_sem_duracao"},
        {"proposto": "300", "motivo": "piso_sem_duracao"},
    ]


@pytest.mark.needs_db
async def test_piso_indecidivel_sem_cotacao_enviada_continua_escalando(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O rebaixamento e ESTREITO: sem `cotacao_enviada_em` o atendimento nao esta fechando nada —
    nunca ouviu preco —, e um valor indecidivel com a escada ja jogada segue acordando a modelo."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        n_contrapropostas=1,
        cotou=False,  # nenhum preco apresentado ainda
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": "300", "proxima_acao_esperada": "fechar com o cliente"},
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA
    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None
    assert a["ia_pausada"] is True


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
    """Sem programa cadastrado na duracao do atendimento, `_piso_do_pacote` nao acha preco de
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
async def test_piso_absoluto_da_linha_vence_o_percentual(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O caso da Catarina (11/08/2026): pacote de 30min cadastrado como 250 = o MÍNIMO dela.
    Os 25% do percentual global permitiriam 187,50; o `preco_minimo` corta em 250, e a guarda
    escala qualquer valor abaixo disso em vez de gravar."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("0.5"),
    )
    await _seed_programa(
        conn,
        modelo_id,
        horas=Decimal("0.5"),
        preco=Decimal("250"),
        preco_minimo=Decimal("250"),
    )
    # Sem o piso da linha, 200 passaria (fica acima dos 187,50 do percentual).
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "200"}) is True
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "250"}) is False


@pytest.mark.needs_db
async def test_duracao_com_dois_pacotes_julga_pelo_piso_MAIS_ALTO(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O furo que o piso por PACOTE fecha (o cadastro da Lucia e da Tatiane): duas linhas na mesma
    duração (Normal 400 com piso 300, Completo 800 com piso 600) e nenhum serviço vendido gravado.
    O piso da linha mais barata (ADR-0004 §Decisão item 5) deixava o Completo de 800 vendável a
    300 — valor real da tabela, então o guard de saída também o aceitava: sem escalada e sem
    rastro.

    Aqui a conversa não tem NENHUMA fala da IA semeada, então a dedução do pacote pelo preço
    cotado (11/08/2026) não tem o que ler e vale o FALLBACK: sem saber qual pacote é, o piso mais
    alto — o único válido para os dois. A dedução em si está coberta, sem DB, em
    tests/unit/test_piso_de_desconto.py."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(
        conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"), preco_minimo=Decimal("300")
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("800"))
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "800"}) is False
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "600"}) is False
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "300"}) is True
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "280"}) is True


@pytest.mark.needs_db
async def test_servico_vendido_amarra_o_piso_ao_programa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Com o pacote gravado em `atendimento_servicos` (o painel), a ambiguidade some: o piso é o
    da linha DELE. Mesma tabela do teste acima — vendido o Normal, os 300 voltam a ser piso
    legítimo; vendido o Completo, 300 escala."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    normal_id, duracao_id = await _seed_programa(
        conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"), preco_minimo=Decimal("300")
    )
    completo_id, _ = await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("800"))
    await conn.execute(
        """
        INSERT INTO barravips.atendimento_servicos
               (atendimento_id, programa_id, duracao_id, preco_snapshot)
        VALUES (%s, %s, %s, %s)
        """,
        (atendimento_id, normal_id, duracao_id, Decimal("400")),
    )
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "300"}) is False
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "280"}) is True

    await conn.execute(
        "UPDATE barravips.atendimento_servicos SET programa_id = %s WHERE atendimento_id = %s",
        (completo_id, atendimento_id),
    )
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "300"}) is True
    assert await _abaixo_do_piso(conn, atendimento_id, {"valor_acordado": "600"}) is False


@pytest.mark.needs_db
async def test_tipo_nao_aceito_e_descartado_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ciclo 7 da campanha: o tipo fora de oferta nao e um cliente exigindo o impossivel, e na
    ocorrencia mais comum e uma PERGUNTA ("faz video chamada?" chega como `tipo_atendimento=remoto`)
    — escalar ali pausa a IA no turno em que ela ainda era uma duvida. Alinhamento com a guarda
    irma: a duracao off-menu descarta em silencio e deixa a conduta closed-world do prompt recusar
    em personagem.

    O que fica: o campo NAO e gravado (a guarda nao afrouxou), o resto do payload segue, nada pausa
    e o descarte fica auditavel no evento."""
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

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT tipo_atendimento, intencao::text AS intencao, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["tipo_atendimento"] is None  # o tipo que ela nao realiza nunca entra no snapshot
    assert a["intencao"] == "agendamento"  # o resto do payload seguiu gravando
    assert a["ia_pausada"] is False  # e a IA segue conduzindo, recusando em personagem

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0

    # Auditoria no evento (mesmo canal do drift/tipo descartados), com chave PROPRIA: quem le
    # precisa distinguir "ela nao faz isso" do flip pos-crava ("isso ja estava combinado").
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["tipo_fora_de_oferta"]
        for e in eventos
        if "tipo_fora_de_oferta" in e["payload"]
    ]
    assert descartes == [{"pedido": "externo"}]


@pytest.mark.needs_db
async def test_tipo_nao_aceito_repetido_continua_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O tipo voltando num segundo turno TAMBEM nao escala — e esta e a parte contraintuitiva.

    A guarda nao persiste nada, e o `<ja_registrado>` manda o extrator RE-EMITIR o que esta na
    janela: o mesmo `tipo_atendimento=remoto` volta no payload seguinte sem o cliente ter repetido
    coisa alguma. Contar isso como insistencia so mudaria o handoff indevido do turno 1 para o
    turno 2, com um resumo ("o cliente insiste") que seria falso — quem "insistiu" foi o extrator.

    A escalada por insistencia REAL existe, e mora na outra porta: as clausulas "se ele insistir,
    escale com fora_de_oferta" dos blocos `<sem_*>` do prompt, que abrem o handoff pela TOOL, com
    resumo escrito por quem leu a conversa.

    O primeiro turno traz o tipo SOZINHO no payload — o formato mais comum da pergunta — e prova de
    quebra o insert de auditoria no ramo "nenhum campo novo para registrar"."""
    _, atendimento_id = await _seed_par(conn, aceita=["interno"], estado="Triagem")

    primeiro = await registrar_extracao_ia(
        conn, str(atendimento_id), {"tipo_atendimento": "externo"}
    )
    assert primeiro["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "intencao": "agendamento",
            "tipo_atendimento": "externo",
            "proxima_acao_esperada": "combinar a saida",
        },
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    # Tipo NAO gravado nas duas vezes, IA nunca pausada, nenhum card aberto.
    res = await conn.execute(
        "SELECT estado::text AS estado, tipo_atendimento, ia_pausada, "
        "responsavel_atual::text AS responsavel_atual "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["tipo_atendimento"] is None
    assert a["ia_pausada"] is False
    assert a["responsavel_atual"] != "modelo"

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0

    # Os DOIS descartes ficam no audit log — o rastro existe para o painel, nao para contar
    # insistencia.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["tipo_fora_de_oferta"]
        for e in eventos
        if "tipo_fora_de_oferta" in e["payload"]
    ]
    assert descartes == [{"pedido": "externo"}, {"pedido": "externo"}]


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
async def test_video_chamada_no_cardapio_aceita_remoto_sem_o_checkbox(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """R2 do diagnostico de handoffs indevidos: o produto tinha DOIS interruptores independentes.

    Com `checkbox OFF + programa PRESENTE`, o PROMPT vendia a chamada (o gate
    `<sem_video_chamada>` e derivado de `modelo_programas`) e cotava o preco da tabela, enquanto o
    DOMINIO descartava toda extracao `remoto` em silencio (antes do ciclo 7: escalava e pausava a
    IA). O atendimento nunca virava `remoto`, entao o trilho inteiro do ADR-0021/0029 — bloqueio
    previo, Pix antecipado, cron `confirmar_em_execucao`, card "Hora da video chamada" — nunca
    armava: a venda acontecia na conversa e nao existia no sistema.

    O cardapio e o site unico de "o que ela vende" (`core.catalogo.e_video_chamada`, o MESMO
    predicado que o prompt usa), entao ele passa a habilitar `remoto` tambem. O checkbox segue
    valendo sozinho — a derivacao e UNIAO, ninguem perde comportamento."""
    modelo_id, atendimento_id = await _seed_par(conn, aceita=["interno"], estado="Triagem")
    await _seed_programa(
        conn, modelo_id, horas=Decimal("0.25"), preco=Decimal("150"), nome="Vídeo chamada"
    )
    antes = _incoerente("programa_sem_checkbox")

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"tipo_atendimento": "remoto", "proxima_acao_esperada": "combinar a chamada"},
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA
    res = await conn.execute(
        "SELECT tipo_atendimento::text AS tipo, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["tipo"] == "remoto"  # o que o cardapio dela vende entra no snapshot
    assert a["ia_pausada"] is False

    # Nenhum descarte auditado, nenhuma escalada — e a divergencia de cadastro fica MEDIDA.
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0
    assert _incoerente("programa_sem_checkbox") == antes + 1


@pytest.mark.needs_db
async def test_tipo_fora_de_oferta_incrementa_o_contador(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O descarte do tipo era MUDO em producao (so `logger.info`): trocamos um handoff visivel por
    um silencio. Sem contador, a extracao classificando `remoto` por engano em massa — ou um
    cadastro que perdeu o tipo que a modelo de fato vende — nao aparece em lugar nenhum.

    A modelo aqui nao tem nem checkbox nem linha de chamada: o descarte e o comportamento certo."""
    _, atendimento_id = await _seed_par(conn, aceita=["interno"], estado="Triagem")
    antes = _descartes("remoto")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"tipo_atendimento": "remoto", "proxima_acao_esperada": "seguir qualificando"},
    )

    assert _descartes("remoto") == antes + 1
    res = await conn.execute(
        "SELECT tipo_atendimento FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["tipo_atendimento"] is None


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
                horario_evidenciado=True,  # os dois clientes cravaram a MESMA hora
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
async def test_numero_pequeno_demais_para_ser_preco_nao_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "seria amanha a noite, umas 21h" virando `valor_acordado=21` (medido ao vivo em 12/08): nao
    e o cliente pedindo barato, e a extracao lendo a HORA como valor. Cair na guarda do piso pausava
    a IA no turno em que ele marcava o encontro — a conversa morria em "Deixa eu ver certinho"."""
    modelo_id, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="agendamento")
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"valor_acordado": 21, "duracao_horas": 1, "proxima_acao_esperada": "confirmar"},
    )

    assert resultado["mensagem"].startswith("Extracao registrada")
    res = await conn.execute(
        "SELECT valor_acordado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None  # descartado, nao gravado
    assert a["ia_pausada"] is False  # e nao escalou

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_reagendamento_pos_bloqueio_escala(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Atendimento ja em Aguardando_confirmacao COM bloqueio: mudar o horario que ELE cravou
    # (horario_evidenciado) escala (branch 12).
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
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
async def test_reoferta_da_propria_ia_aceita_por_ele_realoca_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O A/B EXATO do teste acima: mesma reserva, mesma hora nova, mesma modelo JA acionada — muda
    so que a hora nova saiu da BOCA DELA (`eb04:154412781666344` t27, corrida c12_tardio).

    Ali a IA reofertou "Consigo te receber a partir das 10:30, fecha ?" sobre a reserva de 10:00 e
    o cliente aceitou; o `aviso_saida_em` estava carimbado pela chegada DELE, entao a remarcacao
    segura nao valia e o aceite virou escalada — IA pausada no turno do fechamento. Aceitar a
    oferta DELA nao e reagendamento: a reserva segue a conversa, sem acordar ninguem."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    # A modelo JA acionada (o gate que sozinho decidia o veredito ate aqui).
    await conn.execute(
        "UPDATE barravips.atendimentos SET aviso_saida_em = now() WHERE id = %s",
        (atendimento_id,),
    )

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "18:00:00", "proxima_acao_esperada": "confirmar a hora nova"},
        horario_evidenciado=True,  # ele cravou a hora dela ("18h entao ?")
        fala_da_ia_no_turno="Consigo te receber as 18h, fecha ?",
    )

    assert resultado["mensagem"].startswith("Extracao registrada")
    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(18, 0)  # a reserva seguiu a conversa
    assert a["ia_pausada"] is False
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_correcao_da_propria_extracao_descarta_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`eb02:1460423151841` t12: a extracao gravou uma hora que ninguem disse, no turno seguinte se
    corrigiu para a que estava na bolha dela, e a fala do cliente ("Calma ai / Ainda num confirmei
    nada") nao tinha hora nenhuma. O snapshot torto entrou carimbado como evidenciado por ELE, e por
    isso o ramo "descarta" — que existe justo para ruido dela — era inalcancavel: virava escalada.

    Ruido dela nao move a agenda NEM acorda a modelo: o horario do payload cai, a reserva fica onde
    esta e a IA continua conduzindo."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        "UPDATE barravips.atendimentos SET pix_status = 'aguardando' WHERE id = %s",
        (atendimento_id,),
    )

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "18:00:00", "proxima_acao_esperada": "aguardar confirmacao"},
        horario_evidenciado=False,  # a fala do turno nao tem hora
        fala_da_ia_no_turno="Entao fica 18h amor",
    )

    assert resultado["mensagem"].startswith("Extracao registrada")
    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(15, 0)  # descartado, a reserva nao se mexe
    assert a["ia_pausada"] is False
    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s", (atendimento_id,)
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_limpar_horario_pos_bloqueio_libera_a_reserva_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Remarcacao ABERTA ("hoje nao consigo mais, marco outro dia") com bloqueio previo ativo.

    Prova r3, eixo `remarcacao` t6: o `limpar` curto-circuitava em "mudanca" e a escalada pausava a
    IA — no t7 o cliente voltou com "amanha 21h" e falou no vazio. O medo que justificava o
    curto-circuito (zerar o snapshot deixa o bloqueio ORFAO travando a agenda) e real, mas a
    resposta certa nao e escalar: e SOLTAR a reserva junto com o snapshot enquanto a modelo nao foi
    acionada (mesma remarcacao segura de 12/08 que ja governa o ramo "realoca"), e devolver a
    conversa para combinar o novo dia."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,  # a hora que ele cravou e que virou reserva
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"limpar": ["data_desejada", "horario_desejado"]},
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA
    # A soltura da reserva e efeito real do turno: o turno tem de ser critico (nao cancelavel).
    assert resultado["novo_estado"] == "Qualificado"
    res = await conn.execute(
        "SELECT estado::text AS estado, horario_desejado, data_desejada, bloqueio_id, "
        "horario_evidenciado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] is None  # o recuo dele vale
    assert a["data_desejada"] is None
    assert a["horario_evidenciado"] is False
    assert a["bloqueio_id"] is None  # reserva solta, nao orfa
    assert a["ia_pausada"] is False  # e a IA segue conduzindo
    # Volta pra Qualificado: sem hora combinada o encontro nao esta marcado — e so dali a FSM
    # reserva de novo quando ele cravar o dia novo.
    assert a["estado"] == "Qualificado"

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert [b["estado"] for b in bloqueios] == ["cancelado"]  # o slot voltou pra agenda

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_dia_novo_apos_a_reserva_solta_reserva_de_novo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O t7 que morria no vazio: depois do recuo, o cliente crava o dia/hora novos e o encontro
    volta a ficar marcado — com reserva NOVA, sem passar por ninguem."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await registrar_extracao_ia(
        conn, str(atendimento_id), {"limpar": ["data_desejada", "horario_desejado"]}
    )

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"data_desejada": "2026-12-04", "horario_desejado": "21:00:00"},
        horario_evidenciado=True,  # o detector do turno viu a hora na fala DELE
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["bloqueio_id"] is not None
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT estado::text AS estado, inicio FROM barravips.bloqueios "
        "WHERE atendimento_id = %s ORDER BY created_at",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert [b["estado"] for b in bloqueios] == ["cancelado", "bloqueado"]
    assert bloqueios[-1]["inicio"].astimezone(timezone(timedelta(hours=-3))).day == 4


@pytest.mark.needs_db
async def test_limpar_horario_com_modelo_acionada_ainda_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A porta da escalada continua de pe: com aviso de saida dado, a modelo ja se organizou pela
    hora do card — soltar a reserva em silencio dessincronizaria os dois."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        "UPDATE barravips.atendimentos SET aviso_saida_em = now() WHERE id = %s",
        (atendimento_id,),
    )

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"limpar": ["data_desejada", "horario_desejado"]},
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA
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
async def test_dia_novo_sobre_reserva_palpite_realoca_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Prova r3, eixo `explorador_ambiguo_a` t7: a hora reservada era PALPITE da IA (21:30 proposto
    2x, nunca aceito) e o cliente pede outro DIA ("amanha da?"). O ramo da troca de data devolvia
    "mudanca" — "Horario ja reservado: mudanca escalada para a modelo" e IA pausada no ponto de
    fechar. Com a modelo nao acionada, a reserva-palpite so acompanha o dia dele."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    # A reserva vira PALPITE (mesma montagem dos testes irmaos do palpite).
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_evidenciado = false WHERE id = %s",
        (atendimento_id,),
    )
    res = await conn.execute(
        "SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    bloqueio_do_palpite = row["bloqueio_id"]

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"data_desejada": "2026-12-04", "proxima_acao_esperada": "combinar a hora de amanha"},
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA
    res = await conn.execute(
        "SELECT data_desejada, horario_desejado, bloqueio_id, ia_pausada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["data_desejada"] == date(2026, 12, 4)  # o dia DELE vale
    assert a["horario_desejado"] == time(15, 0)  # a hora segue sendo o palpite, no dia novo
    assert a["ia_pausada"] is False
    assert a["bloqueio_id"] != bloqueio_do_palpite

    res = await conn.execute(
        "SELECT estado::text AS estado, inicio FROM barravips.bloqueios "
        "WHERE atendimento_id = %s ORDER BY created_at",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert [b["estado"] for b in bloqueios] == ["cancelado", "bloqueado"]
    assert bloqueios[-1]["inicio"].astimezone(timezone(timedelta(hours=-3))).day == 4

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_dia_novo_sobre_reserva_palpite_com_pix_andando_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Acionada a modelo (Pix andando), o dia novo volta a ser evento dela: escala, como antes."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_evidenciado = false, "
        "pix_status = 'aguardando' WHERE id = %s",
        (atendimento_id,),
    )

    resultado = await registrar_extracao_ia(
        conn, str(atendimento_id), {"data_desejada": "2026-12-04"}
    )

    assert resultado["mensagem"] in MENSAGENS_GUARD_ESCALADA
    res = await conn.execute(
        "SELECT data_desejada, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["data_desejada"] == date(2026, 12, 3)  # nao mexeu na reserva
    assert a["ia_pausada"] is True


@pytest.mark.needs_db
async def test_aceite_sem_valor_preenche_com_o_preco_que_a_ia_cotou(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Medido ao vivo (12/08, 6 de 35 conversas): a extracao marca o aceite e grava a duracao, mas
    deixa `valor_acordado` NULL — o encontro chega ao painel marcado e sem preco. O preco nao e
    inventado: e o da tabela para a duracao fechada, e so entra porque a IA o COTOU na conversa."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", intencao="agendamento", duracao_horas=Decimal("1")
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_fala_da_ia(conn, atendimento_id, "400 1h no meu local")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "proxima_acao_esperada": "confirmar",
            "sinais_qualificacao": {"aceita_valor": True},
        },
    )

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("400")


@pytest.mark.needs_db
async def test_encontro_marcado_sem_valor_preenche_mesmo_sem_o_sinal_de_aceite(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O extrator as vezes nao marca `aceita_valor` no turno do "isso, fechado". Em
    `Aguardando_confirmacao` o aceite e implicito: ninguem crava hora sobre um preco que nao topou.
    """
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(21, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_fala_da_ia(conn, atendimento_id, "400 1h no meu local")

    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "aguardar"})

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["valor_acordado"] == Decimal("400")


@pytest.mark.needs_db
async def test_aceite_sem_valor_nao_preenche_com_negociacao_na_mesa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Com contraproposta na conversa, qual numero ficou de pe e decisao da conversa — nao de um
    default. O campo continua NULL (e o painel mostra que falta), nunca o preco cheio por cima de
    um desconto que ela ofereceu."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Triagem", intencao="agendamento", duracao_horas=Decimal("1")
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await conn.execute(
        "UPDATE barravips.atendimentos SET n_contrapropostas = 1 WHERE id = %s", (atendimento_id,)
    )
    await _seed_fala_da_ia(conn, atendimento_id, "400 1h no meu local")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"proxima_acao_esperada": "confirmar", "sinais_qualificacao": {"aceita_valor": True}},
    )

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["valor_acordado"] is None


@pytest.mark.needs_db
async def test_hora_dele_sobre_palpite_realoca_o_bloqueio_sem_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O slot reservado veio de PALPITE (fallback de tempo imediato / hora que a IA ofereceu e ele
    nao respondeu: `horario_evidenciado` false) e agora ELE crava a hora. Isso e o primeiro
    agendamento de fato, nao um reagendamento: a reserva muda de hora, a IA segue conduzindo.

    Sem isto (medido ao vivo em 12/08) a fala do cliente "pode ser 21h hoje" caia na branch 12 —
    escalada, IA pausada e a venda morrendo no turno do fechamento.

    SETUP: com o freio da proveniencia, a FSM nao reserva mais sobre palpite — a reserva sem marca
    e a que o banco JA tem (a coluna nasceu `false`, migration sem backfill) e a que sobra quando a
    marca cai (`true -> false`, valor novo sem evidencia). O teste chega la reservando com a marca
    e derrubando-a: o que a branch precisa e a combinacao "existe reserva + ninguem sustenta a hora
    reservada", nao o caminho que produziu esse par."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_evidenciado = false WHERE id = %s",
        (atendimento_id,),
    )
    res = await conn.execute(
        "SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    bloqueio_do_palpite = row["bloqueio_id"]
    assert bloqueio_do_palpite is not None

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "21:00:00", "proxima_acao_esperada": "confirmar 21h"},
        horario_evidenciado=True,  # o detector do turno viu a hora na fala DELE
    )

    assert resultado["mensagem"].startswith("Extracao registrada")
    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada, bloqueio_id, horario_evidenciado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(21, 0)  # a hora DELE vale
    assert a["ia_pausada"] is False  # nao escalou
    assert a["horario_evidenciado"] is True
    assert a["bloqueio_id"] != bloqueio_do_palpite  # reserva realocada

    res = await conn.execute(
        "SELECT inicio, estado::text AS estado FROM barravips.bloqueios "
        "WHERE atendimento_id = %s ORDER BY created_at",
        (atendimento_id,),
    )
    bloqueios = await res.fetchall()
    assert [b["estado"] for b in bloqueios] == ["cancelado", "bloqueado"]  # o velho soltou o slot
    # `inicio` volta em UTC; 21:00 BRT = 00:00 UTC do dia seguinte.
    assert bloqueios[-1]["inicio"].astimezone(timezone(timedelta(hours=-3))).hour == 21

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_ia_trocando_o_proprio_palpite_nao_move_a_agenda_nem_escala(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A IA oferece "Consigo as 3h" num turno e "Consigo as 2h" no seguinte, sem ele responder:
    ruido dela, nao pedido dele. Nao move a reserva e nao acorda a modelo.

    SETUP: mesma montagem do teste irmao acima (reserva com a marca, marca derrubada em seguida) —
    o freio da proveniencia nao deixa mais a FSM reservar sobre palpite."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(15, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_evidenciado = false WHERE id = %s",
        (atendimento_id,),
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "18:00:00", "proxima_acao_esperada": "reoferta da IA"},
    )

    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada, proxima_acao_esperada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(15, 0)  # reserva intacta
    assert a["ia_pausada"] is False
    assert a["proxima_acao_esperada"] == "reoferta da IA"  # o resto do payload gravou

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


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
        horario_evidenciado=True,  # a hora reservada e a que ele cravou
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
        horario_evidenciado=True,  # a hora e DELE
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
        horario_evidenciado=True,  # a hora e DELE; quem barra e a agenda, nao o freio
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


@pytest.mark.needs_db
async def test_intencao_nao_rebaixa_de_agendamento(conn: AsyncConnection[dict[str, Any]]) -> None:
    """`intencao` e MONOTONICA: o COALESCE incremental deixava o extrator barato rebaixar
    'agendamento' -> 'cotacao' no turno seguinte, devolvendo o slot "ele querer mesmo marcar" ao
    belief e prendendo o atendimento em Triagem (#35, 24/07)."""
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="agendamento")

    await registrar_extracao_ia(
        conn, str(atendimento_id), {"intencao": "cotacao", "proxima_acao_esperada": "cotar"}
    )

    res = await conn.execute(
        "SELECT intencao::text AS intencao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["intencao"] == "agendamento"  # nao rebaixou


@pytest.mark.needs_db
async def test_intencao_rebaixa_com_limpar_explicito(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O canal do RECUO continua aberto: `limpar` tem precedencia sobre a monotonicidade -- e o
    jeito de o cliente que desmarcou desqualificar o atendimento (DESC do campo)."""
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="agendamento")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"limpar": ["intencao"], "proxima_acao_esperada": "cliente recuou"},
    )

    res = await conn.execute(
        "SELECT intencao::text AS intencao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["intencao"] is None


@pytest.mark.needs_db
async def test_intencao_sobe_normalmente(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Monotonicidade nao trava a SUBIDA: cotacao -> agendamento grava normal."""
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="cotacao")

    await registrar_extracao_ia(
        conn, str(atendimento_id), {"intencao": "agendamento", "proxima_acao_esperada": "fechar"}
    )

    res = await conn.execute(
        "SELECT intencao::text AS intencao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["intencao"] == "agendamento"


@pytest.mark.needs_db
async def test_flip_de_tipo_pos_bloqueio_nao_grava_nem_cobra_pix(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """#41 (24/07 10:19): interno ja combinado, com slot reservado; o cliente insiste que ela va
    ate ele e o extrator grava `tipo_atendimento=externo` — a propria prosa do payload dizia
    "estou recusando". Bastava o flip ser gravado para o bloco deterministico de Pix (independente
    da transicao) cobrar R$100 de deslocamento num encontro que seguia sendo no local dela."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,  # a hora e DELE: e ela que autoriza a reserva
    )
    # 1º turno: crava o horario -> Aguardando_confirmacao + bloqueio previo (o tipo fica combinado).
    await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar o encontro"}
    )
    res = await conn.execute(
        "SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    assert (await res.fetchone() or {})["bloqueio_id"] is not None

    # 2º turno: o pedido dele chega como tipo_atendimento=externo. A modelo ACEITA externo — a
    # guarda de tipo-aceito passa reto, e era por aqui que o flip entrava.
    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"tipo_atendimento": "externo", "proxima_acao_esperada": "recusando ir ate ele"},
    )

    assert "pix_solicitado" not in resultado
    res = await conn.execute(
        "SELECT tipo_atendimento::text AS tipo, pix_status::text AS pix_status "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["tipo"] == "interno"  # o combinado continua valendo
    assert a["pix_status"] != "aguardando"

    # O descarte fica auditavel no evento (mesmo principio do drift_descartado da branch 12).
    # Sem ORDER BY: os dois turnos rodam na MESMA transacao e `now()` e o timestamp da
    # TRANSACAO — os dois eventos empatam em `created_at` e `eventos[-1]` seria sorteio.
    # (uuidv7 desempataria AQUI — os inserts distam >1ms — mas nao e garantia no caso geral:
    # dentro do mesmo ms o sufixo e aleatorio.)
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos "
        "WHERE atendimento_id = %s AND tipo = 'extracao_registrada'",
        (atendimento_id,),
    )
    eventos = await res.fetchall()
    descartes = [
        e["payload"]["tipo_descartado"] for e in eventos if "tipo_descartado" in e["payload"]
    ]
    assert descartes == [{"pedido": "externo", "mantido": "interno"}]


@pytest.mark.needs_db
async def test_flip_de_tipo_em_aguardando_sem_bloqueio_tambem_e_descartado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesmo flip do #41 no atendimento sem bloqueio previo (borda): `Aguardando_confirmacao` ja
    significa horario combinado, entao o tipo ja esta combinado mesmo sem o bloqueio."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 1),
        duracao_horas=Decimal("1"),
    )
    res = await conn.execute(
        "SELECT bloqueio_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    assert (await res.fetchone() or {})["bloqueio_id"] is None

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"tipo_atendimento": "externo", "proxima_acao_esperada": "recusando ir ate ele"},
    )

    assert "pix_solicitado" not in resultado
    res = await conn.execute(
        "SELECT tipo_atendimento::text AS tipo FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    assert (await res.fetchone() or {})["tipo"] == "interno"


@pytest.mark.needs_db
async def test_tipo_sem_bloqueio_ainda_e_gravado(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O descarte e ESTREITO: sem slot reservado o tipo ainda esta sendo decidido, e a extracao
    continua sendo quem o grava (senao o atendimento nunca sai da triagem)."""
    _, atendimento_id = await _seed_par(conn, estado="Triagem", intencao="cotacao")

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"tipo_atendimento": "externo", "proxima_acao_esperada": "pegar o endereco dele"},
    )

    res = await conn.execute(
        "SELECT tipo_atendimento::text AS tipo FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    assert (await res.fetchone() or {})["tipo"] == "externo"


@pytest.mark.needs_db
async def test_cotacao_dita_em_novo_ancora_o_fechamento_dois_turnos_depois(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A IA cota na PRIMEIRA bolha ("400 1h no meu local"), quando o atendimento ainda esta em
    `Novo` — o backstop de carimbo do ADR 0022 exigia `Triagem`/`Qualificado` e o preco dito nao
    ancorava nada. Dois turnos depois, o cliente cravava a hora, a transicao para
    `Aguardando_confirmacao` batia em `CotacaoAusente`, a transacao revertia INTEIRA e a hora se
    perdia — com a IA dizendo "Confirmado amor" sobre um banco sem reserva (medido ao vivo 12/08).
    """
    agora = datetime(2026, 12, 1, 9, 0, tzinfo=BRT)
    _, atendimento_id = await _seed_par(conn, cotou=False)  # estado Novo, sem carimbo

    carimbou = await carimbar_cotacao_por_texto_enviado(conn, atendimento_id, "400 1h no meu local")
    assert carimbou is True

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "intencao": "agendamento",
            "tipo_atendimento": "interno",
            # A data e AMANHA de verdade, calculada do relogio, e nao a data em que este teste
            # foi escrito. Cravada, ela virou uma bomba-relogio: passou a ser passado, a reserva
            # passou a bater em `AntecedenciaInsuficiente` — que e a conduta CERTA para uma hora
            # que ja foi — e o teste reprovou o codigo por acertar.
            "data_desejada": (agora + timedelta(days=1)).date().isoformat(),
            "horario_desejado": "22:00",
            "duracao_horas": "1",
            "proxima_acao_esperada": "confirmar o encontro de amanha 22h",
        },
        agora=agora,
        horario_evidenciado=True,  # "amanha 22h" saiu da boca DELE neste turno
    )

    assert resultado["novo_estado"] == "Aguardando_confirmacao"
    res = await conn.execute(
        "SELECT horario_desejado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(22, 0)


@pytest.mark.needs_db
async def test_upgrade_de_pacote_recota_pela_tabela_em_vez_de_reverter(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Cliente com 1h/400 fechado pede 2h: a extracao registra a duracao nova e esquece o valor, e
    a guarda do par revertia o turno INTEIRO — a auto-reoferta batia no mesmo erro e o cliente que
    estava dobrando o ticket recebia silencio (medido ao vivo 12/08, 4 de 5 conversas). O preco nao
    e improvisado: e a unica linha da tabela para 2h e a IA acabou de cota-lo na fala do turno."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("700"))
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 400 WHERE id = %s", (atendimento_id,)
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"duracao_horas": "2", "proxima_acao_esperada": "confirmar o upgrade para 2h"},
        fala_da_ia_no_turno="Da certo sim amor / 2h fica 700 / Seguimos as 21h ?",
    )

    res = await conn.execute(
        "SELECT duracao_horas, valor_acordado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert (a["duracao_horas"], a["valor_acordado"]) == (Decimal("2"), Decimal("700"))


@pytest.mark.needs_db
async def test_upgrade_sem_a_ia_ter_cotado_o_periodo_novo_segue_revertendo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O contrapeso: sem o preco novo na boca da IA, o re-cote nao acontece e a guarda continua
    valendo — vender periodo por preco improvisado e exatamente o prejuizo que ela impede."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(conn, modelo_id, horas=Decimal("2"), preco=Decimal("700"))
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 400 WHERE id = %s", (atendimento_id,)
    )

    with pytest.raises(ParPrecoDuracaoInvalido):
        await registrar_extracao_ia(
            conn,
            str(atendimento_id),
            {"duracao_horas": "2", "proxima_acao_esperada": "confirmar o upgrade para 2h"},
            fala_da_ia_no_turno="Da certo sim amor / seguimos as 21h ?",
        )


@pytest.mark.needs_db
async def test_remarcacao_segura_realoca_em_vez_de_escalar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Hora COMBINADA por ele (evidenciada) e ele mesmo muda, com a modelo ainda nao acionada:
    ajuste de agenda, nao evento que mereca acordar ninguem (decisao do operador, 12/08). Escalar
    ali matava 5 de 5 conversas do roteiro `remarcou` e a hora nova nem era gravada."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "22:00:00", "proxima_acao_esperada": "confirmar 22h"},
        horario_evidenciado=True,  # a hora nova saiu da boca DELE neste turno
    )

    assert resultado["mensagem"].startswith("Extracao registrada")
    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(22, 0)
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE atendimento_id = %s "
        "ORDER BY created_at",
        (atendimento_id,),
    )
    assert [b["estado"] for b in await res.fetchall()] == ["cancelado", "bloqueado"]


@pytest.mark.needs_db
@pytest.mark.parametrize(
    ("coluna", "valor"),
    [("aviso_saida_em", "now()"), ("pix_status", "'enviado'::barravips.pix_status_enum")],
)
async def test_remarcacao_com_a_modelo_ja_acionada_continua_escalando(
    conn: AsyncConnection[dict[str, Any]], coluna: str, valor: str
) -> None:
    """O contrapeso da remarcacao segura: cliente a caminho (aviso de saida) ou Pix em andamento
    significam que o encontro saiu do papel — mudar a hora ali e' decisao da modelo, nao da IA."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=True,
    )
    await registrar_extracao_ia(conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"})
    await conn.execute(
        f"UPDATE barravips.atendimentos SET {coluna} = {valor} WHERE id = %s", (atendimento_id,)
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"horario_desejado": "22:00:00", "proxima_acao_esperada": "remarcar"},
        horario_evidenciado=True,
    )

    res = await conn.execute(
        "SELECT horario_desejado, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(20, 0)  # preservado
    assert a["ia_pausada"] is True


@pytest.mark.needs_db
async def test_pivo_para_remoto_nao_deixa_o_backstop_gravar_o_preco_presencial(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Backstop de preco CEGO ao tipo (revisao de isolamento de dominio, loop-massa r3).

    Cadastro real da Catarina: Normal 1h 400 e vídeo chamada 1h 150, MESMA duracao. O cliente pivota
    para a chamada e fecha; `valor_acordado` chega NULL e o backstop do pacote fechado resolve a
    linha pela `_linhas_de_tabela`, que e `apenas_presenciais=True` FIXO — a chamada some da leitura,
    sobra UMA linha (400) e o backstop gravaria o preco PRESENCIAL numa venda remota de 150. Dai o
    `_solicitar_pix_deslocamento_se_aplicavel` cobra o Pix ANTECIPADO da chamada por 400.

    Fail-closed: no remoto o backstop nao preenche, e o valor certo entra pela extracao do turno
    seguinte. O irmao abaixo prova que o freio e so do remoto."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        aceita=["interno", "remoto"],
        estado="Qualificado",
        tipo_atendimento="remoto",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(
        conn,
        modelo_id,
        horas=Decimal("1"),
        preco=Decimal("150"),
        preco_minimo=Decimal("150"),
        nome="Vídeo chamada",
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "confirmar a chamada",
        },
        fala_da_ia_no_turno="A hora presencial fica 400 amor, e a video chamada 150",
    )

    res = await conn.execute(
        "SELECT valor_acordado, pix_status::text AS pix_status "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None  # o 400 presencial NAO entra numa chamada
    assert a["pix_status"] != "aguardando"  # e ninguem cobra Pix de um valor que nao existe


@pytest.mark.needs_db
async def test_no_presencial_o_backstop_do_pacote_fechado_continua_preenchendo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O negativo do freio acima: mesmo cadastro, mesmo turno, tipo INTERNO — o backstop segue
    gravando o preco da tabela que a IA cotou (era o caso que ele existe para cobrir: fechamento
    sem preco, 6 de 35 conversas medidas em 12/08)."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        aceita=["interno", "remoto"],
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))
    await _seed_programa(
        conn,
        modelo_id,
        horas=Decimal("1"),
        preco=Decimal("150"),
        preco_minimo=Decimal("150"),
        nome="Vídeo chamada",
    )

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True},
            "proxima_acao_esperada": "confirmar o encontro",
        },
        fala_da_ia_no_turno="A hora fica 400 amor",
    )

    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None and a["valor_acordado"] == Decimal("400")


@pytest.mark.needs_db
async def test_descarte_por_piso_derruba_o_aceite_do_mesmo_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Simetria com `_sem_valor_fantasma` (revisao de isolamento de dominio, loop-massa r3).

    "fecho por 250 as 21h": o numero e o aceite saem do MESMO evento. A guarda do piso recusa o 250
    e, ate a r3, deixava `aceita_valor` vivo — um aceite sem valor nenhum. Quem lia isso em seguida
    era o backstop do pacote fechado (`_preco_cotado_do_pacote_fechado` le o `aceita_valor` DO
    TURNO): o piso recusava o numero dele e o sistema gravava o preco CHEIO da tabela como venda
    combinada, na mesma transacao. O aceite cai junto; os outros sinais ficam."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "250",
            "duracao_horas": "1",
            "sinais_qualificacao": {"aceita_valor": True, "informa_local": True},
            "proxima_acao_esperada": "contrapor pela escada",
        },
        fala_da_ia_no_turno="A hora fica 400 amor",
    )

    res = await conn.execute(
        "SELECT valor_acordado, sinais_qualificacao FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] is None  # nem o 250 recusado nem o 400 cheio pelo backstop
    sinais = a["sinais_qualificacao"] or {}
    assert not sinais.get("aceita_valor")  # o aceite saiu do mesmo evento falso
    assert sinais.get("informa_local") is True  # e so ele


@pytest.mark.needs_db
async def test_duracao_off_menu_nao_faz_o_piso_escalar_um_valor_que_e_o_proprio_piso(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`objetor_a` #6, o outro lado do descarte de cardapio (finalizacao da r3).

    O cliente PERGUNTOU 30 min, a IA RECUSOU e a extracao gravou `duracao_horas=0.5` mesmo assim,
    junto de um valor que e EXATAMENTE o piso da 1h em curso (300 = 25% sobre 400). Sem o descarte
    ANTES do gate do piso, `_abaixo_do_piso` resolve o piso sobre a 0.5 — que nao tem linha —,
    `_piso_do_pacote` devolve `(None, "sem_linha")` e o `abaixo = piso is None or ...` sai True por
    ausencia de tabela: escalada `fora_de_oferta` e IA PAUSADA sobre uma venda legitima.

    Este e o teste que segura a DISJUNCAO: o descarte roda cedo no ramo COM valor (onde a guarda do
    par preco x duracao e impossivel por construcao) e tarde no ramo sem valor (onde ela e o ponto
    inteiro). O irmao `test_duracao_muda_sem_valor_par_abaixo_do_piso_erro_recuperavel` pina o
    outro lado da mesma moeda — e os dois so passam juntos com os dois pontos de aplicacao.

    `n_contrapropostas=1` de proposito: com a escada intacta o descarte silencioso do H3 mascararia
    o defeito (nao escalaria de qualquer forma). A rodada JOGADA e o caso em que ele morde."""
    modelo_id, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        duracao_horas=Decimal("1"),
        n_contrapropostas=1,
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {
            "valor_acordado": "300",
            "duracao_horas": "0.5",
            "proxima_acao_esperada": "cravar o horario",
        },
        fala_da_ia_no_turno="Consigo 300 amor",
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT valor_acordado, duracao_horas, ia_pausada FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["valor_acordado"] == Decimal("300")  # a venda legitima e gravada
    assert a["duracao_horas"] == Decimal("1")  # a 0.5 off-menu nao entra; vale a persistida
    assert a["ia_pausada"] is False

    res = await conn.execute(
        "SELECT count(*) AS n FROM barravips.escaladas WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    esc = await res.fetchone()
    assert esc is not None and esc["n"] == 0


@pytest.mark.needs_db
async def test_duracao_off_menu_sem_valor_no_payload_nao_e_gravada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O outro ponto de aplicacao do MESMO veredito — o ramo SEM valor, depois da guarda do par.

    Sem valor no payload e sem valor persistido, a guarda do par nao tem par a conferir e passa
    reto; o descarte tardio e quem impede a `duracao_horas=0.5` de virar snapshot. Este pin existia
    so como unidade sobre o predicado (`test_duracao_fora_do_cardapio.py`): o caminho fim-a-fim, que
    e onde a ORDEM importa, nao estava coberto — desligar o sitio tardio deixava a suite inteira
    verde."""
    modelo_id, atendimento_id = await _seed_par(
        conn, estado="Qualificado", tipo_atendimento="interno", intencao="agendamento"
    )
    await _seed_programa(conn, modelo_id, horas=Decimal("1"), preco=Decimal("400"))

    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"duracao_horas": "0.5", "proxima_acao_esperada": "recusar o pacote de 30 min"},
    )

    assert resultado["mensagem"] not in MENSAGENS_GUARD_ESCALADA

    res = await conn.execute(
        "SELECT duracao_horas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["duracao_horas"] is None  # o pacote que ela nao vende nao entra no snapshot


# --- palpite recusado sai do snapshot (P0 externo_a, prova r3) --------------------------------


@pytest.mark.needs_db
async def test_horario_palpite_recusado_e_retirado_do_snapshot(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A raiz do latch da prova r3: `21:00` gravado pelo fallback de tempo imediato (palpite,
    `horario_evidenciado=false`), o tipo flipou para externo, o piso subiu e a reserva passou a
    recusar. O texto do erro manda a IA NAO registrar a hora que vai ofertar — e o `COALESCE`
    preserva o valor recusado. `retirar_horario_palpite` e o que desarma isso."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        horario_desejado=time(21, 0),
        data_desejada=date(2026, 12, 3),
        horario_evidenciado=False,
    )

    assert await retirar_horario_palpite(conn, atendimento_id, motivo="antecedencia_insuficiente")

    res = await conn.execute(
        "SELECT horario_desejado, horario_evidenciado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] is None
    assert a["horario_evidenciado"] is False
    # E o registro seguinte NAO ressuscita o valor: sem hora no snapshot, o `COALESCE` nao tem o
    # que preservar e a FSM nao re-tenta a reserva invalida.
    resultado = await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "reofertar 22h"}
    )
    assert resultado["novo_estado"] is None
    res = await conn.execute(
        "SELECT horario_desejado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["horario_desejado"] is None
    # Audit log: a retirada e uma decisao do sistema sobre o dado, tem de deixar rastro.
    res = await conn.execute(
        "SELECT payload FROM barravips.eventos WHERE atendimento_id = %s AND "
        "tipo = 'correcao_registro'",
        (atendimento_id,),
    )
    evento = await res.fetchone()
    assert evento is not None
    assert evento["payload"]["campo"] == "horario_desejado"


@pytest.mark.needs_db
async def test_hora_evidenciada_pelo_cliente_nao_e_retirada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """So PALPITE morre. A hora que saiu da boca dele fica gravada mesmo quando a agenda a recusa —
    o snapshot tem de continuar dizendo o que ele pediu; quem recusa e a conduta da fala."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="externo",
        intencao="agendamento",
        horario_desejado=time(21, 0),
        horario_evidenciado=True,
    )

    assert not await retirar_horario_palpite(conn, atendimento_id, motivo="antecedencia")

    res = await conn.execute(
        "SELECT horario_desejado FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    a = await res.fetchone()
    assert a is not None and a["horario_desejado"] == time(21, 0)


@pytest.mark.needs_db
async def test_palpite_com_reserva_de_pe_nao_e_retirado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagar a hora com bloqueio de pe deixaria o bloqueio ORFAO travando a agenda — o mesmo medo
    que `liberar_bloqueio_previo` resolve na remarcacao aberta. Quem solta reserva e aquele
    caminho, nunca este."""
    _, atendimento_id = await _seed_par(
        conn,
        estado="Qualificado",
        tipo_atendimento="interno",
        intencao="agendamento",
        horario_desejado=time(20, 0),
        data_desejada=date(2026, 12, 3),
        duracao_horas=Decimal("1"),
        horario_evidenciado=False,
    )
    # Cria a reserva pelo caminho normal (FSM -> Aguardando_confirmacao + bloqueio).
    await registrar_extracao_ia(
        conn, str(atendimento_id), {"proxima_acao_esperada": "confirmar"}, horario_evidenciado=True
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET horario_evidenciado = false WHERE id = %s",
        (atendimento_id,),
    )

    assert not await retirar_horario_palpite(conn, atendimento_id, motivo="antecedencia")

    res = await conn.execute(
        "SELECT horario_desejado, bloqueio_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["horario_desejado"] == time(20, 0)
    assert a["bloqueio_id"] is not None
