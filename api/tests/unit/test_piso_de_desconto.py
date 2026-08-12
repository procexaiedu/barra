"""Piso do Desconto de fechamento (ADR-0031) — o site ÚNICO da conta.

`piso_de_desconto` é `preço de tabela x (1 - desconto_teto_pct)`. O mesmo número serve a dois
consumidores que precisam concordar até no arredondamento: a guarda que JULGA o `valor_acordado`
(`_abaixo_do_piso`, hoje amarrada ao PACOTE) e a cauda, que MOSTRA o número à IA em vez do
percentual que ela multiplicava de cabeça (`contraproposta_da_escada`). Sem DB, sem crédito.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from prometheus_client import REGISTRY

from barra.dominio.atendimentos.service import (
    _abaixo_do_piso,
    _piso_do_pacote,
    contraproposta_da_escada,
    degrau_de_desconto,
    estado_da_escada,
    patamar_vigente,
    piso_de_desconto,
)

_ATENDIMENTO = UUID("22222222-2222-2222-2222-222222222222")

# --- a conta (pura) -----------------------------------------------------------------------------


def test_piso_e_o_teto_percentual_sobre_a_tabela() -> None:
    # default de settings: desconto_teto_pct = 0.25 (ADR-0031, ~25%).
    assert piso_de_desconto(Decimal("400")) == Decimal("300.00")
    assert piso_de_desconto(Decimal("700")) == Decimal("525.00")


def test_piso_nao_arredonda_por_conta_propria() -> None:
    """Quem julga e quem mostra recebem o MESMO Decimal — arredondar aqui é o que faria a oferta
    que a cauda mandou fazer cair um centavo abaixo do piso e escalar à toa."""
    assert piso_de_desconto(Decimal("350")) == Decimal("262.50")


def test_degrau_e_o_percentual_intermediario_sobre_a_tabela() -> None:
    """Site único da conta do degrau, irmão do piso (default: desconto_degrau_pct = 0.125). É o
    número que a cauda mostra na rodada n=0 — de cabeça o modelo tirou "320" de 400 (trace 11/08),
    que não é degrau (350) nem teto (300), e o guard derrubou a oferta."""
    assert degrau_de_desconto(Decimal("400")) == Decimal("350.000")
    assert degrau_de_desconto(Decimal("700")) == Decimal("612.500")


# --- o valor que a cauda mostra ------------------------------------------------------------------


class _FakeConn:
    """Responde a query de linhas da duração com os pares (preco, preco_minimo) combinados."""

    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas
        self.params: tuple[Any, ...] = ()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        self.params = params
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


# A escada depende de o encontro ser HOJE (decisão do dono do produto, 11/08/2026): hoje vai
# DIRETO ao piso e não há segunda rodada (agenda de hoje é ociosidade que não volta); outro dia
# mantém a escalada de 2 rodadas do ADR-0031; dia ainda não dito não desconta nada.


async def _oferta(
    linhas: list[dict[str, Any]],
    *,
    encontro: Any = "outro_dia",
    n: int = 0,
    duracao: Any = 1,
) -> Decimal | None:
    return await contraproposta_da_escada(
        _FakeConn(linhas),  # type: ignore[arg-type]
        "m1",
        duracao,
        encontro=encontro,
        n_contrapropostas=n,
    )


async def test_encontro_hoje_vai_direto_ao_piso_e_nao_tem_segunda() -> None:
    assert await _oferta([_linha("400")], encontro="hoje", n=0) == Decimal("300.00")
    assert await _oferta([_linha("400")], encontro="hoje", n=1) is None


async def test_outro_dia_mantem_degrau_depois_piso() -> None:
    assert await _oferta([_linha("400")], encontro="outro_dia", n=0) == Decimal("350")
    assert await _oferta([_linha("400")], encontro="outro_dia", n=1) == Decimal("300.00")
    assert await _oferta([_linha("400")], encontro="outro_dia", n=2) is None


async def test_dia_desconhecido_nao_oferta_numero_nenhum() -> None:
    """O terceiro caso da decisão: sem saber o dia não há desconto — a jogada é defender o valor
    e sondar o dia, que é o que o degrau 1 do <desconto> já manda fazer."""
    for n in (0, 1, 2):
        assert await _oferta([_linha("400")], encontro="dia_desconhecido", n=n) is None


def test_estado_da_escada_conhece_quantas_rodadas_cada_encontro_tem() -> None:
    """O gating deixou de ser "n == 1 / n >= 2": com encontro hoje a escada acaba em UMA."""
    assert estado_da_escada("hoje", 0) == "ultima"
    assert estado_da_escada("hoje", 1) == "esgotada"
    assert estado_da_escada("outro_dia", 0) == "aberta"
    assert estado_da_escada("outro_dia", 1) == "ultima"
    assert estado_da_escada("outro_dia", 2) == "esgotada"
    assert estado_da_escada("outro_dia", 3) == "esgotada"  # defesa: contagem acima do previsto
    assert estado_da_escada("dia_desconhecido", 0) == "sem_dia"


def test_patamar_vigente_e_o_da_ultima_oferta_feita() -> None:
    """O que o extra de fetiche consome (ADR-0038): o patamar em que o valor da MESA já está."""
    assert patamar_vigente("outro_dia", 0) == "cheio"
    assert patamar_vigente("outro_dia", 1) == "degrau"
    assert patamar_vigente("outro_dia", 2) == "piso"
    assert patamar_vigente("hoje", 0) == "cheio"
    assert patamar_vigente("hoje", 1) == "piso"  # hoje pula o degrau
    assert patamar_vigente("dia_desconhecido", 1) == "cheio"


async def test_duracao_com_precos_diferentes_nao_devolve_numero() -> None:
    """A oferta é sobre o pacote VENDIDO, que o atendimento não grava. Com dois preços na mesma
    duração não dá pra saber de qual pacote é o desconto — a cauda cala e vale a prosa do
    <desconto>. É o mesmo fail-closed que o `_piso_do_pacote` aplica do lado de quem JULGA."""
    assert await _oferta([_linha("400"), _linha("700")]) is None


async def test_duracao_com_o_mesmo_preco_em_duas_linhas_continua_valendo() -> None:
    """Dois programas de 400 na mesma duração não são ambiguidade de VALOR — é o caso que o
    `min == max` da versão agregada já liberava, e a troca para linhas não pode ter perdido."""
    assert await _oferta([_linha("400"), _linha("400")], n=1) == Decimal("300.00")


async def test_sem_programa_na_duracao_nao_devolve_numero() -> None:
    assert await _oferta([]) is None


async def test_sem_duracao_fechada_nao_consulta_nem_devolve_numero() -> None:
    conn = _FakeConn([_linha("400")])

    assert (
        await contraproposta_da_escada(
            conn,  # type: ignore[arg-type]
            "m1",
            None,
            encontro="outro_dia",
            n_contrapropostas=0,
        )
        is None
    )
    assert conn.params == ()


async def test_escada_fechada_nao_consulta_a_tabela() -> None:
    """Sem rodada a oferecer (hoje já usou a única; dia desconhecido), a query nem roda."""
    conn = _FakeConn([_linha("400")])

    assert (
        await contraproposta_da_escada(
            conn,  # type: ignore[arg-type]
            "m1",
            1,
            encontro="hoje",
            n_contrapropostas=1,
        )
        is None
    )
    assert conn.params == ()


# --- o PAR da oferta condicionada ao dia (ADR-0041) ---------------------------------------------
# Irmã da `contraproposta_da_escada`, lida de uma vez em vez de rodada a rodada: com o dia ainda
# desconhecido a IA parou de interrogar ("Seria hoje ?") e passou a fazer a condição viajar dentro
# da oferta ("se vier hoje X, outro dia Y"). Os DOIS números têm de vir calculados — o segundo de
# cabeça faria a resposta dele ("então outro dia") parecer aumento de preço.


async def _par(linhas: list[dict[str, Any]], *, duracao: Any = 1) -> Any:
    from barra.dominio.atendimentos.service import oferta_condicionada_ao_dia

    return await oferta_condicionada_ao_dia(
        _FakeConn(linhas),  # type: ignore[arg-type]
        "m1",
        duracao,
    )


async def test_par_da_1h_da_catarina_e_piso_e_degrau_nessa_ordem() -> None:
    """A tabela real: 1h = 400 com `preco_minimo` 300. Hoje é o piso (300, que o clamp já iguala
    aos 25%), outro dia é o degrau (350). O primeiro número é o de HOJE — a ordem do par é a ordem
    em que os números saem na fala."""
    assert await _par([_linha("400", "300")]) == (Decimal("300"), Decimal("350.000"))


async def test_par_da_2h_da_catarina() -> None:
    """2h = 800 com mínimo 600: (600, 700) — o mesmo par que o ADR-0040 usa como exemplo."""
    assert await _par([_linha("800", "600")], duracao=2) == (Decimal("600"), Decimal("700.000"))


async def test_linha_nao_descontavel_nao_tem_par() -> None:
    """Os 30min da Catarina (250 = o mínimo dela): os dois estágios colapsam no preço de tabela.
    Oferta condicional de zero real não condiciona nada — a cauda cala e vale a sonda do dia."""
    assert await _par([_linha("250", "250")], duracao=0.5) is None


async def test_par_colapsado_pelo_minimo_tambem_devolve_nada() -> None:
    """O veto que só o PAR tem: mínimo 380 sobre 400 põe piso e degrau no mesmo número. "Hoje 380,
    outro dia 380" é teatro de desconto — pior que não ter par nenhum."""
    assert await _par([_linha("400", "380")]) is None


async def test_par_e_fail_closed_como_o_resto_da_familia() -> None:
    assert await _par([]) is None
    assert await _par([_linha("400"), _linha("700")]) is None
    assert await _par([_linha("400")], duracao=None) is None


async def test_par_com_o_mesmo_preco_em_duas_linhas_usa_o_minimo_mais_apertado() -> None:
    """Mesmo critério da `_contraproposta_da_tabela`: sem saber qual pacote ele leva, valem as
    ofertas mais ALTAS. Aqui as duas sobem para 350 (o mínimo da linha mais apertada) e o par
    colapsa — o veto acima é o que impede a IA de "condicionar" 350 a 350."""
    assert await _par([_linha("400"), _linha("400", "350")]) is None


# --- o piso do PACOTE (programa x duracao) --------------------------------------------------------
# O piso era o da linha MAIS BARATA da duração (ADR-0004 §Decisão item 5). Com dois programas na
# mesma duração (Normal 400 / Completo 800 — o cadastro da Lucia e da Tatiane) isso fazia o piso de
# QUALQUER pacote de 1h ser o do mais barato: o Completo de 800 ficava vendável a 300, e como 300 é
# um valor REAL da tabela o conjunto legítimo do output_guard também o aceitava — venda abaixo do
# piso sem escalada, sem log e sem métrica.
#
# Inverter para o piso MAIS ALTO fechava o furo e abria outro, pior em frequência: com o piso
# ambíguo em 600, fechar o Normal pelo preço CHEIO de 400 escalava `fora_de_oferta` — toda venda do
# pacote mais barato virava escalada manual. O desempate (decisão de 11/08/2026) é a conversa: a IA
# COTA antes de fechar, e o preço que ela falou identifica o pacote.


class _FakeConnDoPacote:
    """Responde as leituras de `_abaixo_do_piso`: o atendimento, o serviço vendido, a tabela da
    duração e a janela de falas da IA (de onde sai o preço COTADO). Registra os SQLs para provar
    quem foi lido — e quem NÃO foi."""

    def __init__(
        self,
        linhas: list[dict[str, Any]],
        servicos: list[dict[str, Any]] | None = None,
        falas: list[str] | None = None,
    ) -> None:
        self.linhas = linhas
        self.servicos = servicos or []
        self.falas = falas or []
        self.sqls: list[str] = []

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        self.sqls.append(sql)
        if "atendimento_servicos" in sql:
            payload: list[dict[str, Any]] = self.servicos
        elif "modelo_programas" in sql:
            payload = self.linhas
        elif "mensagens" in sql:
            payload = [{"conteudo": fala} for fala in self.falas]
        else:
            payload = [
                {"modelo_id": "m1", "duracao_horas": Decimal("1"), "conversa_id": "c1"},
            ]

        class _R:
            async def fetchall(self) -> list[dict[str, Any]]:
                return payload

            async def fetchone(self) -> dict[str, Any] | None:
                return payload[0] if payload else None

        return _R()


async def _piso(
    linhas: list[dict[str, Any]],
    servicos: list[dict[str, Any]] | None = None,
    *,
    falas: list[str] | None = None,
    valor: str | None = None,
    fala_do_turno: str | None = None,
) -> tuple[Decimal | None, str]:
    return await _piso_do_pacote(
        _FakeConnDoPacote(linhas, servicos, falas),  # type: ignore[arg-type]
        _ATENDIMENTO,
        "m1",
        Decimal("1"),
        valor=None if valor is None else Decimal(valor),
        conversa_id="c1",
        fala_da_ia_no_turno=fala_do_turno,
    )


async def test_uma_linha_na_duracao_segue_valendo_o_piso_dela() -> None:
    """O cadastro da Catarina hoje: uma linha por duração. Mais alto == mais barato — nenhuma
    escalada nova, que é o requisito de não regredir."""
    assert await _piso([_linha("400")]) == (Decimal("300.00"), "duracao_unica")


async def test_duas_linhas_de_pisos_iguais_nao_sao_ambiguidade() -> None:
    """Dois programas de 400 na 1h: o piso é o mesmo número para os dois."""
    assert await _piso([_linha("400", programa="p1"), _linha("400", programa="p2")]) == (
        Decimal("300.00"),
        "duracao_unica",
    )


async def test_pisos_divergentes_sem_nada_deduzir_valem_o_MAIS_ALTO() -> None:
    """Normal 400 (piso 300) e Completo 800 (piso 600), sem serviço vendido E sem preço cotado na
    conversa: não há o que deduzir, e só o piso mais alto é válido para QUALQUER uma das linhas.
    É o FALLBACK — raro, e onde o fail-closed é barato."""
    piso, origem = await _piso([_linha("400", programa="p1"), _linha("800", programa="p2")])

    assert piso == Decimal("600.00")
    assert origem == "duracao_ambigua"


async def test_servico_vendido_desfaz_a_ambiguidade() -> None:
    """`atendimento_servicos` é a única materialização da identidade do pacote (só o painel
    escreve nela): com ela, o piso é o da linha DELE — e o Normal volta a poder fechar em 300."""
    linhas = [_linha("400", programa="p1"), _linha("800", programa="p2")]

    assert await _piso(linhas, [{"programa_id": "p1"}]) == (Decimal("300.00"), "programa_vendido")
    assert await _piso(linhas, [{"programa_id": "p2"}]) == (Decimal("600.00"), "programa_vendido")


async def test_dois_servicos_vendidos_voltam_a_ser_ambiguos() -> None:
    """Pacote que é a soma de dois programas não tem "o programa" a que amarrar o piso — cai na
    regra da duração (mesmo fail-closed do `_base_do_pacote` do extra de fetiche)."""
    linhas = [_linha("400", programa="p1"), _linha("800", programa="p2")]

    assert await _piso(linhas, [{"programa_id": "p1"}, {"programa_id": "p2"}]) == (
        Decimal("600.00"),
        "duracao_ambigua",
    )


# --- dedução do pacote pelo preço COTADO (decisão de 11/08/2026) ----------------------------------

_TABELA_LUCIA = [_linha("400", programa="p1"), _linha("800", programa="p2")]


async def test_preco_cotado_identifica_o_pacote_BARATO() -> None:
    """A cotação de 400 na conversa diz que o pacote em jogo é o Normal — piso 300, não os 600 do
    Completo. Sem isto, fechar o Normal pelo preço CHEIO escalava `fora_de_oferta`."""
    assert await _piso(_TABELA_LUCIA, falas=["Fica 400 1h no meu local amor"]) == (
        Decimal("300.00"),
        "preco_cotado",
    )


async def test_preco_cotado_identifica_o_pacote_CARO() -> None:
    """O outro lado da mesma dedução: cotado o Completo, o piso é o DELE (600) — é o que fecha o
    furo original sem depender do painel."""
    assert await _piso(_TABELA_LUCIA, falas=["O completo sai por 800 amor"]) == (
        Decimal("600.00"),
        "preco_cotado",
    )


async def test_cotacao_que_o_scanner_nao_reconhece_cai_no_fallback() -> None:
    """O limite conhecido da dedução: `precos_ofertados_na_fala` é ESTREITO de propósito (o mesmo
    detector julga a bolha na saída), e a fala "O completo é 800 a 1h amor" — que é literalmente a
    frase do <girias_do_cliente> — não casa nenhum dos contextos monetários dele ("é X" não está
    na lista, e o padrão preço+duração exige "800 1h", sem o "a" no meio).

    Não é regressão: sem dedução vale o fallback, que é o comportamento de hoje para TODA venda
    ambígua. É perda de recall — e a fronteira que uma revisão do scanner (compartilhado com o
    output_guard) teria de mover."""
    assert await _piso(_TABELA_LUCIA, falas=["O completo é 800 a 1h amor"]) == (
        Decimal("600.00"),
        "duracao_ambigua",
    )


async def test_cotacao_do_TURNO_conta_mesmo_sem_estar_no_historico() -> None:
    """O caso mais comum: `valor_acordado` é gravado JÁ NA COTAÇÃO, então a única cotação que
    existe é a bolha que a IA acabou de escrever — ela ainda não está em `mensagens`."""
    assert await _piso(_TABELA_LUCIA, fala_do_turno="sai por 800 a 1h amor") == (
        Decimal("600.00"),
        "preco_cotado",
    )


async def test_preco_em_clausula_negada_nao_deduz_pacote() -> None:
    """A dedução herda o cuidado do valor fantasma: "não consigo por 800 não" cita o número e não
    cota pacote nenhum — sem cotação válida, vale o fallback rigoroso."""
    assert await _piso(_TABELA_LUCIA, falas=["Poxa amor, não consigo por 800 não"]) == (
        Decimal("600.00"),
        "duracao_ambigua",
    )


async def test_preco_cotado_que_nao_e_de_nenhuma_linha_nao_deduz() -> None:
    """Contraproposta de desconto (350) não é preço de tabela: não identifica pacote, e o piso
    volta a ser o mais alto."""
    assert await _piso(_TABELA_LUCIA, falas=["consigo 350 se fechar agora"]) == (
        Decimal("600.00"),
        "duracao_ambigua",
    )


async def test_dois_pacotes_cotados_e_valor_no_cheio_identifica_a_linha() -> None:
    """A IA cotou os DOIS (o cliente perguntou o preço de cada um). O pacote volta a ser ambíguo —
    mas um fechamento em exatamente 400 é o Normal vendido no CHEIO, e uma guarda de piso de
    DESCONTO não tem desconto nenhum a julgar aí."""
    falas = ["O normal fica 400 amor", "O completo sai por 800 amor"]

    assert await _piso(_TABELA_LUCIA, falas=falas, valor="400") == (
        Decimal("300.00"),
        "preco_cotado",
    )
    assert await _piso(_TABELA_LUCIA, falas=falas, valor="800") == (
        Decimal("600.00"),
        "preco_cotado",
    )


async def test_dois_pacotes_cotados_com_valor_descontado_e_ambiguo() -> None:
    """Mesma conversa, valor que NÃO é preço cheio de nenhuma das linhas: aí é desconto de verdade
    sobre um pacote que ninguém sabe qual é — fallback rigoroso, o piso mais alto."""
    falas = ["O normal fica 400 amor", "O completo sai por 800 amor"]

    assert await _piso(_TABELA_LUCIA, falas=falas, valor="350") == (
        Decimal("600.00"),
        "duracao_ambigua",
    )


async def test_duracao_de_piso_unico_nao_le_a_conversa() -> None:
    """O cadastro da Catarina (uma linha por duração): não há ambiguidade a desfazer, então a
    dedução não pode mudar o número e a janela de falas nem é lida — a origem segue `duracao_unica`
    (a série de prod não muda de significado) e o fechamento não custa uma query a mais."""
    conn = _FakeConnDoPacote([_linha("400")], falas=["Fica 400 1h amor"])

    assert await _piso_do_pacote(
        conn,  # type: ignore[arg-type]
        _ATENDIMENTO,
        "m1",
        Decimal("1"),
        valor=Decimal("400"),
        conversa_id="c1",
    ) == (Decimal("300.00"), "duracao_unica")
    assert not [sql for sql in conn.sqls if "mensagens" in sql]


async def test_servico_vendido_vence_a_cotacao() -> None:
    """Ordem de força da evidência: o painel gravou o Completo, a conversa cotou 400 — vale o
    painel. A cotação é dedução; `atendimento_servicos` é o registro."""
    assert await _piso(_TABELA_LUCIA, [{"programa_id": "p2"}], falas=["Fica 400 1h amor"]) == (
        Decimal("600.00"),
        "programa_vendido",
    )


async def test_programa_vendido_sem_linha_na_duracao_escala() -> None:
    """O pacote vendido não existe naquela duração: sem piso, escala (fail-closed)."""
    assert await _piso([_linha("400", programa="p1")], [{"programa_id": "p9"}]) == (
        None,
        "sem_linha",
    )


async def test_sem_tabela_na_duracao_escala() -> None:
    assert await _piso([]) == (None, "sem_linha")


def _contador(origem: str, resultado: str) -> float:
    # Gotcha: `get_sample_value` NAO duplica o sufixo `_total` (ver tests/test_judge_conduta_metrica).
    return (
        REGISTRY.get_sample_value(
            "agente_piso_pacote_total", {"origem": origem, "resultado": resultado}
        )
        or 0.0
    )


async def test_a_decisao_do_piso_vira_metrica() -> None:
    """Sem métrica, o próximo caso passa igualmente despercebido: era a ausência de rastro (não a
    conta errada) que fazia a venda abaixo do piso ser invisível. Prova também a ORDEM das labels
    — `origem` primeiro —, que o fallback sem prometheus_client obriga a ser posicional."""
    conn = _FakeConnDoPacote([_linha("400", programa="p1"), _linha("800", programa="p2")])
    antes = _contador("duracao_ambigua", "escalado")

    await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "300"})  # type: ignore[arg-type]

    assert _contador("duracao_ambigua", "escalado") == antes + 1


async def test_a_deducao_pelo_cotado_tambem_vira_metrica() -> None:
    """A série nova: `origem="preco_cotado"` é o que mede se a dedução está pegando. Ela caindo com
    `duracao_ambigua` subindo = a IA está fechando sem cotar antes (ou o scanner de fala parou de
    reconhecer a cotação)."""
    conn = _FakeConnDoPacote(_TABELA_LUCIA, falas=["Fica 400 1h no meu local amor"])
    antes = _contador("preco_cotado", "aceito")

    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "400"}) is False  # type: ignore[arg-type]

    assert _contador("preco_cotado", "aceito") == antes + 1


async def test_abaixo_do_piso_julga_pelo_pacote_e_nao_pela_linha_mais_barata() -> None:
    """A ponta que o domínio consome, sem cotação nenhuma na conversa: com Normal 400 /
    Completo 800 na 1h e nenhum serviço gravado, os 300 (piso do Normal) deixam de passar como se
    fossem piso do Completo."""
    conn = _FakeConnDoPacote([_linha("400", programa="p1"), _linha("800", programa="p2")])

    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "300"}) is True  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "600"}) is False  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "800"}) is False  # type: ignore[arg-type]


async def test_venda_normal_do_pacote_barato_NAO_escala_mais() -> None:
    """O falso-positivo que motivou a correção: a IA cotou 400, o cliente fechou em 400 — preço
    cheio, desconto nenhum. Isso escalava `fora_de_oferta` (piso ambíguo 600) em TODA venda do
    pacote mais barato, que é o caso comum, não o raro."""
    conn = _FakeConnDoPacote(_TABELA_LUCIA, falas=["Fica 400 1h no meu local amor"])

    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "400"}) is False  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "300"}) is False  # type: ignore[arg-type]
    # O desconto do NORMAL tem fim: abaixo do piso dele, escala como sempre escalou.
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "250"}) is True  # type: ignore[arg-type]


async def test_completo_cotado_nao_fecha_no_piso_do_normal() -> None:
    """O furo original, agora fechado pela conversa (sem depender de o painel gravar o serviço):
    cotado o Completo de 800, os 300 do Normal são 62% de desconto e escalam."""
    conn = _FakeConnDoPacote(_TABELA_LUCIA, falas=["O completo sai por 800 amor"])

    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "300"}) is True  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "800"}) is False  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "600"}) is False  # type: ignore[arg-type]


async def test_cotacao_do_turno_chega_pela_fala_da_ia() -> None:
    """A porta pela qual a cotação deste turno entra em `_abaixo_do_piso` (mesma do valor
    fantasma): sem ela, a venda que cota e fecha no MESMO turno cairia no fallback rigoroso."""
    conn = _FakeConnDoPacote(_TABELA_LUCIA)

    assert (
        await _abaixo_do_piso(
            conn,  # type: ignore[arg-type]
            _ATENDIMENTO,
            {"valor_acordado": "400"},
            "Fica 400 1h no meu local amor",
        )
        is False
    )
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "400"}) is True  # type: ignore[arg-type]


async def test_catarina_uma_linha_por_duracao_nao_ganha_escalada_nova() -> None:
    """O cadastro real de hoje: uma linha na duração. Fecha no cheio, fecha no piso, e só abaixo
    dele escala — exatamente como antes da mudança, com ou sem cotação na conversa."""
    conn = _FakeConnDoPacote([_linha("400")], falas=["Fica 400 1h amor"])

    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "400"}) is False  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "300"}) is False  # type: ignore[arg-type]
    assert await _abaixo_do_piso(conn, _ATENDIMENTO, {"valor_acordado": "299"}) is True  # type: ignore[arg-type]


# --- o piso ABSOLUTO da linha (`preco_minimo`, 11/08/2026) ----------------------------------------


def test_minimo_clampa_a_conta_percentual() -> None:
    """Regra da casa (percentual) vs regra desta linha (mínimo): vence a mais apertada. Os 30min
    da Catarina são cadastrados como 250 = o mínimo dela; sem o clamp o teto sairia 187,50."""
    assert piso_de_desconto(Decimal("250"), Decimal("250")) == Decimal("250")
    assert degrau_de_desconto(Decimal("250"), Decimal("250")) == Decimal("250")


def test_minimo_no_meio_do_caminho_corta_so_o_teto() -> None:
    """Mínimo entre o degrau e o teto: a primeira contraproposta (350) segue de pé, a última para
    no piso cadastrado em vez dos 25% cheios."""
    assert degrau_de_desconto(Decimal("400"), Decimal("320")) == Decimal("350.000")
    assert piso_de_desconto(Decimal("400"), Decimal("320")) == Decimal("320")


def test_minimo_folgado_nao_muda_nada() -> None:
    """Piso abaixo do que o percentual já permite é inerte — é o caso de toda linha com
    `preco_minimo` NULL (a coluna nasceu vazia em prod)."""
    assert piso_de_desconto(Decimal("400"), Decimal("100")) == Decimal("300.00")
    assert piso_de_desconto(Decimal("400"), None) == Decimal("300.00")


async def test_linha_nao_descontavel_nao_vira_contraproposta() -> None:
    """`preco_minimo == preco`: a conta clampada devolve o próprio preço de tabela, e mostrá-lo à
    IA a mandaria "oferecer" 250 sobre uma tabela de 250 — concessão de zero real. A cauda cala."""
    assert await _oferta([_linha("250", "250")], n=1) is None
    assert await _oferta([_linha("250", "250")], n=0) is None


async def test_minimo_ambiguo_entre_linhas_de_mesmo_preco_usa_o_mais_apertado() -> None:
    """Mesmo preço, pisos diferentes: sem saber qual pacote ele leva, só a oferta mais ALTA é
    válida para qualquer um dos dois."""
    assert await _oferta([_linha("400"), _linha("400", "350")], n=1) == Decimal("350")


# --- como a duração fracionária CHEGA na fala (filtro do template) --------------------------------


def test_duracao_de_pacote_fala_meia_hora_como_o_cliente_fala() -> None:
    """Os templates concatenavam "h" na variável crua: o pacote de 30min sairia "(0.5h)" na cauda
    e a IA repassaria "0,5h" ao cliente que pediu "meia hora"."""
    from barra.agente.persona import _duracao_de_pacote

    assert _duracao_de_pacote("0.5") == "30min"
    assert _duracao_de_pacote(Decimal("0.5")) == "30min"
    assert _duracao_de_pacote("1") == "1h"
    assert _duracao_de_pacote(Decimal("12.00")) == "12h"
    assert _duracao_de_pacote("1.5") == "1h30"


# --------------------------------------------------------------------- fallback 2 do degrau
# Validação ao vivo de 11/08: "faz por 300 a hora?" não tem dígito de duração — o fallback 1
# (duracao_pedida_no_burst) devolve None e a <escada_disponivel> sumia no turno da objeção.
# O fallback 2 infere a linha em negociação pelo VALOR proposto (menor preço da tabela acima).


def _tabela() -> dict[float, list[Decimal]]:
    return {1.0: [Decimal("400")], 2.0: [Decimal("700")], 12.0: [Decimal("2000")]}


def test_fallback2_proposto_abaixo_da_menor_linha_aponta_1h() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    assert _horas_da_linha_contraproposta(["faz por 300 a hora?"], _tabela()) == 1.0


def test_fallback2_eco_da_tabela_e_descartado_antes_de_decidir() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    # "400 tá salgado" cita o 400 cotado (eco) + o 300 proposto — só o 300 decide.
    assert _horas_da_linha_contraproposta(["400 ta salgado demais, faz 300?"], _tabela()) == 1.0


def test_fallback2_proposto_entre_linhas_aponta_a_linha_de_cima() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    assert _horas_da_linha_contraproposta(["consigo 500 no pix"], _tabela()) == 2.0


def test_fallback2_proposto_acima_de_toda_a_tabela_devolve_none() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    assert _horas_da_linha_contraproposta(["pago 3000"], _tabela()) is None


def test_fallback2_dois_valores_novos_e_ambiguo() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    # Dois valores ancorados em verbo apontando linhas DIFERENTES (300→1h, 650→2h): sem decisão.
    assert (
        _horas_da_linha_contraproposta(["faz 300 a hora, ou pago 650 as duas"], _tabela()) is None
    )


def test_fallback2_sem_valor_citado_devolve_none() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    assert _horas_da_linha_contraproposta(["ta salgado amor"], _tabela()) is None


def test_fallback2_menor_linha_acima_empatada_em_duas_duracoes_e_ambigua() -> None:
    from barra.agente.nos.prepare_context import _horas_da_linha_contraproposta

    tabela = {1.0: [Decimal("400")], 1.5: [Decimal("400")]}
    assert _horas_da_linha_contraproposta(["faz 300?"], tabela) is None
