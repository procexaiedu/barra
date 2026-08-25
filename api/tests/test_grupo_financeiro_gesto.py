"""O ✅ e o ❌ do telefonista sobre a Ficha de agendamento (spec 0006, tickets 08 e 20).

Offline: funcao pura, sem banco, sem chave, sem rede — a mesma escolha do teste do razao, e pelo
mesmo motivo (a spec pede tabela de casos lado a lado para a regra que decide dinheiro).

O que se prova aqui e a REGRA do gesto, que nao depende da grafia do evento da EvoGo (essa ainda
nao foi capturada — ver `tests/test_webhook_gesto_na_borda.py` e
`.scratch/agente-financeiro-v2/PAYLOAD-EVOGO.md`). Tres invariantes sao de quebrar calado:

  * **o segundo gesto nao duplica a venda** (ADR-0046 §5). O ✅ e a fala da modelo sao a mesma
    noticia por duas bocas; se as duas criarem linha, o faturamento infla e o extrato continua
    fechando — ninguem procura;
  * **o ❌ nao apaga dinheiro em silencio** e o ✅ nao cria dinheiro sobre um "nao rolou";
  * **tirar a reacao desfaz o que ELA causou**, nunca o que a outra porta causou.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from barra.dominio.grupo_financeiro.dedup import chave_de_conteudo
from barra.dominio.grupo_financeiro.gesto import (
    ESTADOS_COBRAVEIS,
    PORTA_DA_REACAO,
    PORTA_DO_PAGAMENTO,
    AlvoDoGesto,
    DecisaoDoGesto,
    EstadoDaFicha,
    GestoNaFicha,
    chave_da_venda_da_ficha,
    decidir_gesto,
    ler_sinal,
)

CHECK = "✅"
CANCELA = "❌"
REMOCAO = ""
TELEFONISTA = "5521999990000@s.whatsapp.net"
MODELO = "5521988887777@s.whatsapp.net"


def _alvo(estado: EstadoDaFicha = "aberta", **kwargs: Any) -> AlvoDoGesto:
    return AlvoDoGesto(estado=estado, **kwargs)


# --- vocabulario ------------------------------------------------------------------------------


@pytest.mark.parametrize("emoji", ["✅", "✔️", "☑️", "✔"])
def test_o_vezinho_em_qualquer_grafia_e_check(emoji: str) -> None:
    """ "Dar o vezinho" chega com ou sem seletor de variacao, conforme o teclado."""
    assert ler_sinal(emoji) == "check"


@pytest.mark.parametrize("emoji", ["❌", "❎", "✖️", "🚫"])
def test_o_xis_em_qualquer_grafia_e_cancelamento(emoji: str) -> None:
    assert ler_sinal(emoji) == "cancela"


@pytest.mark.parametrize("emoji", ["👍", "❤️", "🔥", "😂", "👏"])
def test_emoji_fora_do_vocabulario_nao_e_sinal_nenhum(emoji: str) -> None:
    """O grupo reage com coracao e palma o tempo todo. Palpitar aqui seria criar venda por engano."""
    assert ler_sinal(emoji) is None


@pytest.mark.parametrize("emoji", ["👍", "❤️", "🔥"])
def test_emoji_fora_do_vocabulario_nao_mexe_em_estado_nenhum(emoji: str) -> None:
    decisao = decidir_gesto(GestoNaFicha(emoji), _alvo("aberta"))

    assert decisao == DecisaoDoGesto("ignorar", "emoji_fora_do_vocabulario")
    assert decisao.estado_resultante is None
    assert decisao.evento is None


def test_reacao_em_mensagem_que_nao_e_ficha_sai_ignorada() -> None:
    """O caso COMUM: reacao no recibo, na foto do comprovante, na conversa."""
    assert decidir_gesto(GestoNaFicha(CHECK), None) == DecisaoDoGesto("ignorar", "sem_ficha_alvo")


# --- o ✅ promove (ticket 20) ------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["aberta", "confirmada"])
def test_check_sem_a_modelo_ter_falado_registra_a_venda(estado: EstadoDaFicha) -> None:
    decisao = decidir_gesto(GestoNaFicha(CHECK, TELEFONISTA), _alvo(estado))

    assert decisao.efeito == "promover_a_venda"
    assert decisao.estado_resultante == "realizada"
    assert decisao.pergunta is None, "promocao e calada: a forma vai na cobranca da manha"


def test_o_check_nao_leva_a_ficha_para_confirmada() -> None:
    """ADR-0046 §5: o ✅ vem DEPOIS do pagamento. `confirmada` nao e mais produzida por gesto."""
    decisao = decidir_gesto(GestoNaFicha(CHECK), _alvo("aberta"))

    assert decisao.estado_resultante == "realizada"


def test_o_evento_da_promocao_carimba_quem_promoveu_e_de_onde_veio() -> None:
    """Sem o carimbo nao da para saber se tirar o ✅ pode desfazer a venda."""
    decisao = decidir_gesto(GestoNaFicha(CHECK), _alvo("aberta"))

    assert decisao.evento is not None
    assert decisao.evento.tipo == "realizacao"
    assert decisao.evento.campo == PORTA_DA_REACAO
    assert (decisao.evento.valor_anterior, decisao.evento.valor_novo) == ("aberta", "realizada")


def test_modelo_falou_primeiro_e_o_check_depois_nao_duplica() -> None:
    """ "recebi, foi dinheiro" e depois o ✅ -> UMA venda."""
    decisao = decidir_gesto(
        GestoNaFicha(CHECK, TELEFONISTA),
        _alvo("realizada", venda_id=uuid4(), promovida_por=PORTA_DO_PAGAMENTO),
    )

    assert decisao == DecisaoDoGesto("ignorar", "venda_ja_registrada")


def test_venda_ja_existente_com_ficha_atrasada_so_alinha_o_estado() -> None:
    """A linha ja existe (outra porta); o ✅ no maximo poe a ficha em dia — nunca cria a segunda."""
    decisao = decidir_gesto(
        GestoNaFicha(CHECK), _alvo("aberta", venda_id=uuid4(), promovida_por=PORTA_DO_PAGAMENTO)
    )

    assert decisao.efeito == "so_marcar_realizada"
    assert decisao.estado_resultante == "realizada"


def test_check_sobre_ficha_cancelada_pergunta_em_vez_de_ressuscitar() -> None:
    decisao = decidir_gesto(
        GestoNaFicha(CHECK), _alvo("cancelada", cliente="Igor", valor=Decimal("700.00"))
    )

    assert decisao.efeito == "perguntar"
    assert decisao.estado_resultante is None
    assert decisao.pergunta is not None
    assert "Igor" in decisao.pergunta and "700,00" in decisao.pergunta


# --- o ❌ cancela (ticket 08) ------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["aberta", "confirmada"])
def test_xis_cancela_a_ficha(estado: EstadoDaFicha) -> None:
    decisao = decidir_gesto(GestoNaFicha(CANCELA, TELEFONISTA), _alvo(estado))

    assert decisao.efeito == "cancelar"
    assert decisao.estado_resultante == "cancelada"
    assert decisao.evento is not None
    assert decisao.evento.tipo == "cancelamento"
    assert decisao.evento.valor_anterior == estado, "sem o de->para nao da para reabrir depois"


def test_ficha_cancelada_para_de_ser_cobrada() -> None:
    """O outro lado do ❌: a rotina da manha so cobra `aberta`/`confirmada`."""
    decisao = decidir_gesto(GestoNaFicha(CANCELA), _alvo("aberta"))

    assert decisao.estado_resultante not in ESTADOS_COBRAVEIS
    assert "aberta" in ESTADOS_COBRAVEIS and "confirmada" in ESTADOS_COBRAVEIS


def test_xis_depois_da_venda_existir_vira_pergunta_e_nao_apaga_dinheiro() -> None:
    decisao = decidir_gesto(
        GestoNaFicha(CANCELA),
        _alvo("realizada", venda_id=uuid4(), cliente="Igor", valor=Decimal("700.00")),
    )

    assert decisao.efeito == "perguntar"
    assert decisao.estado_resultante is None
    assert decisao.evento is None
    assert decisao.pergunta is not None and "Igor" in decisao.pergunta


def test_xis_repetido_na_ficha_ja_cancelada_nao_faz_nada() -> None:
    assert decidir_gesto(GestoNaFicha(CANCELA), _alvo("cancelada")) == DecisaoDoGesto(
        "ignorar", "gesto_sem_efeito"
    )


# --- tirar a reacao ---------------------------------------------------------------------------


def test_tirar_o_xis_devolve_a_ficha_ao_estado_anterior() -> None:
    decisao = decidir_gesto(
        GestoNaFicha(REMOCAO, TELEFONISTA),
        _alvo(
            "cancelada",
            estado_anterior="confirmada",
            autor_do_gesto_vigente=TELEFONISTA,
        ),
    )

    assert decisao.efeito == "reabrir"
    assert decisao.estado_resultante == "confirmada"
    assert decisao.evento is not None
    assert (decisao.evento.tipo, decisao.evento.campo) == ("alteracao", "estado")


def test_tirar_o_xis_sem_rastro_do_anterior_volta_para_aberta() -> None:
    decisao = decidir_gesto(GestoNaFicha(REMOCAO), _alvo("cancelada"))

    assert decisao.estado_resultante == "aberta"


def test_tirar_o_check_desfaz_a_venda_que_ele_mesmo_criou() -> None:
    decisao = decidir_gesto(
        GestoNaFicha(REMOCAO, TELEFONISTA),
        _alvo(
            "realizada",
            venda_id=uuid4(),
            promovida_por=PORTA_DA_REACAO,
            estado_anterior="aberta",
            autor_do_gesto_vigente=TELEFONISTA,
        ),
    )

    assert decisao.efeito == "desfazer_promocao"
    assert decisao.estado_resultante == "aberta"


def test_tirar_o_check_nao_desfaz_a_venda_que_a_modelo_criou() -> None:
    """Ela disse que recebeu. Tirar o ✅ desfaz o ✅, nao a palavra de quem recebeu o dinheiro."""
    decisao = decidir_gesto(
        GestoNaFicha(REMOCAO, TELEFONISTA),
        _alvo(
            "realizada",
            venda_id=uuid4(),
            promovida_por=PORTA_DO_PAGAMENTO,
            autor_do_gesto_vigente=TELEFONISTA,
        ),
    )

    assert decisao == DecisaoDoGesto("ignorar", "venda_de_outra_porta")


def test_reacao_tirada_por_outra_pessoa_nao_desfaz_o_gesto_de_quem_a_pos() -> None:
    decisao = decidir_gesto(
        GestoNaFicha(REMOCAO, MODELO),
        _alvo("cancelada", autor_do_gesto_vigente=TELEFONISTA),
    )

    assert decisao == DecisaoDoGesto("ignorar", "remocao_de_outro_autor")


def test_tirar_reacao_de_ficha_que_nao_mudou_de_estado_nao_faz_nada() -> None:
    assert decidir_gesto(GestoNaFicha(REMOCAO), _alvo("aberta")) == DecisaoDoGesto(
        "ignorar", "gesto_sem_efeito"
    )


# --- a idempotencia das duas portas -----------------------------------------------------------
#
# "Dois casos novos que so a segunda porta cria: ✅ antes da fala da modelo, e fala antes do ✅.
# Nos dois a venda tem que existir UMA vez ao final. E teste de idempotencia, e e onde o bug vai
# estar." (spec 0006, Testing Decisions). O livro-caixa abaixo e o indice unico parcial
# `vendas_registradas_chave_conteudo_viva_uniq` em memoria.

DATA_DA_FICHA = date(2026, 8, 20)
VALOR = Decimal("700.00")
MODELO_ID = uuid4()
CLIENTE = "Igor"


def _chave_da_ficha() -> str:
    return chave_da_venda_da_ficha(
        data_da_ficha=DATA_DA_FICHA, valor=VALOR, modelo_id=MODELO_ID, cliente=CLIENTE
    )


class _Livro:
    """Um livro-caixa minimo: a chave de conteudo e o que impede a segunda linha."""

    def __init__(self) -> None:
        self.linhas: dict[str, str] = {}

    def promover(self, porta: str) -> None:
        self.linhas.setdefault(_chave_da_ficha(), porta)


def _porta_da_modelo(livro: _Livro) -> AlvoDoGesto:
    """A outra porta (ticket 07), como ela tem que se comportar para as duas fecharem."""
    livro.promover(PORTA_DO_PAGAMENTO)
    return AlvoDoGesto(estado="realizada", venda_id=uuid4(), promovida_por=PORTA_DO_PAGAMENTO)


def _porta_do_check(livro: _Livro, alvo: AlvoDoGesto) -> AlvoDoGesto:
    decisao = decidir_gesto(GestoNaFicha(CHECK, TELEFONISTA), alvo)
    if decisao.efeito == "promover_a_venda":
        livro.promover(PORTA_DA_REACAO)
        return AlvoDoGesto(estado="realizada", venda_id=uuid4(), promovida_por=PORTA_DA_REACAO)
    return alvo


def test_o_check_depois_da_fala_da_modelo_deixa_uma_venda_so() -> None:
    livro = _Livro()
    alvo = _porta_da_modelo(livro)

    _porta_do_check(livro, alvo)

    assert len(livro.linhas) == 1
    assert livro.linhas[_chave_da_ficha()] == PORTA_DO_PAGAMENTO


def test_a_fala_da_modelo_depois_do_check_deixa_uma_venda_so() -> None:
    livro = _Livro()
    _porta_do_check(livro, _alvo("aberta"))

    _porta_da_modelo(livro)

    assert len(livro.linhas) == 1
    assert livro.linhas[_chave_da_ficha()] == PORTA_DA_REACAO


def test_a_chave_da_venda_e_datada_pela_ficha_e_nao_pelo_dia_do_gesto() -> None:
    """O ✅ vem no dia seguinte o tempo todo. Datar pelo gesto faria as duas portas divergirem —
    duas linhas do mesmo atendimento, com o indice unico achando tudo em ordem."""
    dia_do_gesto = date(2026, 8, 21)

    pelo_gesto = chave_de_conteudo(
        data=dia_do_gesto, valor=VALOR, modelo_id=MODELO_ID, cliente=CLIENTE
    )

    assert _chave_da_ficha() == chave_de_conteudo(
        data=DATA_DA_FICHA, valor=VALOR, modelo_id=MODELO_ID, cliente=CLIENTE
    )
    assert _chave_da_ficha() != pelo_gesto
