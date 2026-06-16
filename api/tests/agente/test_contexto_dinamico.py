"""M1-T2 (B) — contexto dinâmico concatenado no último HumanMessage (02 §5).

Chama `prepare_context` direto com um fake runtime (fake-pool de UMA conexão). Verifica que o
estado do atendimento (#7/Qualificado/externo), o cliente e a linha da agenda 48h aparecem SÓ
no último HumanMessage, e que o prefixo cacheável (SystemMessage) fica INTACTO. needs_db: lê o
Postgres real, ROLLBACK sempre (espelha test_repo_integracao.py).
"""

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _fakes import FakeRuntime
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import prepare_context


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


class _PoolDeUmaConexao:
    """Pool fake de UMA conexao: prepare_context le a MESMA transacao da fixture (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["externo"]),
    )
    return modelo_id


async def _seed_cliente(connection: AsyncConnection[dict[str, Any]], nome: str) -> UUID:
    cliente_id = uuid4()
    await connection.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", nome),
    )
    return cliente_id


async def _seed_conversa(
    connection: AsyncConnection[dict[str, Any]],
    cliente_id: UUID,
    modelo_id: UUID,
    *,
    recorrente: bool,
    observacoes_internas: str,
) -> UUID:
    conversa_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.conversas
            (id, cliente_id, modelo_id, evolution_chat_id, recorrente, observacoes_internas)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            conversa_id,
            cliente_id,
            modelo_id,
            f"test-chat-{uuid4().hex}",
            recorrente,
            observacoes_internas,
        ),
    )
    return conversa_id


async def _seed_atendimento(
    connection: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
) -> UUID:
    atendimento_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento)
        VALUES (%s, 7, %s, %s, %s, 'Qualificado', 'externo')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _inserir_mensagem(
    connection: AsyncConnection[dict[str, Any]], *, conversa_id: UUID, conteudo: str
) -> None:
    await connection.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'texto', %s, %s)
        """,
        (uuid4(), conversa_id, conteudo, f"test-evo-{uuid4().hex}"),
    )


async def _inserir_bloqueio_48h(
    connection: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, offset_horas: int, estado: str
) -> None:
    """Bloqueio ativo daqui a `offset_horas` (dentro das 48h). now() em SQL evita skew de relógio."""
    await connection.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem)
        VALUES (%s, %s, now() + make_interval(hours => %s), now() + make_interval(hours => %s),
                %s, 'manual')
        """,
        (uuid4(), modelo_id, offset_horas, offset_horas + 1, estado),
    )


async def _seed_disponibilidade(
    connection: AsyncConnection[dict[str, Any]],
    modelo_id: UUID,
    *,
    dia_semana: int,
    hora_inicio: str,
    hora_fim: str,
) -> None:
    """Regra de Disponibilidade (gate do `proximo_livre`). hora_fim == hora_inicio = 24h (ADR 0005)."""
    await connection.execute(
        """
        INSERT INTO barravips.modelo_disponibilidade
            (id, modelo_id, data_inicio, dia_semana, hora_inicio, hora_fim)
        VALUES (%s, %s, current_date - 7, %s, %s, %s)
        """,
        (uuid4(), modelo_id, dia_semana, hora_inicio, hora_fim),
    )


def _texto_system(msg: SystemMessage) -> str:
    """Concatena o texto dos content blocks do SystemMessage (content e lista no formato 1.x)."""
    if isinstance(msg.content, str):
        return msg.content
    return "".join(b.get("text", "") for b in msg.content if isinstance(b, dict))


@pytest.mark.needs_db
async def test_contexto_dinamico_no_ultimo_humanmessage(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn, nome="Carlos")
    conversa_id = await _seed_conversa(
        conn,
        cliente_id,
        modelo_id,
        recorrente=True,
        observacoes_internas="cliente VIP, sempre fecha rápido",
    )
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id, conteudo="oi, tudo bem?")
    # 2 bloqueios nao-sobrepostos em 48h: prova que cada um sai em sua propria linha (fix do template).
    await _inserir_bloqueio_48h(conn, modelo_id, offset_horas=3, estado="bloqueado")
    await _inserir_bloqueio_48h(conn, modelo_id, offset_horas=10, estado="em_atendimento")

    ctx = ContextAgente(
        db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=str(uuid4()),
    )
    res = await prepare_context({"messages": []}, FakeRuntime(ctx))

    assert isinstance(res, Command)
    assert res.goto == "intercept_disclosure"
    msgs = res.update["messages"]

    # o contexto dinamico vive no ULTIMO HumanMessage, DEPOIS da msg do cliente.
    ultimo_human = [m for m in msgs if isinstance(m, HumanMessage)][-1]
    assert ultimo_human.content.startswith("oi, tudo bem?")
    assert "#7" in ultimo_human.content
    assert "Qualificado" in ultimo_human.content
    assert "externo" in ultimo_human.content
    assert "Carlos" in ultimo_human.content
    # belief-state: Qualificado com tipo preenchido (externo) mas sem horario_desejado -> o item
    # faltante aparece EXPLICITO em <ainda_falta>, e o proximo passo determinístico vem do estado.
    assert "<situacao_do_atendimento" in ultimo_human.content
    assert "o dia e o horário" in ultimo_human.content
    assert "<proximo_passo>" in ultimo_human.content
    # data atual (04 §2.1): ancora "hoje" no contexto dinamico p/ a IA escrever datas absolutas
    # em consultar_agenda. Vem do banco (current_date) -> assertar o formato YYYY-MM-DD, nao o
    # valor exato (depende do relogio/fuso do banco).
    assert re.search(r'hoje="\d{4}-\d{2}-\d{2}"', str(ultimo_human.content))
    # as linhas dos bloqueios das 48h aparecem como tags XML <bloqueio .../> (uma por linha),
    # guarda contra a regressao do for-loop grudado (02 §5).
    linhas_bloqueio = [
        ln
        for ln in ultimo_human.content.splitlines()
        if ln.startswith("<bloqueio ") and 'estado="ocupado"' in ln
    ]
    assert len(linhas_bloqueio) == 2
    # o estado bruto (bloqueado/em_atendimento) NUNCA chega ao LLM — vira "ocupado"
    assert 'estado="em_atendimento"' not in ultimo_human.content
    assert 'estado="bloqueado"' not in ultimo_human.content
    assert "disponibilidade total" not in ultimo_human.content.lower()

    # prefixo cacheavel INTACTO: nenhum SystemMessage recebeu o texto do contexto dinamico.
    systems = [m for m in msgs if isinstance(m, SystemMessage)]
    assert systems
    for s in systems:
        assert "<situacao_do_atendimento" not in _texto_system(s)


async def _montar_ctx_com_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> tuple[UUID, ContextAgente]:
    """Seed mínimo (modelo/cliente/conversa/atendimento/msg + 1 bloqueio em 48h) p/ checar o render."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn, nome="Carlos")
    conversa_id = await _seed_conversa(
        conn, cliente_id, modelo_id, recorrente=False, observacoes_internas=""
    )
    atendimento_id = await _seed_atendimento(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    await _inserir_mensagem(conn, conversa_id=conversa_id, conteudo="consegue hj 22h?")
    await _inserir_bloqueio_48h(conn, modelo_id, offset_horas=3, estado="bloqueado")
    ctx = ContextAgente(
        db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_id),
        atendimento_id=str(atendimento_id),
        cliente_id=str(cliente_id),
        turno_id=str(uuid4()),
    )
    return modelo_id, ctx


def _linha_bloqueio(content: str) -> str:
    return next(ln for ln in content.splitlines() if ln.startswith("<bloqueio "))


@pytest.mark.needs_db
async def test_proximo_livre_renderiza_quando_dentro_da_disponibilidade(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Disponibilidade total (7 dias, 24h): o slot adjacente ao bloqueio sempre cai numa janela ->
    # o atributo proximo_livre é renderizado no <bloqueio>.
    modelo_id, ctx = await _montar_ctx_com_bloqueio(conn)
    for dow in range(7):
        await _seed_disponibilidade(
            conn, modelo_id, dia_semana=dow, hora_inicio="00:00", hora_fim="00:00"
        )

    res = await prepare_context({"messages": []}, FakeRuntime(ctx))
    assert isinstance(res, Command)
    ultimo_human = [m for m in res.update["messages"] if isinstance(m, HumanMessage)][-1]
    assert "proximo_livre=" in _linha_bloqueio(str(ultimo_human.content))


@pytest.mark.needs_db
async def test_proximo_livre_ausente_fora_da_disponibilidade(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Regra só num dia da semana distante do bloqueio (now()+3h) e do seu slot adjacente:
    # o gate barra e o atributo proximo_livre NÃO é renderizado.
    modelo_id, ctx = await _montar_ctx_com_bloqueio(conn)
    res_now = await conn.execute("SELECT (now() AT TIME ZONE 'America/Sao_Paulo') AS agora")
    agora_row = await res_now.fetchone()
    assert agora_row is not None
    dow_hoje = (agora_row["agora"].weekday() + 1) % 7  # Python weekday -> DOW Postgres
    dow_distante = (dow_hoje + 3) % 7
    await _seed_disponibilidade(
        conn, modelo_id, dia_semana=dow_distante, hora_inicio="00:00", hora_fim="00:00"
    )

    res = await prepare_context({"messages": []}, FakeRuntime(ctx))
    assert isinstance(res, Command)
    ultimo_human = [m for m in res.update["messages"] if isinstance(m, HumanMessage)][-1]
    linha = _linha_bloqueio(str(ultimo_human.content))
    assert 'estado="ocupado"' in linha
    assert "proximo_livre=" not in linha
