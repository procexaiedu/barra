"""Rodada 3 (closed-world) — a ficha com cardápio completo chega ao contexto que a IA lê.

Fecha o caminho inteiro: spec de ficha (formato MODELOS_REAIS, com `fetiches`) → seed do
harness (`evals.harness._seed_modelo`, get-or-create no catálogo curado) → `_carregar_bp3`
(a MESMA leitura de prod) → BP_MODELO renderizado com os inclusos e o `<cardapio_fechado>`.

`needs_db` (Postgres via TEST_DATABASE_URL), conn real autocommit=False + ROLLBACK sempre —
mesmo padrão de test_fetiche_preco_calculado.py.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from evals.harness import _seed_modelo
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.nos.prepare_context import _carregar_bp3

pytestmark = [pytest.mark.needs_db, pytest.mark.asyncio]


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


FICHA = {
    "nome": "Júlia",
    "localizacao_operacional": "Centro (Campinas-SP)",
    "programas": [
        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 600},
        {"nome": "Completo", "duracao_nome": "1 hora", "horas": 1, "preco": 1000},
    ],
    # Formato das fichas MODELOS_REAIS pós-enriquecimento: inclusos evidenciados no corpus.
    "fetiches": [
        {"nome": "beijo na boca", "preco": None, "cobra_por_pessoa": False},
        {"nome": "Oral sem camisinha", "preco": None, "cobra_por_pessoa": False},
    ],
    # Documentação de evidência ("não faço anal") — o seed IGNORA a chave: em prod a recusa vem
    # da AUSÊNCIA no cardápio + <cardapio_fechado>, não de uma lista de negativos.
    "nao_faz": ["anal"],
}


async def test_ficha_com_cardapio_completo_chega_ao_bp_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn, FICHA)
    (
        bp3_md,
        _nome,
        _max_h,
        sem_fetiches,
        _sem_menage,
        _sem_vc,
        _sem_externo,
        _end,
        _local,
        _precos,
        _cardapio,
    ) = await _carregar_bp3(conn, str(modelo_id))
    # os inclusos da ficha entram no <fetiches> — <sem_fetiches> deixa de disparar por artefato.
    assert sem_fetiches is False
    assert "beijo na boca" in bp3_md
    assert "Oral sem camisinha" in bp3_md
    assert "Inclusos" in bp3_md
    # a declaração closed-world sai DEPOIS das listas que ela fecha.
    assert "<cardapio_fechado>" in bp3_md
    assert bp3_md.index("<cardapio_fechado>") > bp3_md.index("<fetiches>")
    # o "nao_faz" NÃO vira texto: a recusa é pela ausência (nada de lista de negativos no prompt).
    assert "anal" not in bp3_md.lower()


async def test_ficha_sem_completo_nao_tem_porta_do_anal(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    # Modelo que "não faz anal" = SEM o programa Completo na tabela: a giria anal→Completo do
    # BP_GERAL não encontra linha pra cotar e o pedido cai na recusa do <cardapio_fechado>.
    ficha = {**FICHA, "programas": [FICHA["programas"][0]]}
    modelo_id = await _seed_modelo(conn, ficha)
    bp3_md, *_resto = await _carregar_bp3(conn, str(modelo_id))
    assert "Completo" not in bp3_md
    assert "<cardapio_fechado>" in bp3_md
