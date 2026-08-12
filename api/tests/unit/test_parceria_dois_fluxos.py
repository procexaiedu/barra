"""Os dois fluxos da parceira (ADR-0042) — as invariantes duras, testadas nos DOIS sentidos.

Os dois fluxos partem da MESMA pessoa na MESMA conversa e divergem em tudo. Os modos de falha são
os piores possíveis: passar o telefone dela numa conversa de DUPLA perde as duas vendas e queima o
canal; cotar as duas num pedido de ANAL promete o que a modelo não faz. Por isso cada invariante
aqui tem o par positivo E o negativo — um teste que só prova o caminho feliz não prova separação.

Sem DB e sem crédito: o discriminante é puro, a bolha é pura, e as travas da tool rodam contra um
fake de conexão.
"""

from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from barra.agente._parceria import (
    eh_bolha_de_contato_da_parceira,
    fluxo_da_parceira,
    formatar_bolha_contato_parceira,
)
from barra.agente.nos._foco_do_turno import fetiches_no_burst
from barra.agente.nos.output_guard import _limpar_bolhas, tem_chave_pix
from barra.agente.nos.prepare_context import (
    _BaseDoPatamar,
    _familias_fora_do_cardapio,
    _resolver_fetiches_em_pauta,
)
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.modelos.parcerias import Parceria
from barra.workers.envio import midia_conta_como_book

# --- Cadastro da Catarina (o real de prod), com a parceira Yasmin -------------------------------
# Tabela: 1h 400 (mínimo 300), 2h 800 (mínimo 600). O item de composição "Dupla de modelos" está
# cadastrado com o sentinel de flag "pago sem valor" — o regime DERIVADO do ADR-0038/0039, o de
# quase todo o prod: o extra é a linha de 1h do MESMO programa, no patamar vigente.
_PROGRAMAS = [
    {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": Decimal("1"), "preco": 400},
    {"nome": "Normal", "duracao_nome": "2 horas", "duracao_horas": Decimal("2"), "preco": 800},
]
_CARDAPIO = {
    "fetiches": [
        {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False},
        {"nome": "Dupla de modelos", "preco": Decimal("1"), "cobra_por_pessoa": True},
        {"nome": "Dois casais (2 modelos)", "preco": Decimal("1"), "cobra_por_pessoa": True},
    ],
    "programas": _PROGRAMAS,
}
# Cardápio SEM o item de dupla: é o que separa "ela faz esse arranjo" de "ela tem uma parceira".
_CARDAPIO_SEM_DUPLA = {
    "fetiches": [{"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False}],
    "programas": _PROGRAMAS,
}

_YASMIN = Parceria(
    parceira_id="019ff2e1-339a-7a7f-ae5c-a63e5796883f",
    nome="Yasmin",
    idade=19,
    encaminhamento_ativo=True,
    encaminhamento_atos=("anal",),
    dupla_ativa=True,
)


def _decidir(fala: str, cardapio: dict[str, Any] = _CARDAPIO, parceria: Parceria | None = _YASMIN):
    """O caminho REAL do turno: regex do burst -> resolução contra o cadastro -> discriminante."""
    familias = fetiches_no_burst([HumanMessage(content=fala)])
    resolvidos = _resolver_fetiches_em_pauta(familias, cardapio)
    return fluxo_da_parceira(
        familias,
        familias_fora_do_cardapio=_familias_fora_do_cardapio(familias, resolvidos),
        parceria=parceria,
    )


# --- A fronteira do discriminante, nos dois sentidos --------------------------------------------


def test_pedido_de_ato_fora_do_cardapio_arma_o_ENCAMINHAMENTO() -> None:
    """Ele pede anal, a Catarina não tem anal, a Yasmin faz: fluxo A."""
    assert _decidir("você faz anal ?") == ("encaminhamento", "anal")


def test_pedido_de_duas_mulheres_arma_a_DUPLA() -> None:
    """Ele pede vocês duas e a composição está no cardápio dela: fluxo B."""
    assert _decidir("rola você e uma amiga sua ?") == ("dupla", "dupla_de_modelos")
    assert _decidir("queria dois casais, eu e um amigo") == ("dupla", "dois_casais")


def test_os_dois_fluxos_nunca_no_mesmo_turno() -> None:
    """O burst misto ("vocês duas fazem anal ?") arma UM fluxo, e é o B.

    Assimetria de dano: B nunca emite telefone, e o ato fora do cardápio continua recebendo a
    recusa closed-world dentro do encontro que ela está vendendo. O caminho inverso mandaria o
    contato da parceira para quem estava comprando as duas."""
    familias = fetiches_no_burst([HumanMessage(content="vocês duas fazem anal ?")])
    assert set(familias) >= {"anal", "dupla_de_modelos"}

    decidido = _decidir("vocês duas fazem anal ?")

    assert decidido is not None
    assert decidido[0] == "dupla"
    # E o anal segue marcado como FORA do cardápio dela — a recusa não sumiu, só não virou fluxo.
    resolvidos = _resolver_fetiches_em_pauta(familias, _CARDAPIO)
    assert {r["nome"]: r["status"] for r in resolvidos}["anal"] == "fora"


def test_sem_parceria_nenhum_fluxo_arma() -> None:
    """A whitelist do par É a linha da tabela: sem ela, os dois pedidos caem no default."""
    assert _decidir("você faz anal ?", parceria=None) is None
    assert _decidir("rola você e uma amiga sua ?", parceria=None) is None


def test_ato_que_ela_FAZ_nao_encaminha() -> None:
    """O encaminhamento existe para o que ela NÃO faz. Com o anal no cardápio dela, o pedido é
    dela — encaminhar ali seria dar de graça uma venda que já era sua."""
    com_anal = {
        "fetiches": [*_CARDAPIO["fetiches"], {"nome": "Anal", "preco": None}],
        "programas": _PROGRAMAS,
    }
    assert _decidir("você faz anal ?", cardapio=com_anal) is None


def test_ato_fora_do_cardapio_mas_fora_da_autorizacao_do_par_nao_encaminha() -> None:
    """`encaminhamento_atos` é a whitelist POR ATO. Fisting não está lá: recusa de sempre."""
    assert _decidir("faz fisting ?") is None


def test_dupla_sem_o_item_no_cardapio_dela_nao_arma() -> None:
    """Closed-world vence a parceria: ter uma parceira não é oferecer o arranjo. Sem o item, não
    há de onde tirar o número das duas — e vender sem preço é pior que recusar."""
    assert _decidir("rola você e uma amiga sua ?", cardapio=_CARDAPIO_SEM_DUPLA) is None


def test_flags_do_par_desligam_cada_fluxo_isoladamente() -> None:
    """As duas autorizações são independentes: um par pode vender junto e não poder encaminhar."""
    so_dupla = Parceria(**{**vars_de(_YASMIN), "encaminhamento_ativo": False})
    so_encaminha = Parceria(**{**vars_de(_YASMIN), "dupla_ativa": False})

    assert _decidir("você faz anal ?", parceria=so_dupla) is None
    assert _decidir("rola você e uma amiga sua ?", parceria=so_dupla) is not None
    assert _decidir("você faz anal ?", parceria=so_encaminha) is not None
    assert _decidir("rola você e uma amiga sua ?", parceria=so_encaminha) is None


def test_acompanhante_dele_nunca_e_dupla() -> None:
    """A segunda pessoa que ELE traz não é a parceira: armar a dupla ali ofereceria uma modelo que
    ninguém pediu."""
    assert _decidir("vou levar minha namorada, quanto fica ?") is None
    assert _decidir("eu e um amigo meu, dá pra nós dois ?") is None


def vars_de(p: Parceria) -> dict[str, Any]:
    """`vars()` não funciona em dataclass com slots; este é o equivalente."""
    return {campo: getattr(p, campo) for campo in p.__dataclass_fields__}


# --- O telefone: a bolha determinística e a rede anti-Pix ---------------------------------------


def test_a_bolha_do_contato_sobrevive_a_rede_anti_pix() -> None:
    """A colisão que derrubaria a bolha em silêncio: o E.164 tem 13 dígitos corridos e casa o ramo
    `\\d{11,14}` do `_RE_CHAVE_PIX`. O carve-out é o que a mantém viva."""
    bolha = formatar_bolha_contato_parceira("Yasmin", "+5521995346564")

    assert tem_chave_pix(bolha)  # o regex REALMENTE morde — o carve-out não é decorativo
    assert eh_bolha_de_contato_da_parceira(bolha)
    turno = f"Ela te espera amor\n\n{bolha}"
    assert _limpar_bolhas(turno) == turno


def test_a_rede_anti_pix_continua_matando_chave_de_verdade() -> None:
    """O outro sentido: o carve-out não pode ter aberto a porta para chave inventada."""
    for chave in (
        "minha chave pix é 12345678900",
        "chave pix: chave@exemplo.com",
        "manda pra 123e4567-e89b-12d3-a456-426614174000",
        "meu cpf 123.456.789-00 amor",
    ):
        assert tem_chave_pix(chave)
        assert not eh_bolha_de_contato_da_parceira(chave)
        assert _limpar_bolhas(f"Oi amor\n\n{chave}") == "Oi amor"


def test_o_carve_out_nao_absolve_telefone_em_fala_solta() -> None:
    """Estreito de propósito: só a forma EXATA que o sistema monta. Uma bolha escrita pela LLM com
    um número dentro continua morrendo — é justamente ela que nunca pode sair."""
    for quase in (
        "contato da Yasmin: +5521995346564 amor",
        "o contato da Yasmin: +5521995346564",
        "contato da Yasmin: 5521995346564",
        "Yasmin: +5521995346564",
    ):
        assert not eh_bolha_de_contato_da_parceira(quase)


def test_normaliza_o_numero_do_cadastro_para_e164() -> None:
    """O painel grava com e sem o `+` e com pontuação; a bolha sai sempre na mesma forma (que é
    contrato com o carve-out)."""
    for cru in ("+5521995346564", "5521995346564", "+55 (21) 99534-6564"):
        assert formatar_bolha_contato_parceira("Yasmin", cru) == "contato da Yasmin: +5521995346564"


# --- Fotos da parceira não carimbam o book ------------------------------------------------------


def test_foto_da_parceira_nao_carimba_o_book_e_o_dela_continua_disponivel() -> None:
    """`marcar_book_enviado` carimbava QUALQUER envio de mídia: as fotos da Yasmin acenderiam
    `<ja_enviou_book>` e bloqueariam o book da Catarina pelo resto da negociação."""
    assert not midia_conta_como_book({"midia_id": "x", "de": "parceira"})
    assert midia_conta_como_book({"midia_id": "x", "de": "eu"})
    # Mídia gravada antes desta mudança (payload sem `de`) segue contando como book.
    assert midia_conta_como_book({"midia_id": "x"})


# --- O preço da dupla (ADR-0039, tabela da Catarina) --------------------------------------------


def _total_da_dupla(patamar: str, horas: str, pacote: str, uma_hora: str) -> str:
    from barra.dominio.atendimentos.service import valor_no_patamar

    base = _BaseDoPatamar(
        patamar=patamar,  # type: ignore[arg-type]
        pacote=valor_no_patamar(Decimal(pacote), None, patamar),  # type: ignore[arg-type]
        horas=Decimal(horas),
        linha_de_uma_hora=(Decimal(uma_hora), None),
    )
    return _resolver_fetiches_em_pauta(("dupla_de_modelos",), _CARDAPIO, base)[0]["total"]


@pytest.mark.parametrize(
    ("patamar", "horas", "pacote", "esperado"),
    [
        # 1h no piso (300) + o extra da 1h NO PISO (300) = 600 — "hoje 600".
        ("piso", "1", "400", "R$600"),
        # 2h cheia é a tabela estática (800 + 400 = 1200); no piso, 600 + 300 = 900.
        ("piso", "2", "800", "R$900"),
    ],
)
def test_dupla_soma_o_extra_da_linha_de_1h_no_patamar_vigente(
    patamar: str, horas: str, pacote: str, esperado: str
) -> None:
    """ADR-0039: a 2ª pessoa custa o MESMO extra dos atos — a linha de 1h do programa, no patamar
    vigente. O pacote NÃO dobra."""
    # A linha de 1h da tabela é sempre 400 (cheia) com mínimo 300 — quem aplica o patamar aos DOIS
    # lados (pacote e extra) é o `extra_de_fetiche`, não o cadastro.
    assert _total_da_dupla(patamar, horas, pacote, "400") == esperado


def test_no_patamar_cheio_o_numero_e_a_tabela_estatica() -> None:
    """No cheio não há bloco de turno: a coluna "Total com a 2ª pessoa" do `<fetiches>` já É o
    número (1h 400+400=800; 2h 800+400=1200), e injetar um total aqui só duplicaria a fonte."""
    from barra.agente.persona import render_fetiches

    bloco = render_fetiches(_CARDAPIO["fetiches"], _PROGRAMAS)

    assert "800" in bloco  # 1h com a 2ª pessoa
    assert "1.200" in bloco or "1200" in bloco  # 2h com a 2ª pessoa
    assert "total" not in _resolver_fetiches_em_pauta(("dupla_de_modelos",), _CARDAPIO, None)[0]


# --- As tags do contexto: uma por turno, nunca as duas -------------------------------------------


def _render(**kw: Any) -> str:
    base: dict[str, Any] = {
        "parceira_nome": "Yasmin",
        "parceira_fluxo": None,
        "parceira_ato": None,
        "parceira_ja_encaminhada": False,
        "parceira_dupla_assumida": False,
    }
    return render_contexto_dinamico(**{**base, **kw})


def test_a_tag_da_dupla_manda_fechar_e_proibe_o_telefone() -> None:
    out = _render(parceira_fluxo="dupla")

    assert "<dupla_em_pauta" in out
    assert "<parceira_faz_o_que_voce_nao_faz" not in out
    assert "fecha sozinha" in out
    assert "telefone dela NUNCA vai ao cliente" in out


def test_a_tag_do_encaminhamento_proibe_cotar_e_exige_o_sim_dele() -> None:
    out = _render(parceira_fluxo="encaminhamento", parceira_ato="anal")

    assert "<parceira_faz_o_que_voce_nao_faz" in out
    assert "<dupla_em_pauta" not in out
    assert "NÃO cota valor nenhum" in out
    assert "antes do SIM dele" in out


def test_nenhuma_tag_sem_fluxo() -> None:
    out = _render()

    assert "<dupla_em_pauta" not in out
    assert "<parceira_faz_o_que_voce_nao_faz" not in out


def test_as_travas_duraveis_renderizam_sozinhas() -> None:
    assert "<ja_encaminhou_a_parceira>" in _render(parceira_ja_encaminhada=True)
    assert "<dupla_ja_assumida>" in _render(parceira_dupla_assumida=True)
    assert "<ja_encaminhou_a_parceira>" not in _render()
    assert "<dupla_ja_assumida>" not in _render()
