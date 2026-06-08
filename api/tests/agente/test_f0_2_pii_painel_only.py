"""F0.2 — Invariante PII: o montador de contexto NUNCA carrega campo painel-only.

CONTEXT.md ("Dados cadastrais da modelo", "Perfil físico preferido", "Mapa de clientes",
ADRs 0006/0007/0008): RG, CPF, endereço residencial, tipo físico, perfil físico preferido e
coordenada do mapa são **painel-only/Fernando** — a IA conversacional nunca os lê. O ponto de
entrada desses dados no prompt seria uma query do montador (`agente/nos/prepare_context.py`)
que os SELECIONASSE: tudo que ele carrega vai para o BP_MODELO ou para o contexto dinâmico da
cauda, ou seja, para o prompt do agente.

Este teste extrai por AST o SQL de TODOS os `conn.execute(...)` do montador e falha se qualquer
coluna painel-only aparecer na lista de seleção. É determinístico e sem banco — roda no `make
test` padrão (não é `needs_db`, não fica pulado quando falta `TEST_DATABASE_URL`), então é gate
de PR de verdade: adicionar `rg`/`cpf`/`tipo_fisico`/`latitude`/... a um SELECT do montador deixa
o PR vermelho. Casa 1:1 com o critério do roadmap (F0.2): "montador nunca carrega painel-only".

Extrai por AST (não por grep no texto-fonte) de propósito: os docstrings/comentários do módulo
citam essas colunas legitimamente (ex.: o comentário que explica POR QUE o geo do atendimento é
excluído). Só os literais de string passados a `.execute` são SQL real; o resto é prosa.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

# `barra.agente.nos.prepare_context` resolve para a FUNÇÃO (o `nos/__init__` reexporta e sombreia
# o submódulo — memória nos_submodulo_sombreado_por_funcao); pega o módulo por importlib.
prepare_context_mod = importlib.import_module("barra.agente.nos.prepare_context")

# Colunas painel-only que a IA conversacional nunca pode carregar (CONTEXT.md + ADRs 0006/0007/0008).
# Cada entrada é um nome de coluna real do schema; o match é por palavra inteira (\b), então
# `endereco_residencial_formatado` (proibido) não colide com `endereco` do atendimento (o endereço
# operacional do cliente, que a IA PRECISA ler no externo).
COLUNAS_PAINEL_ONLY = frozenset(
    {
        # PII sensível da ficha cadastral da modelo (ADR 0007)
        "rg",
        "cpf",
        "endereco_residencial_formatado",
        # Resto da ficha cadastral — painel-only (ADR 0007)
        "cor_pele",
        "cor_cabelo",
        "altura_cm",
        "tamanho_pe",
        # Tipo físico (balde de venda) da modelo (ADR 0006)
        "tipo_fisico",
        # Perfil físico preferido do cliente (ADR 0006)
        "perfis_preferidos",
        # Coordenada do Mapa de clientes (ADR 0008) — modelos e atendimentos
        "latitude",
        "longitude",
    }
)

# Coluna sabidamente carregada pelo montador: âncora p/ provar que a extração não veio vazia
# (senão a ausência das proibidas seria um verde vácuo).
COLUNA_ESPERADA = "numero_curto"


def _sqls_do_montador() -> list[str]:
    """Extrai por AST o primeiro argumento (string literal) de cada `conn.execute(...)` do módulo.

    Pega só o SQL real — nada de comentário/docstring do .py — evitando falso-positivo de prosa.
    """
    fonte = Path(prepare_context_mod.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    sqls: list[str] = []
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "execute"
            and no.args
            and isinstance(no.args[0], ast.Constant)
            and isinstance(no.args[0].value, str)
        ):
            sqls.append(no.args[0].value)
    return sqls


def _colunas_painel_only_presentes(sql: str) -> set[str]:
    corpo = sql.lower()
    return {col for col in COLUNAS_PAINEL_ONLY if re.search(rf"\b{re.escape(col)}\b", corpo)}


def test_extracao_de_sql_nao_veio_vazia() -> None:
    """Âncora anti-vácuo: a extração achou SQL e ele contém a coluna esperada do montador."""
    corpus = " ".join(_sqls_do_montador()).lower()
    assert corpus.strip(), "nenhum SQL extraído do montador — a extração por AST regrediu"
    assert re.search(rf"\b{COLUNA_ESPERADA}\b", corpus), (
        f"coluna esperada {COLUNA_ESPERADA!r} sumiu do montador — a âncora do teste está obsoleta"
    )


def test_montador_nunca_carrega_campo_painel_only() -> None:
    """F0.2: nenhuma query do montador SELECIONA coluna painel-only (RG/CPF/endereço/tipo
    físico/perfil preferido/mapa). Falha se qualquer campo PII entra no prompt do agente."""
    vazamentos: dict[str, set[str]] = {}
    for sql in _sqls_do_montador():
        presentes = _colunas_painel_only_presentes(sql)
        if presentes:
            vazamentos[sql.strip()[:80]] = presentes

    assert not vazamentos, (
        "montador de contexto carrega coluna painel-only (vaza PII no prompt do agente):\n"
        + "\n".join(f"  - {cols} em: {sql!r}…" for sql, cols in vazamentos.items())
    )
