"""DEPLOY-05/06: guarda de ambiente que bloqueia seeds em producao.

Testa a lógica PURA de `barra.core.migracoes` — sem banco, offline.
"""

from __future__ import annotations

import pytest

from barra.core.migracoes import e_arquivo_seed, seed_bloqueado

# Nomes que CONTÊM seed (prefixo legacy, timestamp novo, posições variadas).
NOMES_SEED = [
    "0038_seed_pix_deslocamento.sql",
    "20260524061000_seed_painel_dados_24-05.sql",
    "20260527225046_fonte_decisao_seed_cleanup.sql",
    "SEED_maiusculo.sql",
    "0099_dados_seed.sql",
    "infra/sql/0038_seed_pix_deslocamento.sql",  # caminho não atrapalha
]

# Migrations de schema reais — nenhuma contém "seed".
NOMES_SCHEMA = [
    "20260529220000_fetiches.sql",
    "0041_atendimentos_endereco_geo.sql",
    "20260601100000_schema_migrations.sql",
    "0001_init.sql",
]


@pytest.mark.parametrize("nome", NOMES_SEED)
def test_e_arquivo_seed_detecta_seed(nome: str) -> None:
    assert e_arquivo_seed(nome) is True


@pytest.mark.parametrize("nome", NOMES_SCHEMA)
def test_e_arquivo_seed_ignora_schema(nome: str) -> None:
    assert e_arquivo_seed(nome) is False


def test_diretorio_seeds_nao_confunde_arquivo_de_schema() -> None:
    # `seeds/` no caminho não deve marcar um .sql de schema como seed.
    assert e_arquivo_seed("infra/seeds/0001_init.sql") is False


@pytest.mark.parametrize("nome", NOMES_SEED)
def test_producao_recusa_seed(nome: str) -> None:
    assert seed_bloqueado(nome, "producao") is True


@pytest.mark.parametrize("nome", NOMES_SEED)
@pytest.mark.parametrize("ambiente", ["desenvolvimento", "teste"])
def test_nao_producao_permite_seed(nome: str, ambiente: str) -> None:
    assert seed_bloqueado(nome, ambiente) is False


@pytest.mark.parametrize("nome", NOMES_SCHEMA)
@pytest.mark.parametrize("ambiente", ["producao", "desenvolvimento", "teste"])
def test_schema_nunca_bloqueado(nome: str, ambiente: str) -> None:
    assert seed_bloqueado(nome, ambiente) is False
