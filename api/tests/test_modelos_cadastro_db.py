"""Integração real (needs_db) dos dados cadastrais (ADR 0007).

Conexão de TEST_DATABASE_URL, ROLLBACK no teardown — nada persiste no banco. Cobre o que o
FakeConn não cobre: INSERT/SELECT real com as 8 colunas + enums, e os disparos reais de
UniqueViolation (CPF parcial-unique) e CheckViolation (range de altura). Espelha o padrão de
tests/agente/test_repo_integracao.py.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, UniqueViolation
from psycopg.rows import dict_row


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


async def _inserir(
    connection: AsyncConnection[dict[str, Any]],
    *,
    cpf: str | None = None,
    altura_cm: int | None = 170,
    cor_pele: str | None = "parda",
    cor_cabelo: str | None = "castanho_escuro",
) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             rg, cpf, endereco_residencial_formatado, place_id_residencial,
             cor_pele, cor_cabelo, altura_cm, tamanho_pe)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[],
                %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            modelo_id,
            "Cadastro Teste",
            28,
            f"test-wpp-{uuid4().hex}",
            500,
            ["interno"],
            "12.345.678-9",
            cpf,
            "Rua X, 100 - Rio de Janeiro",
            "ChIJ_residencial",
            cor_pele,
            cor_cabelo,
            altura_cm,
            37,
        ),
    )
    return modelo_id


@pytest.mark.needs_db
async def test_insert_e_leitura_dados_cadastrais(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id = await _inserir(conn, cpf="52998224725")
    result = await conn.execute(
        """
        SELECT rg, cpf, endereco_residencial_formatado, place_id_residencial,
               cor_pele, cor_cabelo, altura_cm, tamanho_pe
          FROM barravips.modelos WHERE id = %s
        """,
        (modelo_id,),
    )
    row = await result.fetchone()
    assert row is not None
    assert row["cpf"] == "52998224725"
    assert row["rg"] == "12.345.678-9"
    assert row["endereco_residencial_formatado"] == "Rua X, 100 - Rio de Janeiro"
    assert row["place_id_residencial"] == "ChIJ_residencial"
    assert row["cor_pele"] == "parda"
    assert row["cor_cabelo"] == "castanho_escuro"
    assert row["altura_cm"] == 170
    assert row["tamanho_pe"] == 37


@pytest.mark.needs_db
async def test_cpf_duplicado_viola_unique(conn: AsyncConnection[dict[str, Any]]) -> None:
    await _inserir(conn, cpf="52998224725")
    with pytest.raises(UniqueViolation):
        await _inserir(conn, cpf="52998224725")


@pytest.mark.needs_db
async def test_dois_cpf_null_convivem(conn: AsyncConnection[dict[str, Any]]) -> None:
    # Índice unique é parcial (WHERE cpf IS NOT NULL): múltiplos NULL não colidem.
    await _inserir(conn, cpf=None)
    await _inserir(conn, cpf=None)  # não deve levantar


@pytest.mark.needs_db
async def test_altura_fora_range_viola_check(conn: AsyncConnection[dict[str, Any]]) -> None:
    with pytest.raises(CheckViolation):
        await _inserir(conn, altura_cm=300)
