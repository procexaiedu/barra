"""ADR-0049 / ticket 01 — a regra de aceitacao do destino do Pix de deslocamento, sem banco.

O contrato de `ChavesDaOperacao`, em uma frase: **aceitar e coisa da operacao inteira, divergir e
coisa da expectativa**. O conjunto `chaves` diz o que pode receber (casa, modelo, telefonista);
`chave_da_modelo` diz se existe expectativa — sem ela o comprovante nao tem contra o que divergir,
que e o estado de producao em 20/08/2026 (0 modelos com chave preenchida).
"""

from barra.workers.pix import ChavesDaOperacao

CASA = "casa-elite@pix.example"
MODELO = "modelo@pix.example"
TELEFONISTA = "+55 71 99984-0879"


def test_vazio_nao_aceita_e_nao_tem_expectativa() -> None:
    """O default e o estado de hoje: cadastro vazio nao autoriza nada E nao cobra nada.

    `aceita_chave` False sozinho NAO reprova comprovante nenhum — quem reprova e a combinacao com
    `chave_da_modelo` preenchida, em `validar_pix`. Separar as duas coisas e o conserto do ticket.
    """
    conhecidas = ChavesDaOperacao()
    assert conhecidas.aceita_chave(MODELO) is False
    assert conhecidas.chave_da_modelo is None
    assert conhecidas.titular_da_modelo is None


def test_aceita_qualquer_chave_da_operacao_nao_so_a_da_modelo() -> None:
    """O bug dormente em uma linha: antes, so `chave_da_modelo` passava."""
    conhecidas = ChavesDaOperacao(
        chaves=(CASA, MODELO, TELEFONISTA),
        chave_da_modelo=MODELO,
    )
    assert conhecidas.aceita_chave(CASA)
    assert conhecidas.aceita_chave(MODELO)
    assert conhecidas.aceita_chave(TELEFONISTA)
    assert conhecidas.aceita_chave("golpista@pix.example") is False


def test_a_grafia_da_tela_do_banco_nao_derruba_a_chave() -> None:
    """O OCR le a chave como o banco a imprime; o cadastro guarda como o humano a digitou."""
    conhecidas = ChavesDaOperacao(chaves=(TELEFONISTA,), chave_da_modelo=MODELO)
    assert conhecidas.aceita_chave("+5571999840879")
    assert conhecidas.aceita_chave("71 99984 0879") is False  # falta o DDI: outra chave


def test_titular_aceita_qualquer_titular_da_operacao() -> None:
    conhecidas = ChavesDaOperacao(
        titulares=("Elite Servicos Ltda", "Maria Silva"),
        titular_da_modelo="Maria Silva",
    )
    assert conhecidas.aceita_titular("Elite Servicos Ltda")
    assert conhecidas.aceita_titular("maria da conceicao silva")  # primeiro + ultimo, match parcial
    assert conhecidas.aceita_titular("Fulano de Tal") is False
