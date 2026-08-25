"""ADR-0049 §6 / ticket 06 — o cartao entra pelo mesmo mecanismo, pelo nome do estabelecimento.

O dinheiro do cartao cai em dois lugares e a ata descreve os dois como normais: *"o ideal e ser na
nossa conta"* e *"a mina tem a maquina no celular dela, que e aquele PagBank/InfinitePay"*.
Perguntado de quem e a maquininha de cada uma das quatro modelos ativas, o dono respondeu *"nao sei
te responder"* — entao o dado nao pode vir de cadastro de confianca por modelo (revogado pelo
ADR-0047) nem de campo novo na ficha (que a Lula ja disse que nao sobrevive ao dia de pico).

Vem do print da maquininha, que ela ja manda: ele carrega o NOME DO ESTABELECIMENTO. E a mesma
evidencia da chave Pix noutro campo — e por isso a resposta e o mesmo `PapelResolvido`, a
classificacao e uma das classes que ja existem, e o bolso sai da mesma `resolver_bolso`.

Sem banco: o registro e uma sequencia e a resolucao e pura.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from barra.agente_financeiro.comprovante import ExtracaoDoComprovante
from barra.dominio.grupo_financeiro.comprovante import (
    ChaveComDono,
    ChaveVista,
    EstabelecimentoComDono,
    bolso_do_cartao,
    classificacao_do_cartao,
    normalizar_estabelecimento,
    papel_da_chave,
    papel_do_estabelecimento,
    sugestoes_de_cadastro,
    sugestoes_de_estabelecimento,
)

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
BIANCA = UUID("22222222-2222-2222-2222-222222222222")

MAQUININHA_DA_CASA = "Elite Servicos Ltda"
MAQUININHA_DELA = "PAGBANK * YASMIN"

REGISTRO = (
    EstabelecimentoComDono(nome=MAQUININHA_DA_CASA, papel="casa"),
    EstabelecimentoComDono(
        nome=MAQUININHA_DELA, papel="modelo", dono_id=YASMIN, dono_nome="Yasmin"
    ),
)


# --- a normalizacao ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lido", "cadastrado"),
    [
        ("PagBank", "PAGBANK"),  # o cupom vem em caixa alta, o gestor digitou como leu
        ("PAG BANK", "PagBank"),  # espaco que o OCR inventa (ou perde) entre as palavras
        ("Infinite-Pay", "InfinitePay"),
        ("MERCEARIA SAO JOAO", "Mercearia São João"),  # a dobra de acento que o Postgres nao faz
        ("  InfinitePay  ", "InfinitePay"),
    ],
)
def test_o_mesmo_estabelecimento_escrito_de_outro_jeito_e_o_mesmo(
    lido: str, cadastrado: str
) -> None:
    """O OCR le a grafia do cupom; o gestor digitou a dele. Se as duas nao casarem, o cadastro nao
    explica nada e a fila de sugestoes pede a mesma maquininha para sempre."""
    assert normalizar_estabelecimento(lido) == normalizar_estabelecimento(cadastrado)


def test_maquininhas_diferentes_da_mesma_operadora_nao_se_confundem() -> None:
    """Sem prefixo e sem "contem": "PAGBANK * YASMIN" e "PAGBANK * ELITE" sao duas contas, e casar
    uma pela outra e um palpite sobre de quem e o dinheiro."""
    assert normalizar_estabelecimento("PAGBANK * YASMIN") != normalizar_estabelecimento(
        "PAGBANK * ELITE"
    )
    assert papel_do_estabelecimento("PAGBANK * ELITE", REGISTRO).papel == "desconhecida"


# --- de quem e a maquininha ----------------------------------------------------------------------


def test_a_maquininha_da_casa_responde_casa() -> None:
    resolvido = papel_do_estabelecimento("ELITE SERVICOS LTDA", REGISTRO)
    assert resolvido.papel == "casa"
    assert resolvido.e_da_casa is True


def test_a_maquininha_dela_responde_por_PESSOA() -> None:
    """`e_da_modelo` continua sendo por pessoa: a maquininha da Yasmin nao explica a venda da
    Bianca. E o mesmo criterio da chave Pix, e por isso e a mesma funcao."""
    resolvido = papel_do_estabelecimento(MAQUININHA_DELA, REGISTRO)
    assert resolvido.papel == "modelo"
    assert resolvido.dono_id == YASMIN
    assert resolvido.e_da_modelo(YASMIN) is True
    assert resolvido.e_da_modelo(BIANCA) is False


@pytest.mark.parametrize("nome", [None, "", "   ", "***"])
def test_estabelecimento_ausente_ou_vazio_e_desconhecida_e_nunca_a_casa(nome: str | None) -> None:
    """Closed-world na ponta que doi: o OCR nao leu o topo do cupom. Assumir a casa aqui fixaria o
    bolso da venda em `empresa` sem evidencia nenhuma."""
    assert papel_do_estabelecimento(nome, REGISTRO).papel == "desconhecida"


def test_registro_vazio_devolve_desconhecida_para_tudo() -> None:
    """O estado de producao em 20/08/2026: ninguem cadastrou maquininha nenhuma, e nada quebra."""
    assert papel_do_estabelecimento("PagBank", ()).papel == "desconhecida"


def test_a_maquininha_inativa_continua_dizendo_de_quem_ela_e() -> None:
    """Autoria nao e autorizacao: a maquininha devolvida mes passado continua explicando o print de
    tres semanas atras. Quem pergunta "esta em uso hoje?" filtra por `ativo` do lado de fora."""
    registro = (
        EstabelecimentoComDono(
            nome="InfinitePay", papel="modelo", dono_id=YASMIN, dono_nome="Yasmin", ativo=False
        ),
    )
    assert papel_do_estabelecimento("InfinitePay", registro).e_da_modelo(YASMIN) is True


def test_os_dois_registros_nao_se_atravessam() -> None:
    """Uma chave Pix chamada `pagbank@elite.com` nao e a maquininha PagBank, e a maquininha nao
    responde por destino de Pix. Duas perguntas com a mesma forma, dois registros — misturar faria
    o comprovante de transferencia ser explicado por um cupom de cartao."""
    chaves = (ChaveComDono(chave="pagbank@elite.com", papel="casa"),)
    assert papel_do_estabelecimento("pagbank@elite.com", REGISTRO).papel == "desconhecida"
    assert papel_da_chave("PAGBANK * YASMIN", chaves).papel == "desconhecida"


# --- o efeito: classe e bolso ---------------------------------------------------------------------


def test_a_maquininha_dela_vira_entrada_da_modelo_e_bolso_dela() -> None:
    """Quem paga no cartao e sempre o CLIENTE. Com a maquininha dela, o dinheiro caiu com ela e
    nunca passou pela casa — a MESMA classe do Pix que o cliente manda para a chave dela."""
    papel = papel_do_estabelecimento(MAQUININHA_DELA, REGISTRO)
    assert classificacao_do_cartao(papel, modelo_id=YASMIN) == "entrada_da_modelo"
    resolvido = bolso_do_cartao(papel, modelo_id=YASMIN)
    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_modelo"


def test_a_maquininha_da_casa_fixa_o_bolso_em_empresa() -> None:
    """O caso que hoje nasce `nao_dito` e o razao trata como `dela`: o razao debita dela um bruto
    que ela nunca teve na mao."""
    papel = papel_do_estabelecimento(MAQUININHA_DA_CASA, REGISTRO)
    assert classificacao_do_cartao(papel, modelo_id=YASMIN) == "cliente_para_a_casa"
    resolvido = bolso_do_cartao(papel, modelo_id=YASMIN)
    assert resolvido.bolso == "empresa"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_casa"


def test_maquininha_de_OUTRA_modelo_nao_resolve_o_bolso_desta_venda() -> None:
    """Cadastrada sim, dela nao. Errar para `dela` aqui creditaria a venda a quem nao recebeu."""
    papel = papel_do_estabelecimento(MAQUININHA_DELA, REGISTRO)
    assert classificacao_do_cartao(papel, modelo_id=BIANCA) == "nao_classificado"
    assert bolso_do_cartao(papel, modelo_id=BIANCA).bolso == "nao_dito"


def test_maquininha_desconhecida_deixa_o_bolso_nao_dito_em_vez_de_chutar() -> None:
    """`nao_dito` e estado legitimo (ADR-0047 §3): entra na cobranca da manha e sai de la quando
    alguem classificar a maquininha na fila."""
    papel = papel_do_estabelecimento("MAQUININHA QUE NINGUEM CADASTROU", REGISTRO)
    assert classificacao_do_cartao(papel, modelo_id=YASMIN) == "nao_classificado"
    assert bolso_do_cartao(papel, modelo_id=YASMIN).bolso == "nao_dito"


def test_maquininha_de_terceiro_cadastrada_nao_vira_dinheiro_de_ninguem() -> None:
    """O papel que existe para PARAR de alarmar, nao para atribuir dinheiro."""
    registro = (EstabelecimentoComDono(nome="Bar do Ze", papel="terceiro"),)
    papel = papel_do_estabelecimento("BAR DO ZE", registro)
    assert papel.e_conhecida is True
    assert classificacao_do_cartao(papel, modelo_id=YASMIN) == "nao_classificado"
    assert bolso_do_cartao(papel, modelo_id=YASMIN).bolso == "nao_dito"


# --- a fila de sugestoes, que e a mesma ------------------------------------------------------------


def _vista(nome: str, vezes: int) -> ChaveVista:
    return ChaveVista(
        chave=nome, vezes=vezes, primeiro_em=date(2026, 8, 1), ultimo_em=date(2026, 8, 20)
    )


def test_maquininha_desconhecida_recorrente_entra_na_mesma_fila() -> None:
    """Mesma funcao de corte, mesma ordem, mesma frase do ticket 05 — o gestor nao precisa saber
    que existem dois registros."""
    fila = sugestoes_de_estabelecimento(
        [_vista("PAGBANK * OUTRA", 4), _vista(MAQUININHA_DA_CASA, 9), _vista("InfinitePay", 2)],
        REGISTRO,
    )
    assert [v.chave for v in fila] == ["PAGBANK * OUTRA", "InfinitePay"]


def test_a_primeira_aparicao_ainda_nao_e_sugestao() -> None:
    """O corte e o mesmo do ticket 05: a fila existe para o destino que VOLTOU."""
    assert sugestoes_de_estabelecimento([_vista("PAGBANK * OUTRA", 1)], REGISTRO) == ()


def test_a_fila_da_chave_nao_mudou_de_comportamento() -> None:
    """O ticket 06 refatorou o corte da fila para servir aos dois registros; se a fila da chave
    tivesse mudado junto, o ticket 05 teria regredido em silencio."""
    chaves = (ChaveComDono(chave="casa@pix.example", papel="casa"),)
    fila = sugestoes_de_cadastro(
        [_vista("agiota@pix.example", 3), _vista("casa@pix.example", 7)], chaves
    )
    assert [v.chave for v in fila] == ["agiota@pix.example"]


# --- o que o OCR devolve ---------------------------------------------------------------------------


def _extracao(**campos: object) -> ExtracaoDoComprovante:
    base: dict[str, object] = {"e_comprovante": False, "legivel": True}
    base.update(campos)
    return ExtracaoDoComprovante(**base)


def test_o_print_da_maquininha_traz_o_estabelecimento() -> None:
    leitura = _extracao(
        e_de_cartao=True, valor="600.00", estabelecimento=" PAGBANK * YASMIN "
    ).como_leitura()
    assert leitura.e_de_cartao is True
    assert leitura.estabelecimento == "PAGBANK * YASMIN"
    assert leitura.valor == Decimal("600.00")


def test_cartao_desliga_transferencia_mesmo_se_o_modelo_marcar_os_dois() -> None:
    """A trava que vale dinheiro: um print de maquininha com `e_comprovante=True` entra no abate
    FIFO e da por comprovada uma transferencia que a modelo nunca fez."""
    leitura = _extracao(e_comprovante=True, e_de_cartao=True, valor="600.00").como_leitura()
    assert leitura.e_comprovante is False
    assert leitura.e_de_cartao is True


def test_chave_lida_num_print_de_cartao_e_descartada() -> None:
    """Comprovante de venda no cartao nao tem chave Pix: um destino lido ali e alucinacao, e ele
    entraria na fila de sugestoes de CHAVE como um fantasma que ninguem consegue classificar."""
    leitura = _extracao(
        e_de_cartao=True, chave_destino="casa@pix.example", estabelecimento="PagBank"
    ).como_leitura()
    assert leitura.chave_destino is None


def test_a_transferencia_continua_sem_estabelecimento() -> None:
    """O caminho de hoje nao muda: o comprovante de Pix e identificado pela chave, e o campo novo
    fica `None` mesmo se o modelo escrever algo nele."""
    leitura = _extracao(
        e_comprovante=True,
        valor="600.00",
        chave_destino="casa@pix.example",
        estabelecimento="Banco Qualquer",
    ).como_leitura()
    assert leitura.e_de_cartao is False
    assert leitura.estabelecimento is None
    assert leitura.chave_destino == "casa@pix.example"


def test_o_prompt_nao_cita_a_maquininha_real_de_ninguem() -> None:
    """Mesma armadilha da chave real (o comentario do modulo): o unico exemplo do prompt e o que o
    modelo emite quando o campo esta ilegivel — e o estabelecimento decide o BOLSO da venda."""
    from barra.agente_financeiro.comprovante import PROMPT_COMPROVANTE

    minusculo = PROMPT_COMPROVANTE.lower()
    assert "pagbank" not in minusculo
    assert "infinitepay" not in minusculo


def test_o_schema_que_sobe_ao_provider_tem_os_campos_do_cartao() -> None:
    propriedades = ExtracaoDoComprovante.model_json_schema()["properties"]
    assert "e_de_cartao" in propriedades
    assert "estabelecimento" in propriedades
