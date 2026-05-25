"""Validacao de schema das fixtures de cache_hit (DB-free, sem chave da Anthropic).

Espelha test_fixtures_leitura.py: garante que cada .jsonl em evals/canonicos/cache_hit/ e JSON
valido por linha, carrega as chaves criticas do schema (evals/README.md; 08 §2.4), que
tool_calls_obrigatorias/proibidas sao listas disjuntas, e que os `id` sao unicos entre os
arquivos. NAO roda o agente nem mede cache de verdade -- a medicao live (cache_read no 2º turno,
em burst quente) fica no runner do M6 (08 §3.1). Este e o gate barato de schema.
"""

import json
from pathlib import Path

import pytest

# Resolve evals/ a partir deste arquivo (api/tests/agente -> api/evals), sem caminho absoluto.
_CACHE_HIT = Path(__file__).resolve().parents[2] / "evals" / "canonicos" / "cache_hit"


def _linhas() -> list[tuple[str, str]]:
    """(label, linha bruta) por linha nao-vazia de cada *.jsonl, ordenado por nome de arquivo.

    Le como UTF-8 estrito (sem -sig): um BOM faria json.loads falhar no teste -- justamente o
    que queremos garantir (regras de autoria: UTF-8 sem BOM).
    """
    itens: list[tuple[str, str]] = []
    for arquivo in sorted(_CACHE_HIT.glob("*.jsonl")):
        for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), start=1):
            if linha.strip():
                itens.append((f"{arquivo.name}:{n}", linha))
    return itens


_LINHAS = _linhas()


def test_ha_fixtures() -> None:
    assert _LINHAS, f"nenhuma fixture .jsonl encontrada em {_CACHE_HIT}"


@pytest.mark.parametrize("label,raw", _LINHAS, ids=[label for label, _ in _LINHAS])
def test_schema_da_fixture(label: str, raw: str) -> None:
    fixture = json.loads(raw)  # JSON valido por linha (falha aqui = linha malformada/BOM)

    for chave in (
        "id",
        "categoria",
        "subcategoria",
        "estado_inicial",
        "expectativas",
        "rubricas",
    ):
        assert chave in fixture, f"{label}: falta a chave '{chave}'"

    par = fixture.get("par")
    assert isinstance(par, dict), f"{label}: 'par' ausente ou nao e objeto"
    assert par.get("cliente_id"), f"{label}: par.cliente_id ausente"
    assert par.get("modelo_id"), f"{label}: par.modelo_id ausente"

    mensagens = fixture.get("mensagens_entrada")
    assert isinstance(mensagens, list) and mensagens, f"{label}: mensagens_entrada vazio"

    exp = fixture["expectativas"]
    obrigatorias = exp.get("tool_calls_obrigatorias", [])
    proibidas = exp.get("tool_calls_proibidas", [])
    assert isinstance(obrigatorias, list), f"{label}: tool_calls_obrigatorias nao e lista"
    assert isinstance(proibidas, list), f"{label}: tool_calls_proibidas nao e lista"
    # Consistencia: uma tool nunca pode estar obrigatoria E proibida ao mesmo tempo.
    conflito = set(obrigatorias) & set(proibidas)
    assert not conflito, f"{label}: tool(s) em obrigatorias E proibidas: {sorted(conflito)}"


def test_ids_unicos_entre_arquivos() -> None:
    ids = [json.loads(raw)["id"] for _, raw in _LINHAS]
    duplicados = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicados, f"ids duplicados entre arquivos: {duplicados}"
