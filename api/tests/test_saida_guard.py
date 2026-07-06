"""SEC-PII-02 / SEC-OUT-01 — funções puras da rede final de saída (`workers/_saida_guard`).

A redação é POR ECO: só mascara PII que o próprio cliente mandou. O teste-chave garante que a
chave Pix da modelo (CPF/telefone que NÃO veio do cliente) nunca é mascarada — senão a rede
quebraria o Pix de deslocamento quando a humanização (M4) anexar a chave.
"""

import random

from barra.workers._saida_guard import (
    extrair_tokens_pii,
    normalizar_emoji_voz,
    normalizar_travessao,
    redigir_pii_eco,
    remover_marcador_quote,
    tem_marcador_ia,
    tem_placeholder_eco,
)


class _Rng:
    """rng de teste p/ a trava de frequência: .random() devolve sempre `v` (0.0 mantém, 1.0 remove)."""

    def __init__(self, v: float) -> None:
        self._v = v

    def random(self) -> float:
        return self._v


_KEEP = _Rng(0.0)  # 0.0 >= keep nunca True → mantém (isola o teste de whitelist/máx-1/seca)
_DROP = _Rng(1.0)  # 1.0 >= keep sempre True → remove


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
    assert normalizar_emoji_voz(["Oii amor 🥰"], rng=_KEEP) == ["Oii amor 🥰"]
    assert normalizar_emoji_voz(["tudo bem? 😊"], rng=_KEEP) == ["tudo bem? 😊"]
    assert normalizar_emoji_voz(["que delícia 🔥❤"]) == ["que delícia"]


def test_emoji_maximo_um_por_bolha_mantem_o_ultimo() -> None:
    """Rajada vira 1 (o corpus usa emoji como sufixo único)."""
    assert normalizar_emoji_voz(["ai amor 🥰🥰🥰"], rng=_KEEP) == ["ai amor 🥰"]


def test_emoji_secado_na_cotacao_e_logistica() -> None:
    """Da cotação em diante é seco: bolha com preço ou logística perde o emoji (persona <voz>)."""
    assert normalizar_emoji_voz(["800 1h ou 1200 2h 🥰"]) == ["800 1h ou 1200 2h"]
    assert normalizar_emoji_voz(["te espero no endereço 🥰"]) == ["te espero no endereço"]


def test_emoji_mantido_na_saudacao() -> None:
    assert normalizar_emoji_voz(["Boa tarde amor 🥰"], rng=_KEEP) == ["Boa tarde amor 🥰"]


def test_emoji_bolha_sem_emoji_intacta() -> None:
    assert normalizar_emoji_voz(["seria hoje?"]) == ["seria hoje?"]


def test_emoji_descarta_bolha_que_virou_vazia() -> None:
    """Bolha que era só um glyph fora do whitelist some; o turno não vai vazio."""
    assert normalizar_emoji_voz(["uma gracinha 🥰", "🌻"], rng=_KEEP) == ["uma gracinha 🥰"]
    assert normalizar_emoji_voz(["🌻"]) == ["🌻"]  # esvaziaria tudo → devolve original


# --- trava de frequência de emoji (atos não-secos): calibrada ao corpus humano ---------


def test_emoji_trava_frequencia_remove_quando_sorteio_falha() -> None:
    """Ato não-seco: com o sorteio em 'remove', o emoji whitelistado cai (a trava de frequência)."""
    assert normalizar_emoji_voz(["Boa tarde amor 🥰"], rng=_DROP) == ["Boa tarde amor"]
    assert normalizar_emoji_voz(["uma gracinha 🥰"], rng=_DROP) == ["uma gracinha"]


def test_emoji_trava_nao_afeta_atos_secos() -> None:
    """Ato seco já zera por _ATOS_SECOS, independe do sorteio (mesmo com rng em 'mantém')."""
    assert normalizar_emoji_voz(["800 1h no meu local 🥰"], rng=_KEEP) == ["800 1h no meu local"]


def test_emoji_frequencia_converge_para_alvo_do_corpus() -> None:
    """Em agregado, a fração de bolhas que mantêm emoji ≈ keep-alvo por ato (saudação 0.57, outro
    0.34) — a trava traz a frequência do agente à do corpus humano."""
    rng = random.Random(20260622)
    n = 4000
    saud = sum(
        normalizar_emoji_voz(["Boa noite amor 🥰"], rng=rng)[0].endswith("🥰") for _ in range(n)
    )
    outro = sum(
        normalizar_emoji_voz(["que delícia amor 🥰"], rng=rng)[0].endswith("🥰") for _ in range(n)
    )
    assert 0.52 < saud / n < 0.62  # keep-alvo 0.57
    assert 0.29 < outro / n < 0.39  # keep-alvo 0.34


# --- tem_placeholder_eco: token de ensino não-substituído ({valor}, [insira ...]) ------


def test_placeholder_detecta_chave_de_ensino() -> None:
    """A chave {palavra} dos exemplos <ela> que o modelo copiou literal = cotação quebrada."""
    assert tem_placeholder_eco("{valor} 1h no meu local rs")
    assert tem_placeholder_eco("te espero às {horario} amor")
    assert tem_placeholder_eco("é na {rua}, {bairro}")


def test_placeholder_detecta_colchete_instrucional() -> None:
    """Colchete de fill-in que o DeepSeek inventa ([insira a rua], [seu endereço])."""
    assert tem_placeholder_eco("é na [insira a rua] número 10")
    assert tem_placeholder_eco("o ponto é [seu endereço aqui]")


def test_placeholder_nao_casa_marker_quote() -> None:
    """[quote]/[quote: trecho] NÃO é placeholder ('quote' fora dos gatilhos) — senão barraria reply
    legítimo. (Na prática o chunking já removeu o marker antes desta rede; defesa em profundidade.)"""
    assert not tem_placeholder_eco("[quote] beleza amor")
    assert not tem_placeholder_eco("[quote: quanto 1h] 800 amor")


def test_placeholder_nao_casa_fala_legitima() -> None:
    """Cotação/horário/endereço reais (sem chaves nem colchete de fill-in) passam limpos."""
    assert not tem_placeholder_eco("800 1h ou 1200 2h no meu local")
    assert not tem_placeholder_eco("te espero às 23h30 amor")
    assert not tem_placeholder_eco("é na Rua das Flores, Chácara da Barra rs")
    assert not tem_placeholder_eco("seria hoje? 🥰")


# --- normalizar_travessao: em-dash '—' → vírgula (persona <voz>) ----------------


def test_travessao_entre_trechos_vira_virgula() -> None:
    """O caso documentado: o DeepSeek vaza '—' em endereço apesar da regra."""
    assert normalizar_travessao(["é na Rua X — Chácara da Barra"]) == [
        "é na Rua X, Chácara da Barra"
    ]
    assert normalizar_travessao(["X—Y"]) == ["X, Y"]  # colado, sem espaços
    assert normalizar_travessao(["A — B — C"]) == ["A, B, C"]  # múltiplos


def test_travessao_nas_pontas_some() -> None:
    """Travessão de lista/ênfase solta na ponta vira nada (vírgula na ponta seria feia)."""
    assert normalizar_travessao(["— item solto"]) == ["item solto"]
    assert normalizar_travessao(["fim da frase —"]) == ["fim da frase"]


def test_travessao_nao_toca_hifen_nem_en_dash() -> None:
    """Hífen ASCII (bem-vindo) e en-dash (faixa numérica) são preservados — só o em-dash sai."""
    assert normalizar_travessao(["seja bem-vindo ao guarda-roupa"]) == [
        "seja bem-vindo ao guarda-roupa"
    ]
    en = chr(0x2013)  # en-dash (U+2013) montado sem literal ambíguo no source
    assert normalizar_travessao([f"das 10{en}12h"]) == [f"das 10{en}12h"]  # en-dash intocado


def test_travessao_no_op_sem_em_dash_e_preserva_bolhas() -> None:
    """Sem em-dash não muda nada; a contagem de bolhas é preservada (transform por-bolha)."""
    assert normalizar_travessao(["oi amor", "tudo bem?"]) == ["oi amor", "tudo bem?"]


# --- Scrub do marcador [quote] residual (SEC-OUT) -------------------------------------------------
def test_quote_scrub_bem_formado_no_inicio_e_removido() -> None:
    """Marker bem-formado que o chunking deixou passar: removido, texto íntegro, sem buraco."""
    assert remover_marcador_quote("[quote: atende casal] sim amor") == ("sim amor", True)


def test_quote_scrub_puro_removido() -> None:
    assert remover_marcador_quote("[quote] pode vir sim") == ("pode vir sim", True)


def test_quote_scrub_malformado_sem_dois_pontos() -> None:
    """`[quote trecho]` (sem `:`) escapa do strip ANCORADO do chunking — a rede final pega."""
    assert remover_marcador_quote("[quote atende casal] sim amor") == ("sim amor", True)


def test_quote_scrub_espaco_interno_e_caixa() -> None:
    assert remover_marcador_quote("[ QUOTE : oi ] tudo bem?") == ("tudo bem?", True)


def test_quote_scrub_fora_do_inicio_da_bolha() -> None:
    """Marker no meio da bolha (o strip ancorado do chunking nunca pegaria) some sem duplicar espaço."""
    assert remover_marcador_quote("bom [quote] dia amor") == ("bom dia amor", True)


def test_quote_scrub_bolha_so_marker_vira_vazia() -> None:
    """Bolha que era só o marker vira "" (o caller a descarta e realinha o quote)."""
    assert remover_marcador_quote("[quote: oi]") == ("", True)


def test_quote_scrub_sem_marker_nao_altera_e_nao_conta() -> None:
    assert remover_marcador_quote("posso te atender amanhã?") == ("posso te atender amanhã?", False)


def test_quote_scrub_nao_casa_palavra_quotes_em_colchete() -> None:
    """`\\b` após 'quote' evita casar 'quotes' (não é o marker) — texto legítimo preservado."""
    assert remover_marcador_quote("[quotes do dia]") == ("[quotes do dia]", False)
