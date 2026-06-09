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


def test_fechado_com_dois_numeros_e_valor_ambiguo() -> None:
    # Antes pegava o 1o numero (R$50) e fechava em silencio; agora exige confirmacao.
    comando = parse_comando_grupo("fechado #5 paguei 50 no uber e fechei 1500")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.numero_curto == 5
    assert comando.payload["motivo"] == "valor_ambiguo"


def test_fechado_decimal_malformado_e_valor_ambiguo() -> None:
    # "1,5" vira dois candidatos (1 e 5) -> ambiguo em vez de silenciosamente virar Decimal('1').
    comando = parse_comando_grupo("fechado #5 1,5")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.payload["motivo"] == "valor_ambiguo"


def test_valor_pelado_ambiguo_citando_card_e_invalido() -> None:
    comando = parse_comando_grupo(
        "paguei 50 e fechei 1500", quoted_numero_curto=7, aguardando_valor=True
    )
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.payload["motivo"] == "valor_ambiguo"


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


def test_forgiveness_sinonimos_de_fechamento() -> None:
    # UX §6.3: `fechei`/`fechamos` valem como `fechado`/`finalizado`.
    for texto in ("fechei 1500 #3", "fechamos 1500 #3"):
        comando = parse_comando_grupo(texto)
        assert comando is not None, texto
        assert comando.comando == "registrar_fechado", texto
        assert comando.payload["valor_final"] == Decimal("1500"), texto


def test_forgiveness_sinonimos_de_perda_com_motivo() -> None:
    # `perdi` / `não rolou` / `nao rolou` valem como `perdido`.
    for texto in ("perdi sumiu #3", "não rolou sumiu #3", "nao rolou sumiu #3"):
        comando = parse_comando_grupo(texto)
        assert comando is not None, texto
        assert comando.comando == "registrar_perdido", texto
        assert comando.payload["motivo"] == "sumiu", texto


def test_forgiveness_perda_sem_motivo_cai_no_erro_que_pede_motivo() -> None:
    # §6.3: sinônimo de perda sem motivo ainda exige o motivo (erro 6.2), não inventa um.
    comando = parse_comando_grupo("nao rolou #3")
    assert comando is not None
    assert comando.comando == "comando_invalido"
    assert comando.payload["motivo"] == "motivo_perda_obrigatorio"


def test_forgiveness_sinonimo_citando_lembrete_segue_fluxo_normal() -> None:
    # Sinônimo numa resposta-quote ao lembrete não vira valor-pelado: cai no fluxo de fechamento,
    # herdando o #N do card citado.
    comando = parse_comando_grupo("fechei 1500", quoted_numero_curto=7, aguardando_valor=True)
    assert comando is not None
    assert comando.comando == "registrar_fechado"
    assert comando.numero_curto == 7
    assert comando.payload["valor_final"] == Decimal("1500")


def test_pendencias_reconhece_sinonimos_sem_numero() -> None:
    # UX §6.4: digest sob demanda, sem `#N`. Acentuado/sem acento, caixa e espacos tolerados.
    for texto in ("pendências", "pendencias", "Pendencias", "  status  ", "STATUS", "pendentes"):
        comando = parse_comando_grupo(texto)
        assert comando is not None, texto
        assert comando.comando == "listar_pendencias", texto
        assert comando.numero_curto is None, texto


def test_pendencias_nao_dispara_em_frase_que_contem_a_palavra() -> None:
    # Igualdade exata: "qual o status do #5" NAO e o digest (e referencia a um atendimento).
    assert parse_comando_grupo("qual o status do #5") is None
    assert parse_comando_grupo("status do atendimento") is None


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


def test_extrair_mensagem_imagem_base64_nivel_mensagem() -> None:
    # WEBHOOK_BASE64: a Evolution entrega a midia decifrada em `message.base64`.
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "IMG1", "remoteJid": "5521@g.us", "fromMe": False},
            "message": {
                "imageMessage": {
                    "url": "https://mmg.whatsapp.net/v/x.enc",
                    "mimetype": "image/jpeg",
                },
                "base64": "QUJD",
            },
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.tipo == "imagem"
    assert msg.media_base64 == "QUJD"
    assert msg.media_mimetype == "image/jpeg"
    # a url crua do CDN cifrado continua disponivel, mas nao e mais o caminho primario
    assert msg.media_url == "https://mmg.whatsapp.net/v/x.enc"


def test_extrair_mensagem_imagem_base64_aninhado_no_image_message() -> None:
    # Variacao de versao: base64 dentro de `imageMessage.base64`.
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "IMG2", "remoteJid": "5521@g.us", "fromMe": False},
            "message": {
                "imageMessage": {
                    "url": "https://mmg.whatsapp.net/v/y.enc",
                    "mimetype": "image/png",
                    "base64": "REVG",
                }
            },
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.media_base64 == "REVG"
    assert msg.media_mimetype == "image/png"


def test_extrair_mensagem_imagem_sem_base64_fica_none() -> None:
    # Sem WEBHOOK_BASE64 (ou bug #2375): base64 ausente -> None (cai no download host-locked).
    payload = {
        "instance": "barra-piloto",
        "data": {
            "key": {"id": "IMG3", "remoteJid": "5521@g.us", "fromMe": False},
            "message": {"imageMessage": {"url": "https://mmg.whatsapp.net/v/z.enc"}},
        },
    }
    msg = extrair_mensagem(payload)
    assert msg is not None
    assert msg.media_base64 is None
