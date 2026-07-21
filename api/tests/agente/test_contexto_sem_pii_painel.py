"""Invariante de isolamento: PII / dado painel-only NUNCA entra no contexto da IA por modelo.

A montagem do prompt (`_carregar_bp3` + `_resolver_variaveis`, prepare_context.py) le do banco o
que a IA pode ver. CONTEXT.md ("Dados cadastrais", "Perfil fisico preferido", "Mapa de clientes",
ADRs 0006/0007/0008) define um conjunto de campos que sao painel-only/Fernando e a IA "nunca le":
RG/CPF/endereco residencial, tipo_fisico, cor de pele/cabelo, altura, tamanho do pe, perfil fisico
preferido do cliente, e a geo (latitude/longitude) do Mapa.

Hoje os SELECTs sao listas de colunas EXPLICITAS que ja excluem esses campos — este teste e a
REDE DETERMINISTICA que trava a regressao: captura todo SQL que o montador emite e falha se
qualquer coluna proibida for selecionada. Sem DB nem LLM (FakeConn que so grava as queries).
"""

import importlib
import re
from typing import Any
from uuid import uuid4

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta funcoes do submodulo; importlib pega o modulo real (memoria
# "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.prepare_context")

# Campos painel-only/PII que a IA conversacional nunca pode carregar (CONTEXT.md + ADR 0006/07/08).
# `endereco` operacional do atendimento (ponto de encontro externo) e legitimo; o proibido e o
# `endereco_residencial` da ficha cadastral — por isso casamos o nome completo.
COLUNAS_PROIBIDAS = (
    "rg",
    "cpf",
    "endereco_residencial",
    "cor_pele",
    "cor_cabelo",
    "altura",
    "tamanho_pe",
    "tipo_fisico",
    "perfil_fisico_preferido",
    "latitude",
    "longitude",
)


class _Res:
    def __init__(self, *, one: dict[str, Any] | None = None, allrows: list[dict[str, Any]]) -> None:
        self._one = one
        self._all = allrows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._one

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._all


class _ConnGravador:
    """Conn fake que GRAVA cada query e devolve linhas plausiveis por tabela (so p/ o montador
    rodar ate o fim). Nao executa SQL — o objeto do teste e a lista de queries capturadas."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def execute(self, query: str, params: Any = None) -> _Res:
        self.queries.append(query)
        if "barravips.modelos" in query and "idade" in query:
            return _Res(
                one={
                    "nome": "Bia",
                    "idade": 25,
                    "idiomas": ["pt"],
                    "localizacao_operacional": "Centro",
                    "tipo_atendimento_aceito": ["interno"],
                },
                allrows=[],
            )
        if "modelo_programas" in query:
            return _Res(
                allrows=[
                    {"nome": "Programa", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 500}
                ]
            )
        if "modelo_fetiches" in query:
            return _Res(allrows=[{"nome": "fetiche", "preco": None}])
        # demais (atendimentos/conversas/clientes/bloqueios/disponibilidade/historico/agora):
        # fetchone None (cada caller faz `or {}` ou trata None) e fetchall vazio.
        return _Res(one=None, allrows=[])


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # _resolver_variaveis usa o conn passado, nao o pool
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )


async def test_montador_de_contexto_nao_seleciona_pii_painel() -> None:
    conn = _ConnGravador()
    ctx = _ctx()

    # Exercita os dois caminhos que leem do banco para o prompt: BP3 por-modelo + contexto dinamico.
    await mod._carregar_bp3(conn, ctx.modelo_id)  # type: ignore[arg-type]
    await mod._resolver_variaveis(conn, ctx)  # type: ignore[arg-type]

    # Sanidade: cobrimos de fato modelo E cliente (senao o teste passaria a vazio).
    juntas = "\n".join(conn.queries).lower()
    assert "barravips.modelos" in juntas
    assert "barravips.clientes" in juntas

    # Invariante: nenhuma coluna painel-only/PII foi selecionada para o contexto da IA.
    for query in conn.queries:
        alvo = query.lower()
        for coluna in COLUNAS_PROIBIDAS:
            assert not re.search(rf"\b{coluna}\b", alvo), (
                f"coluna painel-only '{coluna}' vazou para o contexto da IA na query: {query}"
            )
