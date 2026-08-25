"""O ouvido do Agente financeiro (spec 0005, ticket 06): o que sai daqui rumo ao provider.

Offline: sem banco, sem chave, sem rede — o cliente OpenRouter e um fake plugado no cache do
modulo. Estes sao os invariantes que o teste de porta (`tests/integracao/test_grupo_financeiro_
audio.py`) stuba de proposito e que, se quebrarem, quebram calado: um `format` errado no
`input_audio` faz o provider recusar o ogg do WhatsApp (400) e o agente simplesmente para de
ouvir o grupo — sem venda faltando em lugar nenhum visivel.
"""

from typing import Any, cast

import pytest

from barra.agente_financeiro import transcricao
from barra.agente_financeiro.porta import de_evolution
from barra.agente_financeiro.transcricao import ouvinte_do_grupo
from barra.core.stt import MODELO_STT_PADRAO, PROMPT_STT
from barra.dominio.grupo_financeiro.modelos import AudioDoGrupo
from barra.webhook.parser import extrair_mensagem

OGG = b"OggS\x00\x02fake-opus"


class _Usage:
    prompt_tokens = 400
    completion_tokens = 8


class _Resposta:
    def __init__(self, texto: str) -> None:
        mensagem = type("_Msg", (), {"content": texto})()
        self.choices = [type("_Escolha", (), {"message": mensagem})()]
        self.usage = _Usage()


class _ClienteFake:
    def __init__(self, texto: str) -> None:
        self.chamadas: list[dict[str, Any]] = []
        dono = self

        class _Completions:
            async def create(self, **kwargs: Any) -> _Resposta:
                dono.chamadas.append(kwargs)
                return _Resposta(texto)

        self.chat = type("_Chat", (), {"completions": _Completions()})()


class _Settings:
    def __init__(self, chave: str | None = "sk-fake", modelo: str | None = None) -> None:
        self.openrouter_api_key = chave
        self.openrouter_model_audio_transcribe = modelo
        self.usd_brl_cotacao = 5.5


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> _ClienteFake:
    """Planta o fake no cache de clientes: `ouvinte_do_grupo` acha ele em vez de abrir httpx."""
    fake = _ClienteFake("Foi pix")
    monkeypatch.setattr(transcricao, "_cliente_cache", {"sk-fake": cast(Any, fake)})
    return fake


async def test_sem_chave_nao_ha_ouvido(monkeypatch: pytest.MonkeyPatch) -> None:
    """`None` explicito, e nao um transcritor que sempre falha: a porta CONTA a diferenca entre
    "nao tenho provider configurado" e "tentei e nao consegui"."""
    monkeypatch.setattr(transcricao, "_cliente_cache", {})
    assert ouvinte_do_grupo(_Settings(chave=None)) is None
    assert ouvinte_do_grupo(_Settings(chave="")) is None


async def test_manda_o_audio_no_formato_que_o_openrouter_aceita(cliente: _ClienteFake) -> None:
    ouvir = ouvinte_do_grupo(_Settings())
    assert ouvir is not None

    texto = await ouvir(AudioDoGrupo(conteudo=OGG, mimetype="audio/ogg; codecs=opus"))

    assert texto == "Foi pix"
    (chamada,) = cliente.chamadas
    assert chamada["model"] == MODELO_STT_PADRAO
    partes = chamada["messages"][0]["content"]
    assert partes[0] == {"type": "text", "text": PROMPT_STT}
    # ogg, e nao "wav"/"mp3": o parametro de codec do WhatsApp e ruido, o container e que decide.
    assert partes[1]["input_audio"]["format"] == "ogg"
    assert chamada["temperature"] == 0


@pytest.mark.parametrize(
    ("mimetype", "formato"),
    [
        ("audio/ogg", "ogg"),
        ("audio/mp4", "m4a"),  # audio encaminhado do iOS
        ("audio/mpeg", "mp3"),
        (None, "ogg"),  # EvoGo as vezes nao carimba content-type -> o caso dominante
        ("application/octet-stream", "ogg"),
    ],
)
async def test_formato_derivado_do_mimetype(
    cliente: _ClienteFake, mimetype: str | None, formato: str
) -> None:
    ouvir = ouvinte_do_grupo(_Settings())
    assert ouvir is not None

    await ouvir(AudioDoGrupo(conteudo=OGG, mimetype=mimetype))

    assert cliente.chamadas[-1]["messages"][0]["content"][1]["input_audio"]["format"] == formato


async def test_audio_sem_fala_devolve_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """O marcador de silencio nao pode virar "texto" — senao o grupo registraria a fala vazia."""
    fake = _ClienteFake("(sem fala)")
    monkeypatch.setattr(transcricao, "_cliente_cache", {"sk-fake": cast(Any, fake)})
    ouvir = ouvinte_do_grupo(_Settings())
    assert ouvir is not None

    assert await ouvir(AudioDoGrupo(conteudo=OGG, mimetype="audio/ogg")) is None


def test_envelope_de_audio_da_evolution_chega_a_porta_com_os_bytes() -> None:
    """A traducao que o webhook faz, exercitada aqui e nao so em producao.

    Os bytes viajam no `midia` porque a `url` do `audioMessage` aponta para o CDN cifrado do
    WhatsApp: quem chamar a porta com o envelope e sem os bytes entrega um audio que ninguem
    consegue ouvir — e o efeito seria silencioso (mensagem registrada, dado do grupo perdido).
    """
    payload = {
        "event": "messages.upsert",
        "instance": "procex",
        "data": {
            "key": {
                "id": "3EB0AUDIO",
                "remoteJid": "120363111111111111@g.us",
                "participant": "5571988887777@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Yasmin",
            "message": {
                "audioMessage": {
                    "url": "https://mmg.whatsapp.net/v/t62.7117-24/cifrado.enc",
                    "mimetype": "audio/ogg; codecs=opus",
                    "ptt": True,
                }
            },
        },
    }
    evento = extrair_mensagem(payload)
    assert evento is not None and evento.tipo == "audio"

    entrada = de_evolution(evento, midia=(OGG, "audio/ogg"))

    assert entrada.grupo_jid == "120363111111111111@g.us"
    assert entrada.tipo == "audio"
    assert entrada.texto == ""
    assert entrada.audio is not None
    assert entrada.audio.conteudo == OGG
    assert entrada.audio.mimetype == "audio/ogg"
    assert entrada.autor_jid == "5571988887777@s.whatsapp.net"


def test_midia_de_imagem_nao_vira_audio() -> None:
    """Comprovante de Pix e do ticket 07, com outro leitor: carregar bytes que ninguem le seria
    so peso — e um `audio` preenchido faria a porta chamar STT sobre uma foto."""
    payload = {
        "event": "messages.upsert",
        "instance": "procex",
        "data": {
            "key": {"id": "3EB0IMG", "remoteJid": "120363111111111111@g.us", "fromMe": False},
            "message": {"imageMessage": {"url": "https://mmg.whatsapp.net/x.enc", "caption": "ok"}},
        },
    }
    evento = extrair_mensagem(payload)
    assert evento is not None and evento.tipo == "imagem"

    assert de_evolution(evento, midia=(b"jpeg-bytes", "image/jpeg")).audio is None


async def test_modelo_do_env_vence_o_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`openrouter_model_audio_transcribe` chega VAZIO quando o Portainer nao define a var — o
    `or` do default e o que impede o `model=""` que o provider rejeita com 400."""
    fake = _ClienteFake("600")
    monkeypatch.setattr(transcricao, "_cliente_cache", {"sk-fake": cast(Any, fake)})

    ouvir = ouvinte_do_grupo(_Settings(modelo="google/outro-modelo"))
    assert ouvir is not None
    await ouvir(AudioDoGrupo(conteudo=OGG))
    assert fake.chamadas[-1]["model"] == "google/outro-modelo"

    ouvir_vazio = ouvinte_do_grupo(_Settings(modelo=""))
    assert ouvir_vazio is not None
    await ouvir_vazio(AudioDoGrupo(conteudo=OGG))
    assert fake.chamadas[-1]["model"] == MODELO_STT_PADRAO
