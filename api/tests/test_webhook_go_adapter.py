"""Adaptador de webhook Evolution GO (whatsmeow) → shape v2 (`adaptar_webhook_go`) + a ponta a
ponta com `extrair_mensagem`. Garante que o envelope CamelCase da EvoGo vira o shape que o resto
do módulo de webhook já parseia, e que payload v2/não-Go passa reto."""

from barra.webhook.parser import adaptar_webhook_go, extrair_mensagem


def _payload_go_mensagem(
    *, chat: str, texto: str = "oi", from_me: bool = False, sender: str | None = None
) -> dict:
    return {
        "event": "Message",
        "instanceName": "elitebaby01",
        "instanceToken": "tok",
        "data": {
            "Info": {
                "ID": "MSG-1",
                "Chat": chat,
                "IsFromMe": from_me,
                "Sender": sender or chat,
                "SenderAlt": "99@lid",
                "PushName": "Cliente",
            },
            "Message": {"conversation": texto},
        },
    }


def test_adapta_mensagem_go_para_v2() -> None:
    adaptado = adaptar_webhook_go(_payload_go_mensagem(chat="5521999@s.whatsapp.net"))
    assert adaptado["event"] == "messages.upsert"
    assert adaptado["instance"] == "elitebaby01"
    key = adaptado["data"]["key"]
    assert key["id"] == "MSG-1"
    assert key["remoteJid"] == "5521999@s.whatsapp.net"
    assert key["fromMe"] is False
    assert adaptado["data"]["message"] == {"conversation": "oi"}


def test_mensagem_go_flui_no_extrair_mensagem() -> None:
    msg = extrair_mensagem(adaptar_webhook_go(_payload_go_mensagem(chat="5521999@s.whatsapp.net")))
    assert msg is not None
    assert msg.evolution_message_id == "MSG-1"
    assert msg.remote_jid == "5521999@s.whatsapp.net"
    assert msg.texto == "oi"
    assert msg.instance_id == "elitebaby01"
    assert msg.from_me is False


def test_lid_usa_sender_real_como_remote_jid_alt() -> None:
    """Chat vem como @lid; o E.164 real está no Sender (`@s.whatsapp.net`). O adaptador o expõe em
    remoteJidAlt p/ o ramo @lid do webhook resolver o telefone (invertido vs. v2)."""
    payload = _payload_go_mensagem(chat="88@lid", sender="5521999@s.whatsapp.net")
    key = adaptar_webhook_go(payload)["data"]["key"]
    assert key["remoteJid"] == "88@lid"
    assert key["remoteJidAlt"] == "5521999@s.whatsapp.net"


def test_participant_de_grupo_prefere_jid_real_sobre_lid() -> None:
    """No grupo, `participant` alimenta o reconhecimento de Fernando (igualdade em fernando_jids,
    JIDs @s.whatsapp.net). Se o Sender vier @lid, o adaptador escolhe o JID real do SenderAlt —
    senão o comando de Fernando cairia em ignored."""
    payload = {
        "event": "Message",
        "instanceName": "elitebaby01",
        "data": {
            "Info": {
                "ID": "G-1",
                "Chat": "123@g.us",
                "IsFromMe": False,
                "Sender": "77@lid",
                "SenderAlt": "5519983382045@s.whatsapp.net",
            },
            "Message": {"conversation": "fechado 800 #3"},
        },
    }
    key = adaptar_webhook_go(payload)["data"]["key"]
    assert key["remoteJid"] == "123@g.us"
    assert key["participant"] == "5519983382045@s.whatsapp.net"


def test_conexao_go_vira_connection_update() -> None:
    payload = {
        "event": "Connection",
        "instanceName": "elitebaby01",
        "data": {"state": "connected"},
    }
    adaptado = adaptar_webhook_go(payload)
    assert adaptado["event"] == "connection.update"
    assert adaptado["data"]["state"] == "open"


def test_conexao_go_connected_bool() -> None:
    payload = {"event": "Connection", "instanceName": "x", "data": {"Connected": False}}
    assert adaptar_webhook_go(payload)["data"]["state"] == "close"


def test_qrcode_go_vira_qrcode_updated() -> None:
    payload = {"event": "QRCode", "instanceName": "x", "data": {"Qrcode": "data:..."}}
    assert adaptar_webhook_go(payload)["event"] == "qrcode.updated"


def test_payload_v2_passa_reto() -> None:
    """Payload v2 (Baileys) não é tocado — compat durante a transição."""
    v2 = {
        "event": "messages.upsert",
        "instance": "modelo-x",
        "data": {"key": {"id": "V2", "remoteJid": "5521@s.whatsapp.net"}, "message": {}},
    }
    assert adaptar_webhook_go(v2) is v2


def test_evento_go_sem_traducao_vira_ignorado() -> None:
    """Receipt/Presence/HistorySync não viram turno: passam com o event cru e caem no
    extrair_mensagem → None (ignored)."""
    payload = {"event": "Receipt", "instanceName": "x", "data": {"Info": {"ID": "R1"}}}
    adaptado = adaptar_webhook_go(payload)
    assert adaptado["event"] == "Receipt"
    assert extrair_mensagem(adaptado) is None
