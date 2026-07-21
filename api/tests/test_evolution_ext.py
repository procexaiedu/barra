"""EvolutionClient sobre a Evolution GO (whatsmeow): envio de texto/mídia, markread, presença,
status e info de grupo. A EvoGo escopa a operação pelo TOKEN da instância (header `apikey`),
resolvido nome→token via GET /instance/all — então cada teste mocka /instance/all + o endpoint de
operação (sem instância no path)."""

import json

import httpx
import pytest
import respx

from barra.core.evolution import EvolutionClient, limpar_cache_tokens
from barra.settings import Settings

BASE = "http://evolution.test"
TOKEN = "tok-inst-1"


@pytest.fixture(autouse=True)
def _cache_limpo() -> None:
    """O cache nome→token é módulo-level; zera antes de cada teste p/ não vazar tokens/instâncias
    entre casos."""
    limpar_cache_tokens()


def _client() -> EvolutionClient:
    settings = Settings(evolution_base_url=BASE, evolution_api_key="global-key")
    return EvolutionClient(settings)


def _mock_instance_all(name: str = "inst-1", token: str = TOKEN) -> None:
    respx.get(f"{BASE}/instance/all").mock(
        return_value=httpx.Response(
            200, json={"data": [{"name": name, "token": token, "connected": True}]}
        )
    )


class RecordingConn:
    """Conn mínima que registra as queries — prova que enviar_* grava em envios_evolution
    (registrar_envio chama conn.execute)."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> None:
        self.queries.append((query, params))


@respx.mock
async def test_enviar_texto_resolve_token_e_chama_send_text() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-1"})
    )
    conn = RecordingConn()
    mid = await _client().enviar_texto(
        conn=conn,
        instance_id="inst-1",
        remote_jid="5521999@s.whatsapp.net",
        texto="oi amor",
        contexto="conversa_cliente",
        tipo="texto",
    )
    assert mid == "MID-1"
    req = route.calls.last.request
    # instância NÃO vai no path; number vira só os dígitos; auth é o TOKEN da instância.
    assert json.loads(req.content) == {"number": "5521999", "text": "oi amor"}
    assert req.headers["apikey"] == TOKEN
    assert any("INSERT INTO barravips.envios_evolution" in q for q, _ in conn.queries)


@respx.mock
async def test_enviar_texto_grupo_mantem_jid() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-G"})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="123456@g.us",
        texto="card",
        contexto="grupo_coordenacao",
        tipo="card",
    )
    assert json.loads(route.calls.last.request.content)["number"] == "123456@g.us"


@respx.mock
async def test_enviar_texto_quoted_usa_message_id() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-Q"})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="faço sim vida",
        contexto="conversa_cliente",
        tipo="texto",
        quoted_message_id="ABCDEF1234",
        quoted_text="você faz anal?",
    )
    body = json.loads(route.calls.last.request.content)
    # EvoGo resolve a citação pelo id (whatsmeow guarda a msg); não ecoa o texto como a v2.
    assert body["quoted"] == {"messageId": "ABCDEF1234"}


@respx.mock
async def test_enviar_texto_sem_quoted_nao_inclui_chave() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-N"})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="oi",
        contexto="conversa_cliente",
        tipo="texto",
    )
    assert "quoted" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_enviar_texto_remove_marker_quote_residual() -> None:
    """Rede de segurança: um `[quote...]` que escapou do chunk NUNCA chega ao cliente — vazá-lo
    entrega que é uma IA."""
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/text").mock(
        return_value=httpx.Response(200, json={"id": "MID-R"})
    )
    await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="oii amor [quote: faz oral] faço sim vida",
        contexto="conversa_cliente",
        tipo="texto",
    )
    body = json.loads(route.calls.last.request.content)
    assert "[quote" not in body["text"].lower()
    assert body["text"] == "oii amor faço sim vida"


@respx.mock
async def test_enviar_midia_chama_send_media_e_grava() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/media").mock(
        return_value=httpx.Response(200, json={"id": "MID-M"})
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
    assert mid == "MID-M"
    body = json.loads(route.calls.last.request.content)
    # EvoGo: `type` (não `mediatype`), `url` (não `media`), mídia por URL.
    assert body == {
        "number": "5521",
        "type": "image",
        "url": "https://minio.test/foto.jpg",
        "caption": "aqui, olha 😏",
    }
    assert any("INSERT INTO barravips.envios_evolution" in q for q, _ in conn.queries)


@respx.mock
async def test_enviar_midia_traduz_foto_para_image() -> None:
    """Os callers reais passam `media_type='foto'` (midia_tipo_enum do domínio); a EvoGo aceita
    image/video/audio no `type`. Traduz 'foto'->'image' na fronteira."""
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/media").mock(
        return_value=httpx.Response(200, json={"id": "MID-F"})
    )
    await _client().enviar_midia(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/foto.png",
        caption=None,
        media_type="foto",
        contexto="conversa_cliente",
        tipo="midia",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["type"] == "image"
    assert "caption" not in body  # caption=None não entra


@respx.mock
async def test_enviar_midia_view_once_sob_toggle() -> None:
    """Mídia exclusiva: com o toggle ligado o body leva `viewOnce`; com ele desligado o campo é
    omitido (a EvoGo oficial ignora o campo, então o default OFF mantém a mídia normal)."""
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/media").mock(
        return_value=httpx.Response(200, json={"id": "MID-V"})
    )

    async def _enviar(view_once_toggle: bool) -> dict[str, object]:
        settings = Settings(
            evolution_base_url=BASE,
            evolution_api_key="global-key",
            evolution_view_once=view_once_toggle,
        )
        await EvolutionClient(settings).enviar_midia(
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
        return dict(json.loads(route.calls.last.request.content))

    assert (await _enviar(True))["viewOnce"] is True
    assert "viewOnce" not in await _enviar(False)


@respx.mock
async def test_enviar_midia_quoted_usa_message_id() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/send/media").mock(
        return_value=httpx.Response(200, json={"id": "MID-Q2"})
    )
    await _client().enviar_midia(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        url="https://minio.test/foto.jpg",
        caption="[quote: foto] essa sou eu",
        media_type="image",
        contexto="conversa_cliente",
        tipo="image",
        quoted_message_id="XYZ987",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["quoted"] == {"messageId": "XYZ987"}
    assert body["caption"] == "essa sou eu"  # marker [quote] removido do caption


@respx.mock
async def test_marcar_lida_chama_markread_sem_gravar() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/message/markread").mock(
        return_value=httpx.Response(200, json={"message": "success"})
    )
    # marcar_lida nem recebe conn → estruturalmente não grava em envios_evolution
    await _client().marcar_lida(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        message_ids=["A", "B"],
    )
    assert json.loads(route.calls.last.request.content) == {"number": "5521", "id": ["A", "B"]}


@respx.mock
async def test_set_presence_chama_message_presence() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/message/presence").mock(
        return_value=httpx.Response(200, json={"message": "success"})
    )
    await _client().set_presence(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        presence="composing",
        delay_ms=1500,
    )
    assert json.loads(route.calls.last.request.content) == {
        "number": "5521",
        "state": "composing",
        "isAudio": False,
    }


@respx.mock
async def test_set_presence_recording_marca_is_audio() -> None:
    _mock_instance_all()
    route = respx.post(f"{BASE}/message/presence").mock(
        return_value=httpx.Response(200, json={"message": "success"})
    )
    await _client().set_presence(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        presence="recording",
        delay_ms=0,
    )
    body = json.loads(route.calls.last.request.content)
    assert body["state"] == "composing" and body["isAudio"] is True


@respx.mock
async def test_set_presence_best_effort_engole_falha() -> None:
    _mock_instance_all()
    respx.post(f"{BASE}/message/presence").mock(side_effect=httpx.ConnectError("down"))
    # best-effort (05 §4.1): falha de rede loga e segue, não estoura o turno
    await _client().set_presence(
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        presence="composing",
        delay_ms=1500,
    )


@respx.mock
async def test_estado_conexao_pascalcase_open() -> None:
    _mock_instance_all()
    respx.get(f"{BASE}/instance/status").mock(
        return_value=httpx.Response(200, json={"data": {"Connected": True, "LoggedIn": True}})
    )
    assert await _client().estado_conexao("inst-1") == "open"


@respx.mock
async def test_estado_conexao_conectando_e_fechado() -> None:
    _mock_instance_all()
    respx.get(f"{BASE}/instance/status").mock(
        return_value=httpx.Response(200, json={"data": {"Connected": True, "LoggedIn": False}})
    )
    assert await _client().estado_conexao("inst-1") == "connecting"


@respx.mock
async def test_buscar_grupo_info_normaliza_participants_pascalcase() -> None:
    _mock_instance_all()
    respx.post(f"{BASE}/group/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "Participants": [
                        # JID vem como @lid (shape real da EvoGo); o telefone real é PhoneNumber.
                        {"JID": "888@lid", "PhoneNumber": "5519@s.whatsapp.net", "LID": "888@lid"},
                        {"PhoneNumber": "5521"},  # dígitos crus → recebe @s.whatsapp.net
                    ]
                }
            },
        )
    )
    info = await _client().buscar_grupo_info("inst-1", "123@g.us")
    # prefere PhoneNumber (E.164 real), nunca o JID @lid — a verificação de Coordenação casa por
    # dígitos do telefone.
    assert info["participants"] == [
        {"id": "5519@s.whatsapp.net"},
        {"id": "5521@s.whatsapp.net"},
    ]


@respx.mock
async def test_reresolve_token_no_401() -> None:
    """Token em cache virou inválido (rotacionado) → 401 → re-resolve /instance/all e repete."""
    all_route = respx.get(f"{BASE}/instance/all").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"name": "inst-1", "token": "velho"}]}),
            httpx.Response(200, json={"data": [{"name": "inst-1", "token": "novo"}]}),
        ]
    )
    send_route = respx.post(f"{BASE}/send/text").mock(
        side_effect=[
            httpx.Response(401, json={"error": "unauthorized"}),
            httpx.Response(200, json={"id": "MID-OK"}),
        ]
    )
    mid = await _client().enviar_texto(
        conn=RecordingConn(),
        instance_id="inst-1",
        remote_jid="5521@s.whatsapp.net",
        texto="oi",
        contexto="conversa_cliente",
        tipo="texto",
    )
    assert mid == "MID-OK"
    assert all_route.call_count == 2  # resolveu de novo após o 401
    assert send_route.call_count == 2
    assert send_route.calls[-1].request.headers["apikey"] == "novo"


@respx.mock
async def test_criar_instancia_500_already_exists_e_idempotente() -> None:
    """A EvoGo devolve HTTP 500 `{"error":"instance already exists"}` para nome duplicado — o
    criar_instancia trata como idempotente (o connect seguinte resolve o token existente)."""
    respx.post(f"{BASE}/instance/create").mock(
        return_value=httpx.Response(500, json={"error": "instance already exists"})
    )
    res = await _client().criar_instancia("elitebaby01")
    assert res["status"] == "exists"


@respx.mock
async def test_criar_instancia_500_generico_levanta() -> None:
    """500 que NÃO é 'already exists' não pode ser mascarado como idempotente — propaga."""
    respx.post(f"{BASE}/instance/create").mock(
        return_value=httpx.Response(500, json={"error": "internal boom"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await _client().criar_instancia("elitebaby01")


@respx.mock
async def test_instancia_inexistente_levanta() -> None:
    respx.get(f"{BASE}/instance/all").mock(
        return_value=httpx.Response(200, json={"data": [{"name": "outra", "token": "x"}]})
    )
    from barra.core.errors import ErroDominio

    with pytest.raises(ErroDominio):
        await _client().enviar_texto(
            conn=RecordingConn(),
            instance_id="inst-1",
            remote_jid="5521@s.whatsapp.net",
            texto="oi",
            contexto="conversa_cliente",
            tipo="texto",
        )
