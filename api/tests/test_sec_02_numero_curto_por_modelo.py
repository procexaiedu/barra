"""SEC-02: comando #N no grupo de Coordenacao e escopado pela modelo dona da instance.

Invariante (CONTEXT.md "Atendimento" / "#N por modelo"): numero_curto e UNIQUE por
(modelo_id, numero_curto), nao global. Dois grupos de Coordenacao distintos podem ter o
MESMO #N; um comando num grupo so pode afetar o atendimento da modelo daquele grupo.
A barreira e a QUERY (AND modelo_id = %s), nunca a boa-vontade do chamador.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from barra.webhook import routes
from barra.webhook.parser import MensagemEvolution

_MODELO_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_MODELO_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_ATEND_A = UUID("a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1")
_ATEND_B = UUID("b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1")

# Mesmo #N nas duas modelos — exatamente o cenario de corrupcao cross-modelo.
_NUMERO = 5


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    """Conn fake que resolve modelo por instance e atendimento por (numero, modelo)."""

    def __init__(self) -> None:
        self.binds: list[tuple[str, Any]] = []
        self._modelo_por_instance = {"inst-a": _MODELO_A, "inst-b": _MODELO_B}
        self._atend_por_chave = {
            (_NUMERO, _MODELO_A): _ATEND_A,
            (_NUMERO, _MODELO_B): _ATEND_B,
        }

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        self.binds.append((query, params))
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([])  # nao e outbound do backend
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            modelo_id = self._modelo_por_instance.get(params[0])
            return _Result([{"id": modelo_id}] if modelo_id is not None else [])
        if "FROM barravips.atendimentos" in query:
            numero, modelo_id = params[0], params[1]
            atend = self._atend_por_chave.get((numero, modelo_id))
            return _Result([{"id": atend}] if atend is not None else [])
        return _Result([])


def _request() -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(evolution_fernando_jids=[]))
        )
    )


def _msg(instance_id: str) -> MensagemEvolution:
    # from_me=True -> autor "modelo"; comando fechado com valor e #N explicito.
    return MensagemEvolution(
        evolution_message_id="MSG-1",
        instance_id=instance_id,
        remote_jid="120363000000000000@g.us",
        sender_jid=None,
        from_me=True,
        texto=f"fechado 1000 #{_NUMERO}",
        tipo="texto",
        media_url=None,
        quoted_message_id=None,
    )


async def test_comando_so_afeta_atendimento_da_modelo_dona_da_instance(monkeypatch) -> None:
    aplicados: list[UUID] = []

    async def _fake_aplicar(conn, *, origem, autor, atendimento_id, comando, payload):
        aplicados.append(atendimento_id)

    monkeypatch.setattr(routes, "aplicar_comando", _fake_aplicar)

    # Grupo da modelo A: comando #5 deve fechar o #5 da A, jamais o #5 da B.
    conn_a = FakeConn()
    res_a = await routes._processar_grupo(conn_a, _request(), _msg("inst-a"), None)
    assert res_a == {"status": "processed"}
    assert aplicados == [_ATEND_A]
    assert _ATEND_B not in aplicados

    # A query de atendimento foi escopada por modelo_id (a barreira e o AND modelo_id=%s).
    atend_binds = [p for (q, p) in conn_a.binds if "FROM barravips.atendimentos" in q]
    assert atend_binds == [(_NUMERO, _MODELO_A)]

    # Grupo da modelo B: mesmo #5, mas resolve o atendimento da B.
    aplicados.clear()
    conn_b = FakeConn()
    res_b = await routes._processar_grupo(conn_b, _request(), _msg("inst-b"), None)
    assert res_b == {"status": "processed"}
    assert aplicados == [_ATEND_B]
    assert _ATEND_A not in aplicados


async def test_modelo_nao_resolvida_recusa_sem_afetar_atendimento(monkeypatch) -> None:
    aplicados: list[UUID] = []

    async def _fake_aplicar(conn, *, origem, autor, atendimento_id, comando, payload):
        aplicados.append(atendimento_id)

    monkeypatch.setattr(routes, "aplicar_comando", _fake_aplicar)

    conn = FakeConn()
    res = await routes._processar_grupo(conn, _request(), _msg("instance-desconhecida"), None)

    # Instance sem modelo cadastrada: recusa, e nunca toca atendimento de ninguem.
    assert res == {"status": "unknown_instance"}
    assert aplicados == []
    assert [p for (q, p) in conn.binds if "FROM barravips.atendimentos" in q] == []
