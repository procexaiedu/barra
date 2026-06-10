"""Integração do webhook Evolution: idempotência, outbound ignorado e webhook fino (M3c)."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from barra.main import app

_MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENTE_ID = UUID("22222222-2222-2222-2222-222222222222")
_CONVERSA_ID = UUID("33333333-3333-3333-3333-333333333333")


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """Conn fake que registra queries/binds e retorna respostas determinísticas."""

    def __init__(
        self, *, mensagem_existe: bool, envio_existe: bool, grupo_por_banco: bool = False
    ) -> None:
        self.mensagem_existe = mensagem_existe
        self.envio_existe = envio_existe
        self.grupo_por_banco = grupo_por_banco
        self.queries: list[str] = []
        self.binds: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        self.binds.append((query, params))
        if "FROM barravips.mensagens WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.mensagem_existe else [])
        if "FROM barravips.envios_evolution WHERE evolution_message_id" in query:
            return _Result([{"?column?": 1}] if self.envio_existe else [])
        if "WHERE coordenacao_chat_id" in query:
            return _Result([{"?column?": 1}] if self.grupo_por_banco else [])
        if "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"?column?": 1}])  # _instance_cadastrada
        if "SELECT id FROM barravips.modelos WHERE evolution_instance_id" in query:
            return _Result([{"id": _MODELO_ID}])
        if "INSERT INTO barravips.clientes" in query:
            return _Result([{"id": _CLIENTE_ID}])
        if "INSERT INTO barravips.conversas" in query:
            return _Result([{"id": _CONVERSA_ID}])
        return _Result([])


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn

    async def close(self) -> None:
        return None


class FakeArq:
    """ArqRedis fake: registra set/enqueue_job; aclose é chamado no teardown do lifespan."""

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


def _payload_grupo(message_id: str = "MSG-1", from_me: bool = True) -> dict[str, Any]:
    return {
        "instance": "barra",
        "data": {
            "key": {
                "id": message_id,
                "remoteJid": "120363000000000000@g.us",
                "fromMe": from_me,
            },
            "message": {"conversation": "finalizado 1000 #12"},
        },
    }


def _configurar_grupo() -> None:
    settings = app.state.settings
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None


def test_webhook_idempotente_nao_duplica_mensagem() -> None:
    _configurar_grupo()
    settings = app.state.settings
    settings.evolution_grupo_coordenacao_jid = "outro-jid@g.us"  # força ramo cliente
    conn = FakeConn(mensagem_existe=True, envio_existe=False)
    payload = {
        "instance": "barra",
        "data": {
            "key": {"id": "MSG-DUPL", "remoteJid": "5521999999999@s.whatsapp.net"},
            "message": {"conversation": "oi"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "duplicate"}
    insert_msg = [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q]
    assert insert_msg == []


def test_webhook_outbound_do_backend_e_ignorado_no_grupo() -> None:
    _configurar_grupo()
    conn = FakeConn(mensagem_existe=False, envio_existe=True)
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        response = client.post("/webhook/evolution", json=_payload_grupo("OUTBOUND-1"))
    assert response.status_code == 200
    assert response.json() == {"status": "outbound_ignored"}
    update_atendimento = [q for q in conn.queries if "UPDATE barravips.atendimentos" in q]
    assert update_atendimento == []


def test_webhook_cliente_texto_persiste_orfa_e_enfileira_turno() -> None:
    """Webhook fino (M3c): texto do cliente → mensagem órfã + enqueue, sem atendimento eager."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = "grupo-diferente@g.us"  # força ramo cliente
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    arq = FakeArq()
    payload = {
        "instance": "barra",
        "data": {
            "key": {"id": "MSG-TXT-1", "remoteJid": "5521988887777@s.whatsapp.net"},
            "message": {"conversation": "oi, tudo bem?"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "received"}

    # Mensagem persistida como órfã: atendimento_id (2º bind) é NULL.
    insert_msg = [(q, p) for (q, p) in conn.binds if "INSERT INTO barravips.mensagens" in q]
    assert len(insert_msg) == 1
    _, params = insert_msg[0]
    assert params is not None
    assert params[0] == _CONVERSA_ID  # conversa_id
    assert params[1] is None  # atendimento_id NULL

    # Nenhum atendimento criado no caminho do cliente (criação é do coordenador).
    assert [q for q in conn.queries if "INSERT INTO barravips.atendimentos" in q] == []

    # Turno enfileirado uma única vez, com _job_id estático de coalescência.
    assert len(arq.enqueued) == 1
    nome, kwargs = arq.enqueued[0]
    assert nome == "processar_turno"
    assert kwargs["conversa_id"] == str(_CONVERSA_ID)
    assert kwargs["_job_id"] == f"turno:{_CONVERSA_ID}"
    # pending + debounce marcados em Redis.
    chaves = {chave for (chave, _v, _ex) in arq.sets}
    assert f"pending:conv:{_CONVERSA_ID}" in chaves
    assert f"debounce:conv:{_CONVERSA_ID}" in chaves


def test_webhook_from_me_1a1_persiste_modelo_manual_sem_turno() -> None:
    """fromMe no chat 1:1 sem registro em envios_evolution = a modelo digitando manualmente no
    proprio numero (mvp/05 §4.2/§5.3): persiste com direcao='modelo_manual' e NAO enfileira
    turno — a IA absorve no contexto do proximo turno do cliente, nunca responde a propria
    modelo. Antes era gravada como 'cliente' e virava turno."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = "grupo-diferente@g.us"  # força ramo cliente
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    arq = FakeArq()
    payload = {
        "instance": "barra",
        "data": {
            "key": {
                "id": "MSG-MANUAL-1",
                "remoteJid": "5521988887777@s.whatsapp.net",
                "fromMe": True,
            },
            "message": {"conversation": "amor, chego 22h em ponto"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "modelo_manual"}
    insert_msg = [(q, p) for (q, p) in conn.binds if "INSERT INTO barravips.mensagens" in q]
    assert len(insert_msg) == 1
    query, params = insert_msg[0]
    assert params is not None
    assert "modelo_manual" in query or "modelo_manual" in params
    assert "'cliente'" not in query
    # Nenhum turno: a IA nao responde a fala da propria modelo.
    assert arq.enqueued == []


def test_webhook_from_me_1a1_eco_da_ia_e_ignorado() -> None:
    """fromMe no 1:1 que JA esta em envios_evolution e eco do envio da propria IA: ignora sem
    persistir nada (desambiguacao canonica pelo originador real — webhook/CLAUDE.md)."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = "grupo-diferente@g.us"
    conn = FakeConn(mensagem_existe=False, envio_existe=True)
    arq = FakeArq()
    payload = {
        "instance": "barra",
        "data": {
            "key": {
                "id": "MSG-ECO-1",
                "remoteJid": "5521988887777@s.whatsapp.net",
                "fromMe": True,
            },
            "message": {"conversation": "oi amor, tudo bem?"},
        },
    }
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "outbound_ignored"}
    assert [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q] == []
    assert arq.enqueued == []


def test_webhook_grupo_reconhecido_por_coordenacao_chat_id() -> None:
    """Multi-modelo: comando chega do grupo da modelo (coordenacao_chat_id) com o JID
    global de settings DESLIGADO. Deve entrar no fluxo de grupo (e aqui parar como
    `invalid` porque o atendimento #12 não existe no FakeConn) — nunca ser tratado como
    mensagem de cliente. Sem o reconhecimento por banco, cairia no ramo cliente
    (INSERT em clientes/mensagens + enqueue de turno) e o comando se perderia."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = None  # JID global desligado
    settings.evolution_fernando_jids = []
    conn = FakeConn(mensagem_existe=False, envio_existe=False, grupo_por_banco=True)
    arq = FakeArq()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = arq
        response = client.post("/webhook/evolution", json=_payload_grupo("CMD-GRUPO-1"))

    assert response.status_code == 200
    assert response.json() == {"status": "invalid"}
    # Não foi tratado como cliente: nenhum INSERT de cliente/mensagem, nenhum turno.
    assert [q for q in conn.queries if "INSERT INTO barravips.clientes" in q] == []
    assert [q for q in conn.queries if "INSERT INTO barravips.mensagens" in q] == []
    assert arq.enqueued == []


def test_webhook_token_invalido_retorna_401() -> None:
    settings = app.state.settings
    settings.evolution_webhook_token = "secreto"
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    try:
        with TestClient(app) as client:
            app.state.db_pool = FakePool(conn)
            response = client.post(
                "/webhook/evolution",
                json=_payload_grupo("X"),
                headers={"X-Webhook-Token": "errado"},
            )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "WEBHOOK_NAO_AUTORIZADO"
    finally:
        settings.evolution_webhook_token = ""


def test_webhook_jid_fora_da_allowlist_retorna_403() -> None:
    """Allowlist de teste ligada: JID que não está na lista é barrado na porta (403)."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    settings.jid_permitido = ["120363111111111111@g.us"]
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    try:
        with TestClient(app) as client:
            app.state.db_pool = FakePool(conn)
            response = client.post("/webhook/evolution", json=_payload_grupo("FORA-1"))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "JID_NAO_PERMITIDO"
    finally:
        settings.jid_permitido = []


def test_webhook_allowlist_libera_coordenacao_alem_do_cliente() -> None:
    """#8: a allowlist pina o grupo do cliente E o de Coordenação. O comando de grupo
    (JID da Coordenação) passa o gate em vez de levar 403 — destrava o fechamento no rig."""
    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.evolution_grupo_coordenacao_jid = "120363000000000000@g.us"
    settings.evolution_fernando_jids = []
    # Grupo do cliente + grupo de Coordenação na mesma allowlist.
    settings.jid_permitido = ["120363423572479616@g.us", "120363000000000000@g.us"]
    conn = FakeConn(mensagem_existe=False, envio_existe=False)
    try:
        with TestClient(app) as client:
            app.state.db_pool = FakePool(conn)
            app.state.arq = FakeArq()
            response = client.post("/webhook/evolution", json=_payload_grupo("COORD-OK-1"))
        # Passou o gate e entrou no fluxo de grupo (para como `invalid`: #12 não existe no
        # FakeConn). O que importa é NÃO ser 403 — a porta deixou a Coordenação passar.
        assert response.status_code == 200
        assert response.json() == {"status": "invalid"}
    finally:
        settings.jid_permitido = []


def _payload_grupo_texto(texto: str, message_id: str = "CMD-ERR") -> dict[str, Any]:
    return {
        "instance": "barra",
        "data": {
            "key": {"id": message_id, "remoteJid": "120363000000000000@g.us", "fromMe": True},
            "message": {"conversation": texto},
        },
    }


def _capturar_respostas(monkeypatch: Any) -> list[tuple[str, str]]:
    """Substitui `_responder_grupo` por um capturador (sem rede) e devolve a lista de
    (texto, tipo) enviados — prova o wiring §6 sem POSTar no Evolution."""
    from barra.webhook import routes

    capturas: list[tuple[str, str]] = []

    async def _fake(
        _settings: Any, _conn: Any, _msg: Any, texto: str, tipo: str = "erro_comando"
    ) -> None:
        capturas.append((texto, tipo))

    monkeypatch.setattr(routes, "_responder_grupo", _fake)
    return capturas


def test_webhook_grupo_sem_numero_responde_erro_recuperacao(monkeypatch: Any) -> None:
    """Comando sem #N (fora de resposta-quote): ack `invalid` e erro com recuperação (§6.2)."""
    from barra.webhook.respostas import texto_erro_comando

    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = None
    settings.evolution_fernando_jids = []
    capturas = _capturar_respostas(monkeypatch)
    conn = FakeConn(mensagem_existe=False, envio_existe=False, grupo_por_banco=True)
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = FakeArq()
        response = client.post("/webhook/evolution", json=_payload_grupo_texto("finalizado 1000"))

    assert response.json() == {"status": "invalid"}
    assert capturas == [(texto_erro_comando("numero_curto_ausente"), "erro_comando")]


def test_webhook_grupo_atendimento_inexistente_responde_erro(monkeypatch: Any) -> None:
    """Comando com #N que não casa um atendimento aberto: ack `invalid` + erro com recuperação."""
    from barra.webhook.respostas import texto_erro_comando

    settings = app.state.settings
    settings.evolution_webhook_token = ""
    settings.jid_permitido = None
    settings.evolution_grupo_coordenacao_jid = None
    settings.evolution_fernando_jids = []
    capturas = _capturar_respostas(monkeypatch)
    conn = FakeConn(mensagem_existe=False, envio_existe=False, grupo_por_banco=True)
    with TestClient(app) as client:
        app.state.db_pool = FakePool(conn)
        app.state.arq = FakeArq()
        response = client.post(
            "/webhook/evolution", json=_payload_grupo_texto("finalizado 1000 #12")
        )

    assert response.json() == {"status": "invalid"}
    assert capturas == [(texto_erro_comando("atendimento_nao_encontrado"), "erro_comando")]
