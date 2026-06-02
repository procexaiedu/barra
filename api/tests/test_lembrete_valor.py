"""Testes do Lembrete de fechamento (ADR-0007): cron cobrar_valor_final + resolução do quote."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        self.transacoes = 0  # quantas vezes conn.transaction() foi aberto (transacao + savepoints)

    async def execute(self, query: str, params: tuple | None = None) -> _Result:
        self.queries.append(query)
        return _Result(self._rows)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["FakeConn"]:
        # Espelha psycopg3: transacao no nivel externo, savepoint quando aninhado. Nao suprime
        # excecao -> a falha de um alvo propaga e e capturada pelo except do laco (best-effort).
        self.transacoes += 1
        yield self


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
        "coordenacao_chat_id": "grupo-modelo-a@g.us",
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
    # REL-05: trava o alvo escopado em `a` (LATERAL agregado exige OF a) e pula o que outro
    # worker já segurou — em vez de disparar o mesmo card 2x.
    assert "FOR UPDATE OF a SKIP LOCKED" in q


def test_roda_dentro_de_transacao() -> None:
    # REL-05: busca + envio na MESMA transacao (1 externa + 1 savepoint por alvo) -> o lock do
    # FOR UPDATE sobrevive ate o card commitar.
    conn = FakeConn([_alvo("enviar", 0)])
    asyncio.run(cobrar_valor_final(conn, FakeEvolution(), FakeSettings()))
    assert conn.transacoes == 2  # 1 transacao externa + 1 savepoint do alvo


def test_falha_de_um_alvo_nao_aborta_o_lote() -> None:
    # REL-05: dentro da transacao unica, o savepoint isola a falha — o 1o alvo (canal ausente)
    # vira falha e o 2o ainda recebe o card. Sem savepoint, a transacao abortada derrubaria o 2o.
    conn = FakeConn(
        [
            _alvo("enviar", 0, evolution_instance_id=None),  # canal ausente -> RuntimeError
            _alvo("enviar", 0, numero_curto=9, cliente_nome="Ana"),
        ]
    )
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 1  # so o 2o conta
    assert len(evo.envios) == 1
    assert "#9" in evo.envios[0]["texto"]


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
    assert env["remote_jid"] == "grupo-modelo-a@g.us"
    assert "#7" in env["texto"]
    assert "Carlos" in env["texto"]


def test_card_vai_para_o_grupo_da_modelo_dona() -> None:
    # Isolamento por par: cada card é postado no grupo de Coordenação DA MODELO dona do
    # atendimento (`coordenacao_chat_id`), nunca num JID global — senão o nome do cliente de
    # uma modelo vazaria no grupo de outra.
    conn = FakeConn(
        [
            _alvo("enviar", 0, coordenacao_chat_id="grupo-a@g.us", cliente_nome="Carlos"),
            _alvo(
                "enviar", 0, coordenacao_chat_id="grupo-b@g.us", cliente_nome="Ana", numero_curto=9
            ),
        ]
    )
    evo = FakeEvolution()
    asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    destinos = {e["remote_jid"]: e["texto"] for e in evo.envios}
    assert "Carlos" in destinos["grupo-a@g.us"]
    assert "Ana" in destinos["grupo-b@g.us"]


def test_coordenacao_ausente_vira_falha_sem_quebrar_lote() -> None:
    # `coordenacao_chat_id` NULL (modelo sem grupo configurado) não cai em fallback global:
    # vira falha best-effort, sem enviar o card a lugar nenhum.
    conn = FakeConn([_alvo("enviar", 0, coordenacao_chat_id=None)])
    evo = FakeEvolution()
    total = asyncio.run(cobrar_valor_final(conn, evo, FakeSettings()))
    assert total == 0
    assert evo.envios == []


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
