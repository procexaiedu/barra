"""Onde reacao e edicao MORREM hoje na borda do webhook (spec 0006, ticket 08).

Offline: so parser, sem app, sem banco, sem rede.

Este arquivo e o mapa da fronteira, e ele existe porque a fronteira e o bloqueio do ticket: **o
payload real de reacao e de edicao da EvoGo nao existe no repo e nao e adivinhavel**. O que da para
fixar hoje e o comportamento ATUAL — os dois gestos entram e sao descartados, em qualquer chat — e
a regra que nao depende da grafia (gesto so vira evento em `@g.us`).

O caminho de cada um, verificado aqui:

  * **reacao**: `adaptar_webhook_go` traduz o envelope e passa `data.Message` INTACTO, entao o
    `reactionMessage` chega vivo ate `extrair_mensagem` — que o descarta no gate explicito
    (`parser.py`: "reactionMessage e explicito porque versoes da Evolution podem trazer o emoji em
    `.text` (nao-vazio) e ainda assim nao e turno"). Sem esse gate a reacao virava TURNO FANTASMA
    no agente de venda, e e por isso que ele fica onde esta;
  * **edicao**: chega como `protocolMessage` de tipo de edit e morre no ramo da REVOGACAO —
    `extrair_delecao` so aceita `REVOKE` e devolve `None` para "protocolMessage de outros tipos
    (edicao de mensagem, sincronizacao de estado), que nao apagam nada". Depois dele
    `extrair_mensagem` tambem devolve `None` (protocolMessage nao tem texto), e o webhook responde
    200 'ignored'.

O teste do fim e o unico `xfail` do arquivo, e ele e o marcador da divida: o fixture e
**HIPOTETICO**. Roteiro da captura em `.scratch/agente-financeiro-v2/PAYLOAD-EVOGO.md`.
"""

import json
from typing import Any

import pytest

from barra.webhook.parser import (
    GRAFIA_DO_GESTO_CONFIRMADA,
    ReacaoEvolution,
    adaptar_webhook_go,
    esboco_do_payload,
    extrair_delecao,
    extrair_gesto,
    extrair_mensagem,
    parece_gesto_em_grupo,
)

GRUPO_JID = "120363000000000001@g.us"
CLIENTE_JID = "5521999998888@s.whatsapp.net"
TELEFONISTA_JID = "5521999990000@s.whatsapp.net"
ID_DO_ALVO = "3EB0FICHA0001"
ID_DO_ENVELOPE = "3EB0GESTO9999"


def _reacao_v2(remote_jid: str = GRUPO_JID, emoji: str = "✅") -> dict[str, Any]:
    """Reacao no shape v2 (Baileys) — o formato que o resto do parser ja entende.

    ⚠️ HIPOTETICO no que toca a EvoGo: e o shape do WhatsApp/Baileys, nao um payload capturado da
    instancia que roda em producao.
    """
    return {
        "event": "messages.upsert",
        "instance": "procex",
        "data": {
            "key": {
                "id": ID_DO_ENVELOPE,
                "remoteJid": remote_jid,
                "fromMe": False,
                "participant": TELEFONISTA_JID,
            },
            "pushName": "Lula",
            "message": {
                "reactionMessage": {
                    "key": {"id": ID_DO_ALVO, "remoteJid": remote_jid, "fromMe": True},
                    "text": emoji,
                    "senderTimestampMs": "1755700000000",
                }
            },
        },
    }


def _reacao_go(emoji: str = "✅") -> dict[str, Any]:
    """A mesma reacao no envelope da Evolution GO (whatsmeow), antes de `adaptar_webhook_go`."""
    return {
        "event": "Message",
        "instanceName": "procex",
        "data": {
            "Info": {
                "ID": ID_DO_ENVELOPE,
                "Chat": GRUPO_JID,
                "Sender": TELEFONISTA_JID,
                "IsFromMe": False,
                "PushName": "Lula",
            },
            "Message": {
                "reactionMessage": {
                    "key": {"id": ID_DO_ALVO, "remoteJid": GRUPO_JID, "fromMe": True},
                    "text": emoji,
                }
            },
        },
    }


def _edicao_v2() -> dict[str, Any]:
    """Edicao: `protocolMessage` de tipo de edit, com o texto novo dentro."""
    return {
        "event": "messages.upsert",
        "instance": "procex",
        "data": {
            "key": {
                "id": ID_DO_ENVELOPE,
                "remoteJid": GRUPO_JID,
                "fromMe": False,
                "participant": TELEFONISTA_JID,
            },
            "message": {
                "protocolMessage": {
                    "key": {"id": ID_DO_ALVO, "remoteJid": GRUPO_JID, "fromMe": True},
                    "type": "MESSAGE_EDIT",
                    "editedMessage": {"conversation": "Valor: R$ 800"},
                }
            },
        },
    }


# --- o estado de hoje: os dois gestos morrem na borda -------------------------------------------


def test_reacao_e_descartada_por_extrair_mensagem() -> None:
    """O gate explicito de `reactionMessage`: sem ele, turno fantasma no agente de venda."""
    assert extrair_mensagem(_reacao_v2()["data"]) is None
    assert extrair_mensagem(_reacao_v2()) is None


def test_reacao_com_emoji_no_texto_continua_descartada() -> None:
    """Versoes que trazem o emoji em `.text` nao podem virar mensagem de texto "✅"."""
    assert extrair_mensagem(_reacao_v2(emoji="👍")) is None


def test_reacao_nao_e_confundida_com_delecao() -> None:
    assert extrair_delecao(_reacao_v2()) is None


def test_o_adaptador_go_entrega_a_reacao_intacta_e_ela_morre_no_mesmo_gate() -> None:
    """`adaptar_webhook_go` so traduz o ENVELOPE: o `reactionMessage` chega vivo ao gate."""
    adaptado = adaptar_webhook_go(_reacao_go())

    assert adaptado["event"] == "messages.upsert"
    assert "reactionMessage" in adaptado["data"]["message"]
    assert extrair_mensagem(adaptado) is None


def test_edicao_morre_no_ramo_da_revogacao() -> None:
    """`extrair_delecao` so aceita REVOKE — a edicao cai fora dele e nao apaga nada."""
    assert extrair_delecao(_edicao_v2()) is None


def test_edicao_tambem_nao_vira_mensagem() -> None:
    """Depois do ramo da delecao sobra o gate de texto vazio: 200 'ignored'."""
    assert extrair_mensagem(_edicao_v2()) is None


def test_reacao_do_cliente_no_privado_continua_ruido_do_agente_de_venda() -> None:
    """Historia 56 da spec: no 1:1 a reacao e ruido, e continua sendo descartada como hoje."""
    payload = _reacao_v2(remote_jid=CLIENTE_JID)

    assert extrair_mensagem(payload) is None
    assert extrair_gesto(payload) is None


# --- a porta unica do gesto no webhook, ainda fechada -------------------------------------------


def test_a_grafia_do_gesto_ainda_nao_foi_capturada() -> None:
    """O interruptor que destrava o ticket 08 — e o que este teste guarda.

    Enquanto for `False`, `extrair_gesto` devolve `None` para tudo e nada muda na borda. Virar para
    `True` sem conferir o payload real e exatamente o modo de falha que o projeto ja teve: contrato
    de evento inventado que passa no teste e erra em producao.
    """
    assert GRAFIA_DO_GESTO_CONFIRMADA is False


@pytest.mark.parametrize(
    "payload",
    [_reacao_v2(), _reacao_go(), adaptar_webhook_go(_reacao_go()), _edicao_v2()],
    ids=["reacao_v2", "reacao_go_crua", "reacao_go_adaptada", "edicao_v2"],
)
def test_nenhum_gesto_atravessa_a_borda_hoje(payload: dict[str, Any]) -> None:
    assert extrair_gesto(payload) is None


def test_gesto_fora_de_grupo_nunca_vira_evento() -> None:
    """Regra que NAO depende da grafia: so `@g.us`. Quem decide se o grupo e financeiro e a porta
    unica (closed-world contra `grupos_financeiros`), nunca o parser."""
    assert extrair_gesto(_reacao_v2(remote_jid=CLIENTE_JID)) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOQUEADO: o payload real de reacao da EvoGo nao foi capturado. O fixture acima e "
        "HIPOTETICO (shape Baileys). Roteiro em .scratch/agente-financeiro-v2/PAYLOAD-EVOGO.md: "
        "capturar o JSON cru, substituir o fixture, conferir campo a campo, virar "
        "GRAFIA_DO_GESTO_CONFIRMADA e remover este marcador."
    ),
)
def test_reacao_no_grupo_vira_gesto_com_o_id_do_ALVO() -> None:
    gesto = extrair_gesto(_reacao_v2())

    assert isinstance(gesto, ReacaoEvolution)
    # O id que importa e o da mensagem TOCADA, nunca o do envelope: o envelope e uma mensagem de
    # sistema nova, com id proprio, que nunca virou nada no nosso banco (mesma licao da revogacao).
    assert gesto.evolution_message_id == ID_DO_ALVO
    assert gesto.evolution_message_id != ID_DO_ENVELOPE
    assert gesto.remote_jid == GRUPO_JID
    assert gesto.emoji == "✅"
    assert gesto.participant == TELEFONISTA_JID


# --- a captura da grafia (temporaria, sai quando a chave virar) ----------------------------------


def _payload_de_reacao(*, remote_jid: str = "120363000@g.us") -> dict[str, object]:
    """O envelope HIPOTETICO de reacao — o mesmo contra o qual `_ler_gesto_hipotetico` foi escrito.

    Serve so para exercitar a captura: se o real for diferente (que e a suspeita), a captura tem
    que disparar do mesmo jeito, porque ela casa por substring e nao pela grafia exata.
    """
    return {
        "event": "messages.upsert",
        "instance": "procex-teste",
        "data": {
            "key": {"id": "ENVELOPE123", "remoteJid": remote_jid, "fromMe": False},
            "message": {
                "reactionMessage": {
                    "key": {"id": "ALVO456", "remoteJid": remote_jid, "fromMe": True},
                    "text": "✅",
                    "senderTimestampMs": 1756000000000,
                }
            },
        },
    }


def test_a_captura_dispara_para_reacao_em_grupo_e_nao_para_chat_de_cliente() -> None:
    """A fronteira e o `@g.us`, nao a grafia: reacao do CLIENTE continua ruido para o agente de
    venda, e nao pode virar linha de log nenhuma."""
    assert parece_gesto_em_grupo(_payload_de_reacao()) is True
    assert parece_gesto_em_grupo(_payload_de_reacao(remote_jid="5511999@s.whatsapp.net")) is False


@pytest.mark.parametrize(
    "grafia",
    ["reactionMessage", "ReactionMessage", "REACTION_MESSAGE", "protocolMessage", "editedMessage"],
)
def test_a_captura_casa_por_substring_porque_a_grafia_e_o_desconhecido(grafia: str) -> None:
    """Casar pela grafia exata seria pedir para descobrir o que ja se sabe. A EvoGo marshala o
    `waE2E.Message` do whatsmeow, e a caixa dele nao foi vista ao vivo."""
    payload = _payload_de_reacao()
    message = payload["data"]["message"]  # type: ignore[index]
    assert isinstance(message, dict)
    payload["data"]["message"] = {grafia: message["reactionMessage"]}  # type: ignore[index]

    assert parece_gesto_em_grupo(payload) is True


def test_a_captura_nao_dispara_para_mensagem_comum_de_grupo() -> None:
    """Senao todo card postado viraria um esboco no log, e a captura deixaria de ser captura."""
    payload = _payload_de_reacao()
    payload["data"]["message"] = {"conversation": "bom dia"}  # type: ignore[index]

    assert parece_gesto_em_grupo(payload) is False


def test_o_esboco_preserva_a_arvore_e_os_ids_e_redige_jid_e_texto_longo() -> None:
    """O esboco existe para responder DUAS perguntas — onde mora o alvo e onde mora o emoji — sem
    virar dump de payload. Id fica (e o que prova alvo x envelope); JID sai (e telefone)."""
    esboco = esboco_do_payload(_payload_de_reacao())

    assert isinstance(esboco, dict)
    reacao = esboco["data"]["message"]["reactionMessage"]
    assert reacao["key"]["id"] == "ALVO456"
    assert reacao["key"]["remoteJid"] == "<jid>"
    assert reacao["key"]["fromMe"] is True
    assert reacao["text"] == "✅"
    # Timestamp cru: e por ele (e pelo `text` vazio) que se distingue reacao POSTA de RETIRADA.
    assert reacao["senderTimestampMs"] == 1756000000000
    assert esboco["data"]["key"]["id"] == "ENVELOPE123"


def test_o_esboco_corta_texto_de_mensagem_e_nao_carrega_conteudo() -> None:
    """Um `protocolMessage` de EDICAO carrega o texto novo. A captura quer a FORMA, nao a frase."""
    payload = _payload_de_reacao()
    payload["data"]["message"] = {  # type: ignore[index]
        "protocolMessage": {
            "type": "MESSAGE_EDIT",
            "key": {"id": "ALVO456"},
            "editedMessage": {"conversation": "o valor certo era 700 e nao 500, corrige ai"},
        }
    }

    esboco = esboco_do_payload(payload)
    assert isinstance(esboco, dict)
    editada = esboco["data"]["message"]["protocolMessage"]["editedMessage"]["conversation"]
    assert editada.startswith("<str:")
    assert "700" not in editada


def test_o_esboco_nao_estoura_em_payload_recursivo_ou_gigante() -> None:
    """Borda hostil: o webhook e entrada nao-confiavel, e a captura roda ANTES de qualquer gate de
    negocio. Ela para na profundidade e no numero de itens em vez de estourar a pilha."""
    fundo: dict[str, object] = {"fim": 1}
    for _ in range(50):
        fundo = {"n": fundo}
    esboco = esboco_do_payload({"data": fundo, "lista": list(range(500))})

    assert isinstance(esboco, dict)
    assert json.dumps(esboco)  # serializavel, que e o que o log exige
    assert len(esboco["lista"]) == 24
