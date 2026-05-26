import asyncio
from decimal import Decimal

from barra.core.evolution import envio_existe
from barra.webhook.parser import extrair_mensagem, parse_comando_grupo


class _Result:
    async def fetchone(self):
        return {"exists": 1}


class _Conn:
    async def execute(self, query: str, params: tuple[str]):
        assert "envios_evolution" in query
        assert params == ("backend-msg",)
        return _Result()


def test_finalizado_sem_valor_e_comando_invalido() -> None:
    comando = parse_comando_grupo("finalizado #12")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.numero_curto == 12
    assert comando.payload["motivo"] == "valor_final_obrigatorio"


def test_finalizado_com_valor_brasileiro() -> None:
    comando = parse_comando_grupo("finalizado R$ 1.000 #12")
    assert comando is not None
    assert comando.comando == "registrar_fechado"
    assert comando.payload["valor_final"] == 1000


def test_fechado_com_valor_decimal() -> None:
    comando = parse_comando_grupo("fechado 1500,50 #9")
    assert comando is not None
    assert comando.comando == "registrar_fechado"
    assert comando.payload["valor_final"] == Decimal("1500.50")


def test_finalizado_com_valor_em_k() -> None:
    comando = parse_comando_grupo("finalizado 1k #4")
    assert comando is not None
    assert comando.comando == "registrar_fechado"
    assert comando.payload["valor_final"] == Decimal("1000")


def test_perdido_com_motivo_valido() -> None:
    comando = parse_comando_grupo("perdido sumiu #3")
    assert comando is not None
    assert comando.comando == "registrar_perdido"
    assert comando.numero_curto == 3
    assert comando.payload["motivo"] == "sumiu"


def test_perdido_sem_motivo_e_comando_invalido() -> None:
    comando = parse_comando_grupo("perdido #3")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.payload["motivo"] == "motivo_perda_obrigatorio"


def test_ia_assume_sem_numero_curto_e_invalido() -> None:
    comando = parse_comando_grupo("IA assume")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.numero_curto is None


def test_quote_pode_resolver_numero_curto() -> None:
    comando = parse_comando_grupo("IA assume", quoted_numero_curto=7)
    assert comando is not None
    assert comando.comando == "devolver_para_ia"
    assert comando.numero_curto == 7


def test_texto_irrelevante_retorna_none() -> None:
    assert parse_comando_grupo("oi tudo bem #12") is None
    assert parse_comando_grupo("") is None


def test_valor_pelado_citando_card_de_lembrete_fecha() -> None:
    # ADR-0007: resposta ao card de Lembrete de fechamento aceita valor sem palavra-chave.
    comando = parse_comando_grupo("1500", quoted_numero_curto=7, aguardando_valor=True)
    assert comando is not None
    assert comando.comando == "registrar_fechado"
    assert comando.numero_curto == 7
    assert comando.payload["valor_final"] == Decimal("1500")


def test_valor_pelado_sem_aguardando_valor_e_ignorado() -> None:
    assert parse_comando_grupo("1500", quoted_numero_curto=7) is None


def test_perdido_citando_card_de_lembrete_ainda_funciona() -> None:
    comando = parse_comando_grupo("perdido sumiu", quoted_numero_curto=7, aguardando_valor=True)
    assert comando is not None
    assert comando.comando == "registrar_perdido"
    assert comando.payload["motivo"] == "sumiu"


def test_aguardando_valor_texto_solto_sem_valor_ignorado() -> None:
    assert parse_comando_grupo("ok obrigada", quoted_numero_curto=7, aguardando_valor=True) is None


def test_envios_evolution_identifica_outbound_backend() -> None:
    assert asyncio.run(envio_existe(_Conn(), "backend-msg")) is True


def test_extrair_mensagem_payload_texto() -> None:
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "ABC123", "remoteJid": "5521999999999@s.whatsapp.net", "fromMe": False},
            "message": {"conversation": "Oi, atende em hotel?"},
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.evolution_message_id == "ABC123"
    assert msg.instance_id == "barra-piloto"
    assert msg.remote_jid == "5521999999999@s.whatsapp.net"
    assert msg.from_me is False
    assert msg.tipo == "texto"
    assert msg.texto == "Oi, atende em hotel?"


def test_extrair_mensagem_payload_audio() -> None:
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "AUD1", "remoteJid": "5521@g.us", "fromMe": True},
            "message": {"audioMessage": {"url": "https://cdn/audio.ogg"}},
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.tipo == "audio"
    assert msg.media_url == "https://cdn/audio.ogg"
    assert msg.from_me is True


def test_extrair_mensagem_quote_traz_stanza_id() -> None:
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "QUOTED1", "remoteJid": "5521@g.us", "fromMe": True},
            "message": {
                "extendedTextMessage": {
                    "text": "finalizado 1000",
                    "contextInfo": {"stanzaId": "card-msg-id-1"},
                }
            },
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.quoted_message_id == "card-msg-id-1"
    assert msg.texto == "finalizado 1000"


def test_extrair_mensagem_payload_sem_id_retorna_none() -> None:
    payload = {"instance": "barra", "data": {"key": {}, "message": {}}}
    assert extrair_mensagem(payload) is None
