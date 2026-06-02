"""consultar_agenda (M1-T1): runtime nao vaza no schema, guarda de janela, leitura real.

Tres checagens (04 §2.1):
  1. schema enviado ao LLM tem so data_inicio/data_fim — runtime e injetado pelo ToolNode,
     fora do schema (prova que nao vaza dep ao modelo);
  2. janela > 14 dias retorna ERRO ANTES de tocar o pool (db_pool=None prova que nao consultou);
  3. (needs_db) com bloqueios semeados, lista os ativos e filtra os cancelados.

O bloco needs_db espelha test_repo_integracao.py: conexao de TEST_DATABASE_URL, ROLLBACK no
teardown (nada commita em prod). Um fake-pool de UMA conexao deixa a tool ler os bloqueios
semeados na MESMA transacao, sem commit. A injecao de runtime so acontece dentro do ToolNode,
entao os testes chamam `.coroutine` (a corrotina crua do @tool) com um runtime fake.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.ferramentas.leitura import consultar_agenda

# .coroutine e a corrotina crua do @tool; .ainvoke({...}) NAO injeta runtime, .coroutine sim.
# BaseTool (tipo de retorno do @tool) nao expoe .coroutine no stub — ignore pontual no teste.
_chamar = consultar_agenda.coroutine  # type: ignore[attr-defined]


class _Ctx:
    """ContextAgente minimo: a tool so le db_pool e modelo_id (evita montar o dataclass real)."""

    def __init__(self, pool: Any, modelo_id: str) -> None:
        self.db_pool, self.modelo_id = pool, modelo_id


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


def test_schema_nao_vaza_runtime() -> None:
    """O LLM recebe so data_inicio/data_fim; runtime e injetado pelo ToolNode, fora do schema."""
    assert set(consultar_agenda.args) == {"data_inicio", "data_fim"}


async def test_janela_maior_que_14_dias_retorna_erro() -> None:
    """> 14 dias: retorna ERRO antes de tocar o pool (db_pool=None prova que nao consultou)."""
    out = await _chamar(
        data_inicio="2026-05-01",
        data_fim="2026-05-20",
        runtime=_Runtime(_Ctx(None, "00000000-0000-0000-0000-000000000000")),
    )
    assert out.startswith("ERRO:")


async def test_data_malformada_retorna_erro_recuperavel() -> None:
    """Data invalida: retorna o ERRO recuperavel antes de tocar o pool (db_pool=None prova)."""
    out = await _chamar(
        data_inicio="2026-13-99",
        data_fim="2026-05-20",
        runtime=_Runtime(_Ctx(None, "00000000-0000-0000-0000-000000000000")),
    )
    assert out == "ERRO: data inválida, use YYYY-MM-DD."


# --- AGT-07: cap por nº de bloqueios (sem DB; a constraint de não-sobreposição inviabiliza
#     semear 50+ bloqueios reais, então um fake-pool devolve as linhas direto) ---


class _FakeRowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeRowsConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_a: Any, **_k: Any) -> _FakeRowsResult:
        return _FakeRowsResult(self._rows)


class _FakeRowsPool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeRowsConn(self._rows)


def _bloqueio_row(dia: int) -> dict[str, Any]:
    return {
        "inicio": datetime(2026, 6, dia, 10, 0, tzinfo=UTC),
        "fim": datetime(2026, 6, dia, 11, 0, tzinfo=UTC),
    }


async def test_consultar_agenda_capa_numero_de_bloqueios() -> None:
    """Mais bloqueios que o teto -> corta em _MAX_BLOQUEIOS e sinaliza o truncamento."""
    from barra.agente.ferramentas.leitura import _MAX_BLOQUEIOS

    rows = [_bloqueio_row(2) for _ in range(_MAX_BLOQUEIOS + 1)]  # 1 acima do teto
    out = await _chamar(
        data_inicio="2026-06-01",
        data_fim="2026-06-07",
        runtime=_Runtime(_Ctx(_FakeRowsPool(rows), "m1")),
    )
    assert out.startswith("Bloqueios:")
    assert out.count("\n- ") == _MAX_BLOQUEIOS  # capado no teto
    assert "há mais nesse" in out  # sufixo de truncamento presente


async def test_consultar_agenda_abaixo_do_teto_sem_sufixo() -> None:
    """Abaixo do teto: lista completa, sem aviso de truncamento."""
    rows = [_bloqueio_row(2), _bloqueio_row(3)]
    out = await _chamar(
        data_inicio="2026-06-01",
        data_fim="2026-06-07",
        runtime=_Runtime(_Ctx(_FakeRowsPool(rows), "m1")),
    )
    assert out.count("\n- ") == 2
    assert "há mais" not in out


# --- needs_db: leitura real contra o Postgres self-hosted, ROLLBACK sempre (espelha test_repo) ---


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    """Conexao numa transacao isolada; ROLLBACK no teardown (nada persiste em prod).

    Mesma config de core/db.py que importa para a leitura: row_factory=dict_row (a tool acessa
    r['inicio']) e prepare_threshold=None (Supavisor transaction mode). Ver test_repo_integracao.py.
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
    """Pool fake de UMA conexao: a tool le na MESMA transacao da fixture (sem commit)."""

    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn  # nao fecha, nao commita (a fixture faz rollback)


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    """Modelo com o minimo de colunas NOT NULL/CHECK (0001 §5.2). Unicos via uuid p/ nao colidir."""
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


async def _inserir_bloqueio(
    connection: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    inicio: datetime,
    fim: datetime,
    estado: str,
) -> None:
    await connection.execute(
        "INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (uuid4(), modelo_id, inicio, fim, estado, "manual"),
    )


@pytest.mark.needs_db
async def test_lista_ativos_e_filtra_cancelados(conn: AsyncConnection[dict[str, Any]]) -> None:
    """2 bloqueios ativos viram 2 linhas; o cancelado na mesma janela e filtrado pela query."""
    modelo_id = await _seed_modelo(conn)
    # 2 ativos NAO sobrepostos (constraint bloqueios_sem_sobreposicao) em dias distintos,
    # horarios no meio do dia (evita borda de TZ no inicio::date). 1 cancelado na janela.
    await _inserir_bloqueio(
        conn,
        modelo_id=modelo_id,
        inicio=datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
        fim=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
        estado="bloqueado",
    )
    await _inserir_bloqueio(
        conn,
        modelo_id=modelo_id,
        inicio=datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
        fim=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
        estado="em_atendimento",
    )
    await _inserir_bloqueio(
        conn,
        modelo_id=modelo_id,
        inicio=datetime(2026, 6, 3, 14, 0, tzinfo=UTC),
        fim=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
        estado="cancelado",
    )

    out = await _chamar(
        data_inicio="2026-06-01",
        data_fim="2026-06-07",
        runtime=_Runtime(_Ctx(_PoolDeUmaConexao(conn), str(modelo_id))),
    )

    assert out.startswith("Bloqueios:")
    # O estado bruto NUNCA chega ao LLM: 'em_atendimento' revelaria que a modelo esta com
    # outro cliente — o CONTEXT.md proibe. bloqueado e em_atendimento viram "ocupado".
    assert "em_atendimento" not in out
    assert "bloqueado" not in out
    assert out.count("(ocupado)") == 2
    assert out.count("\n- ") == 2  # 2 ativos; o cancelado e filtrado pela query


@pytest.mark.needs_db
async def test_janela_sem_bloqueios_disponibilidade_total(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Modelo sem bloqueios na janela -> retorno sinaliza nenhum horário ocupado."""
    modelo_id = await _seed_modelo(conn)
    out = await _chamar(
        data_inicio="2026-06-01",
        data_fim="2026-06-07",
        runtime=_Runtime(_Ctx(_PoolDeUmaConexao(conn), str(modelo_id))),
    )
    assert "Nenhum horário ocupado" in out
