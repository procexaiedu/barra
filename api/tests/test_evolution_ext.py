"""M4b — extensões do EvolutionClient: enviar_midia, marcar_lida, set_presence (05 §4/§5).

Inclui o suporte a `quoted` em sendText/sendMedia (Evolution v2.3.6 / evolution_api_v3) —
o agente humanizado passa o id da última msg do cliente quando uma bolha precisa sair
com reply/citação (regras.md §<quote>).
"""

import json

import httpx
import respx

from barra.core.evolution import EvolutionClient
from barra.settings import Settings

BASE = "http://evolution.test"


def _client() -> EvolutionClient:
    settings = Settings(evolution_base_url=BASE, evolution_api_key="chave-teste")
    return EvolutionClient(settings)


class RecordingConn:
    """Conn mínima que registra as queries — prova que enviar_midia grava em
    envios_evolution (registrar_envio chama conn.execute)."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> None:
        self.queries.append((query, params))


@respx.mock
async def test_enviar_midia_chama_sendmedia_e_grava_envio() -> None:
    route = respx.post(f"{BASE}/message/sendMedia/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-1"}})
    )
    conn = RecordingConn()
    mid = await _client().enviar_midia(
        conn=conn,
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/foto.jpg",
        caption="aqui, olha 😏",
        media_type="image",
        contexto="conversa_cliente",
        tipo="image",
    )
    assert mid == "MID-1"
    assert route.called
    req = route.calls.last.request
    assert json.loads(req.content) == {
        "number": "5521@s.whatsapp.net",
        "mediatype": "image",
        "media": "https://minio.test/foto.jpg",
        "caption": "aqui, olha 😏",
    }
    assert req.headers["apikey"] == "chave-teste"
    # grava em envios_evolution (espelha enviar_texto)
    assert any("INSERT INTO barravips.envios_evolution" in q for q, _ in conn.queries)


@respx.mock
async def test_enviar_midia_ignora_view_once_e_caption_none() -> None:
    route = respx.post(f"{BASE}/message/sendMedia/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-2"}})
    )
    await _client().enviar_midia(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/video.mp4",
        caption=None,
        media_type="video",
        contexto="conversa_cliente",
        tipo="video",
        view_once=True,
    )
    body = json.loads(route.calls.last.request.content)
    # view_once é aceito mas NÃO vai no body (self-host não expõe; 01 §6.13)
    assert "viewOnce" not in body
    assert "view_once" not in body
    # caption=None não entra no body
    assert "caption" not in body


@respx.mock
async def test_enviar_texto_anexa_quoted_quando_recebe_id() -> None:
    route = respx.post(f"{BASE}/message/sendText/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-Q"}})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="não tenho costume amor 😊",
        contexto="conversa_cliente",
        tipo="texto",
        quoted_message_id="ABCDEF1234",
    )
    body = json.loads(route.calls.last.request.content)
    # Sem quoted_text, conversation cai no fallback vazio (defesa; o balão fica sem
    # o snippet, mas a setinha ainda aponta certo pelo key.id).
    assert body["quoted"] == {"key": {"id": "ABCDEF1234"}, "message": {"conversation": ""}}
    assert body["text"] == "não tenho costume amor 😊"


@respx.mock
async def test_enviar_texto_quoted_inclui_texto_real_no_conversation() -> None:
    """Com quoted_text, o balão de reply renderiza o snippet: a Evolution v2.3.6 ecoa
    `quoted.message.conversation` para o contextInfo (não faz lookup pelo id; verificado
    2026-05-30 — sem isso o cliente vê citação vazia)."""
    route = respx.post(f"{BASE}/message/sendText/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-QT"}})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="não tenho costume amor 😊",
        contexto="conversa_cliente",
        tipo="texto",
        quoted_message_id="ABCDEF1234",
        quoted_text="você faz anal?",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["quoted"] == {
        "key": {"id": "ABCDEF1234"},
        "message": {"conversation": "você faz anal?"},
    }


@respx.mock
async def test_enviar_texto_sem_quoted_nao_inclui_chave() -> None:
    route = respx.post(f"{BASE}/message/sendText/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-N"}})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="oi amor",
        contexto="conversa_cliente",
        tipo="texto",
    )
    body = json.loads(route.calls.last.request.content)
    assert "quoted" not in body  # default não polui o payload


@respx.mock
async def test_enviar_midia_anexa_quoted_quando_recebe_id() -> None:
    route = respx.post(f"{BASE}/message/sendMedia/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-Q2"}})
    )
    await _client().enviar_midia(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/foto.jpg",
        caption="olha 😏",
        media_type="image",
        contexto="conversa_cliente",
        tipo="image",
        quoted_message_id="XYZ987",
    )
    body = json.loads(route.calls.last.request.content)
    # sem quoted_text → fallback vazio (mesma regra do enviar_texto)
    assert body["quoted"] == {"key": {"id": "XYZ987"}, "message": {"conversation": ""}}


@respx.mock
async def test_enviar_midia_quoted_inclui_texto_real_no_conversation() -> None:
    """Com quoted_text, o sendMedia também preenche o snippet do balão (Evolution v2.3.6
    ecoa quoted.message.conversation; sem isso, citação vazia)."""
    route = respx.post(f"{BASE}/message/sendMedia/inst-1").mock(
        return_value=httpx.Response(200, json={"key": {"id": "MID-QT2"}})
    )
    await _client().enviar_midia(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/foto.jpg",
        caption="olha 😏",
        media_type="image",
        contexto="conversa_cliente",
        tipo="image",
        quoted_message_id="XYZ987",
        quoted_text="manda foto sua",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["quoted"] == {
        "key": {"id": "XYZ987"},
        "message": {"conversation": "manda foto sua"},
    }


@respx.mock
async def test_marcar_lida_chama_endpoint_sem_gravar() -> None:
    route = respx.post(f"{BASE}/chat/markMessageAsRead/inst-1").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    # marcar_lida nem recebe conn → estruturalmente não grava em envios_evolution
    await _client().marcar_lida(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        message_ids=["A", "B"],
    )
    assert route.called
    # Evolution v2.3.6 self-host exige `readMessages` em camelCase (fix em 6deb321).
    assert json.loads(route.calls.last.request.content) == {
        "readMessages": [
            {"remoteJid": "5521@s.whatsapp.net", "fromMe": False, "id": "A"},
            {"remoteJid": "5521@s.whatsapp.net", "fromMe": False, "id": "B"},
        ]
    }


@respx.mock
async def test_set_presence_chama_endpoint() -> None:
    route = respx.post(f"{BASE}/chat/sendPresence/inst-1").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    await _client().set_presence(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        presence="composing",
        delay_ms=1500,
    )
    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "number": "5521@s.whatsapp.net",
        "presence": "composing",
        "delay": 1500,
    }


@respx.mock
async def test_set_presence_best_effort_engole_falha() -> None:
    respx.post(f"{BASE}/chat/sendPresence/inst-1").mock(side_effect=httpx.ConnectError("down"))
    # best-effort (05 §4.1): falha de rede loga e segue, não estoura o turno
    await _client().set_presence(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        presence="composing",
        delay_ms=1500,
    )
