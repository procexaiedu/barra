"""SEC-PII-02 / SEC-OUT-01 — funções puras da rede final de saída (`workers/_saida_guard`).

A redação é POR ECO: só mascara PII que o próprio cliente mandou. O teste-chave garante que a
chave Pix da modelo (CPF/telefone que NÃO veio do cliente) nunca é mascarada — senão a rede
quebraria o Pix de deslocamento quando a humanização (M4) anexar a chave.
"""

from barra.workers._saida_guard import (
    extrair_tokens_pii,
    normalizar_emoji_voz,
    redigir_pii_eco,
    tem_marcador_ia,
)


def test_extrai_cpf_e_telefone_ignora_numero_curto() -> None:
    tokens = extrair_tokens_pii("cpf 123.456.789-00, zap (11) 98888-7777, valor 100 reais")
    assert "12345678900" in tokens  # CPF normalizado
    assert "11988887777" in tokens  # telefone normalizado
    assert "88887777" in tokens  # cauda de 8 do telefone (casa variação de DDD/+55)
    # "100" (preço) não é PII e não entra
    assert "100" not in tokens


def test_redige_cpf_ecoado_do_cliente() -> None:
    cliente = extrair_tokens_pii("meu cpf é 123.456.789-00")
    texto, tipos = redigir_pii_eco("confere seu cpf 12345678900 então", cliente)
    assert texto == "confere seu cpf *** então"
    assert tipos == ["cpf"]


def test_nao_redige_chave_pix_da_modelo_que_nao_veio_do_cliente() -> None:
    """A chave Pix da modelo (CPF aqui) NÃO está no inbound do cliente → não é mascarada; já o
    telefone que o cliente mandou e a IA ecoou É mascarado."""
    cliente = extrair_tokens_pii("meu zap é (11) 98888-7777")
    texto, tipos = redigir_pii_eco(
        "manda no pix 123.456.789-00 que te ligo no 11988887777", cliente
    )
    assert "123.456.789-00" in texto  # chave Pix da modelo preservada
    assert "11988887777" not in texto  # telefone ecoado do cliente foi mascarado
    # exatamente uma redação; o rótulo pode ser cpf OU telefone (um celular de 11 dígitos sem
    # formatação casa o shape de CPF — sobreposição aceita, a redação é o que importa).
    assert len(tipos) == 1


def test_telefone_casa_apesar_de_prefixo_55() -> None:
    cliente = extrair_tokens_pii("liga +55 11 98888-7777")
    texto, _ = redigir_pii_eco("te ligo no (11) 98888-7777 hoje", cliente)
    assert "98888-7777" not in texto


def test_tokens_cliente_vazio_nao_altera() -> None:
    texto, tipos = redigir_pii_eco("meu cpf 123.456.789-00", set())
    assert texto == "meu cpf 123.456.789-00"
    assert tipos == []


def test_redige_rg_sem_pontuacao_ecoado() -> None:
    """RG corrido (9 dígitos, sem pontos) é PII sensível e deve ser redigido no eco."""
    cliente = extrair_tokens_pii("meu rg é 123456789")
    assert "123456789" in cliente
    texto, tipos = redigir_pii_eco("confirma teu rg 123456789?", cliente)
    assert texto == "confirma teu rg ***?"
    assert tipos == ["rg"]


def test_cep_oito_digitos_nao_colide_com_rg() -> None:
    """CEP tem 8 dígitos; o RG corrido exige 9 — não há colisão (endereço fica de fora)."""
    cliente = extrair_tokens_pii("cep 01310100 e rg 123456789")
    assert "01310100" not in cliente  # 8 dígitos: não é PII redigível aqui
    assert "123456789" in cliente  # 9 dígitos: RG


def test_cep_nao_e_tratado_como_pii() -> None:
    """Endereço/CEP ficam de fora (a IA combina endereço de atendimento externo legitimamente)."""
    cliente = extrair_tokens_pii("é no cep 01310-100")
    assert cliente == set()
    texto, tipos = redigir_pii_eco("o ponto é cep 01310-100", cliente)
    assert texto == "o ponto é cep 01310-100"
    assert tipos == []


def test_marcador_ia_detecta_admissao() -> None:
    assert tem_marcador_ia("na real eu sou uma IA, foi mal")
    assert not tem_marcador_ia("sou a Bia, prazer 😊")


# --- normalizar_emoji_voz: whitelist {🥰,😊} + máx-1 + seca-na-venda ----------


def test_emoji_remove_fora_do_whitelist_mantem_permitido() -> None:
    """Glyph fora de {🥰,😊} cai (girassol idiossincrático, fogo, coração); o permitido fica."""
    assert normalizar_emoji_voz(["Bom dia 🌻"]) == ["Bom dia"]
    assert normalizar_emoji_voz(["Oii amor 🥰"]) == ["Oii amor 🥰"]
    assert normalizar_emoji_voz(["tudo bem? 😊"]) == ["tudo bem? 😊"]
    assert normalizar_emoji_voz(["que delícia 🔥❤"]) == ["que delícia"]


def test_emoji_maximo_um_por_bolha_mantem_o_ultimo() -> None:
    """Rajada vira 1 (o corpus usa emoji como sufixo único)."""
    assert normalizar_emoji_voz(["ai amor 🥰🥰🥰"]) == ["ai amor 🥰"]


def test_emoji_secado_na_cotacao_e_logistica() -> None:
    """Da cotação em diante é seco: bolha com preço ou logística perde o emoji (persona <voz>)."""
    assert normalizar_emoji_voz(["800 1h ou 1200 2h 🥰"]) == ["800 1h ou 1200 2h"]
    assert normalizar_emoji_voz(["te espero no endereço 🥰"]) == ["te espero no endereço"]


def test_emoji_mantido_na_saudacao() -> None:
    assert normalizar_emoji_voz(["Boa tarde amor 🥰"]) == ["Boa tarde amor 🥰"]


def test_emoji_bolha_sem_emoji_intacta() -> None:
    assert normalizar_emoji_voz(["seria hoje?"]) == ["seria hoje?"]


def test_emoji_descarta_bolha_que_virou_vazia() -> None:
    """Bolha que era só um glyph fora do whitelist some; o turno não vai vazio."""
    assert normalizar_emoji_voz(["uma gracinha 🥰", "🌻"]) == ["uma gracinha 🥰"]
    assert normalizar_emoji_voz(["🌻"]) == ["🌻"]  # esvaziaria tudo → devolve original
