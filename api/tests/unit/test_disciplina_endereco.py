"""A2 do endereço: detectar a bolha em que a IA ENTREGA o ponto de encontro (#41, 24/07).

A IA disse "Vem aqui então / Já sabe onde é" às 10:03 e só passou o endereço às 10:10. O detector
alimenta `endereco_enviado_em`, a memória durável que a janela de 20 msgs não consegue ser.
"""

from barra.agente._disciplina import contem_endereco_de_encontro, tokens_do_endereco

# Cadastro real da Tatiane (nome_local NULL em prod) e o da Lucia (mesmo prédio, com nome).
_TOKENS_TATIANE = tokens_do_endereco(
    "R. Santos Dumont, 291 - Cambuí, Campinas - SP, 13024-020", None, "Cambuí, Campinas"
)
_TOKENS_LUCIA = tokens_do_endereco(
    "R. Santos Dumont, 291 - Cambuí, Campinas - SP, 13024-020",
    "Vitória Hotel Residence Newport",
    "Cambuí, Campinas",
)


def test_bolha_que_entrega_a_rua_e_pega() -> None:
    # A bolha das 10:10:55 do #41 — a primeira vez que o endereço saiu de verdade.
    assert contem_endereco_de_encontro("To no hotel na rua Santos Dumont", _TOKENS_TATIANE)


def test_bolha_com_o_nome_do_hotel_e_pega() -> None:
    assert contem_endereco_de_encontro("É o Vitória Newport amor", _TOKENS_LUCIA)


def test_dizer_so_a_regiao_nao_conta_como_endereco() -> None:
    # Degrau ANTERIOR do <tipos_de_encontro>: no 1º contato só a região. "Cambuí" está dentro do
    # endereço formatado — sem descontar a região, isto contaria como endereço entregue.
    assert not contem_endereco_de_encontro("Isso amor, no Cambuí", _TOKENS_TATIANE)
    assert not contem_endereco_de_encontro("Fico em Campinas sim", _TOKENS_TATIANE)


def test_falar_de_hotel_generico_nao_conta() -> None:
    # "hotel"/"rua" aparecem em qualquer endereço: não provam que ela entregou o dela.
    assert not contem_endereco_de_encontro("To no hotel amor, bem discreto", _TOKENS_TATIANE)
    assert not contem_endereco_de_encontro("É aqui na rua de trás", _TOKENS_TATIANE)


def test_a_bolha_do_bug_nao_conta_como_endereco_enviado() -> None:
    # "Já sabe onde é" não passa endereço nenhum — é exatamente o que a flag existe pra desmentir.
    assert not contem_endereco_de_encontro("Vem aqui então", _TOKENS_TATIANE)
    assert not contem_endereco_de_encontro("Já sabe onde é", _TOKENS_TATIANE)


def test_numero_e_uf_nao_viram_evidencia() -> None:
    # "291" e "SP" casariam com quase qualquer texto.
    assert not contem_endereco_de_encontro("São 291 reais com o extra", _TOKENS_TATIANE)
    assert "291" not in _TOKENS_TATIANE
    assert "sp" not in _TOKENS_TATIANE


def test_sem_cadastro_de_endereco_o_detector_fica_desligado() -> None:
    assert not contem_endereco_de_encontro("To no hotel na rua Santos Dumont", set())
    assert tokens_do_endereco(None, None, "Cambuí, Campinas") == set()
