"""Fakes de Postgres compartilhados pelos testes do agente.

NAO ha Postgres de teste: a suite do M0 e toda fake. O grafo le `runtime.context.db_pool`
(nao `get_conn`), entao o fake entra via `ContextAgente(db_pool=FakePool(FakeConn(...)), ...)`.
O M0 nao escreve no DB.

FakeConn responde as queries que o prepare_context dispara:
- "...ia_pausada..." (gate do prepare_context + refetch do post_process) -> {"ia_pausada": bool};
- "FROM barravips.mensagens" (janela deslizante) -> as linhas dadas;
- "barravips.modelo_programas" (BP3, M2-T1) -> os programas dados (default vazio);
- "FROM barravips.modelos" (BP3, M2-T1) -> a identidade dada (default uma modelo pt-BR).
Qualquer outra query devolve vazio.

Reusado por test_prepare_context.py (M0-T4) e test_skeleton.py (M0-T6).
"""

from contextlib import asynccontextmanager
from typing import Any

from barra.agente.contexto import ContextAgente


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


_IDENTIDADE_PADRAO: dict[str, Any] = {
    "nome": "Bia",
    "idade": 26,
    "idiomas": ["pt-BR"],
    "localizacao_operacional": None,
    "tipo_atendimento_aceito": ["interno", "externo"],
}


class FakeConn:
    def __init__(
        self,
        *,
        ia_pausada: bool,
        mensagens: list[dict[str, Any]],
        identidade: dict[str, Any] | None = None,
        programas: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ia_pausada = ia_pausada
        self._mensagens = mensagens
        self._identidade = identidade or _IDENTIDADE_PADRAO
        self._programas = programas or []

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "ia_pausada" in query:
            return _Result([{"ia_pausada": self._ia_pausada}])
        if "FROM barravips.mensagens" in query:
            return _Result(self._mensagens)
        # checa modelo_programas ANTES de modelos (a 1ª nao contem "barravips.modelos").
        if "barravips.modelo_programas" in query:
            return _Result(self._programas)
        if "FROM barravips.modelos" in query:
            return _Result([self._identidade])
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class FakeRuntime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context
