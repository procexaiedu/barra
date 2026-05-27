"""Fakes de Postgres compartilhados pelos testes do agente.

NAO ha Postgres de teste: a suite do M0 e toda fake. O grafo le `runtime.context.db_pool`
(nao `get_conn`), entao o fake entra via `ContextAgente(db_pool=FakePool(FakeConn(...)), ...)`.
O M0 nao escreve no DB.

FakeConn responde as queries que o prepare_context dispara:
- "...ia_pausada..." (gate do prepare_context + refetch do post_process) -> {"ia_pausada": bool};
- "FROM barravips.mensagens" (janela deslizante) -> as linhas dadas;
- "barravips.modelo_programas" (BP3, M2-T1) -> os programas dados (default vazio);
- "FROM barravips.modelos" (BP3, M2-T1) -> a identidade dada (default uma modelo pt-BR).

Quando o LLM real (testes needs_key) decide invocar uma tool de escrita, o caminho passa por
`_executar_idempotente` (transacao + INSERT em tool_calls) e pelo executor da tool (UPDATE em
atendimentos, INSERT em eventos, SELECT de transicao etc.). O fake aceita esse trafego em modo
"primeira-inserção" sem efeito real: transaction() e no-op, INSERT em tool_calls devolve uma
linha (sem conflito), atendimentos default fica em estado "Novo" sem campos -> _decidir_transicao
retorna None e a tool encerra sem disparar bloqueio/handoff. Suficiente para os testes de cache
do M0/M2; testes de comportamento de tool usam DB real (needs_db).

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


_ATENDIMENTO_NOVO_PADRAO: dict[str, Any] = {
    "estado": "Novo",
    "intencao": None,
    "tipo_atendimento": None,
    "horario_desejado": None,
    "data_desejada": None,
    "bloqueio_id": None,
    "duracao_horas": None,
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

    @asynccontextmanager
    async def transaction(self) -> Any:
        # `_executar_idempotente` envelopa o efeito da tool numa transacao real. No fake e no-op:
        # nao ha rollback porque nada e persistido; basta deixar o `async with` funcionar.
        yield

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
        # INSERT em tool_calls com RETURNING turno_id: simula "primeira insercao" (sem conflito),
        # deixando `_executar_idempotente` rodar o executor da tool. params[0] e o turno_id.
        if "INSERT INTO barravips.tool_calls" in query and "RETURNING" in query:
            turno = params[0] if params else None
            return _Result([{"turno_id": turno}])
        # SELECT em atendimentos (usado por _decidir_transicao, _reagendamento_pos_bloqueio,
        # _abaixo_do_piso, _refetch_para_bloqueio, _aviso_saida_aplicavel). Devolve atendimento
        # "Novo" sem campos: _decidir_transicao retorna None (nao promove), branches de bloqueio
        # e piso saem cedo. Acrescenta `modelo_id` quando o SELECT pediu (params=(aid,)).
        if "FROM barravips.atendimentos" in query:
            linha = dict(_ATENDIMENTO_NOVO_PADRAO)
            if "modelo_id" in query:
                # params[0] = atendimento_id; modelo_id sai como UUID gerado a parte (nao usado).
                linha["modelo_id"] = None
            return _Result([linha])
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
