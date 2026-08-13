"""A marca de pausa como fronteira: dois detectores a atravessavam.

A marca (`[pausa de 8h na conversa]`) e uma HumanMessage SINTETICA que `traduzir_mensagens` insere
entre bolhas separadas por um gap grande. Nao e fala de ninguem — e fronteira estrutural — e todo
detector que caminha a janela deveria trata-la como tal. Dois nao tratavam, cada um de um jeito:

* `duracao_dita_na_janela` a lia como FALA: o `_RE_DURACAO_HORAS` casava o "8h" do proprio
  marcador, entao a IA "sabia" a duracao que o cliente nunca disse;
* `_ja_sondou_o_dia` a ATRAVESSAVA: uma sondagem de dias atras calava a sondagem no primeiro turno
  de um atendimento novo — o oposto da conduta de retomada (mesmo modo de falha do incidente
  29/07).

Sem DB, sem credito.
"""

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.nos._foco_do_turno import duracao_dita_na_janela
from barra.agente.nos._janela_do_turno import _ja_sondou_o_dia
from barra.agente.nos.prepare_context import _texto_marca_pausa


def _marca(horas: int) -> HumanMessage:
    """A marca como a janela real a carrega: id com o prefixo deterministico + texto do produtor."""
    from datetime import UTC, datetime, timedelta

    antes = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
    return HumanMessage(
        content=_texto_marca_pausa(antes, antes + timedelta(hours=horas)), id=f"pausa-{horas}"
    )


def test_marca_de_pausa_nao_conta_como_duracao_dita_pelo_cliente() -> None:
    """ "[pausa de 8h na conversa]" nao e o cliente pedindo 8 horas.

    Toda marca de 6h a 47h casava o regex de duracao (so as de "N dias" escapavam), ou seja: quase
    toda conversa RETOMADA — exatamente onde a sondagem de tempo mais importa. Com o falso
    positivo, `tempo_dele_desconhecido` virava False e o <pacote_maior_na_sua_tabela> saia sem o
    `tempo_que_ele_tem="ele ainda nao disse"`, calando a jogada de subir o tempo antes de descer o
    preco."""
    for horas in (6, 8, 12, 23, 47):
        janela = [HumanMessage(content="oi, ta acordada?", id="h1"), _marca(horas)]
        assert not duracao_dita_na_janela(janela), f"marca de {horas}h contou como duracao"


def test_duracao_dita_de_verdade_continua_contando() -> None:
    """Contraprova: a fronteira nao pode calar o detector — quem le "1h" do cliente segue lendo."""
    janela = [
        HumanMessage(content="oi", id="h1"),
        _marca(8),
        HumanMessage(content="quanto é 1h ?", id="h2"),
    ]
    assert duracao_dita_na_janela(janela)


def test_sondagem_do_dia_de_outro_atendimento_nao_cala_a_retomada() -> None:
    """Sondagem ANTES da marca e de outro momento da Conversa cliente.

    Cliente sondado dia 23, some, volta dia 29: o atendimento e novo (`dia_sondado_em` NULL), mas a
    AIMessage antiga ainda esta nas 40 da janela. Varrendo a janela inteira, o <ja_sondou_o_dia>
    proibia a sondagem no PRIMEIRO turno do atendimento novo. O caso legitimo ("ja sondei NESTE
    atendimento") segue coberto pelo OR com `dia_ja_sondado_hist`, que e por atendimento."""
    janela = [
        HumanMessage(content="oi", id="h0"),
        AIMessage(content="Seria hoje amor ?", id="a0"),
        _marca(47),
        HumanMessage(content="oi, tudo bem?", id="h1"),
    ]
    assert not _ja_sondou_o_dia(janela)


def test_sondagem_desta_parte_da_conversa_ainda_conta() -> None:
    """Contraprova: depois da marca, a sondagem volta a valer — o guard anti-repeticao continua de pe."""
    janela = [
        _marca(47),
        HumanMessage(content="oi", id="h1"),
        AIMessage(content="Seria hoje amor ?", id="a1"),
        HumanMessage(content="pode ser", id="h2"),
    ]
    assert _ja_sondou_o_dia(janela)
