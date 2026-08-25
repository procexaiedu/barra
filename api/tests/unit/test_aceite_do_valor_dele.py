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

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import (
    _INSISTENCIA_ABAIXO_DO_PISO,
    _MARCA_INSISTENCIA_PISO,
    _horas_da_escada_com_burst,
    _piso_ja_recusado,
    _resolver_variaveis,
    _ressalva_de_servico_no_burst,
    _valor_dele_vigente,
    _valor_proposto_no_burst,
    _valores_propostos_no_burst,
)
from barra.agente.persona import _env, render_contexto_dinamico
from barra.dominio.atendimentos.service import (
    aceite_do_valor_dele,
    patamar_da_mesa_na_tabela,
    patamar_do_valor,
)
from barra.dominio.conversas.modelos import DirecaoMensagem

# Relógio injetado (BRT-3): sem âncora de tempo a escada não sabe se o encontro é hoje.
_AGORA = datetime(2026, 8, 13, 17, 30, tzinfo=UTC)
_HOJE = date(2026, 8, 13)

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
    # MODAL + INFINITIVO — a fala canônica da objeção, que nenhuma das três famílias via (13/08):
    # o verbo de proposta vem no infinitivo, atrás de um modal, e o número pode não estar colado
    # nele. Sem ela, "consegue fazer 360 ?" devolvia set() e a IA ofertava o PISO num número que ele
    # próprio já tinha posto ACIMA dele.
    ("nossa ta um pouco caro, consegue fazer 360?", {360}),
    ("consegue baixar mais, tipo uns 320?", {320}),
    ("consegue fechar em 350?", {350}),
    ("consegue me fazer 340?", {340}),
    ("tem como baixar pra 280?", {280}),
    ("poderia deixar por 250?", {250}),
    ("pode fazer 300 amor", {300}),
    # ...e o que o modal + o corte de 3-4 dígitos + o sufixo de tempo mantêm de FORA: hora, dia do
    # mês, quantidade de gente e o infinitivo sem modal nenhum.
    ("consegue fazer 22h?", set()),
    ("consegue fazer dia 15?", set()),
    ("consegue fazer amanha as 21h?", set()),
    ("vou fazer 350 flexoes hoje", set()),
    ("consegue vir 22h?", set()),
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
    condicionado: bool = False,
) -> tuple[Decimal | None, str]:
    return await aceite_do_valor_dele(
        _FakeConn(_CATARINA_2H if linhas is None else linhas),  # type: ignore[arg-type]
        "m1",
        duracao,
        valor_proposto=valor_proposto,
        valor_da_mesa=None if mesa is None else Decimal(mesa),
        encontro=encontro,
        n_contrapropostas=n,
        condicionado=condicionado,
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


# --- (4) a RESSALVA de serviço pendurada no número dele -----------------------------------------
# Loop-massa r3, achado 10 da refutação de extração (a metade que faltava do fix 11). O cliente do
# `negociacao_dura_b` t4 não propôs "300": propôs "300 COM 2 finalizações". O `<valor_dele_serve>`
# manda aceitar o número DELE na hora e sem ressalva — e a condição, que ninguém conferiu contra
# `<programas>`/`<fetiches>`, entrava no belief junto com o preço, com autoridade de registro do
# sistema. A primeira metade do fix (`perguntas_do_burst`) só devolveu a condição ao CONTEXTO; o
# caminho determinístico continuava cego a ela.

_RESSALVA: list[tuple[str, bool]] = [
    # o corpus: a condição vem depois do "?" e o número dela é a ressalva
    ("Vc não consegue fazer 1 hr por 300$? Com 2 finalizações", True),
    ("faz 300 com 2 gozadas?", True),
    ("300 com finalização na boca?", True),
    # famílias do cardápio (mesma tabela do <servico_em_pauta>, site único) — o alcance é
    # exatamente o dela: "pra eu e minha esposa" casa `acompanhante_mulher`, "pra mim e minha
    # esposa" não. Alargar aqui e não lá faria o aceite e o foco discordarem sobre a mesma fala.
    ("da pra fazer 300 com beijo na boca?", True),
    ("300 e vc faz anal?", True),
    ("faz 300 pra eu e minha esposa?", True),
    # número limpo: nada muda, o ADR-0040 segue valendo
    ("faz 300?", False),
    ("400 ta salgado demais, faz 300?", False),
    ("só tenho 300 amor", False),
    ("300 fecha?", False),
    ("faz 300 com pix?", False),
    ("300 com desconto pra hoje?", False),
]


@pytest.mark.parametrize(("fala", "esperado"), _RESSALVA, ids=[f for f, _ in _RESSALVA])
def test_ressalva_de_servico_no_burst(fala: str, esperado: bool) -> None:
    assert _ressalva_de_servico_no_burst([fala]) is esperado


def test_ressalva_atravessa_bolhas_do_mesmo_burst() -> None:
    """Mesma fronteira do detector do valor: o burst inteiro, não a última bolha — ele manda o
    número numa e a condição na seguinte."""
    assert _ressalva_de_servico_no_burst(["faz 300?", "com 2 finalizações"]) is True


async def test_numero_com_ressalva_de_servico_nao_fecha_a_venda() -> None:
    """O mesmo 700 que fecha sozinho não fecha com um serviço pendurado nele: sem conferir a
    condição contra o cardápio, o aceite registraria uma promessa que ninguém validou. Fail-closed
    na escada de sempre, como todo o resto da cascata."""
    assert await _decidir(valor_proposto=700, mesa="800") == (Decimal("700"), "aceito")
    assert await _decidir(valor_proposto=700, mesa="800", condicionado=True) == (
        None,
        "condicionado",
    )


async def test_ressalva_sem_numero_dele_continua_sendo_sem_valor() -> None:
    """A ordem da cascata importa para a métrica: sem número não há proposta a condicionar, e
    `sem_valor` continua medindo o detector de fala."""
    assert await _decidir(valor_proposto=None, mesa="800", condicionado=True) == (None, "sem_valor")


# --- (4) a LINHA da escada com belief envenenado (campanha 13/08, eb04:187007389155571) ----------
# A extração gravou `duracao_horas: 12` + `valor_acordado: 2500` a partir de uma PERGUNTA do
# cliente ("qual período mais longo? e quanto?"). Quando ele contrapropôs "Faz por 600?" sobre a
# linha de 2h/700, o gate lia a linha do belief: piso dos 2500 (1875) -> "abaixo_do_piso" -> a
# venda que o ADR-0040 manda fechar (525 <= 600 < 700) morreu em fala enlatada. O valor proposto
# NESTE burst aponta a linha em negociação AGORA (`_horas_da_linha_contraproposta`, o site único):
# quando ela resolve e diverge, vence o burst; ambígua, mantém o belief (fail-closed inalterado).

_TABELA_EB04: dict[float, list[Decimal]] = {2.0: [Decimal("700")], 12.0: [Decimal("2500")]}


def test_linha_do_burst_vence_o_belief_envenenado() -> None:
    """O caso real: belief diz 12h, "Faz por 600?" resolve a linha de 2h/700 — vence o burst."""
    assert _horas_da_escada_com_burst(Decimal("12"), ["Faz por 600?"], _TABELA_EB04) == 2.0


def test_burst_ambiguo_mantem_o_belief() -> None:
    """Fail-closed preservado: sem valor novo, acima de toda a tabela ou com dois valores novos, a
    resolução do burst é None e a linha do belief fica de pé — comportamento de antes."""
    assert _horas_da_escada_com_burst(Decimal("12"), ["ta caro amor"], _TABELA_EB04) == Decimal(
        "12"
    )
    assert _horas_da_escada_com_burst(Decimal("12"), ["pago 3000"], _TABELA_EB04) == Decimal("12")
    assert _horas_da_escada_com_burst(
        Decimal("12"), ["faz 600, ou pago 800"], _TABELA_EB04
    ) == Decimal("12")


def test_burst_na_mesma_linha_do_belief_nao_muda_nada() -> None:
    """Divergência é a condição: proposto que aponta a MESMA linha preserva o valor (e o tipo)
    do belief."""
    assert _horas_da_escada_com_burst(Decimal("2"), ["Faz por 600?"], _TABELA_EB04) == Decimal("2")


def test_sem_belief_ou_sem_burst_e_passthrough() -> None:
    """O ramo do belief vazio continua sendo dos fallbacks 1/2 do call site — o helper não opina."""
    assert _horas_da_escada_com_burst(None, ["Faz por 600?"], _TABELA_EB04) is None
    assert _horas_da_escada_com_burst(Decimal("12"), [], _TABELA_EB04) == Decimal("12")


async def test_eb04_com_a_linha_do_burst_o_600_fecha_no_numero_dele() -> None:
    """A decisão ponta a ponta com os números do caso: linha 2h/700 (piso 525 pelo teto de 25%),
    mesa ainda envenenada (2500) — o 600 fecha no número DELE; com a linha do belief (12h/2500,
    piso 1875) o mesmo 600 morria "abaixo_do_piso". A linha é a causa-raiz, não a mesa."""
    assert await _decidir([_linha("700")], valor_proposto=600, mesa="2500", duracao=2) == (
        Decimal("600"),
        "aceito",
    )
    assert await _decidir([_linha("2500")], valor_proposto=600, mesa="2500", duracao=12) == (
        None,
        "abaixo_do_piso",
    )


# --- (5) o schema da extração: pergunta não move a mesa (campanha 13/08) -------------------------
# O envenenamento do (4) entra pelas DESCRIÇÕES da tool `registrar_extracao` — o extrator fechava
# `valor_acordado`/`duracao_horas` a partir de pergunta. E o eb02:266343857258751: desistência por
# item fora do cardápio ("sem anal não rola") rotulada `motivo_perda_candidato="preco"`, que
# envenena o reengajamento. O enum é fechado no banco (barravips.motivo_perda_enum, sem valor de
# serviço/cardápio): a instrução manda pro rótulo neutro 'outro'. Pina o schema que o LLM VÊ.


def _descricao_da_tool(campo: str) -> str:
    from barra.agente.ferramentas.extracao import registrar_extracao

    schema = registrar_extracao.args_schema
    assert schema is not None
    descricao = schema.model_fields[campo].description
    assert descricao is not None
    return descricao


def test_valor_acordado_nega_a_pergunta_como_aceite() -> None:
    desc = _descricao_da_tool("valor_acordado")

    assert "PERGUNTA não fecha mesa nenhuma" in desc
    assert "quanto é o de 12h" in desc
    assert "aceite EXPLÍCITO" in desc


def test_duracao_horas_nega_a_pergunta_como_pedido() -> None:
    desc = _descricao_da_tool("duracao_horas")

    assert "NÃO é pedi-la" in desc
    assert "quanto é o de 12h" in desc
    assert "Só grave quando ele PEDE aquela duração" in desc


def test_motivo_perda_distingue_cardapio_de_preco() -> None:
    """O enum não tem rótulo de serviço/cardápio (limitação relatada): a instrução proíbe 'preco'
    para perda de cardápio e aponta o neutro 'outro'."""
    desc = _descricao_da_tool("motivo_perda_candidato")

    assert "NÃO rotule 'preco' quando o que travou foi o SERVIÇO" in desc
    assert "sem anal não rola" in desc
    assert "use 'outro'" in desc


def test_o_enum_do_motivo_segue_o_do_banco_sem_valor_de_cardapio() -> None:
    """Pina a limitação: o dia em que o enum ganhar um rótulo de cardápio (migration no banco +
    Literal na tool), este teste cai e a descrição acima deve migrar do 'outro' pro rótulo novo."""
    from typing import get_args

    from barra.agente.ferramentas.extracao import ExtracaoPayload

    tipo = ExtracaoPayload.model_fields["motivo_perda_candidato"].annotation
    rotulos = {a for a in get_args(get_args(tipo)[0])}

    assert rotulos == {"preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"}


# --- (6) o número dele SOBREVIVE ao turno (campanha c7, `desconto_valor_dele_serve`) -------------
# O detector do ADR-0040 lia só o burst DESTE turno. O cliente disse "360" num turno e, no
# seguinte, insistiu sem repetir o número ("consegue mesmo assim ?"): `aceite_do_valor_dele`
# devolvia `sem_valor`, o `<valor_dele_serve>` não renderizava e a IA caía na escada — ofertando o
# PISO (300) num número que ele mesmo já tinha nomeado acima dele. Nas duas rodadas medidas o bloco
# nunca apareceu no turno decisivo.
#
# O fallback lê as bolhas DELE da conversa CONTÍGUA (mesma régua de pausa do
# `_falas_dela_na_conversa_contigua`) e tem retirada própria. O ADR-0040 fica intacto: a linha do
# burst ATUAL continua vencendo, e o histórico só responde quando o burst não traz número nenhum.

_TABELA_1H = {400}


def _bolha(direcao: DirecaoMensagem, texto: str, *, minutos: int = 0) -> dict[str, Any]:
    return {
        "id": f"m{minutos}",
        "direcao": direcao,
        "conteudo": texto,
        "tipo": "texto",
        "created_at": _AGORA + timedelta(minutes=minutos),
    }


def _conversa(*bolhas: tuple[str, str]) -> list[dict[str, Any]]:
    """Janela crua ("ele"/"ela", texto), um minuto entre bolhas — bem dentro da contiguidade."""
    return [
        _bolha(
            DirecaoMensagem.cliente if quem == "ele" else DirecaoMensagem.ia,
            texto,
            minutos=i,
        )
        for i, (quem, texto) in enumerate(bolhas)
    ]


def test_o_numero_dele_atravessa_o_turno_da_insistencia_sem_numero() -> None:
    """O caso medido: ele nomeia 360, ela defende o valor, ele insiste sem repetir o número."""
    linhas = _conversa(
        ("ele", "faz 360?"),
        ("ela", "Poxa amor, esse é o meu valor rs"),
        ("ele", "consegue mesmo assim ?"),
    )

    assert _valor_dele_vigente(["consegue mesmo assim ?"], linhas, _TABELA_1H) == 360


def test_o_burst_atual_vence_o_historico() -> None:
    """ADR-0040 intacto: com número no burst, é ele que manda — o histórico não opina."""
    linhas = _conversa(("ele", "faz 360?"), ("ela", "esse é o meu valor amor"), ("ele", "faz 320?"))

    assert _valor_dele_vigente(["faz 320?"], linhas, _TABELA_1H) == 320


def test_burst_ambiguo_nao_cai_no_historico() -> None:
    """Dois valores novos no burst devolvem None por desenho — cair no histórico seria escolher
    por ele exatamente onde o ADR manda não escolher."""
    linhas = _conversa(("ele", "faz 360?"), ("ele", "faz 340 a hora, ou pago 700 as duas"))

    assert _valor_dele_vigente(["faz 340 a hora, ou pago 700 as duas"], linhas, _TABELA_1H) is None


def test_o_ultimo_valor_dele_e_o_que_vale() -> None:
    """Retirada por valor novo: ele baixou o próprio pedido, e é o pedido de agora que está na
    mesa."""
    linhas = _conversa(
        ("ele", "faz 360?"), ("ela", "esse é o meu valor amor"), ("ele", "só tenho 320")
    )

    assert _valor_dele_vigente([], linhas, _TABELA_1H) == 320


def test_ela_dizendo_o_numero_dele_de_volta_retira_o_pedido() -> None:
    """Ela já disse sim (ou já ofereceu melhor): a pauta passou a ser o número DELA, e mandar
    aceitar o dele de novo repetiria a venda — ou, no caso do menor, SUBIRIA o preço."""
    aceitou = _conversa(("ele", "faz 360?"), ("ela", "Fechado 360 amor, consigo às 21h ?"))
    ofertou_menos = _conversa(("ele", "faz 360?"), ("ela", "Consigo 350 se fechar agora 😊"))

    assert _valor_dele_vigente([], aceitou, _TABELA_1H) is None
    assert _valor_dele_vigente([], ofertou_menos, _TABELA_1H) is None


def test_a_defesa_dela_nao_retira_o_pedido_dele() -> None:
    """As duas falas que o turno decisivo tem por construção: ela repete o preço de TABELA (acima
    do dele) ou recusa citando o número dele. Nenhuma das duas é oferta — retirar aqui apagaria o
    bloco justamente no turno que este fallback existe para salvar."""
    tabela = _conversa(("ele", "faz 360?"), ("ela", "É 400 amor"), ("ele", "vai ?"))
    recusa = _conversa(("ele", "faz 360?"), ("ela", "Poxa amor, não consigo 360"), ("ele", "vai ?"))

    assert _valor_dele_vigente(["vai ?"], tabela, _TABELA_1H) == 360
    assert _valor_dele_vigente(["vai ?"], recusa, _TABELA_1H) == 360


def test_pausa_de_seis_horas_apaga_o_numero_dele() -> None:
    """Mesma régua da marca de pausa (`_GAP_PAUSA`): o que ele ofereceu antes de sumir um dia não
    está mais na mesa — é o incidente de 29/07 visto do lado do preço."""
    linhas = [
        _bolha(DirecaoMensagem.cliente, "faz 360?", minutos=0),
        _bolha(DirecaoMensagem.cliente, "e aí, consegue ?", minutos=7 * 60),
    ]

    assert _valor_dele_vigente(["e aí, consegue ?"], linhas, _TABELA_1H) is None


def test_numero_com_ressalva_de_servico_nao_sobrevive_ao_turno() -> None:
    """O `condicionado` só olha o burst ATUAL — um número com serviço pendurado que atravessasse o
    turno chegaria ao aceite sem a ressalva, e fecharia sobre uma promessa que ninguém conferiu."""
    linhas = _conversa(("ele", "faz 360 com 2 finalizações?"), ("ele", "consegue ?"))

    assert _valor_dele_vigente(["consegue ?"], linhas, _TABELA_1H) is None


def test_bolha_dele_com_dois_valores_novos_zera_o_candidato() -> None:
    linhas = _conversa(("ele", "faz 360? ou pago 340 amanhã"), ("ele", "e aí ?"))

    assert _valor_dele_vigente(["e aí ?"], linhas, _TABELA_1H) is None


def test_eco_da_tabela_dela_nao_e_pedido_dele() -> None:
    """Mesma exclusão do burst: repetir o preço que ELA cotou não é propor nada."""
    linhas = _conversa(("ele", "400 é muito amor"), ("ele", "não dá ?"))

    assert _valor_dele_vigente(["não dá ?"], linhas, _TABELA_1H) is None


# --- (7) a FIAÇÃO: o bloco que a IA lê no turno decisivo -----------------------------------------
# O detector acima é metade; a outra é o bloco chegar ao prompt. Aqui roda o `_resolver_variaveis`
# de verdade sobre a janela crua e renderiza o template — é essa bicondicional (o número
# sobreviveu ⟺ a IA leu a instrução) que as duas rodadas medidas quebraram.


class _FakeConn1h400:
    """Tabela de UMA linha: 1h por 400, sem `preco_minimo` — piso 300 pelo teto de 25%."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = (
            [{"programa_id": "p1", "preco": Decimal("400"), "preco_minimo": None}]
            if "modelo_programas" in sql
            else []
        )

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                return None

            async def fetchall(self) -> list[Any]:
                return linhas

        return _R()


def _negociando(dia: date | None, *, duracao: Decimal | None = Decimal("1")) -> dict[str, Any]:
    """Atendimento com cotação na mesa e ainda não aceita — a janela da objeção de preço."""
    return {
        "estado": "Qualificado",
        "n_contrapropostas": 0,
        "duracao_horas": duracao,
        "valor_acordado": Decimal("400"),
        "data_desejada": dia,
    }


async def _do_turno(
    atendimento: dict[str, Any], linhas: list[dict[str, Any]]
) -> tuple[ContextoDoTurno, str]:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA,
    )
    contexto = await _resolver_variaveis(
        _FakeConn1h400(),  # type: ignore[arg-type]
        ctx,
        linhas,
        atendimento=atendimento,
        precos_por_horas={1.0: [Decimal("400")]},
    )
    return contexto, render_contexto_dinamico(**contexto.como_variaveis())


async def test_insistencia_sem_numero_ainda_manda_aceitar_o_valor_dele() -> None:
    """O turno decisivo do `desconto_valor_dele_serve`: 360 serve (piso 300, mesa 400) e o bloco
    tem de renderizar COM o número — sem ele a IA cai na escada e oferta o piso, jogando fora os
    R$60 que ele próprio já tinha posto na mesa."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE),
        _conversa(
            ("ele", "faz 360?"),
            ("ela", "Poxa amor, esse é o meu valor rs"),
            ("ele", "consegue mesmo assim ?"),
        ),
    )

    assert contexto.aceite_do_valor_dele == "360"
    assert contexto.contraproposta_disponivel is None
    assert "<valor_dele_serve>" in prompt and "360" in prompt


async def test_a_duracao_da_linha_tambem_sobrevive_ao_turno() -> None:
    """Sem `duracao_horas` no belief, a linha da escada saía do valor do burst (fallback 2) — e no
    turno da insistência sem número ela sumia junto, matando o aceite em "ambiguo" antes de ele
    chegar ao piso. O resolver da linha lê o MESMO valor vigente."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE, duracao=None),
        _conversa(("ele", "faz 360?"), ("ela", "esse é o meu valor amor"), ("ele", "vai ?")),
    )

    assert contexto.aceite_do_valor_dele == "360"
    assert "<valor_dele_serve>" in prompt


async def test_ela_ja_tendo_aceito_o_numero_dele_o_bloco_nao_volta() -> None:
    """A retirada, ponta a ponta: com o sim dela na janela, o bloco não reaparece mandando aceitar
    de novo o que já foi aceito."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE),
        _conversa(("ele", "faz 360?"), ("ela", "Fechado 360 amor"), ("ele", "que horas ?")),
    )

    assert contexto.aceite_do_valor_dele is None
    assert "<valor_dele_serve>" not in prompt


# --- (8) o lowball que INSISTE, com o dia ainda fora do belief -----------------------------------
# `desconto_abaixo_teto` (campanha c7): o cliente insistiu em 150 por dois turnos e o prompt não
# tinha instrução de escalada nenhuma — ela morava DENTRO do <escada_disponivel>, que só renderiza
# quando o `escada_estado` sai de `sem_dia`, e o dia só entrou no belief no 3º turno. A IA aplicou
# contraproposta a um "?" em vez de escalar. A regra passou para o <pedido_abaixo_do_piso>, que
# depende do PEDIDO dele, nunca do dia: o dia decide quanto ELA desce, não se o pedido dele cabe.


async def test_lowball_sem_o_dia_ja_traz_a_regra_de_escalada() -> None:
    contexto, prompt = await _do_turno(
        _negociando(None), _conversa(("ele", "nossa ta caro, faz por 150? só tenho isso"))
    )

    assert contexto.escada_estado == "sem_dia"
    assert contexto.pedido_abaixo_do_piso is True
    # O fecho, não a abertura: o <escada_disponivel> CITA a tag como ponteiro condicional ("no
    # turno em que ela chegar"), e só o bloco de verdade fecha.
    assert "</pedido_abaixo_do_piso>" in prompt
    # ...e a ESCALADA não vem junto na primeira aparição (regressão de 13/08, ver a seção 9): o
    # bloco chega com a recusa e o encontro de pé, a cláusula de escalar só entra na insistência.
    assert "fora_de_oferta" not in prompt
    assert "neste turno você NÃO escala" in prompt


async def test_a_insistencia_sem_numero_continua_sendo_lowball() -> None:
    """O turno em que a IA errou: ele cobra com um "?" e o número dele (150) já não está no burst.
    Sem o valor sobrevivendo ao turno, o bloco sumia justamente onde a escalada é a jogada."""
    contexto, prompt = await _do_turno(
        _negociando(None),
        _conversa(
            ("ele", "faz por 150? só tenho isso"),
            ("ela", "Poxa amor, esse é o meu valor rs / Seria hoje ?"),
            ("ele", "vai, 150 e fechamos agora"),
            ("ela", "Não consigo amor"),
            ("ele", "?"),
        ),
    )

    assert contexto.pedido_abaixo_do_piso is True
    assert "</pedido_abaixo_do_piso>" in prompt


async def test_com_o_dia_na_mesa_a_escada_continua_como_hoje() -> None:
    """Sem lowball, nada muda: o bloco novo não sai e o <escada_disponivel> segue com o número
    calculado e a mecânica do degrau."""
    contexto, prompt = await _do_turno(_negociando(_HOJE), _conversa(("ele", "ta caro amor")))

    assert contexto.pedido_abaixo_do_piso is False
    assert contexto.contraproposta_disponivel == "300"
    assert "</pedido_abaixo_do_piso>" not in prompt
    assert "<escada_disponivel>" in prompt


async def test_o_pedido_acima_do_piso_nao_e_lowball() -> None:
    """A fronteira do carimbo é o piso, não "pediu desconto": 360 fecha a venda (bloco do aceite),
    150 escala."""
    contexto, prompt = await _do_turno(_negociando(_HOJE), _conversa(("ele", "faz 360?")))

    assert contexto.pedido_abaixo_do_piso is False
    assert "</pedido_abaixo_do_piso>" not in prompt
    assert "<valor_dele_serve>" in prompt


async def test_com_o_dia_o_lowball_soma_a_escalada_sem_apagar_a_escada() -> None:
    """O que deliberadamente NÃO mudou: o bloco novo acrescenta a regra de escalada, não suprime a
    escada. Com o dia na mesa os dois convivem — o número calculado continua sendo a única resposta
    com número (o <pedido_abaixo_do_piso> diz isso nominalmente), e a escalada é o DEPOIS dela."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE), _conversa(("ele", "nossa ta caro, faz por 150? só tenho isso"))
    )

    assert contexto.pedido_abaixo_do_piso is True
    assert contexto.contraproposta_disponivel == "300"
    assert "</pedido_abaixo_do_piso>" in prompt and "<escada_disponivel>" in prompt


# --- (9) a INSISTÊNCIA como carimbo, não como leitura do modelo ----------------------------------
# Regressão de 13/08: o <pedido_abaixo_do_piso> trazia a cláusula de escalada COLADA na recusa, e na
# primeira aparição do lowball (350 -> 320 -> 280 sobre um piso de 300) o modelo leu a escada de
# números dele como insistência, escalou de saída e ainda saiu com bolha VAZIA — matando uma venda
# que o baseline fechava. Quem separa "mais um número menor, ainda sem resposta dela" de "o mesmo
# pedido depois da recusa" passa a ser determinístico (`_piso_ja_recusado`), e o gate é do template.


def test_a_escada_de_numeros_dele_nao_e_insistencia() -> None:
    """O caso medido, em cru: 350 e 320 estão ACIMA do piso (300) e nem contam; o 280 é a PRIMEIRA
    vez que um pedido abaixo do piso aparece, e ele ainda não ouviu resposta nenhuma sobre ele."""
    linhas = _conversa(
        ("ele", "consegue fazer 350?"),
        ("ela", "Poxa amor, esse é o meu valor rs / Seria hoje ?"),
        ("ele", "e 320?"),
        ("ela", "Não consigo amor"),
        ("ele", "consegue fazer 280?"),
    )

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_o_mesmo_pedido_depois_da_recusa_dela_e_insistencia() -> None:
    """A fala DELA entre as duas bolhas dele é o que carimba: ele já ouviu, e voltou com o mesmo."""
    linhas = _conversa(
        ("ele", "faz 280?"),
        ("ela", "Poxa amor não consigo"),
        ("ele", "vai, 280 e fechamos"),
    )

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is True


def test_ele_descer_o_proprio_pedido_ainda_nao_carimba() -> None:
    """O fail-closed que o recorte cobra: o piso não chega até aqui (ele mora no domínio e uma
    segunda cópia da régua divergiria da que julga a oferta), então só o pedido <= o de agora é
    provadamente lowball repetido. 280 recusado e ele descendo para 250 recebe a recusa curta de
    novo; repetindo o 250, aí sim escala. Uma rodada a mais é o lado barato do erro."""
    linhas = _conversa(
        ("ele", "faz 280?"),
        ("ela", "Não consigo amor"),
        ("ele", "faz 250 então?"),
    )

    assert _piso_ja_recusado(linhas, 250, _TABELA_1H) is False

    repetiu = [
        *linhas,
        _bolha(DirecaoMensagem.ia, "Não consigo amor", minutos=3),
        _bolha(DirecaoMensagem.cliente, "vai, 250 e fechamos", minutos=4),
    ]

    assert _piso_ja_recusado(repetiu, 250, _TABELA_1H) is True


def test_ele_seguir_pro_horario_depois_da_resposta_nao_e_insistencia() -> None:
    """Achado da auditoria de corpus (122 conversas, 13/08): sem exigir que o NÚMERO volte, este
    fio carimbava insistência — e o cliente aqui não está insistindo, está marcando a hora. O valor
    dele sobrevive ao turno (é assim que o <valor_dele_serve> funciona), o carimbo não."""
    linhas = _conversa(
        ("ele", "faz por 280?"),
        ("ela", "Poxa amor não consigo"),
        ("ele", "as 16:00 então"),
    )

    assert _valor_dele_vigente(["as 16:00 então"], linhas, _TABELA_1H) == 280
    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_cobrar_resposta_sem_repetir_o_numero_ainda_nao_escala() -> None:
    """O outro lado do mesmo recorte: "e aí ?" depois da recusa mantém o lowball vivo (o bloco
    renderiza), mas não libera a escalada — uma rodada de recusa a mais é o lado barato do erro."""
    linhas = _conversa(("ele", "faz por 280?"), ("ela", "Não consigo amor"), ("ele", "e aí ?"))

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_bolhas_seguidas_dele_no_mesmo_burst_nao_sao_duas_rodadas() -> None:
    """Sem fala dela no meio, o número repetido é UMA pergunta quebrada em duas bolhas."""
    linhas = _conversa(("ele", "faz 280?"), ("ele", "280 vai?"))

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_pausa_de_seis_horas_apaga_a_insistencia() -> None:
    """Mesma régua da marca de pausa: quem sumiu e voltou não está insistindo, está recomeçando."""
    linhas = [
        _bolha(DirecaoMensagem.cliente, "faz 280?", minutos=0),
        _bolha(DirecaoMensagem.ia, "Poxa amor não consigo", minutos=1),
        _bolha(DirecaoMensagem.cliente, "e agora, 280?", minutos=7 * 60),
    ]

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_eco_do_numero_dela_nao_conta_como_pedido_anterior() -> None:
    """400 é o preço DELA (`ja_conhecidos`): ele repeti-lo não é ter pedido nada."""
    linhas = _conversa(("ele", "400 é muito"), ("ela", "É 400 amor"), ("ele", "faz 280?"))

    assert _piso_ja_recusado(linhas, 280, _TABELA_1H) is False


def test_sem_valor_dele_nao_ha_insistencia_a_carimbar() -> None:
    assert _piso_ja_recusado(_conversa(("ele", "ta caro")), None, _TABELA_1H) is False


async def test_primeira_aparicao_do_lowball_traz_recusa_sem_escalada() -> None:
    """Ponta a ponta, a metade que a regressão quebrou: o bloco chega, manda recusar curto e manter
    o encontro de pé — e a palavra `fora_de_oferta` não existe no prompt deste turno."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE),
        _conversa(
            ("ele", "consegue fazer 350?"),
            ("ela", "Poxa amor, esse é o meu valor rs / Consigo às 21h, fecha ?"),
            ("ele", "consegue fazer 280?"),
        ),
    )

    assert contexto.pedido_abaixo_do_piso is True
    assert "</pedido_abaixo_do_piso>" in prompt
    assert "fora_de_oferta" not in prompt
    assert "recusa curta" in prompt


async def test_insistencia_libera_a_escalada_com_a_recusa_junto() -> None:
    """A outra metade: com o carimbo no <proximo_passo>, a cláusula de escalar entra — e entra
    dizendo que a recusa curta sai na MESMA mensagem (escalar calada foi como a venda morreu)."""
    contexto, prompt = await _do_turno(
        _negociando(_HOJE),
        _conversa(
            ("ele", "consegue fazer 280?"),
            ("ela", "Poxa amor não consigo"),
            ("ele", "vai, 280 e fechamos agora"),
        ),
    )

    assert contexto.pedido_abaixo_do_piso is True
    assert _MARCA_INSISTENCIA_PISO in contexto.proximo_passo
    assert "fora_de_oferta" in prompt
    assert "NUNCA sai calada" in prompt


async def test_o_carimbo_nao_aparece_sem_lowball() -> None:
    """O <proximo_passo> só carrega a frase no turno em que ela vale — nada de carimbo vitalício."""
    contexto, _prompt = await _do_turno(_negociando(_HOJE), _conversa(("ele", "faz 360?")))

    assert _MARCA_INSISTENCIA_PISO not in contexto.proximo_passo


def test_o_literal_do_carimbo_e_o_mesmo_nos_dois_sites() -> None:
    """Eco multi-site: o carimbo é publicado pelo Python e TESTADO pelo Jinja. Renomear a frase de
    um lado só apaga a escalada em silêncio — o Jinja não erra com condição que nunca casa."""
    fonte = _env.loader.get_source(_env, "contexto_dinamico.md.j2")[0]  # type: ignore[union-attr]

    assert _MARCA_INSISTENCIA_PISO in _INSISTENCIA_ABAIXO_DO_PISO
    assert f"'{_MARCA_INSISTENCIA_PISO}' in proximo_passo" in fonte
