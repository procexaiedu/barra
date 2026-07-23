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
    """Vazio em tudo: atendimento e o local CRU (endereco_formatado/nome_local) chegam por kwarg —
    o local é lido junto da identidade em _carregar_bp3 (fusão da leitura de `modelos`)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
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


async def _resolver(atendimento: dict[str, Any]) -> dict[str, Any]:
    # O local CRU é SEMPRE passado (é lido junto da identidade); o gate por estado/tipo decide se
    # ele entra no contexto. Provamos que o gate — não a ausência do dado — é o que protege.
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento=atendimento,
        local_endereco_raw=_ENDERECO,
        local_nome_raw=_HOTEL,
    )


async def test_qualificado_interno_injeta_local_de_encontro() -> None:
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"}
    )
    assert variaveis["local_endereco"] == _ENDERECO
    assert variaveis["local_nome"] == _HOTEL

    saida = render_contexto_dinamico(**variaveis)
    assert "<local_de_encontro>" in saida
    assert _ENDERECO in saida
    assert _HOTEL in saida
    assert "SEM o número" in saida  # instrução dos degraus junto do dado


async def test_triagem_nao_renderiza_endereco() -> None:
    # Mesmo com o local CRU disponível (lido em _carregar_bp3), o gate o mantém FORA do contexto
    # antes de Qualificado: a IA nunca o vê renderizado, então não há o que vazar.
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": "interno"}
    )
    assert variaveis["local_endereco"] is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis)


async def test_externo_qualificado_nao_injeta_endereco_da_modelo() -> None:
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "externo"}
    )
    assert variaveis["local_endereco"] is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis)
