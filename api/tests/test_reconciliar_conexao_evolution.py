"""Testes unit do reconciliador de status de WhatsApp (workers/conexao_evolution) — sem DB real.

FakeConn devolve as modelos canned e guarda os UPDATEs; FakeEvolution responde o estado remoto
por instância.
"""

from __future__ import annotations

import asyncio
from typing import Any

from barra.workers.conexao_evolution import reconciliar_conexao_evolution


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    def __init__(self, modelos: list[dict[str, Any]]) -> None:
        self.modelos = modelos
        self.updates: list[Any] = []

    async def execute(self, sql: str, params: Any = None) -> _Result:
        if sql.lstrip().startswith("UPDATE"):
            self.updates.append(params)
            return _Result([])
        assert "FROM barravips.modelos" in sql
        # A query filtra `pareando` no SQL; o fake devolve o que o chamador montou.
        return _Result(self.modelos)


class FakeEvolution:
    def __init__(self, estados: dict[str, Any]) -> None:
        self.estados = estados
        self.consultadas: list[str] = []

    async def estado_conexao(self, instance_id: str) -> str:
        self.consultadas.append(instance_id)
        estado = self.estados[instance_id]
        if isinstance(estado, Exception):
            raise estado
        return estado


def _modelo(instance: str, status: str) -> dict[str, Any]:
    return {
        "nome": instance.title(),
        "evolution_instance_id": instance,
        "evolution_status": status,
    }


def test_instancia_open_promove_desconectado_para_conectado() -> None:
    """O caso da Tatiane: pareada por fora do painel, webhook perdido, cache travado."""
    conn = FakeConn([_modelo("elitebaby01", "desconectado")])
    total = asyncio.run(reconciliar_conexao_evolution(conn, FakeEvolution({"elitebaby01": "open"})))
    assert total == 1
    assert conn.updates == [("conectado", "conectado", "elitebaby01")]


def test_instancia_close_rebaixa_conectado_para_desconectado() -> None:
    conn = FakeConn([_modelo("lucia", "conectado")])
    total = asyncio.run(reconciliar_conexao_evolution(conn, FakeEvolution({"lucia": "close"})))
    assert total == 1
    assert conn.updates == [("desconectado", "desconectado", "lucia")]


def test_estado_ja_sincronizado_nao_escreve() -> None:
    conn = FakeConn([_modelo("elitebaby01", "conectado")])
    total = asyncio.run(reconciliar_conexao_evolution(conn, FakeEvolution({"elitebaby01": "open"})))
    assert total == 0 and conn.updates == []


def test_unknown_e_connecting_nao_rebaixam() -> None:
    """Instância inexistente (`unknown`) ou pareando (`connecting`) não são evidência de queda."""
    conn = FakeConn([_modelo("sumida", "conectado"), _modelo("nova", "conectado")])
    evolution = FakeEvolution({"sumida": "unknown", "nova": "connecting"})
    total = asyncio.run(reconciliar_conexao_evolution(conn, evolution))
    assert total == 0 and conn.updates == []


def test_falha_da_evolution_nao_derruba_a_varredura() -> None:
    conn = FakeConn([_modelo("quebrada", "conectado"), _modelo("elitebaby01", "desconectado")])
    evolution = FakeEvolution({"quebrada": RuntimeError("timeout"), "elitebaby01": "open"})
    total = asyncio.run(reconciliar_conexao_evolution(conn, evolution))
    assert total == 1
    assert conn.updates == [("conectado", "conectado", "elitebaby01")]
