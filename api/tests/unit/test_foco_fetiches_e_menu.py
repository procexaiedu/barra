"""Rodada 6b — closed-world do cardápio como DADO do turno.

Cobre as três pontas novas: os detectores do burst (`fetiches_no_burst`,
`pediu_restricoes_no_burst`, `composicao_na_janela`), a resolução contra o cadastro
(`_resolver_fetiches_em_pauta`, `_menu_primeira_cotacao`) e o guard da afirmação nua
(`bolhas_afirmacao_nua_de_risco`). O cadastro-padrão dos casos é o real de prod (Tatiane):
Completo/Normal 1h + fetiches incluso/pago — anal NÃO listado (mora no Completo).
"""

from decimal import Decimal

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.nos._foco_do_turno import (
    composicao_na_janela,
    fetiches_no_burst,
    pediu_preco_no_burst,
    pediu_restricoes_no_burst,
)
from barra.agente.nos.output_guard import bolhas_afirmacao_nua_de_risco
from barra.agente.nos.prepare_context import (
    _base_no_patamar,
    _BaseDoPatamar,
    _menu_primeira_cotacao,
    _resolver_fetiches_em_pauta,
)

# Fetiches-padrão (cadastro real): incluso = sem preço; pago = preço; composição = por pessoa.
# A composição usa o NOME NOVO do catálogo (migration 20260811232000): um item por composição,
# com o travessão do rótulo do painel — é ele que os needles de `_NEEDLES_CATALOGO` precisam casar.
_FETICHES_PADRAO = [
    {"nome": "beijo na boca", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Oral sem camisinha", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Beijo Grego", "preco": Decimal("100"), "cobra_por_pessoa": False},
    {"nome": "Chuva dourada", "preco": Decimal("100"), "cobra_por_pessoa": False},
    {"nome": "Acompanhante dele — mulher", "preco": Decimal("100"), "cobra_por_pessoa": True},
]
_PROGRAMAS_PADRAO = [
    {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": Decimal("400")},
    {"nome": "Completo", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": Decimal("800")},
]
_CARDAPIO = {"fetiches": _FETICHES_PADRAO, "programas": _PROGRAMAS_PADRAO}


def _janela(*textos: str) -> list[HumanMessage]:
    return [HumanMessage(content=t) for t in textos]


def test_fetiche_mencionado_no_burst_sai_na_ordem() -> None:
    assert fetiches_no_burst(_janela("Você faz anal?", "e beijo na boca?")) == (
        "anal",
        "beijo_na_boca",
    )


def test_sem_camisinha_perto_de_oral_vira_oral_sem() -> None:
    assert fetiches_no_burst(_janela("faz oral sem camisinha?")) == ("oral_sem",)
    # Longe de oral = penetração sem proteção, família própria (nunca coberta).
    assert fetiches_no_burst(_janela("transa sem camisinha?")) == ("sem_camisinha",)


def test_pediu_restricoes() -> None:
    assert pediu_restricoes_no_burst(_janela("Alguma restrição ?"))
    assert pediu_restricoes_no_burst(_janela("o que você não faz?"))
    assert not pediu_restricoes_no_burst(_janela("qual o valor?"))


def test_composicao_na_janela_inteira_nao_so_no_burst() -> None:
    janela = [
        HumanMessage(content="vocês atendem casal?"),
        AIMessage(content="Atendo sim amor"),
        HumanMessage(content="e qual valor?"),
    ]
    assert composicao_na_janela(janela)
    # burst atual não menciona — nenhuma família de composição sai dele
    assert fetiches_no_burst(janela) == ()


def test_presente_e_pergunta_de_preco() -> None:
    assert pediu_preco_no_burst(_janela("Seu presente? 🤭"))


def test_resolver_incluso_extra_por_pessoa_e_fora() -> None:
    resolvidos = _resolver_fetiches_em_pauta(
        ("oral_sem", "grego", "acompanhante_mulher", "fisting"), _CARDAPIO
    )
    assert [r["status"] for r in resolvidos] == ["incluso", "extra", "por_pessoa", "fora"]
    # Nome exibido é o do CADASTRO quando há match.
    assert resolvidos[0]["nome"] == "Oral sem camisinha"


def test_anal_sem_fetiche_mas_com_completo_e_segunda_porta() -> None:
    assert _resolver_fetiches_em_pauta(("anal",), _CARDAPIO) == (
        {"nome": "anal", "status": "no_completo"},
    )
    # Sem Completo na tabela, anal é fora do cardápio → recusa.
    so_normal = {"fetiches": _FETICHES_PADRAO, "programas": [_PROGRAMAS_PADRAO[0]]}
    assert _resolver_fetiches_em_pauta(("anal",), so_normal)[0]["status"] == "fora"


def test_sem_camisinha_nunca_e_coberto_nem_pelo_oral_sem() -> None:
    assert _resolver_fetiches_em_pauta(("sem_camisinha",), _CARDAPIO)[0]["status"] == "fora"


# --- o TOTAL com fetiche no patamar da negociação (dívida do ADR-0038) --------------------------
# O <fetiches> por-modelo é estático (tabela CHEIA, pré-requisito do cache) e diz "se o valor do
# pacote já desceu, o extra desce junto — o número que vale é o que o bloco do turno te der". Sem
# este total pré-computado a frase não tinha lastro: sobrava a tabela cheia + um valor negociado,
# e somar os dois é a conta de cabeça que o ADR proíbe (incidente real: a bolha "1200 (800+800)").


def _base(
    patamar: str, *, uma_hora: tuple[Decimal, Decimal | None] | None = (Decimal("400"), None)
):
    """Pacote de 1h da Catarina (400 de tabela) no patamar pedido, com a 1h do mesmo programa."""
    from barra.dominio.atendimentos.service import valor_no_patamar

    return _BaseDoPatamar(
        patamar=patamar,  # type: ignore[arg-type]
        pacote=valor_no_patamar(Decimal("400"), None, patamar),  # type: ignore[arg-type]
        horas=Decimal("1"),
        linha_de_uma_hora=uma_hora,
    )


# Sentinel de flag "pago sem valor" (`_PRECO_PAGO_SENTINEL` do painel legado, abaixo do mínimo de
# preço cadastrado): é o regime DERIVADO, o de quase todo o prod.
_CARDAPIO_DERIVADO = {
    "fetiches": [
        {"nome": "Inversão", "preco": Decimal("1"), "cobra_por_pessoa": False},
        {"nome": "Acompanhante dele — mulher", "preco": Decimal("1"), "cobra_por_pessoa": True},
    ],
    "programas": _PROGRAMAS_PADRAO,
}


def test_extra_derivado_traz_o_total_no_patamar_da_negociacao() -> None:
    """1h no piso (300) + o extra da 1h NO PISO (300) = 600 — os ADR-0038/0031 juntos, e não
    300 + 400 (extra de tabela cheia) nem 400 + 400 (a linha do <fetiches>)."""
    resolvidos = _resolver_fetiches_em_pauta(("inversao",), _CARDAPIO_DERIVADO, _base("piso"))

    assert resolvidos[0]["status"] == "extra"
    assert resolvidos[0]["total"] == "R$600"


def test_total_no_degrau_usa_o_degrau_dos_dois_lados() -> None:
    # Degrau da 1h = 350; o extra é a 1h no MESMO estágio = 350. Total 700.
    total = _resolver_fetiches_em_pauta(("inversao",), _CARDAPIO_DERIVADO, _base("degrau"))[0]
    assert total["total"] == "R$700"


def test_patamar_cheio_nao_injeta_total_a_tabela_ja_e_esse_numero() -> None:
    """`_base_no_patamar` devolve None no cheio; sem base, o item volta a apontar o <fetiches>."""
    assert "total" not in _resolver_fetiches_em_pauta(("inversao",), _CARDAPIO_DERIVADO, None)[0]


def test_por_pessoa_soma_o_MESMO_extra_dos_atos_no_patamar() -> None:
    """ADR-0039: a 2ª pessoa custa o extra dos atos (a 1h no patamar), não o pacote dobrado.

    Na 1h os dois regimes coincidem (300 + 300 = 600 tanto pelo dobro quanto pela 1h) — é por
    isso que o assert que separa os regimes está no ato/`por_pessoa` LADO A LADO abaixo, e não
    neste número. O que este teste fixa é que o `status` continua sendo `por_pessoa` (a
    classificação sobreviveu) enquanto o TOTAL sai da mesma conta do `extra`.
    """
    casal = _resolver_fetiches_em_pauta(
        ("acompanhante_mulher",), _CARDAPIO_DERIVADO, _base("piso")
    )[0]
    inversao = _resolver_fetiches_em_pauta(("inversao",), _CARDAPIO_DERIVADO, _base("piso"))[0]

    assert casal["status"] == "por_pessoa"
    assert inversao["status"] == "extra"
    assert casal["total"] == inversao["total"] == "R$600"


def test_por_pessoa_sem_linha_de_uma_hora_perde_o_total() -> None:
    """Caminho NOVO do ADR-0039: o regime velho (pacote dobrado) não precisava da 1h e sempre
    tinha número. Agora a composição cai no mesmo fail-closed dos atos — sem total, a IA volta
    para o <fetiches> em vez de ler um valor inventado."""
    sem_uma_hora = _base("piso", uma_hora=None)
    casal = _resolver_fetiches_em_pauta(("acompanhante_mulher",), _CARDAPIO_DERIVADO, sem_uma_hora)[
        0
    ]

    assert casal["status"] == "por_pessoa"
    assert "total" not in casal


def test_extra_CADASTRADO_nao_acompanha_o_patamar() -> None:
    """Revisão de 11/08 do ADR-0030: o operador digitou um valor, não uma escada — o extra fica
    fixo e só o PACOTE desce. 300 (piso) + 100 (cadastrado no `_CARDAPIO`) = 400."""
    assert _resolver_fetiches_em_pauta(("grego",), _CARDAPIO, _base("piso"))[0]["total"] == "R$400"


def test_sem_linha_de_uma_hora_nao_ha_total_derivado_a_mostrar() -> None:
    """Fail-closed do ADR-0038: o extra É a uma hora; sem ela cadastrada não há número — a linha
    sai sem total e a IA cai no <fetiches>, em vez de ler um valor inventado."""
    resolvidos = _resolver_fetiches_em_pauta(
        ("inversao",), _CARDAPIO_DERIVADO, _base("piso", uma_hora=None)
    )

    assert "total" not in resolvidos[0]


class _FakeConnTabela:
    """Responde as duas leituras do `_base_no_patamar`: as linhas da duração e a linha de 1h."""

    def __init__(self, linhas: list[dict[str, object]], uma_hora: dict[str, object] | None) -> None:
        self.linhas = linhas
        self.uma_hora = uma_hora
        self.queries: list[str] = []

    async def execute(self, sql: str, params: tuple[object, ...] = ()) -> object:
        self.queries.append(sql)
        linhas = [self.uma_hora] if "mp.programa_id = %s" in sql else self.linhas

        class _R:
            async def fetchall(self) -> list[object]:
                return [ln for ln in linhas if ln is not None]

            async def fetchone(self) -> object | None:
                return linhas[0] if linhas and linhas[0] is not None else None

        return _R()


def _linha(preco: str, programa: str = "p1") -> dict[str, object]:
    return {"programa_id": programa, "preco": Decimal(preco), "preco_minimo": None}


async def test_base_no_patamar_desce_o_pacote_e_carrega_a_1h_do_programa() -> None:
    conn = _FakeConnTabela([_linha("400")], {"preco": Decimal("400"), "preco_minimo": None})

    base = await _base_no_patamar(conn, "m1", Decimal("1"), "piso")  # type: ignore[arg-type]

    assert base is not None
    assert base.pacote == Decimal("300.00")
    assert base.linha_de_uma_hora == (Decimal("400"), None)


async def test_base_no_patamar_cheio_nao_consulta_nada() -> None:
    """No cheio a tabela estática do <fetiches> JÁ é o número — nada a pré-computar."""
    conn = _FakeConnTabela([_linha("400")], None)

    assert await _base_no_patamar(conn, "m1", Decimal("1"), "cheio") is None  # type: ignore[arg-type]
    assert conn.queries == []


async def test_base_no_patamar_fail_closed_com_duas_linhas_na_duracao() -> None:
    """Mesmo critério do piso e da escada: com dois pacotes na duração não dá pra dizer QUAL é o
    valor negociado — um total errado é pior que nenhum (a IA cai na tabela cheia)."""
    conn = _FakeConnTabela([_linha("400", "p1"), _linha("800", "p2")], None)

    assert await _base_no_patamar(conn, "m1", Decimal("1"), "piso") is None  # type: ignore[arg-type]


def test_incluso_e_fora_nunca_ganham_total() -> None:
    resolvidos = _resolver_fetiches_em_pauta(("oral_sem", "fisting"), _CARDAPIO, _base("piso"))

    assert all("total" not in r for r in resolvidos)


def test_menu_primeira_cotacao_duas_portas() -> None:
    menu = _menu_primeira_cotacao(_PROGRAMAS_PADRAO)
    assert menu is not None and "400" in menu and "Completo 800" in menu


def test_menu_ancora_na_1h_mesmo_com_pacote_curto_na_tabela() -> None:
    """A tabela da Catarina depois do cadastro dos 30min: Normal tem DUAS linhas (250 nos 30min,
    400 na 1h) e a de 30min vem primeiro na ordem. O menu tem que abrir em 400 — o `<cotacao>`
    manda cotar "na 1h", e abrir em 250 faria o pacote de resgate virar a âncora da conversa."""
    catarina = [
        {
            "nome": "Normal",
            "duracao_nome": "30 minutos",
            "duracao_horas": Decimal("0.5"),
            "preco": Decimal("250"),
        },
        {"nome": "Normal", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": Decimal("400")},
        {"nome": "Completo", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": Decimal("800")},
    ]
    menu = _menu_primeira_cotacao(catarina)
    assert menu is not None
    assert "400 na 1 hora" in menu
    assert "Completo 800 na 1 hora" in menu
    assert "250" not in menu and "30 minutos" not in menu


def test_menu_sem_1h_na_tabela_usa_a_primeira_da_ordem() -> None:
    """Sem linha de 1h, o comportamento é o de antes: a primeira duração da ordem da tabela."""
    sem_uma_hora = [
        {"nome": "Normal", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": Decimal("700")},
        {
            "nome": "Completo",
            "duracao_nome": "2 horas",
            "duracao_horas": 2,
            "preco": Decimal("1300"),
        },
    ]
    menu = _menu_primeira_cotacao(sem_uma_hora)
    assert menu is not None and "700 na 2 horas" in menu


def test_menu_fail_closed_fora_de_duas_portas() -> None:
    assert _menu_primeira_cotacao([_PROGRAMAS_PADRAO[0]]) is None  # uma porta só
    tres = [*_PROGRAMAS_PADRAO, {"nome": "Pernoite", "duracao_nome": "12 horas", "preco": 2000}]
    assert _menu_primeira_cotacao(tres) is None  # três portas
    sem_completo = [
        _PROGRAMAS_PADRAO[0],
        {"nome": "Massagem", "duracao_nome": "1 hora", "preco": Decimal("300")},
    ]
    assert _menu_primeira_cotacao(sem_completo) is None


def test_afirmacao_nua_de_risco_dispara_no_sim_nu() -> None:
    ofensoras = bolhas_afirmacao_nua_de_risco(["Faz anal? 😅"], "Pode sim amor", {"beijo"})
    assert ofensoras == ["Pode sim amor"]


def test_afirmacao_nua_absolvida_por_negacao_cadastro_e_conteudo() -> None:
    vocab_com_completo = {"completo", "anal", "grego"}  # expansão do vocabulário da modelo
    assert not bolhas_afirmacao_nua_de_risco(["Faz anal?"], "Pode sim amor", vocab_com_completo)
    assert not bolhas_afirmacao_nua_de_risco(["Faz anal?"], "Não faço amor", {"beijo"})
    # Bolha que NOMEIA o serviço fica com o detector-irmão (bolhas_servico_fantasma).
    assert not bolhas_afirmacao_nua_de_risco(["Faz anal?"], "Anal não rola amor", {"beijo"})
    # Sem pedido de risco no burst, "pode sim" é resposta legítima a qualquer outra coisa.
    assert not bolhas_afirmacao_nua_de_risco(["posso te beijar?"], "Pode sim amor", {"beijo"})


# --- Taxonomia de COMPOSIÇÕES (11/08/2026) ------------------------------------------------------
# A família única `casal` fundia num regex só tudo que tem mais de duas pessoas
# (`casal|ménage|dupla|nós dois|duas meninas|eu e minha esposa`), e o resolver tinha um fallback
# "qualquer fetiche por-pessoa cobre". Juntos, faziam "eu e um amigo" ser dado por coberto pelo
# item de acompanhante MULHER — a promessa que a modelo que não atende dois homens não pode fazer.
# Agora é uma família por composição, e cada uma casa o SEU item do catálogo.


def test_as_quatro_composicoes_nao_se_confundem() -> None:
    assert fetiches_no_burst(_janela("seria eu e minha esposa")) == ("acompanhante_mulher",)
    assert fetiches_no_burst(_janela("eu e um amigo, dá?")) == ("acompanhante_homem",)
    assert fetiches_no_burst(_janela("você e uma amiga sua rola?")) == ("dupla_de_modelos",)
    assert fetiches_no_burst(_janela("seria nós dois e vocês duas")) == ("dois_casais",)


def test_dois_casais_engloba_as_outras_na_mesma_frase() -> None:
    """ "eu e um amigo e vocês duas" casa as três de uma vez; a mais específica é a que fica —
    três itens de cardápio em pauta para UM pedido só confundiria o turno inteiro."""
    assert fetiches_no_burst(_janela("eu e um amigo e vocês duas, quanto fica?")) == (
        "dois_casais",
    )


def test_casal_seco_continua_sendo_a_composicao_de_mulher() -> None:
    """ "casal", na boca do cliente, é ele + a mulher dele — e é o nome ANTIGO do mesmo item do
    catálogo (a migration renomeia "Casal" no lugar), então resolve pelo cadastro velho também."""
    assert fetiches_no_burst(_janela("vocês atendem casal?")) == ("acompanhante_mulher",)
    velho = {
        "fetiches": [{"nome": "Casal", "preco": Decimal("100"), "cobra_por_pessoa": True}],
        "programas": _PROGRAMAS_PADRAO,
    }
    assert _resolver_fetiches_em_pauta(("acompanhante_mulher",), velho)[0]["status"] == (
        "por_pessoa"
    )


def test_menage_sozinho_nao_resolve_item_nenhum() -> None:
    """A palavra é ambígua por construção (duas mulheres e dois homens, ou uma de cada): resolver
    um item a partir dela seria chutar QUAL. Ela acende só a nota da janela, que manda confirmar
    quem vem antes de cravar o número."""
    assert fetiches_no_burst(_janela("vocês fazem menage?")) == ()
    assert composicao_na_janela(_janela("vocês fazem menage?"))
    assert composicao_na_janela(_janela("seria nós dois"))


def test_item_ausente_do_cardapio_e_recusa_closed_world() -> None:
    """O GANHO da taxonomia, no caso da Catarina: ela tem o item de acompanhante MULHER e não tem
    o de acompanhante HOMEM. Ter um não dá o outro — sem fallback, "eu e um amigo" cai em `fora`,
    que é a recusa que o <servico_em_pauta> já sabe emitir."""
    resolvidos = _resolver_fetiches_em_pauta(
        ("acompanhante_mulher", "acompanhante_homem"), _CARDAPIO
    )

    assert [r["status"] for r in resolvidos] == ["por_pessoa", "fora"]
    assert resolvidos[0]["nome"] == "Acompanhante dele — mulher"  # nome do CADASTRO
    assert resolvidos[1]["nome"] == "ele trazer outro homem junto"  # rótulo da família


def test_o_item_de_homem_cadastrado_nao_cobre_o_de_mulher() -> None:
    """O espelho do teste acima — os needles não vazam de um lado para o outro."""
    so_homem = {
        "fetiches": [
            {"nome": "Acompanhante dele — homem", "preco": Decimal("100"), "cobra_por_pessoa": True}
        ],
        "programas": _PROGRAMAS_PADRAO,
    }
    resolvidos = _resolver_fetiches_em_pauta(
        ("acompanhante_mulher", "acompanhante_homem"), so_homem
    )

    assert [r["status"] for r in resolvidos] == ["fora", "por_pessoa"]


def test_needle_de_composicao_aceita_hifen_no_lugar_do_travessao() -> None:
    """O painel pode gravar "-" onde o rótulo tem "—", e `normalizar` dobra acento e caixa, não
    traço. Sem a grafia alternativa no needle, o item cadastrado ficaria `fora` do próprio nome."""
    com_hifen = {
        "fetiches": [
            {
                "nome": "Acompanhante dele - mulher",
                "preco": Decimal("100"),
                "cobra_por_pessoa": True,
            }
        ],
        "programas": _PROGRAMAS_PADRAO,
    }
    assert _resolver_fetiches_em_pauta(("acompanhante_mulher",), com_hifen)[0]["status"] == (
        "por_pessoa"
    )


def test_composicao_com_outra_modelo_agora_resolve_contra_o_cardapio() -> None:
    """ADR-0042: com a escalada revogada, a modelo do canal COTA a dupla — e cotar exige o item
    resolvido. `dupla_de_modelos`/`dois_casais` voltaram ao regime de todo mundo: ausentes do
    cardápio viram `fora` (closed-world), presentes viram `por_pessoa` com o total das duas.

    Enquanto a conduta era escalar, um `fora` aqui mandaria a IA recusar o que ela devia escalar —
    era essa a razão da exceção, e ela morreu junto com a escalada."""
    assert [r["status"] for r in _resolver_fetiches_em_pauta(("dupla_de_modelos",), _CARDAPIO)] == [
        "fora"
    ]
    com_dupla = {
        "fetiches": [
            *_FETICHES_PADRAO,
            {"nome": "Dupla de modelos", "preco": Decimal("1"), "cobra_por_pessoa": True},
        ],
        "programas": _PROGRAMAS_PADRAO,
    }
    assert _resolver_fetiches_em_pauta(("dupla_de_modelos",), com_dupla)[0]["status"] == (
        "por_pessoa"
    )
    # E não engolem o item que ESTÁ em pauta junto delas.
    resolvidos = _resolver_fetiches_em_pauta(("dupla_de_modelos", "grego"), _CARDAPIO)
    assert [r["status"] for r in resolvidos] == ["fora", "extra"]
