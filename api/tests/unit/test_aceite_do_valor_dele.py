"""O número que o CLIENTE nomeia acima do piso fecha a venda NO NÚMERO DELE (ADR-0040).

O vendedor humano exemplar cotou 2h por 800, ouviu "faz 700" e fechou em 700. O agente respondia
600 — o piso —, porque "faz por X" era só o GATILHO da escada e o X era jogado fora: não existia
em lugar nenhum a comparação `valor_proposto >= piso`. Damos desconto que o cliente não pediu, em
toda negociação em que ele nomeia um valor.

Três peças, nesta ordem: (1) o DETECTOR — que número ele disse, e o que NÃO é número de proposta
(hora, duração, eco da tabela); (2) a DECISÃO — `[piso, mesa)` com pacote resolvido e escada não
esgotada, tudo o mais fail-closed na escada de sempre; (3) o PATAMAR, que deixou de sair só do
contador de rodadas (emenda do ADR-0038). Sem DB, sem crédito.
"""

from decimal import Decimal
from typing import Any

import pytest

from barra.agente.nos.prepare_context import (
    _valor_proposto_no_burst,
    _valores_propostos_no_burst,
)
from barra.dominio.atendimentos.service import (
    aceite_do_valor_dele,
    patamar_da_mesa_na_tabela,
    patamar_do_valor,
)

# --- (1) o DETECTOR: que número saiu da boca DELE -----------------------------------------------
# Tabela de falas com o veredito esperado, no formato do `test_fallback2_*` (test_piso_de_desconto).
# O custo dos dois erros é assimétrico e o recorte segue isso: falso-NEGATIVO devolve exatamente o
# comportamento de hoje (a escada dela), falso-POSITIVO fecha uma venda num número que ele nunca
# ofereceu. Por isso todo ramo exige token verbal COLADO no número, e a família genuinamente
# ambígua com hora/duração ("700?", "é 700?") fica FORA de propósito.

_DETECTA: list[tuple[str, set[int]]] = [
    # verbal, a família que já existia
    ("faz 700", {700}),
    ("faz por 700", {700}),
    ("me faz por 700 amor", {700}),
    ("deixa por 700", {700}),
    ("pago 700", {700}),
    ("topa 700?", {700}),
    ("aceita 700", {700}),
    ("fecho em 700", {700}),
    ("faço 700", {700}),
    ("faz 700 vai", {700}),
    ("consigo 700 hoje", {700}),
    # contexto monetário (extrair_precos_citados), que já entrava pelo mesmo caminho
    ("700 reais", {700}),
    ("R$700", {700}),
    ("por 700 eu fecho", {700}),
    ("faz por 1.200?", {1200}),
    # POSSE/LIMITE — a família que o próprio <desconto> cita nominalmente como gatilho
    ("só tenho 700", {700}),
    ("so tenho 700 amor", {700}),
    ("tenho 700", {700}),
    ("posso pagar 700", {700}),
    ("dá pra pagar 700", {700}),
    ("da pra fazer 700?", {700}),
    ("tem como 700?", {700}),
    ("no máximo 700", {700}),
    ("no maximo 700", {700}),
    ("meu limite é 700", {700}),
    ("meu limite e 700", {700}),
    # POSICIONAL — o número ANTES do verbo
    ("700 fecha?", {700}),
    ("700 e fechamos", {700}),
    ("700 tá bom?", {700}),
    ("700 ta bom pra você?", {700}),
    ("700 serve?", {700}),
    ("700 fica bom?", {700}),
    # falsos-positivos que o piso de 100 e o sufixo de tempo derrubam
    ("fecha 21", set()),
    ("faz 30 min", set()),
    ("faz 21h", set()),
    ("pago 21:30", set()),
    ("faz 2 horas?", set()),
    ("consigo as 21h", set()),
    # ambíguo com hora/duração, deixado de FORA de propósito
    ("700?", set()),
    ("é 700?", set()),
    ("vai 700?", set()),
    # nada de proposta
    ("ta salgado amor", set()),
    ("quanto é 1 hora?", set()),
    ("meu apto é o 704", set()),
]


@pytest.mark.parametrize(("fala", "esperado"), _DETECTA, ids=[f for f, _ in _DETECTA])
def test_valores_propostos_no_burst(fala: str, esperado: set[int]) -> None:
    assert _valores_propostos_no_burst([fala]) == esperado


def test_eco_da_tabela_nao_e_proposta() -> None:
    """ "400 tá salgado, faz 300?" cita dois números e só um é oferta DELE — o 400 é o que ela
    mesma cotou. Sem isso, a fala mais canônica da objeção cairia como "dois números, ambíguo"."""
    assert _valor_proposto_no_burst(["400 ta salgado demais, faz 300?"], {400}) == 300


def test_dois_valores_novos_sao_ambiguos() -> None:
    """Chutar qual dos dois é a oferta é aceitar um valor que ele não propôs."""
    assert _valor_proposto_no_burst(["faz 300 a hora, ou pago 650 as duas"], {400}) is None


def test_sem_valor_novo_devolve_none() -> None:
    assert _valor_proposto_no_burst(["ta caro amor"], {400}) is None
    assert _valor_proposto_no_burst(["400 ta caro amor"], {400}) is None


def test_valor_atravessa_bolhas_do_mesmo_burst() -> None:
    assert _valor_proposto_no_burst(["nossa", "ta caro", "faz 700?"], {800}) == 700


# --- (2) a DECISÃO ------------------------------------------------------------------------------
# O caso que originou a regra: 2h da Catarina, tabela 800, piso absoluto 600 (degrau 700).


class _FakeConn:
    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = self.linhas

        class _R:
            async def fetchall(self) -> list[dict[str, Any]]:
                return linhas

        return _R()


def _linha(preco: str, minimo: str | None = None, programa: str = "p1") -> dict[str, Any]:
    return {
        "programa_id": programa,
        "preco": Decimal(preco),
        "preco_minimo": None if minimo is None else Decimal(minimo),
    }


_CATARINA_2H = [_linha("800", "600")]


async def _decidir(
    linhas: list[dict[str, Any]] | None = None,
    *,
    valor_proposto: int | None,
    mesa: str | None = None,
    encontro: Any = "hoje",
    n: int = 0,
    duracao: Any = 2,
) -> tuple[Decimal | None, str]:
    return await aceite_do_valor_dele(
        _FakeConn(_CATARINA_2H if linhas is None else linhas),  # type: ignore[arg-type]
        "m1",
        duracao,
        valor_proposto=valor_proposto,
        valor_da_mesa=None if mesa is None else Decimal(mesa),
        encontro=encontro,
        n_contrapropostas=n,
    )


async def test_cotado_800_hoje_ele_propoe_700_fecha_em_700() -> None:
    """A linha central do mapa de estados: acima do piso (600) e abaixo da mesa (800) -> é o
    número DELE que fecha, não o 600 que a escada ofereceria."""
    assert await _decidir(valor_proposto=700, mesa="800") == (Decimal("700"), "aceito")


async def test_ele_propoe_abaixo_do_piso_volta_pra_escada() -> None:
    """550 < 600: nada de aceite. Quem responde é a escada de sempre (e, no fechamento, a guarda
    `_abaixo_do_piso`) — o comportamento não muda em nada."""
    assert await _decidir(valor_proposto=550, mesa="800") == (None, "abaixo_do_piso")


async def test_ele_propoe_acima_da_mesa_nada_muda() -> None:
    """900 sobre uma mesa de 800 não é pedido de desconto — não há o que aceitar."""
    assert await _decidir(valor_proposto=900, mesa="800") == (None, "acima_da_mesa")
    # e o próprio valor da mesa também não: repetir o número dela não é proposta nova.
    assert await _decidir(valor_proposto=800, mesa="800") == (None, "acima_da_mesa")


async def test_o_aceite_consome_a_rodada_e_hoje_so_tem_uma() -> None:
    """O anti-leilão. Sem consumir rodada, 700 -> 650 -> 620 seriam todos aceitos (todos >= 600).
    Com encontro HOJE existe UMA rodada: aceitar 700 esgota a escada, e o pedido seguinte cai na
    recusa do <desconto>."""
    assert await _decidir(valor_proposto=650, mesa="700", n=1) == (None, "esgotada")


async def test_outro_dia_tem_duas_rodadas_e_a_segunda_ainda_aceita() -> None:
    """Duas rodadas (ADR-0031): o primeiro aceite (750) consome uma, o segundo (700) a última."""
    assert await _decidir(valor_proposto=750, mesa="800", encontro="outro_dia", n=0) == (
        Decimal("750"),
        "aceito",
    )
    assert await _decidir(valor_proposto=700, mesa="750", encontro="outro_dia", n=1) == (
        Decimal("700"),
        "aceito",
    )
    assert await _decidir(valor_proposto=650, mesa="700", encontro="outro_dia", n=2) == (
        None,
        "esgotada",
    )


async def test_dia_desconhecido_aceita_uma_vez_e_so() -> None:
    """Aceitar o número DELE independe do dia — o dia decide quanto ELA desce. Mas
    `ESCADA_POR_ENCONTRO["dia_desconhecido"]` é vazia e o `estado_da_escada` devolve `sem_dia`
    para qualquer n: sem o `n == 0` explícito o contador nunca esgotaria e o leilão voltaria."""
    assert await _decidir(valor_proposto=700, mesa="800", encontro="dia_desconhecido", n=0) == (
        Decimal("700"),
        "aceito",
    )
    assert await _decidir(valor_proposto=650, mesa="700", encontro="dia_desconhecido", n=1) == (
        None,
        "esgotada",
    )


async def test_sem_numero_dele_nao_ha_nada_a_decidir() -> None:
    assert await _decidir(valor_proposto=None, mesa="800") == (None, "sem_valor")


async def test_duracao_ambigua_e_fail_closed() -> None:
    """Dois pacotes PRESENCIAIS na mesma duração (Normal 400 / Completo 800): sem saber qual ele
    leva, o piso é de qual? Mesmo fail-closed da `_contraproposta_da_tabela`."""
    ambigua = [_linha("400", "300", "p1"), _linha("800", "600", "p2")]
    assert await _decidir(ambigua, valor_proposto=700, mesa="800") == (None, "ambiguo")


async def test_sem_duracao_fechada_e_fail_closed() -> None:
    assert await _decidir(valor_proposto=700, mesa="800", duracao=None) == (None, "ambiguo")


async def test_linha_nao_descontavel_nunca_aceita_menos() -> None:
    """`preco_minimo == preco` (a vídeo chamada, o pacote curto cadastrado como mínimo): não há
    faixa `[piso, mesa)` nenhuma — qualquer número abaixo do preço fica abaixo do piso."""
    assert await _decidir([_linha("250", "250")], valor_proposto=240, mesa="250") == (
        None,
        "abaixo_do_piso",
    )


async def test_sem_valor_na_mesa_a_mesa_e_o_preco_de_tabela() -> None:
    """O turno da objeção costuma ter `valor_acordado` NULL (a extração ainda não gravou) — a
    cotação em aberto é o preço da linha única."""
    assert await _decidir(valor_proposto=700, mesa=None) == (Decimal("700"), "aceito")


async def test_piso_mais_alto_manda_com_dois_minimos_no_mesmo_preco() -> None:
    """Mesmo preço em duas linhas com mínimos diferentes não é ambiguidade de VALOR, mas o piso
    válido é o MAIS ALTO — o único válido para qualquer uma delas (mesma regra da escada)."""
    duas = [_linha("800", "600", "p1"), _linha("800", "700", "p2")]
    assert await _decidir(duas, valor_proposto=650, mesa="800") == (None, "abaixo_do_piso")
    assert await _decidir(duas, valor_proposto=750, mesa="800") == (Decimal("750"), "aceito")


# --- (3) o PATAMAR (emenda do ADR-0038) ---------------------------------------------------------


def test_patamar_do_valor_e_o_mais_raso_que_cabe() -> None:
    """Discreto e monotônico, nunca um fator multiplicativo. Em 800/600 o degrau é 700 e o piso
    600 — e é por isso que aceitar 700 põe a mesa no DEGRAU: o extra de fetiche desce com ela,
    mas não até o piso, que ela nunca ofereceu."""
    p, m = Decimal("800"), Decimal("600")
    assert patamar_do_valor(p, m, Decimal("800")) == "cheio"
    assert patamar_do_valor(p, m, Decimal("750")) == "degrau"
    assert patamar_do_valor(p, m, Decimal("700")) == "degrau"
    assert patamar_do_valor(p, m, Decimal("650")) == "piso"
    assert patamar_do_valor(p, m, Decimal("600")) == "piso"


def test_patamar_do_valor_abaixo_do_piso_para_no_piso() -> None:
    """Não deveria existir (a guarda `_abaixo_do_piso` escala), mas o tipo é fechado em três."""
    assert patamar_do_valor(Decimal("800"), Decimal("600"), Decimal("500")) == "piso"


def test_patamar_do_valor_sem_minimo_usa_so_o_percentual() -> None:
    # 400: degrau 350, piso 300.
    assert patamar_do_valor(Decimal("400"), None, Decimal("400")) == "cheio"
    assert patamar_do_valor(Decimal("400"), None, Decimal("350")) == "degrau"
    assert patamar_do_valor(Decimal("400"), None, Decimal("300")) == "piso"


async def test_patamar_da_mesa_na_tabela_le_o_valor_e_nao_o_contador() -> None:
    conn = _FakeConn(_CATARINA_2H)
    assert await patamar_da_mesa_na_tabela(conn, "m1", 2, Decimal("700")) == "degrau"  # type: ignore[arg-type]
    assert await patamar_da_mesa_na_tabela(conn, "m1", 2, Decimal("600")) == "piso"  # type: ignore[arg-type]


async def test_patamar_da_mesa_na_tabela_e_fail_closed() -> None:
    """Sem valor na mesa ou com a duração ambígua não há resposta — o chamador fica com o
    contador de rodadas, e nada regride."""
    conn = _FakeConn(_CATARINA_2H)
    assert await patamar_da_mesa_na_tabela(conn, "m1", 2, None) is None  # type: ignore[arg-type]
    ambigua = _FakeConn([_linha("400", "300", "p1"), _linha("800", "600", "p2")])
    assert await patamar_da_mesa_na_tabela(ambigua, "m1", 1, Decimal("700")) is None  # type: ignore[arg-type]
