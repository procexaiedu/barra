"""F0.3 — Invariante cross-modelo: o montador + as tools NUNCA trazem dado do par B na entrada.

CONTEXT.md ("IA por modelo") + agente/CLAUDE.md ("Isolamento por par"): a IA da modelo A nunca
enxerga histórico/contexto do MESMO cliente com a modelo B. Toda função que carrega
contexto/histórico recebe `(cliente_id, modelo_id)` JUNTOS; uma regressão que filtrasse só por
`cliente_id` (ou que esquecesse o `modelo_id`) vazaria o par B na entrada do agente.

Este teste é um CANARY de regressão: semeia o par B (MESMO cliente, modelo distinta) com um token
sentinela (`_CANARIO`) espalhado nas superfícies que a IA poderia ler — janela de mensagens,
`observacoes_internas` da conversa, atendimento terminal (histórico), bloqueios de agenda — e então
roda o montador inteiro (`prepare_context`) e a tool `consultar_agenda` ESCOPADOS AO PAR A. Falha se
o token (ou qualquer marca do par B) aparecer no contexto montado ou no retorno da tool.

needs_db de propósito: o isolamento é garantido pelas cláusulas `WHERE cliente_id=%s AND
modelo_id=%s` no SQL real — um `FakeConn` devolve o que lhe dão e NÃO consegue provar a filtragem.
Espelha o rig de test_repo_integracao.py / test_consultar_agenda.py: conexão de TEST_DATABASE_URL,
ROLLBACK sempre no teardown (nada commita em prod), fake-pool de UMA conexão p/ o montador e a tool
lerem na MESMA transação semeada. Pós-F0.1 roda no Postgres efêmero do CI — gate de PR de verdade.

Âncoras anti-vácuo (`_MARCO_A`): provam que o montador de fato produziu o contexto DO par A — sem
elas, "o canário não apareceu" poderia ser um verde vazio (montador que não carregou nada).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import BaseMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.contexto import ContextAgente
from barra.agente.ferramentas.leitura import consultar_agenda
from barra.agente.nos.prepare_context import prepare_context

# Token sentinela do par B: só aparece em registros do par (cliente, modelo_B). Se vazar no
# contexto/args do par A, o isolamento regrediu.
_CANARIO = "CANARIO_PAR_B_NAO_PODE_VAZAR"
# Marca do par A: tem que aparecer no contexto do par A (âncora anti-vácuo).
_MARCO_A = "MARCO_PAR_A_PRESENTE"

# .coroutine = corrotina crua do @tool; .ainvoke({...}) NÃO injeta runtime, .coroutine sim.
_chamar_agenda = consultar_agenda.coroutine  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    """Conexão numa transação isolada; ROLLBACK no teardown (nada persiste em prod).

    Config de core/db.py que importa p/ a leitura: row_factory=dict_row (o montador e a tool
    acessam linha["coluna"]) e prepare_threshold=None (Supavisor transaction mode). Ver
    test_repo_integracao.py.
    """
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
    """Pool fake de UMA conexão: o montador/tool leem na MESMA transação da fixture (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn  # não fecha, não commita (a fixture faz rollback)


class _Runtime:
    """Runtime mínimo (nó/tool leem só `.context`)."""

    def __init__(self, context: Any) -> None:
        self.context = context


# --- seed helpers (mínimo de colunas NOT NULL/CHECK do 0001; únicos via uuid p/ não colidir) ---


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Compartilhado"),
    )
    return cliente_id


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], nome: str) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID, observacoes: str | None
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas
            (id, cliente_id, modelo_id, evolution_chat_id, observacoes_internas)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}", observacoes),
    )
    return conversa_id


async def _inserir_mensagem(
    c: AsyncConnection[dict[str, Any]],
    *,
    conversa_id: UUID,
    direcao: str,
    conteudo: str,
    created_at: datetime,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, evolution_message_id, created_at)
        VALUES (%s, %s, %s, 'texto', %s, %s, %s)
        """,
        (uuid4(), conversa_id, direcao, conteudo, f"test-evo-{uuid4().hex}", created_at),
    )


async def _inserir_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    numero_curto: int,
    estado: str,
    valor_final: int | None = None,
    motivo_perda: str | None = None,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, valor_final, motivo_perda)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            atendimento_id,
            numero_curto,
            cliente_id,
            modelo_id,
            conversa_id,
            estado,
            valor_final,
            motivo_perda,
        ),
    )
    return atendimento_id


async def _inserir_bloqueio_48h(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> None:
    """Bloqueio avulso (sem atendimento) dentro das próximas 48h — janela que o montador lê."""
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem)
        VALUES (%s, %s, now() + interval '2 hours', now() + interval '4 hours', 'bloqueado', 'manual')
        """,
        (uuid4(), modelo_id),
    )


def _texto_de_mensagens(msgs: list[BaseMessage]) -> str:
    """Achata o conteúdo de TODAS as mensagens do contexto montado (system + janela + cauda).

    Todas as mensagens saem como string pura (cache do DeepSeek é automático, sem content-blocks);
    o ramo `list` fica defensivo. Junta tudo p/ buscar o canário em qualquer parte do prompt
    entregue ao LLM.
    """
    partes: list[str] = []
    for m in msgs:
        conteudo = m.content
        if isinstance(conteudo, str):
            partes.append(conteudo)
        elif isinstance(conteudo, list):
            for bloco in conteudo:
                if isinstance(bloco, dict):
                    partes.append(str(bloco.get("text", "")))
                else:
                    partes.append(str(bloco))
    return "\n".join(partes)


async def _montar_par_a_e_par_b(
    c: AsyncConnection[dict[str, Any]],
) -> tuple[UUID, UUID, UUID]:
    """Semeia MESMO cliente com duas modelos. Par B leva o canário em toda superfície legível;
    par A leva as âncoras. Devolve (cliente_id, modelo_a, atendimento_a)."""
    cliente_id = await _seed_cliente(c)
    modelo_a = await _seed_modelo(c, "Bia")
    modelo_b = await _seed_modelo(c, f"{_CANARIO} Modelo B")

    conversa_a = await _seed_conversa(c, cliente_id, modelo_a, f"{_MARCO_A} acompanhar retorno")
    conversa_b = await _seed_conversa(c, cliente_id, modelo_b, f"{_CANARIO} nota interna do par B")

    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    # Par A: 2 mensagens (cliente + ia) — janela ≥ 2 ativa o cache na penúltima; âncora no cliente.
    await _inserir_mensagem(
        c,
        conversa_id=conversa_a,
        direcao="cliente",
        conteudo=f"{_MARCO_A} oi sou do par A",
        created_at=base,
    )
    await _inserir_mensagem(
        c,
        conversa_id=conversa_a,
        direcao="ia",
        conteudo="oi amor",
        created_at=base,
    )
    # Par B: mensagem com canário — não pode entrar na janela do par A.
    await _inserir_mensagem(
        c,
        conversa_id=conversa_b,
        direcao="cliente",
        conteudo=f"{_CANARIO} segredo do par B",
        created_at=base,
    )

    # Par A: atendimento aberto (Novo) — gate de pausa passa e o estado resolve.
    atendimento_a = await _inserir_atendimento(
        c,
        cliente_id=cliente_id,
        modelo_id=modelo_a,
        conversa_id=conversa_a,
        numero_curto=1,
        estado="Novo",
    )
    # Par B: atendimento TERMINAL (Fechado, R$5000) — alimenta o histórico do par B. O montador do
    # par A NÃO pode contabilizá-lo (par A não tem terminal -> histórico vazio).
    await _inserir_atendimento(
        c,
        cliente_id=cliente_id,
        modelo_id=modelo_b,
        conversa_id=conversa_b,
        numero_curto=1,
        estado="Fechado",
        valor_final=5000,
    )

    # Bloqueio do par B nas próximas 48h: a agenda do par A tem que sair "livre".
    await _inserir_bloqueio_48h(c, modelo_b)

    return cliente_id, modelo_a, atendimento_a


@pytest.mark.needs_db
async def test_montador_nao_traz_dado_do_par_b(conn: AsyncConnection[dict[str, Any]]) -> None:
    """prepare_context escopado ao par A: o contexto montado não contém NADA do par B.

    Canário: token do par B (janela/observações/modelo) ausente; histórico do par B ("fechou")
    ausente; bloqueio do par B não rouba a agenda (par A sai "livre"). Âncoras: marca do par A
    presente, provando que o montador produziu o contexto certo (não um verde vazio).
    """
    cliente_id, modelo_a, atendimento_a = await _montar_par_a_e_par_b(conn)

    ctx = ContextAgente(
        db_pool=_PoolDeUmaConexao(conn),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(modelo_a),
        atendimento_id=str(atendimento_a),
        cliente_id=str(cliente_id),
        turno_id=str(uuid4()),
    )
    res = await prepare_context({"messages": []}, _Runtime(ctx))  # type: ignore[arg-type, typeddict-item]
    assert res.update is not None
    texto = _texto_de_mensagens(res.update["messages"])

    # Âncoras: o montador de fato carregou o contexto DO par A.
    assert _MARCO_A in texto, "âncora do par A sumiu — o montador não produziu o contexto esperado"

    # Canário: NADA do par B vaza no contexto entregue ao LLM.
    assert _CANARIO not in texto, (
        "VAZAMENTO cross-modelo: dado do par B entrou no contexto do par A "
        "(janela / observações_internas / BP_MODELO filtrado só por cliente_id?)"
    )
    # Histórico do par B (atendimento Fechado) não pode ser contabilizado p/ o par A: o par A só
    # tem atendimento aberto (Novo), então o bloco <historico> (só renderizado com terminal no par)
    # NÃO pode aparecer. Vazaria como "fechou 1x (R$5k)" se a query do histórico furasse o par.
    # Casa a tag de FECHAMENTO: o bloco renderizado (contexto_dinamico.md.j2) sempre emite
    # </historico>, enquanto a prosa do prompt (regras.md.j2) só menciona <historico> inline — usar
    # a tag de abertura daria falso-positivo na prosa.
    assert "</historico>" not in texto, (
        "VAZAMENTO: histórico de atendimento terminal do par B contado no par A"
    )
    # Agenda do par A sai livre: o bloqueio (par B / modelo B) não vazou nas próximas 48h.
    assert "sem bloqueios nas próximas 48h" in texto, (
        "VAZAMENTO: bloqueio de agenda da modelo B apareceu na agenda da modelo A"
    )


@pytest.mark.needs_db
async def test_consultar_agenda_nao_traz_bloqueio_do_par_b(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A tool consultar_agenda escopada à modelo A nunca lista bloqueio da modelo B (mesma janela)."""
    modelo_a = await _seed_modelo(conn, "Bia")
    modelo_b = await _seed_modelo(conn, f"{_CANARIO} Modelo B")

    # Bloqueios em dias DISTINTOS dentro da mesma janela de consulta; horário no meio do dia
    # (evita borda de TZ no inicio::date), sem sobreposição entre modelos.
    await conn.execute(
        "INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem) "
        "VALUES (%s, %s, %s, %s, 'bloqueado', 'manual')",
        (
            uuid4(),
            modelo_a,
            datetime(2026, 6, 10, 14, 0, tzinfo=UTC),
            datetime(2026, 6, 10, 16, 0, tzinfo=UTC),
        ),
    )
    await conn.execute(
        "INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem) "
        "VALUES (%s, %s, %s, %s, 'bloqueado', 'manual')",
        (
            uuid4(),
            modelo_b,
            datetime(2026, 6, 11, 14, 0, tzinfo=UTC),
            datetime(2026, 6, 11, 16, 0, tzinfo=UTC),
        ),
    )

    # `date` direto: a tool tipou os args (92a8c02) e a conversao YYYY-MM-DD -> date e da
    # camada de args do ToolNode, que este call direto na coroutine NAO atravessa.
    out = await _chamar_agenda(
        data_inicio=date(2026, 6, 9),
        data_fim=date(2026, 6, 15),
        runtime=_Runtime(_CtxAgenda(_PoolDeUmaConexao(conn), str(modelo_a))),
    )

    assert out.startswith("Bloqueios:")
    assert out.count("\n- ") == 1, "a agenda da modelo A devia ter exatamente 1 bloqueio (o dela)"
    assert "10/06" in out, "âncora: o bloqueio da própria modelo A devia aparecer"
    # Canário: o bloqueio da modelo B (11/06) jamais entra na agenda da modelo A.
    assert "11/06" not in out, "VAZAMENTO: bloqueio da modelo B apareceu na agenda da modelo A"


class _CtxAgenda:
    """ContextAgente mínimo p/ a tool (lê db_pool, modelo_id e atendimento_id)."""

    def __init__(self, pool: Any, modelo_id: str) -> None:
        self.db_pool, self.modelo_id = pool, modelo_id
        # consultar_agenda exclui o bloqueio do PRÓPRIO atendimento (ADR 0028); aqui os
        # bloqueios de teste são avulsos (atendimento_id NULL), então qualquer UUID serve.
        self.atendimento_id = str(uuid4())
