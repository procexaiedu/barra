"""ADR-0049 §1 / ticket 03 — "de quem e esta chave" deixa de ser um booleano.

`chave_e_conhecida(chave) -> bool` respondia "esta na lista da casa", e por isso engolia num
unico aviso duas coisas opostas: a chave da PROPRIA modelo (informacao que resolve o bolso da
venda, ADR-0047) e a chave de um terceiro qualquer (ruido). `papel_da_chave` devolve o papel e,
quando o papel pede, QUEM.

Sem banco de proposito: a regra e uma funcao pura sobre `ChaveComDono`, e e a MESMA que o grupo
financeiro (`agente_financeiro/porta.py`) e o Pix de deslocamento (`workers/pix.py`) chamam. Era
a duplicacao que o proprio codigo denunciava em `comprovante.py:69`.
"""

from uuid import uuid4

from barra.dominio.grupo_financeiro.comprovante import (
    ChaveComDono,
    papel_da_chave,
)

YASMIN = uuid4()
BIANCA = uuid4()
TELEFONISTA = uuid4()

CASA = ChaveComDono(chave="casa-elite@pix.example", papel="casa", titular="Elite Servicos Ltda")
DA_YASMIN = ChaveComDono(
    chave="+55 71 99984-0879",
    papel="modelo",
    dono_id=YASMIN,
    dono_nome="Yasmin Ruiva",
    titular="YASMIN NASCIMENTO DE ALBUQUERQUE",
)
DO_TELEFONISTA = ChaveComDono(
    chave="joao@pix.example", papel="telefonista", dono_id=TELEFONISTA, dono_nome="Joao Pereira"
)
DO_AGIOTA = ChaveComDono(chave="agiota@pix.example", papel="terceiro", titular="Erick de Melo")

REGISTRO = (CASA, DA_YASMIN, DO_TELEFONISTA, DO_AGIOTA)


def test_cadastro_vazio_devolve_desconhecida_para_tudo() -> None:
    """Closed-world, e e o estado de producao em 20/08/2026: 1 linha na tabela, nada tipado.

    Nao e um caso de borda — e o caminho que roda hoje em toda leitura de comprovante. Ele tem
    que atravessar sem excecao e sem casar nada por acidente.
    """
    assert papel_da_chave("casa-elite@pix.example", ()).papel == "desconhecida"
    assert papel_da_chave("casa-elite@pix.example", ()).e_conhecida is False
    assert papel_da_chave("casa-elite@pix.example", ()).e_da_casa is False


def test_chave_ausente_e_desconhecida_nunca_casa_por_acidente() -> None:
    """O OCR nao achou o destino. Assumir a casa aqui esconderia justamente o comprovante que mais
    merece um olho humano — e, depois do ticket 04, fixaria o bolso da venda em `empresa` sem
    evidencia nenhuma."""
    assert papel_da_chave(None, REGISTRO).papel == "desconhecida"
    assert papel_da_chave("", REGISTRO).papel == "desconhecida"
    assert papel_da_chave("   ", REGISTRO).papel == "desconhecida"


def test_a_chave_da_casa_continua_sendo_a_da_casa() -> None:
    """O que `chave_e_conhecida` respondia True agora responde `casa` — mesma decisao, com nome."""
    papel = papel_da_chave("casa-elite@pix.example", REGISTRO)
    assert papel.papel == "casa"
    assert papel.e_da_casa
    assert papel.e_conhecida


def test_chave_de_modelo_devolve_QUEM_e_nao_so_nao_e_da_casa() -> None:
    """O ganho do ticket: `terceiro` e `modelo` deixam de ser o mesmo "fora da lista".

    E `e_da_modelo` e por PESSOA — a chave da Yasmin nao responde pela Bianca, que e o buraco que
    a lista plana tinha (qualquer chave cadastrada servia para qualquer atendimento).
    """
    papel = papel_da_chave("+55 71 99984-0879", REGISTRO)
    assert papel.papel == "modelo"
    assert papel.dono_id == YASMIN
    assert papel.dono_nome == "Yasmin Ruiva"
    assert papel.e_da_modelo(YASMIN)
    assert papel.e_da_modelo(BIANCA) is False
    assert papel.e_da_modelo(None) is False
    assert papel.e_da_casa is False


def test_terceiro_e_conhecido_e_mesmo_assim_nao_e_da_casa() -> None:
    """O papel que so existe porque o booleano nao dava conta: "conheco esta chave E ela nao e da
    operacao". Sem ele, o agiota do exemplo voltaria a pedir julgamento humano toda vez."""
    papel = papel_da_chave("agiota@pix.example", REGISTRO)
    assert papel.papel == "terceiro"
    assert papel.e_conhecida
    assert papel.e_da_casa is False
    assert papel.e_da_modelo(YASMIN) is False


def test_telefonista_devolve_quem() -> None:
    papel = papel_da_chave("joao@pix.example", REGISTRO)
    assert papel.papel == "telefonista"
    assert papel.dono_id == TELEFONISTA
    assert papel.dono_nome == "Joao Pereira"


def test_a_grafia_da_tela_do_banco_e_a_mesma_chave() -> None:
    """`+55 71 99984 0879` e `+5571999840879` sao a MESMA chave — o OCR le a grafia do banco, o
    cadastro guarda a grafia de quem digitou. Comportamento identico ao de `chave_e_conhecida`."""
    assert papel_da_chave("+5571999840879", REGISTRO).dono_id == YASMIN
    assert papel_da_chave("+55 71 99984 0879", REGISTRO).dono_id == YASMIN
    assert papel_da_chave("+55 (71) 99984.0879", REGISTRO).dono_id == YASMIN
    assert papel_da_chave("CASA-ELITE@PIX.EXAMPLE", REGISTRO).papel == "casa"
    # Falta o DDI: e outra chave, e continua sendo.
    assert papel_da_chave("71 99984 0879", REGISTRO).papel == "desconhecida"


def test_chave_inativa_continua_tendo_dono() -> None:
    """Inativar nunca deletar. A conta que a casa encerrou mes passado continua sendo a conta da
    casa no comprovante de tres semanas atras — quem pergunta "autoriza destino NOVO?" filtra por
    `ativo` do lado de fora (`workers/pix.py::_recebe_por_esta_operacao`)."""
    encerrada = ChaveComDono(chave="antiga@pix.example", papel="casa", ativo=False)
    papel = papel_da_chave("antiga@pix.example", (encerrada,))
    assert papel.papel == "casa"
    assert papel.e_da_casa


def test_a_primeira_linha_que_casa_manda() -> None:
    """O banco impede chave repetida (`chaves_pix_conhecidas_chave_normalizada_key`), entao esta
    ordem so importa se alguem montar o registro a mao — e mesmo ai ela e deterministica."""
    a = ChaveComDono(chave="x@pix.example", papel="casa")
    b = ChaveComDono(chave="x@pix.example", papel="terceiro")
    assert papel_da_chave("x@pix.example", (a, b)).papel == "casa"
