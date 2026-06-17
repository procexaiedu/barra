"""OBS go-live: custo de chat por turno persistido em `atendimentos.custo_ia_brl`.

Tres camadas:
  - PURO: `custo_chat_turno_brl` soma só as AIMessages com usage_metadata (geradas no turno).
  - OFFLINE: `acumular_custo_atendimento` emite o UPDATE acumulativo e é BEST-EFFORT
    (exceção vira warning, nunca derruba o turno); custo <= 0 é no-op.
  - `needs_db`: aplica a migration (idempotente) na transação do teste, acumula 2x num
    atendimento real e lê a soma de volta — ROLLBACK sempre (banco compartilhado).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente._custo import calcular_custo_brl, custo_chat_turno_brl
from barra.workers.coordenador import acumular_custo_atendimento

COTACAO = 5.50
# input_tokens e o TOTAL do langchain-anthropic (fresco 1000 + read 5000 + write 300 = 6300).
_USAGE = {
    "input_tokens": 6300,
    "output_tokens": 200,
    "input_token_details": {"cache_read": 5000, "ephemeral_1h_input_tokens": 300},
}


# --- puro: custo_chat_turno_brl -----------------------------------------------------------------


def test_soma_so_aimessages_com_usage() -> None:
    # Historicas re-injetadas (usage None) e mensagens de outros papeis nao contam.
    messages = [
        SimpleNamespace(usage_metadata=None),  # historica
        SimpleNamespace(usage_metadata=_USAGE),  # chamada 1 do ReAct
        SimpleNamespace(usage_metadata=_USAGE),  # chamada 2 (extracao forcada)
        SimpleNamespace(),  # ToolMessage-like, sem o atributo
    ]
    esperado = 2 * calcular_custo_brl(_USAGE, COTACAO)
    assert custo_chat_turno_brl(messages, COTACAO) == pytest.approx(esperado)
    assert esperado > 0


def test_turno_sem_usage_da_zero() -> None:
    assert custo_chat_turno_brl([SimpleNamespace(usage_metadata=None)], COTACAO) == 0.0
    assert custo_chat_turno_brl([], COTACAO) == 0.0


def test_extracao_haiku_precificada_pela_tabela_haiku() -> None:
    # Bug C: a AIMessage da extracao forcada roda em Haiku; custo_chat_turno_brl le o
    # response_metadata.model_name e cobra pela tabela Haiku ($1/$5), nao a do Sonnet ($3/$15).
    haiku = SimpleNamespace(
        usage_metadata=_USAGE,
        response_metadata={"model_name": "claude-haiku-4-5-20251001"},
    )
    sonnet = SimpleNamespace(
        usage_metadata=_USAGE,
        response_metadata={"model_name": "claude-sonnet-4-6"},
    )
    custo_haiku = custo_chat_turno_brl([haiku], COTACAO)
    custo_sonnet = custo_chat_turno_brl([sonnet], COTACAO)
    # casa com o calculo direto pela tabela Haiku e fica abaixo do mesmo turno cobrado como Sonnet.
    assert custo_haiku == pytest.approx(
        calcular_custo_brl(_USAGE, COTACAO, model_name="claude-haiku-4-5-20251001")
    )
    assert 0 < custo_haiku < custo_sonnet


def test_model_name_ausente_cai_em_sonnet() -> None:
    # Sem response_metadata (fallback seguro), cobra como Sonnet — o chat principal.
    sem_meta = SimpleNamespace(usage_metadata=_USAGE)
    assert custo_chat_turno_brl([sem_meta], COTACAO) == pytest.approx(
        calcular_custo_brl(_USAGE, COTACAO)
    )


# --- offline: acumular_custo_atendimento ---------------------------------------------------------


class _PoolFake:
    """Pool fake: captura o SQL emitido ou levanta na conexao (caminho best-effort)."""

    def __init__(self, *, falha: bool = False) -> None:
        self.falha = falha
        self.execucoes: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def connection(self) -> Any:
        if self.falha:
            raise RuntimeError("banco fora do ar")
        pool = self

        class _Conn:
            @asynccontextmanager
            async def transaction(self) -> Any:
                yield

            async def execute(self, query: str, params: tuple[Any, ...]) -> None:
                pool.execucoes.append((query, params))

        yield _Conn()


async def test_emite_update_acumulativo() -> None:
    pool = _PoolFake()
    aid = uuid4()
    await acumular_custo_atendimento(pool, aid, 0.1234)  # type: ignore[arg-type]
    assert len(pool.execucoes) == 1
    query, params = pool.execucoes[0]
    assert "custo_ia_brl = custo_ia_brl + %s" in query
    assert params == (0.1234, aid)


async def test_custo_zero_ou_negativo_e_noop() -> None:
    pool = _PoolFake()
    await acumular_custo_atendimento(pool, uuid4(), 0.0)  # type: ignore[arg-type]
    await acumular_custo_atendimento(pool, uuid4(), -1.0)  # type: ignore[arg-type]
    assert pool.execucoes == []


async def test_falha_de_banco_nao_propaga() -> None:
    # Telemetria best-effort: o turno nunca cai por causa do UPDATE de custo.
    await acumular_custo_atendimento(_PoolFake(falha=True), uuid4(), 0.5)  # type: ignore[arg-type]


# --- needs_db: migration + acumulo real ----------------------------------------------------------

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "sql"
    / "20260610184646_atendimentos_custo_ia.sql"
)


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


async def _seed_atendimento(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id, cliente_id, conversa_id, atendimento_id = (uuid4() for _ in range(4))
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Custo", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, ia_pausada,
             fonte_decisao_ultima_transicao)
        VALUES (%s, %s, %s, %s, 'Triagem'::barravips.estado_atendimento_enum, false,
                'extracao_ia')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


class _PoolDeUmaConexao:
    """Reusa a conexao/transacao do teste (mesmo padrao do runner) -> ROLLBACK limpa tudo."""

    def __init__(self, c: AsyncConnection[dict[str, Any]]) -> None:
        self._c = c

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._c


@pytest.mark.needs_db
async def test_acumula_no_banco_real(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Migration idempotente aplicada NA transacao do teste (DDL transacional no Postgres):
    # valida o arquivo real e funciona mesmo antes de aplicada em prod; o ROLLBACK desfaz.
    await conn.execute(_MIGRATION.read_text(encoding="utf-8"))
    atendimento_id = await _seed_atendimento(conn)
    pool = _PoolDeUmaConexao(conn)

    await acumular_custo_atendimento(pool, atendimento_id, 0.10)  # type: ignore[arg-type]
    await acumular_custo_atendimento(pool, atendimento_id, 0.05)  # type: ignore[arg-type]

    res = await conn.execute(
        "SELECT custo_ia_brl FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    assert float(row["custo_ia_brl"]) == pytest.approx(0.15)
