"""financeiro.repo.importados_sem_data — bruto dos Fechados sem evento `fechado_registrado`."""

from typing import Any
from uuid import uuid4

from barra.dominio.financeiro import repo


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class FakeConn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row
        self.query: str | None = None
        self.params: list[Any] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.query = query
        self.params = list(params) if params is not None else []
        return _Result(self._row)


async def test_importados_sem_data_sem_filtro_modelo() -> None:
    conn = FakeConn({"contagem": 402, "valor_bruto": 235080})
    contagem, bruto = await repo.importados_sem_data(conn, None)  # type: ignore[arg-type]

    assert contagem == 402
    assert bruto == 235080.0
    # Recorte: Fechado sem evento fechado_registrado, sem param de modelo.
    assert "NOT EXISTS" in conn.query  # type: ignore[operator]
    assert "fechado_registrado" in conn.query  # type: ignore[operator]
    assert conn.params == []


async def test_importados_sem_data_filtra_modelo() -> None:
    mid = uuid4()
    conn = FakeConn({"contagem": 1, "valor_bruto": 500})
    contagem, bruto = await repo.importados_sem_data(conn, [mid])  # type: ignore[arg-type]

    assert contagem == 1
    assert bruto == 500.0
    assert "a.modelo_id = ANY(%s)" in conn.query  # type: ignore[operator]
    assert conn.params == [[mid]]
