"""#6 (bughunt): `enviar_midia` seleciona a foto com `FOR UPDATE SKIP LOCKED` dentro de uma
transacao explicita.

Duas `enviar_midia` da MESMA tag no MESMO turno rodam em paralelo (asyncio.gather do ToolNode
`_afunc`). Sem lock de fila, ambas leem `ja_no_turno` vazio e escolhem a MESMA foto (TOCTOU) -> o
cliente recebe a foto repetida. O `FOR UPDATE SKIP LOCKED` serializa a selecao; e como o pool do
worker e autocommit=True, o lock so persiste ate o INSERT se a SELECT correr DENTRO de uma
transacao explicita. Unit, sem DB: um conn fake roteia por query e registra o tx_depth de cada
execute.
"""

from contextlib import asynccontextmanager
from typing import Any

from barra.agente.ferramentas.midia import enviar_midia

# .coroutine e a corrotina crua do @tool (injeta runtime); BaseTool nao expoe no stub.
_chamar = enviar_midia.coroutine  # type: ignore[attr-defined]

_MIDIA_ID = "11111111-1111-1111-1111-111111111111"


class _FakeResult:
    def __init__(self, one: Any = None, many: list[dict[str, Any]] | None = None) -> None:
        self._one = one
        self._many = many or []

    async def fetchone(self) -> Any:
        return self._one

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._many


class _FakeConn:
    """Conn fake: roteia por query e grava o tx_depth no momento de cada execute."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, int]] = []
        self.tx_depth = 0

    @asynccontextmanager
    async def transaction(self) -> Any:
        self.tx_depth += 1
        try:
            yield self
        finally:
            self.tx_depth -= 1

    async def execute(self, sql: str, params: Any = None) -> _FakeResult:
        self.executes.append((sql, self.tx_depth))
        if "payload->>'midia_id'" in sql:  # _midias_do_turno: nenhuma midia previa
            return _FakeResult(many=[])
        if "FROM barravips.modelo_midia" in sql:  # candidata
            return _FakeResult(one={"id": _MIDIA_ID, "object_key": "k"})
        if (
            "INSERT INTO barravips.tool_calls" in sql
        ):  # _executar_idempotente: inseriu (sem conflito)
            return _FakeResult(one={"turno_id": "t"})
        return _FakeResult()  # UPDATEs


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Ctx:
    def __init__(self, pool: Any) -> None:
        self.db_pool = pool
        self.modelo_id = "m1"
        self.turno_id = "t1"


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


async def test_candidata_usa_for_update_skip_locked_dentro_de_transacao() -> None:
    conn = _FakeConn()
    out = await _chamar(tag="apresentacao", runtime=_Runtime(_Ctx(_FakePool(conn))), call_idx=0)
    candidatas = [
        (sql, depth) for sql, depth in conn.executes if "FROM barravips.modelo_midia" in sql
    ]
    assert candidatas, "a SELECT candidata deveria ter rodado"
    sql, depth = candidatas[0]
    assert "FOR UPDATE SKIP LOCKED" in sql  # serializa selecao concorrente da mesma tag
    assert depth >= 1  # roda DENTRO da transacao (senao, sob autocommit, o lock soltaria cedo)
    assert "anexada" in out
