"""F1.3 — debounce multi-device + `fromMe` com payload real (UX).

Tranca duas invariantes da borda do webhook contra regressao, exercitando o handler
inteiro (`/webhook/evolution`) com payloads no formato real da Evolution v2.3.6 — nao
o caso sintetico mockado que o `webhook/CLAUDE.md` adverte nao cobrir:

1. **Duplicata real coalescida** (multi-device): WhatsApp Web + celular emitem o MESMO
   `key.id` para a mesma mensagem, e o mesmo contato pode aparecer com JID de telefone
   (`@s.whatsapp.net`) numa entrega e LID (`@lid`) na outra. O dedupe é por
   `evolution_message_id` (independe do JID), entao a 2a entrega vira `duplicate`: sem 2o
   INSERT em `mensagens` e sem 2o turno enfileirado.
2. **`fromMe` distinguido pelo originador real** — manual da modelo atribuida a ELA, nao a
   IA. A IA escreve via `core/evolution.py`, que grava o envio em `envios_evolution`; a
   modelo digitando manualmente no mesmo numero NAO. Card/echo da IA (`envio_existe=True`)
   = `outbound_ignored` antes de qualquer atribuicao; mensagem manual da modelo
   (`fromMe=true`, **sem** `key.participant`, ausente de `envios_evolution`) = autor
   `"modelo"`, processada como comando dela. A distincao nao confia so na flag `fromMe`.

Determinístico (sem banco, sem API): roda no `make test` padrao — gate de PR de verdade.
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from barra.main import app
from barra.webhook.parser import extrair_mensagem
from barra.webhook.routes import _autor_grupo

_MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENTE_ID = UUID("22222222-2222-2222-2222-222222222222")
_CONVERSA_ID = UUID("33333333-3333-3333-3333-333333333333")
_ATENDIMENTO_ID = UUID("44444444-4444-4444-4444-444444444444")

_GRUPO_JID = "120363000000000000@g.us"

# Indice de `evolution_message_id` no bind do INSERT de mensagens (ultima coluna; ver
# `_persistir_cliente`): conversa_id, atendimento_id, direcao, tipo, conteudo, media_key, ev_id.
_INSERT_EVID_IDX = -1


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _DedupeConn:
    """Conn fake com dedupe REAL por `evolution_message_id`: lembra o que ja foi
    inserido em `mensagens` e responde `_mensagem_ja_persistida` a partir disso — em vez
    de um booleano fixo. So assim a 2a entrega multi-device prova a coalescencia (a 1a
    persiste, a 2a vê o id ja gravado), nao a tautologia "se existe entao duplicate"."""

    def __init__(self) -> None:
        self.persistidos: set[str] = set()
        self.queries: list[str] = []
        self.binds: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        self.queries.append(query)
        self.binds.append((query, params))
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            ev_id = params[0] if params else None
            return _Result([{"?column?": 1}] if ev_id in self.persistidos else [])
        if "INSERT INTO barravips.mensagens" in query:
            if params:
                self.persistidos.add(params[_INSERT_EVID_IDX])
            return _Result([])
        if "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"?column?": 1}])  # _instance_cadastrada
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO_ID}])
        if "WHERE coordenacao_chat_id" in query:
            return _Result([])  # nao é grupo: força ramo cliente
        if "INSERT INTO barravips.clientes" in query:
            return _Result([{"id": _CLIENTE_ID}])
        if "INSERT INTO barravips.conversas" in query:
            return _Result([{"id": _CONVERSA_ID}])
        return _Result([])


class _GrupoConn:
    """Conn fake do ramo de grupo: resolve modelo+atendimento e responde `envio_existe`
    pelo flag (IA-echo vs manual)."""

    def __init__(self, *, envio_existe: bool) -> None:
        self._envio_existe = envio_existe
        self.queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        self.queries.append(query)
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([])  # grupo nao é dedupado por mensagens
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self._envio_existe else [])
        if (
            "SELECT status::text AS status FROM barravips.modelos WHERE evolution_instance_id"
            in query
        ):
            return _Result([{"status": "ativa"}])  # _status_modelo_por_instance
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO_ID}])  # _modelo_por_instance
        if "FROM barravips.atendimentos" in query and "numero_curto" in query:
            return _Result([{"id": _ATENDIMENTO_ID}])  # _atendimento_por_numero
        return _Result([])


class _Pool:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn

    async def close(self) -> None:
        return None


class _Arq:
    def __init__(self) -> None:
        self.sets: list[tuple[str, Any, Any]] = []
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: Any, ex: Any = None) -> None:
        self.sets.append((key, value, ex))

    async def enqueue_job(self, name: str, **kwargs: Any) -> Any:
        # devolve truthy como o ARQ real no sucesso (None = coalesced -> dispararia a varredura)
        self.enqueued.append((name, kwargs))
        return object()

    async def aclose(self) -> None:
        return None


def _payload_cliente(message_id: str, remote_jid: str) -> dict[str, Any]:
    """messages.upsert real de cliente 1:1 (texto)."""
    return {
        "event": "messages.upsert",
        "instance": "barra",
        "data": {
            "key": {"id": message_id, "remoteJid": remote_jid, "fromMe": False},
            "pushName": "Cliente",
            "message": {"conversation": "oi, atende em hotel?"},
            "messageType": "conversation",
        },
    }


def _payload_grupo_manual_modelo(message_id: str, texto: str) -> dict[str, Any]:
    """messages.upsert real de mensagem MANUAL da modelo no grupo de Coordenacao:
    `fromMe=true` e **sem** `key.participant` (o quirk capturado em prod — a stack nao
    inclui participant nas proprias mensagens em grupo)."""
    return {
        "event": "messages.upsert",
        "instance": "barra",
        "data": {
            "key": {"id": message_id, "remoteJid": _GRUPO_JID, "fromMe": True},
            "message": {"conversation": texto},
            "messageType": "conversation",
        },
    }


def _configurar(grupo_jid: str | None) -> None:
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = grupo_jid
    settings.evolution_fernando_jids = []


# ---------------------------------------------------------------------------
# 1. Duplicata real coalescida (multi-device): mesmo key.id, JIDs diferentes.
# ---------------------------------------------------------------------------


def test_duplicata_multidevice_mesmo_id_jids_diferentes_coalesce() -> None:
    """A mesma mensagem chega 2x (WhatsApp Web + celular): mesmo `key.id`, mas JID de
    telefone numa entrega e LID na outra. A 1a persiste e enfileira; a 2a vira
    `duplicate` — sem 2o INSERT, sem 2o turno. Coalescencia por message_id, nao por JID."""
    _configurar(grupo_jid="grupo-diferente@g.us")  # força ramo cliente
    conn = _DedupeConn()
    arq = _Arq()
    msg_id = "3EB0C4...MULTIDEVICE"
    primeira = _payload_cliente(msg_id, "5521999999999@s.whatsapp.net")
    segunda = _payload_cliente(msg_id, "199999999999@lid")  # mesmo contato, JID diferente

    with TestClient(app) as client:
        app.state.db_pool = _Pool(conn)
        app.state.arq = arq
        r1 = client.post("/webhook/evolution", json=primeira)
        r2 = client.post("/webhook/evolution", json=segunda)

    assert r1.json() == {"status": "received"}
    assert r2.json() == {"status": "duplicate"}

    inserts = [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q]
    assert len(inserts) == 1, "duplicata multi-device gravou a mensagem 2x"

    turnos = [n for (n, _k) in arq.enqueued if n == "processar_turno"]
    assert len(turnos) == 1, "duplicata multi-device enfileirou o turno 2x"


# ---------------------------------------------------------------------------
# 2. fromMe distinguido pelo originador real (modelo vs IA), payload real.
# ---------------------------------------------------------------------------


def test_autor_grupo_manual_modelo_sem_participant_e_modelo() -> None:
    """Parser + atribuicao isolados: payload real `fromMe=true` SEM `key.participant`
    extrai `sender_jid=None`/`from_me=True`, e `_autor_grupo` (sem Fernando) o atribui a
    `"modelo"` — nao confia na ausencia de participant pra cair em None."""
    msg = extrair_mensagem(_payload_grupo_manual_modelo("MANUAL-1", "fechado 1500 #12"))
    assert msg is not None
    assert msg.from_me is True
    assert msg.sender_jid is None  # fromMe nao traz participant (quirk real)
    assert _autor_grupo([], msg) == "modelo"


def test_grupo_manual_modelo_aplica_comando_como_modelo(monkeypatch: Any) -> None:
    """Fluxo inteiro: mensagem MANUAL da modelo no grupo (fromMe, sem participant, ausente
    de `envios_evolution`) → `aplicar_comando(autor="modelo")`. Atribuida a ela, nao a IA."""
    _configurar(grupo_jid=_GRUPO_JID)
    conn = _GrupoConn(envio_existe=False)
    capturado: dict[str, Any] = {}

    async def _fake_aplicar(conn_: Any, **kwargs: Any) -> None:
        capturado.update(kwargs)

    monkeypatch.setattr("barra.webhook.routes.aplicar_comando", _fake_aplicar)

    with TestClient(app) as client:
        app.state.db_pool = _Pool(conn)
        app.state.arq = _Arq()
        resp = client.post(
            "/webhook/evolution",
            json=_payload_grupo_manual_modelo("MANUAL-2", "fechado 1500 #12"),
        )

    assert resp.json() == {"status": "processed"}
    assert capturado.get("autor") == "modelo"
    assert capturado.get("comando") == "registrar_fechado"
    assert capturado.get("atendimento_id") == _ATENDIMENTO_ID


def test_grupo_echo_da_ia_e_ignorado_nao_vira_comando_da_modelo(monkeypatch: Any) -> None:
    """O echo da propria IA volta como `fromMe=true` (mesmo numero). Como o id ESTA em
    `envios_evolution` (originador real = backend), vira `outbound_ignored` ANTES de
    qualquer atribuicao — `aplicar_comando` nunca roda. Sem o gate por originador, o
    `fromMe` sozinho atribuiria o texto da IA a modelo e o re-executaria como comando."""
    _configurar(grupo_jid=_GRUPO_JID)
    conn = _GrupoConn(envio_existe=True)
    chamadas: list[dict[str, Any]] = []

    async def _fake_aplicar(conn_: Any, **kwargs: Any) -> None:
        chamadas.append(kwargs)

    monkeypatch.setattr("barra.webhook.routes.aplicar_comando", _fake_aplicar)

    with TestClient(app) as client:
        app.state.db_pool = _Pool(conn)
        app.state.arq = _Arq()
        resp = client.post(
            "/webhook/evolution",
            json=_payload_grupo_manual_modelo("ECHO-IA-1", "fechado 1500 #12"),
        )

    assert resp.json() == {"status": "outbound_ignored"}
    assert chamadas == [], "echo da IA foi processado como comando da modelo"
