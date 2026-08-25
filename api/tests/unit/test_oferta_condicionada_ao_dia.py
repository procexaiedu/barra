"""Oferta condicionada ao dia + subir o tempo antes de descer o preço (ADR-0041) — a fiação.

A DECISÃO e o par de números moram no domínio (`oferta_condicionada_ao_dia`, testada em
`test_piso_de_desconto.py`); o RENDER mora em `test_contraproposta_flag.py`. Aqui fica o meio: quem
decide que existe um SALTO na mesa, como o par vira TOTAL quando o salto tem extra pago junto, e
qual é o pacote maior que a conduta de subir o tempo oferece.

Sem DB, sem crédito.
"""

from decimal import Decimal
from typing import Any, ClassVar

from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import (
    _horas_da_linha_cotada,
    _pacote_maior_na_tabela,
    _par_condicionado_ao_dia,
    _salto_na_mesa,
    _SaltoNaMesa,
)

# --- o SALTO: quando a oferta condicionada vale ---------------------------------------------------
# NÃO vale para toda primeira cotação — prometer "se vier hoje sai por X" a quem nunca reclamou de
# preço entrega o teto de desconto a todo cliente, que é a erosão que o ADR-0004 mandou monitorar.
# Vale quando o número que entra agora é MAIOR do que o que ele já ouviu.

_COMPOSICAO = {"nome": "Acompanhante dele — mulher", "preco": None, "cobra_por_pessoa": True}
_ANAL = {"nome": "Anal", "preco": Decimal("300"), "cobra_por_pessoa": False}
_BEIJO = {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False}
_CARDAPIO: dict[str, list[dict[str, Any]]] = {"fetiches": [_COMPOSICAO, _ANAL, _BEIJO]}


def _contexto(**over: Any) -> ContextoDoTurno:
    """Só os campos que `_salto_na_mesa` lê — o resto do dataclass é irrelevante aqui."""
    base: dict[str, Any] = {
        "agora": None,
        "data_atual": None,
        "hora_atual": None,
        "numero_curto": None,
        "estado": "Qualificado",
        "estado_humano": "combinando o encontro",
        "tipo_humano": None,
        "slots_faltantes": [],
        "proximo_passo": "",
        "turnos_cobrando_o_mesmo": 0,
        "acao_pendente": None,
        "intencao": None,
        "tipo_atendimento": None,
        "urgencia": None,
        "pix_status": "",
        "data_desejada": None,
        "horario_desejado": None,
        "horario_ja_combinado": False,
        "horario_evidenciado": False,
        "endereco": None,
        "bairro": None,
        "valor_fechado": None,
        "valor_aceito": False,
        "duracao_fechada": None,
        "n_contrapropostas": 0,
        "escada_estado": "sem_dia",
        "contraproposta_disponivel": None,
        "aceite_do_valor_dele": None,
        "encontro_do_dia": "dia_desconhecido",
        "patamar_da_mesa": "cheio",
        "preco_na_mesa": True,
        "n_perguntas_de_horario": 0,
        "dia_ja_sondado_hist": False,
        "book_ja_enviado": False,
        "endereco_ja_enviado": False,
        "amiga_ja_ofertada": False,
        "foto_portaria_ja_pedida": False,
        "motivo_resgate_ja_perguntado": False,
        "local_endereco": None,
        "local_nome": None,
        "numero_liberado": False,
        "tabela_max_horas": 0.0,
        "sem_periodo_longo": False,
        "sem_fetiches": False,
        "sem_menage": False,
        "sem_video_chamada": False,
        "sem_externo": False,
        "recorrente": False,
        "observacoes_internas": None,
        "ultimo_motivo_perda": None,
        "cliente_nome": None,
        "historico_anteriores": None,
        "bloqueios": [],
        "disponibilidade": [],
        "horario_minimo": None,
        "horario_minimo_apresentado": None,
        "proximo_horario": None,
        "janelas_livres": [],
        "min_desde_ultima_msg_cliente": None,
        "combinado_hora": None,
        "min_para_combinado": None,
    }
    return ContextoDoTurno(**{**base, **over})


def test_composicao_na_janela_e_salto() -> None:
    """O exemplo do dono do produto: "quanto para casal ?" depois de ele já ter ouvido a 1h. O
    número que entra agora é o pacote MAIS a segunda pessoa — salto sobre o que estava na mesa."""
    salto = _salto_na_mesa(_contexto(composicao_em_pauta=True), _CARDAPIO, Decimal("1"), None)

    assert salto is not None
    assert salto.horas == Decimal("1")
    assert salto.extras == (_COMPOSICAO,)


def test_fetiche_pago_no_burst_e_salto() -> None:
    contexto = _contexto(fetiches_em_pauta=({"nome": "Anal", "status": "extra"},))

    salto = _salto_na_mesa(contexto, _CARDAPIO, Decimal("1"), None)

    assert salto is not None and salto.extras == (_ANAL,)


def test_fetiche_incluso_nao_e_salto() -> None:
    """Incluso não muda o número: não há salto a condicionar."""
    contexto = _contexto(fetiches_em_pauta=({"nome": "Beijo na boca", "status": "incluso"},))

    assert _salto_na_mesa(contexto, _CARDAPIO, Decimal("1"), None) is None


def test_pacote_maior_pedido_e_salto_sem_extra() -> None:
    """Upgrade de duração: o salto é a própria linha maior, e o par sai dela — sem extra a somar."""
    salto = _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), 2.0)

    assert salto is not None
    assert (salto.horas, salto.extras) == (Decimal("2"), ())


def test_duracao_menor_pedida_nao_e_salto() -> None:
    """Descer o tempo é o degrau 3 do <desconto> ("250 30minutos amor"), não um salto."""
    assert _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), 0.5) is None


def test_primeira_cotacao_limpa_nao_e_salto() -> None:
    """A fronteira que o escopo existe para segurar: cliente que só perguntou o preço não recebe
    oferta condicionada nenhuma — vale o <escada_travada_sem_o_dia> de sempre."""
    assert _salto_na_mesa(_contexto(), _CARDAPIO, Decimal("1"), None) is None
    assert _salto_na_mesa(_contexto(composicao_em_pauta=True), None, Decimal("1"), None) is None
    assert _salto_na_mesa(_contexto(composicao_em_pauta=True), _CARDAPIO, None, None) is None


# --- o PAR já formatado ---------------------------------------------------------------------------


class _FakeConnCatarina:
    """A tabela da Catarina no programa Normal: 30min 250/250 · 1h 400/300 · 2h 800/600."""

    _TABELA: ClassVar[dict[Decimal, tuple[Decimal, Decimal]]] = {
        Decimal("0.5"): (Decimal("250"), Decimal("250")),
        Decimal("1"): (Decimal("400"), Decimal("300")),
        Decimal("2"): (Decimal("800"), Decimal("600")),
    }

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        horas = Decimal(str(params[-1])) if params else Decimal("1")
        preco, minimo = self._TABELA.get(horas, (None, None))
        linhas = (
            []
            if preco is None
            else [
                {
                    "programa_id": "p1",
                    "nome": "Normal",
                    "preco": preco,
                    "preco_minimo": minimo,
                }
            ]
        )

        class _R:
            async def fetchall(self) -> list[dict[str, Any]]:
                return linhas

            async def fetchone(self) -> dict[str, Any] | None:
                return linhas[0] if linhas else None

        return _R()


async def _par(salto: _SaltoNaMesa) -> Any:
    return await _par_condicionado_ao_dia(_FakeConnCatarina(), "m1", salto)  # type: ignore[arg-type]


async def test_par_sem_extra_e_o_da_linha() -> None:
    assert await _par(_SaltoNaMesa(horas=Decimal("2"), extras=())) == ("600", "700")


async def test_par_com_composicao_e_o_TOTAL_nos_dois_patamares() -> None:
    """O número da fala que o dono ditou ("se vier hoje consigo fazer 600 uma hora"): 1h para dois
    é o pacote MAIS a segunda pessoa, e desde o ADR-0039 a segunda pessoa custa o mesmo que
    qualquer extra — a linha de 1h no MESMO patamar. Piso 300+300 = 600; degrau 350+350 = 700.

    Mandar a IA somar o par do pacote com o extra é a conta de cabeça que o ADR-0038 proíbe: por
    isso o par já sai somado."""
    salto = _SaltoNaMesa(horas=Decimal("1"), extras=(_COMPOSICAO,))

    assert await _par(salto) == ("600", "700")


async def test_par_com_extra_de_preco_CADASTRADO_nao_condiciona() -> None:
    """Preço cadastrado não acompanha a escada (ADR-0030 revisado): o extra é o mesmo nos dois
    patamares e o par continua separado só pelo pacote. Continua válido — o que o veto pega é o
    par colapsado, e aqui 300+300=600 e 350+300=650 seguem distintos."""
    salto = _SaltoNaMesa(horas=Decimal("1"), extras=(_ANAL,))

    assert await _par(salto) == ("600", "650")


async def test_par_de_linha_nao_descontavel_nao_existe() -> None:
    assert await _par(_SaltoNaMesa(horas=Decimal("0.5"), extras=())) is None


async def test_par_com_extra_sem_pacote_de_1h_e_fail_closed() -> None:
    """Pacote de menos de 1h não tem fetiche pago (CONTEXT.md): sem extra calculável, sem par."""
    assert await _par(_SaltoNaMesa(horas=Decimal("0.5"), extras=(_COMPOSICAO,))) is None


# --- o pacote MAIOR da tabela (subir o tempo antes de descer o preço) ------------------------------


def _tabela() -> dict[float, list[Decimal]]:
    return {
        0.5: [Decimal("250")],
        1.0: [Decimal("400")],
        2.0: [Decimal("800")],
        6.0: [Decimal("2000")],
    }


def test_pacote_maior_e_o_imediatamente_acima_nao_o_maior_de_todos() -> None:
    """Pular da 1h para o pernoite não é subir o tempo — é outra venda."""
    assert _pacote_maior_na_tabela(_tabela(), Decimal("1")) == {"horas": "2", "preco": "800"}
    assert _pacote_maior_na_tabela(_tabela(), Decimal("0.5")) == {"horas": "1", "preco": "400"}


def test_sem_pacote_acima_nao_ha_o_que_subir() -> None:
    assert _pacote_maior_na_tabela(_tabela(), Decimal("6")) is None
    assert _pacote_maior_na_tabela(_tabela(), None) is None
    assert _pacote_maior_na_tabela(None, Decimal("1")) is None


def test_duracao_acima_ambigua_e_fail_closed() -> None:
    """Mesmo critério do <pacote_em_pauta>: com dois preços presenciais na duração, o número
    errado é pior que nenhum."""
    tabela = {1.0: [Decimal("400")], 2.0: [Decimal("800"), Decimal("1400")]}

    assert _pacote_maior_na_tabela(tabela, Decimal("1")) is None


# --- o gate, ponta a ponta ------------------------------------------------------------------------
# As duas condutas são resolvidas em `_anexar_contexto_dinamico` (e não em `_resolver_variaveis`)
# porque dependem do cardápio já casado contra o burst. O gate é estreito de propósito: preço na
# mesa, escada intacta e, para a oferta condicionada, dia desconhecido + salto.


class _FakeConnDoTurno(_FakeConnCatarina):
    """A Catarina nas queries de tabela; vazio em todo o resto (mensagens, bloqueios, histórico)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        if "modelo_programas" in sql:
            return await super().execute(sql, params)

        class _R:
            async def fetchall(self) -> list[Any]:
                return []

            async def fetchone(self) -> None:
                return None

        return _R()


_COMPOSICAO_ROW = {
    "nome": "Acompanhante dele — mulher",
    "preco": None,
    "cobra_por_pessoa": True,
}
_CARDAPIO_DA_CATARINA: dict[str, list[dict[str, Any]]] = {
    "fetiches": [_COMPOSICAO_ROW],
    "programas": [{"nome": "Normal", "duracao_nome": "1 hora", "preco": Decimal("400")}],
}


async def _turno(fala: str, *, mensagens: Any = None, **over: Any) -> Any:
    from datetime import UTC, datetime

    from langchain_core.messages import HumanMessage

    from barra.agente.contexto import ContextAgente
    from barra.agente.nos.prepare_context import _anexar_contexto_dinamico

    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 8, 11, 17, 30, tzinfo=UTC),
    )
    atendimento: dict[str, Any] = {
        "estado": "Qualificado",
        "n_contrapropostas": 0,
        "duracao_horas": Decimal("1"),
        "valor_acordado": Decimal("400"),
        "data_desejada": None,
        **over,
    }
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnDoTurno(),  # type: ignore[arg-type]
        ctx,
        mensagens if mensagens is not None else [HumanMessage(fala)],
        atendimento=atendimento,
        precos_por_horas={1.0: [Decimal("400")], 2.0: [Decimal("800")]},
        cardapio_rows=_CARDAPIO_DA_CATARINA,
    )
    return contexto


async def test_casal_com_o_dia_desconhecido_acende_a_oferta_condicionada() -> None:
    """A conversa do dono do produto: ele já ouviu a 1h, volta com "e pra nós dois ?" e o dia
    nunca foi dito. O contexto entrega 600 e 700 — a IA não improvisa nem o primeiro nem o
    segundo."""
    contexto = await _turno("e pra nós dois ?")

    assert contexto.escada_estado == "sem_dia"
    assert (contexto.oferta_se_hoje, contexto.oferta_se_outro_dia) == ("600", "700")


async def test_objecao_sem_salto_nao_acende_a_oferta_condicionada() -> None:
    """A fronteira do escopo: cliente que só achou caro continua no <escada_travada_sem_o_dia> —
    dar o teto a quem nunca pediu é a erosão que o ADR-0004 mandou monitorar."""
    contexto = await _turno("nossa, ta caro demais")

    assert contexto.escada_estado == "sem_dia"
    assert contexto.oferta_se_hoje is None and contexto.oferta_se_outro_dia is None


async def test_o_pacote_maior_entra_enquanto_nenhum_desconto_saiu() -> None:
    """Subir o tempo é a jogada ANTERIOR à escada: vale desde o preço na mesa, sem depender de
    objeção. E o tempo dele é desconhecido enquanto ele não nomear uma duração."""
    contexto = await _turno("ta caro")

    assert contexto.pacote_maior == {"horas": "2", "preco": "800"}
    assert contexto.tempo_dele_desconhecido is True


async def test_duracao_dita_por_ele_desliga_a_sondagem_de_tempo() -> None:
    """Ele dizendo "1h" já responde o que a sondagem procuraria — o pacote maior continua
    oferecível, mas não há o que perguntar."""
    contexto = await _turno("quanto fica 1h ?")

    assert contexto.pacote_maior == {"horas": "2", "preco": "800"}
    assert contexto.tempo_dele_desconhecido is False


async def test_com_a_escada_ja_descida_nenhuma_das_duas_condutas_renasce() -> None:
    """Depois de uma contraproposta, subir o tempo virou upsell em cima de desconto já dado e a
    oferta condicionada perdeu o sentido (o número já saiu)."""
    contexto = await _turno("e pra nós dois ?", n_contrapropostas=1)

    assert contexto.oferta_se_hoje is None
    assert contexto.pacote_maior is None


# --- fallback 3 da duração em pauta: o preço que a PRÓPRIA IA cotou (campanha 13/08) --------------
# Caso eb02:26311003246742: a IA cotou "400 1h", o belief não gravou `duracao_horas` e o cliente
# REPERGUNTOU o preço — sem dígito de duração no burst (fallback 1) e sem valor proposto por ele
# (fallback 2), `duracao_em_pauta` ficava None e o <pacote_maior_na_sua_tabela> sumia da cauda em
# TODA repergunta de preço antes de alguém nomear duração. O preço que ELA pôs na mesa resolve a
# linha de volta (`_horas_da_linha_cotada`), com o fail-closed da família.


def test_preco_cotado_pela_ia_resolve_a_linha_da_tabela() -> None:
    """Igualdade EXATA, não "menor linha acima": a cotação sai da tabela por construção — a
    heurística do valor PROPOSTO (`_horas_da_linha_contraproposta`) pegaria a linha de cima."""
    assert _horas_da_linha_cotada("400", _tabela()) == 1.0
    assert _horas_da_linha_cotada("800", _tabela()) == 2.0


def test_preco_cotado_que_nao_e_de_linha_nenhuma_e_fail_closed() -> None:
    """O total com extra ou a contraproposta dela (350) não são preço de tabela: zero linhas
    casadas -> None, e o degrau degrada como sempre."""
    assert _horas_da_linha_cotada("350", _tabela()) is None


def test_preco_cotado_em_duas_linhas_e_fail_closed() -> None:
    """Mesmo preço em duas durações: escolher seria chutar a linha — None."""
    tabela = {1.0: [Decimal("400")], 1.5: [Decimal("400")]}

    assert _horas_da_linha_cotada("400", tabela) is None


def test_sem_preco_sem_tabela_ou_preco_ilegivel_devolve_none() -> None:
    assert _horas_da_linha_cotada(None, _tabela()) is None
    assert _horas_da_linha_cotada("400", None) is None
    assert _horas_da_linha_cotada("uns 400", _tabela()) is None


async def test_repergunta_de_preco_sem_belief_reancora_pelo_preco_cotado() -> None:
    """O turno inteiro do eb02: cotação de "400 1h" na janela, belief sem duração e sem valor, e
    ele repergunta o preço — o degrau de upsell (2h/800) volta a renderizar."""
    from datetime import UTC, datetime

    from langchain_core.messages import AIMessage, HumanMessage

    contexto = await _turno(
        "quanto fica mesmo?",
        mensagens=[
            AIMessage("Fica 400 1h no meu local amor"),
            HumanMessage("quanto fica mesmo?"),
        ],
        duracao_horas=None,
        valor_acordado=None,
        cotacao_enviada_em=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert contexto.preco_cotado_valor == "400"
    assert contexto.pacote_maior == {"horas": "2", "preco": "800"}


async def test_repergunta_com_cotacao_fora_da_tabela_segue_fail_closed() -> None:
    """A cotação vigente é uma contraproposta dela (500, que não é linha da tabela): nada a
    resolver — o comportamento antigo (sem degrau) fica de pé."""
    from datetime import UTC, datetime

    from langchain_core.messages import AIMessage, HumanMessage

    contexto = await _turno(
        "quanto fica mesmo?",
        mensagens=[
            AIMessage("consigo 500 se vier hoje amor"),
            HumanMessage("quanto fica mesmo?"),
        ],
        duracao_horas=None,
        valor_acordado=None,
        cotacao_enviada_em=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert contexto.pacote_maior is None
