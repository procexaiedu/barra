"""Testes do Lembrete de fechamento (ADR-0007): cron cobrar_valor_final + resolução do quote."""

import asyncio
from uuid import uuid4

from barra.webhook.routes import _resolver_card
from barra.workers.lembrete_valor import CARD_KIND, OBS_ESCALADA, cobrar_valor_final


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict]:
        return self._rows

    async def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.queries: list[str] = []

    async def execute(self, query: str, params: tuple | None = None) -> _Result:
        self.queries.append(query)
        return _Result(self._rows)


class FakeEvolution:
    def __init__(self) -> None:
        self.envios: list[dict] = []

    async def enviar_texto(self, **kwargs: object) -> str:
        self.envios.append(kwargs)
        return "card-msg-1"


class FakeSettings:
    def __init__(self, **over: object) -> None:
        self.lembrete_valor_ativo = True
        self.lembrete_valor_tolerancia_min = 15
        self.lembrete_valor_intervalo_min = 30
        self.lembrete_valor_max_toques = 3
        self.evolution_grupo_coordenacao_jid = "5521@g.us"
        for k, v in over.items():
            setattr(self, k, v)


def _alvo(acao: str, toques: int, **over: object) -> dict:
    base = {
        "id": uuid4(),
        "numero_curto": 7,
        "evolution_instance_id": "inst-1",
        "cliente_nome": "Carlos",
        "toques": toques,
        "acao": acao,
    }
    base.update(over)
    return base


def test_desligado_nao_consulta_nem_age() -> None:
    conn = FakeConn([_alvo("enviar", 0)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings(lembrete_valor_ativo=False)))
    assert total == 0
    assert evo.envios == []
    assert conn.queries == []  # nem busca alvos quando desligado


def test_query_alvos_tem_guardas() -> None:
    conn = FakeConn([])
    asyncio.run(cobrar_valor_final(conn, FakeEvolution(), FakeSettings()))
    q = conn.queries[0]
    assert "Em_execucao" in q
    assert "card_kind" in q
    assert "e.observacao = %s" in q  # guard: já escalado some do conjunto
    assert "fechada_em IS NULL" in q
    assert "make_interval" in q


def test_envia_primeiro_card() -> None:
    conn = FakeConn([_alvo("enviar", 0)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 1
    assert len(evo.envios) == 1
    env = evo.envios[0]
    assert env["contexto"] == "grupo_coordenacao"
    assert env["tipo"] == "card"
    assert env["payload"] == {"card_kind": CARD_KIND}
    assert env["remote_jid"] == "5521@g.us"
    assert "#7" in env["texto"]
    assert "Carlos" in env["texto"]


def test_reenvio_ainda_manda_card() -> None:
    conn = FakeConn([_alvo("enviar", 1)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 1
    assert len(evo.envios) == 1


def test_escala_apos_max_nao_manda_card(monkeypatch) -> None:
    chamado: dict = {}

    async def fake_handoff(conn, **kwargs):
        chamado.update(kwargs)

    monkeypatch.setattr("barra.dominio.escaladas.service.abrir_handoff", fake_handoff)
    conn = FakeConn([_alvo("escalar", 3)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 1
    assert evo.envios == []  # escala não envia card
    assert chamado["responsavel"] == "Fernando"
    assert chamado["observacao"] == OBS_ESCALADA

    from barra.dominio.escaladas.modelos import TipoEscalada

    assert chamado["tipo"] == TipoEscalada.outro


def test_canal_ausente_vira_falha_sem_quebrar_lote() -> None:
    conn = FakeConn([_alvo("enviar", 0, evolution_instance_id=None)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 0  # falha não conta como ação
    assert evo.envios == []


def test_resolver_card_de_lembrete() -> None:
    conn = FakeConn([{"numero_curto": 7, "lembrete": True}])
    numero, aguardando = asyncio.run(_resolver_card(conn, "card-1"))
    assert numero == 7
    assert aguardando is True
