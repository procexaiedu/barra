"""POST /v1/pix/{id}/aprovar num atendimento que já é terminal (`Fechado`/`Perdido`).

A fila de revisão de comprovantes é assíncrona **por design** (CONTEXT.md, "Pix de deslocamento":
o Pix nunca trava o fluxo — divergência vira `em_revisao` e Fernando revisa depois). Então o
caminho normal é: o encontro acontece, a modelo manda `finalizado 800` no grupo (`Fechado`) e só
dias depois Fernando limpa a fila e aprova o comprovante.

Aprovar é uma decisão sobre o **comprovante**, não sobre o **atendimento**: `pix_status` e
`decisao_final` são gravados (auditoria financeira, timeline do cliente), mas o atendimento não
volta para `Confirmado` — isso sumiria com a venda do faturamento (dashboard/resumo filtram
`estado='Fechado'`), reabriria o par contra o índice único parcial
`atendimentos_um_aberto_por_par` e devolveria o zumbi ao `timeout_longo`.

Mesmo padrão de FakeConn dos demais testes de rota do painel (test_atendimentos_pausar.py): sem
DB real, só a fiação do endpoint. A regra de estado em si está coberta em test_operacional.py.
"""

from contextlib import asynccontextmanager
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.dominio.pix import routes as pix_routes
from barra.main import app

CHAT_COORDENACAO = "5521999@g.us"
INSTANCIA = "inst-1"


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """`_pix()` -> UPDATE comprovantes_pix -> `aplicar_comando` (SELECT FOR UPDATE, UPDATE
    atendimentos, INSERT eventos)."""

    def __init__(self, *, pix: dict[str, Any], atendimento: dict[str, Any]) -> None:
        self.pix = pix
        self.atendimento = atendimento
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.comprovantes_pix p" in query and "SELECT" in query:
            return _Result([self.pix])
        if "FOR UPDATE OF a" in query:
            return _Result([self.atendimento])
        if "UPDATE barravips.atendimentos" in query:
            if "ia_pausada = true" in query:
                self.atendimento["estado"] = "Confirmado"
                self.atendimento["ia_pausada"] = True
            if "pix_status = 'validado'" in query:
                self.atendimento["pix_status"] = "validado"
        return _Result([])


class _EvolutionEspiao:
    # A rota instancia o client por conta própria (`EvolutionClient(settings)`), então o espião
    # acumula os envios num atributo de classe.
    enviados: ClassVar[list[str]] = []

    def __init__(self, _settings: Any) -> None:
        pass

    async def enviar_texto(self, **kwargs: Any) -> str:
        _EvolutionEspiao.enviados.append(kwargs["texto"])
        return "msg-1"


@pytest.fixture(autouse=True)
def _evolution_espiao(monkeypatch: pytest.MonkeyPatch):
    _EvolutionEspiao.enviados = []
    monkeypatch.setattr(pix_routes, "EvolutionClient", _EvolutionEspiao)
    yield


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _atendimento(estado: str) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "estado": estado,
        "pix_status": "em_revisao",
        "ia_pausada": estado not in {"Fechado", "Perdido"},
        "tipo_atendimento": "externo",
        "percentual_repasse": None,
        "bloqueio_id": None,
    }


def _pix_row(atendimento: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "atendimento_id": atendimento["id"],
        "decisao_pipeline": "em_revisao",
        "decisao_final": None,
        "numero_curto": 12,
        "conversa_id": uuid4(),
        "coordenacao_chat_id": CHAT_COORDENACAO,
        "evolution_instance_id": INSTANCIA,
    }


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def _aprovar(conn: FakeConn, pix_id: UUID):
    app.dependency_overrides[get_conn] = _override(conn)
    try:
        with TestClient(app) as client:
            return client.post(f"/v1/pix/{pix_id}/aprovar", json={}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)


@pytest.mark.parametrize("estado", ["Fechado", "Perdido"])
def test_aprovar_pix_de_atendimento_terminal_nao_reverte_estado(estado: str) -> None:
    atendimento = _atendimento(estado)
    pix = _pix_row(atendimento)
    conn = FakeConn(pix=pix, atendimento=atendimento)

    response = _aprovar(conn, pix["id"])

    # Aprovar não é erro: o operador está limpando a fila e a decisão é legítima.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decisao_final"] == "validado"
    # ...o comprovante é registrado...
    assert any("UPDATE barravips.comprovantes_pix" in q for q in conn.queries)
    assert conn.atendimento["pix_status"] == "validado"
    # ...e o atendimento continua terminal, sem pausa da IA nem transição.
    assert conn.atendimento["estado"] == estado
    assert conn.atendimento["ia_pausada"] is False
    assert not any("ia_pausada = true" in q for q in conn.queries)
    # A resposta diz ao painel o que aconteceu de fato.
    assert body["atendimento"]["estado"] == estado
    assert body["atendimento"]["terminal"] is True
    # E a modelo não recebe "Saida confirmada" de um encontro que já acabou.
    assert _EvolutionEspiao.enviados == []


def test_aprovar_pix_de_atendimento_vivo_segue_confirmando_e_avisando() -> None:
    atendimento = _atendimento("Aguardando_confirmacao")
    pix = _pix_row(atendimento)
    conn = FakeConn(pix=pix, atendimento=atendimento)

    response = _aprovar(conn, pix["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decisao_final"] == "validado"
    assert body["atendimento"]["estado"] == "Confirmado"
    assert body["atendimento"]["terminal"] is False
    assert conn.atendimento["estado"] == "Confirmado"
    assert conn.atendimento["ia_pausada"] is True
    assert _EvolutionEspiao.enviados == ["Saida confirmada #12"]
