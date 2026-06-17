"""WhatsApp LID na borda do webhook: o cliente é sempre o telefone E.164, nunca o @lid.

Payloads ancorados na captura real de prod (Evolution v2.3.6, instância 'lucia', 17/06):
um 1:1 inbound via LID chega com `remoteJid='<id>@lid'` e o telefone real em
`remoteJidAlt='<telefone>@s.whatsapp.net'`.
"""

from barra.webhook.parser import MensagemEvolution, extrair_mensagem
from barra.webhook.routes import _resolver_identidade_cliente


def _msg(remote_jid: str, remote_jid_alt: str | None = None) -> MensagemEvolution:
    return MensagemEvolution(
        evolution_message_id="M",
        instance_id="lucia",
        remote_jid=remote_jid,
        remote_jid_alt=remote_jid_alt,
        sender_jid=None,
        from_me=False,
        texto="oi",
        tipo="texto",
        media_url=None,
        quoted_message_id=None,
    )


def test_extrair_mensagem_captura_remote_jid_alt_no_lid() -> None:
    # Payload real: cliente 1:1 via LID — o telefone E.164 vem em key.remoteJidAlt.
    payload = {
        "instance": "lucia",
        "data": {
            "key": {
                "id": "3B9C97626E6D3955151A",
                "remoteJid": "265394770157821@lid",
                "remoteJidAlt": "5519983382045@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "oi"},
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.remote_jid == "265394770157821@lid"
    assert msg.remote_jid_alt == "5519983382045@s.whatsapp.net"


def test_extrair_mensagem_sem_remote_jid_alt_fica_none() -> None:
    payload = {
        "instance": "barra",
        "data": {
            "key": {"id": "X", "remoteJid": "5521999999999@s.whatsapp.net", "fromMe": False},
            "message": {"conversation": "oi"},
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.remote_jid_alt is None


def test_resolver_lid_usa_telefone_do_remote_jid_alt() -> None:
    # @lid: telefone vem do remoteJidAlt; chat_id é reconstruído como <telefone>@s.whatsapp.net
    # (responder para o @lid falha — Evolution #1585).
    assert _resolver_identidade_cliente(
        _msg("265394770157821@lid", "5519983382045@s.whatsapp.net")
    ) == ("5519983382045", "5519983382045@s.whatsapp.net")


def test_resolver_lid_sem_alt_rejeita() -> None:
    # Fail-closed: sem o E.164, nunca grava o LID como telefone.
    assert _resolver_identidade_cliente(_msg("265394770157821@lid")) is None


def test_resolver_lid_com_alt_nao_numerico_rejeita() -> None:
    # Defensivo: alt que não traz dígitos de telefone não vira cliente.
    assert _resolver_identidade_cliente(_msg("265394770157821@lid", "outracoisa@lid")) is None


def test_resolver_lid_remove_device_do_alt() -> None:
    assert _resolver_identidade_cliente(
        _msg("265394770157821@lid", "5512992609133:9@s.whatsapp.net")
    ) == ("5512992609133", "5512992609133@s.whatsapp.net")


def test_resolver_jid_normal_mantem_comportamento_atual() -> None:
    assert _resolver_identidade_cliente(_msg("5521999999999@s.whatsapp.net")) == (
        "5521999999999",
        "5521999999999@s.whatsapp.net",
    )
