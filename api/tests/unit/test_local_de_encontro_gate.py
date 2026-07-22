"""Gate estrutural do endereço (análise prod 22/07, caso #12): o ponto de encontro da modelo
só entra no contexto do turno (<local_de_encontro>) a partir de Qualificado e em atendimento
interno — em Novo/Triagem a IA literalmente não tem o endereço para vazar, e no externo/remoto
o bloco não se aplica (endereço é do cliente / não há local)."""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _libera_local_de_encontro, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_ENDERECO = "Av. Aquidabã, 130 - Centro, Campinas-SP"
_HOTEL = "Hotel Sirius"


def test_gate_por_estado_e_tipo() -> None:
    # Libera: Qualificado em diante, só interno.
    for estado in ("Qualificado", "Aguardando_confirmacao", "Confirmado", "Em_execucao"):
        assert _libera_local_de_encontro(estado, "interno")
    # Trava: pré-Qualificado (mesmo interno), tipo indefinido, externo/remoto, terminais.
    for estado in ("Novo", "Triagem", None, "Fechado", "Perdido"):
        assert not _libera_local_de_encontro(estado, "interno")
    for tipo in ("externo", "remoto", None):
        assert not _libera_local_de_encontro("Qualificado", tipo)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Serve o atendimento e a ficha da modelo; vazio no resto. Registra as queries feitas."""

    def __init__(self, atendimento: dict[str, Any]) -> None:
        self.atendimento = atendimento
        self.calls: list[str] = []

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        self.calls.append(sql)
        if "barravips.atendimentos" in sql and "numero_curto" in sql:
            return _Result([self.atendimento])
        if "endereco_formatado" in sql and "barravips.modelos" in sql:
            return _Result([{"endereco_formatado": _ENDERECO, "nome_local": _HOTEL}])
        return _Result([])


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 22, 23, 0, tzinfo=UTC),
    )


async def test_qualificado_interno_injeta_local_de_encontro() -> None:
    conn = _FakeConn({"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"})
    variaveis = await _resolver_variaveis(conn, _ctx())  # type: ignore[arg-type]
    assert variaveis["local_endereco"] == _ENDERECO
    assert variaveis["local_nome"] == _HOTEL

    saida = render_contexto_dinamico(**variaveis)
    assert "<local_de_encontro>" in saida
    assert _ENDERECO in saida
    assert _HOTEL in saida
    assert "SEM o número" in saida  # instrução dos degraus junto do dado


async def test_triagem_nao_carrega_nem_renderiza_endereco() -> None:
    conn = _FakeConn({"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": "interno"})
    variaveis = await _resolver_variaveis(conn, _ctx())  # type: ignore[arg-type]
    assert variaveis["local_endereco"] is None
    # A query da ficha nem roda: o endereço não entra no processo antes do gate.
    assert not any("endereco_formatado" in sql for sql in conn.calls)
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis)


async def test_externo_qualificado_nao_injeta_endereco_da_modelo() -> None:
    conn = _FakeConn({"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "externo"})
    variaveis = await _resolver_variaveis(conn, _ctx())  # type: ignore[arg-type]
    assert variaveis["local_endereco"] is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis)
