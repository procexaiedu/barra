"""Contador determinístico de contrapropostas (padrão A2, agente/CLAUDE.md) + a escada que ele
gateia.

A disciplina do desconto dependia da janela de 20 msgs: contraproposta fora da janela → LLM podia
ofertar de novo. Agora a flag é MATERIALIZADA: `contar_contrapropostas` (agente/_disciplina.py)
detecta a forma canônica ("Consigo 500 se você vier hoje") no write-time (workers/envio.py) e
carimba `atendimentos.n_contrapropostas`; `_resolver_variaveis` lê a coluna (não reescaneia as
falas da IA) e o template injeta a tag instrutiva certa pra cada rodada.

QUANTAS rodadas existem deixou de ser constante (decisão do dono do produto, 11/08/2026): depende
de o encontro ser HOJE (piso direto, uma só — agenda de hoje é ociosidade que não volta), outro
dia (degrau e depois piso, ADR-0031) ou dia ainda não dito (nenhum desconto; sonda-se o dia). O
contador continua sendo o mesmo; quem sabe onde ele para é `estado_da_escada`.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from barra.agente._disciplina import contar_contrapropostas
from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import _resolver_variaveis, _valor_dele_no_prompt
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.conversas.modelos import DirecaoMensagem

_AGORA_UTC = datetime(2026, 8, 11, 17, 30, tzinfo=UTC)
_HOJE = date(2026, 8, 11)
_OUTRO_DIA = date(2026, 8, 13)

# --- detector puro (agente/_disciplina.py) ------------------------------------------------------


def test_conta_contrapropostas_canonicas() -> None:
    assert contar_contrapropostas(["Consigo 500 se você vier hoje 😊"]) == 1
    assert contar_contrapropostas(["Poxa amor\n\nConsigo 450 se fechar agora"]) == 1
    # acento/caixa não escondem ("CONSIGO", "consigo R$ 400")
    assert contar_contrapropostas(["CONSIGO 400 amor"]) == 1
    assert contar_contrapropostas(["consigo r$ 400 pra hoje"]) == 1


def test_conta_ate_duas_contrapropostas_no_mesmo_atendimento() -> None:
    historico = [
        "Oii",
        "600 1h no meu local",
        "Consigo 500 se você vier hoje 😊",
        "Poxa amor não consigo",
        "Consigo 450 se fechar agora 😊",
    ]
    assert contar_contrapropostas(historico) == 2


def test_conta_o_aceite_do_valor_dele_em_forma_natural() -> None:
    """ADR-0040: a rodada também é consumida quando quem nomeia o número é o CLIENTE e ela só diz
    sim. Sem isso a escada não esgota e a conversa vira leilão (700 -> 650 -> 620).

    A alternativa era prescrever no prompt UMA frase que o detector já lesse ("Consigo 700 sim
    amor") — recusada: conduta prescrita como frase vira tique, e uma frase com CARGA FUNCIONAL
    pune toda variação. Então o detector é que alarga, e o teste varia a fala de propósito."""
    assert contar_contrapropostas(["Fechado 700 amor, consigo às 21h ?"]) == 1
    assert contar_contrapropostas(["Tabom, 700 então / Te espero às 22h amor"]) == 1
    assert contar_contrapropostas(["Combinado 700 amor"]) == 1
    assert contar_contrapropostas(["Faço 700 sim amor"]) == 1
    assert contar_contrapropostas(["Fecho 700 amor"]) == 1
    assert contar_contrapropostas(["700 fechado então"]) == 1
    assert contar_contrapropostas(["Consigo 700 sim amor"]) == 1


def test_o_ramo_do_aceite_nao_confunde_cotacao_com_contraproposta() -> None:
    """A fronteira que o ramo novo não pode cruzar: cotação é "400 1h no meu local" e não gasta
    rodada nenhuma. Nenhum ramo casa número solto (o token de fechamento vem COLADO nele) e
    número seguido de DURAÇÃO está barrado por lookahead — é o que separa o aceite da cotação
    com muleta na frente."""
    assert contar_contrapropostas(["Fechado, 400 1h no meu local amor"]) == 0
    assert contar_contrapropostas(["400 1h no meu local", "Seria que horas amor ?"]) == 0
    assert contar_contrapropostas(["Podemos combinar 2h 1000, aproveitar bastante rs"]) == 0
    assert contar_contrapropostas(["Fechado amor", "Te espero às 21h"]) == 0
    # e a recusa continua não contando, com o token novo ou sem ele
    assert contar_contrapropostas(["Poxa amor, não consigo 700"]) == 0


def test_conta_o_consigo_com_verbo_ou_preposicao_no_meio() -> None:
    """A fala que o dono do produto ditou para a oferta condicionada ao dia (ADR-0041) — "se vier
    hoje consigo FAZER 600 uma hora" — não casava o ramo antigo, que exigia o número COLADO em
    "consigo". Medido em 11/08 no regex de então: só "consigo 600" dava True; "consigo fazer 600",
    "consigo te fazer por 600" e "consigo deixar em 600" davam False.

    O efeito do furo era o pior possível: o contador não andava, a escada nunca esgotava e a IA
    repetia a mesma oferta para sempre — e `patamar_da_mesa` desalinhava do que ela já tinha
    falado, que é de onde o extra de fetiche desce (ADR-0038)."""
    assert contar_contrapropostas(["se vier hoje consigo fazer 600 uma hora"]) == 1
    assert contar_contrapropostas(["consigo te fazer por 600"]) == 1
    assert contar_contrapropostas(["consigo deixar em 600"]) == 1
    assert contar_contrapropostas(["consigo 600 se vier hoje"]) == 1
    # variações da mesma família — o elo é opcional e aceita verbo, preposição, ou os dois
    assert contar_contrapropostas(["consigo por 600 amor"]) == 1
    assert contar_contrapropostas(["consigo em 600"]) == 1
    assert contar_contrapropostas(["Consigo te deixar em 700 hoje 😊"]) == 1
    assert contar_contrapropostas(["Hoje eu faço 600, outro dia fica 700"]) == 1


def test_o_elo_do_consigo_nao_derruba_nenhuma_fronteira() -> None:
    """As duas que o ramo tem de segurar, com o elo novo no meio.

    A RECUSA continua barrada pelo mesmo lookbehind (ele morde no "consigo", antes do elo). E o
    UPSELL da conduta de subir o tempo ("consigo fazer 2h por 800") NÃO é contraproposta: subir o
    ticket é venda, não desconto, e contá-lo gastaria uma rodada da escada num turno em que ela
    não desceu um centavo."""
    assert contar_contrapropostas(["nao consigo 600"]) == 0
    assert contar_contrapropostas(["não consigo fazer 600"]) == 0
    assert contar_contrapropostas(["não consigo te fazer por 600 amor"]) == 0
    assert contar_contrapropostas(["consigo fazer 2h por 800"]) == 0
    assert contar_contrapropostas(["400 1h no meu local"]) == 0
    assert contar_contrapropostas(["Podemos combinar 2h 1000, aproveitar bastante rs"]) == 0


def test_nao_flaga_recusa_nem_horario_nem_cotacao() -> None:
    # recusa da escada ("não consigo") não é contraproposta
    assert contar_contrapropostas(["Poxa amor não consigo"]) == 0
    # hora não é preço: 1-2 dígitos + h ficam fora do \d{3,}
    assert contar_contrapropostas(["Consigo às 22h amor", "consigo 14h sim"]) == 0
    # confirmação sem número e cotação de tabela (sem "consigo") ficam fora
    assert contar_contrapropostas(["Consigo sim amor", "600 1h no meu local"]) == 0
    assert contar_contrapropostas([]) == 0


# --- _resolver_variaveis lê a coluna materializada ----------------------------------------------
# A memória durável (e o reset em recorrência) deixou de vir de um scan das falas: cada atendimento
# tem sua PRÓPRIA coluna `n_contrapropostas`, carimbada no write-time. Aqui provamos só a LEITURA;
# a contagem no write-time (idempotente por bolha inserida) é coberta em test_envio_flags_disciplina.


class _FakeConnVazio:
    """Vazio em tudo: _resolver_variaveis recebe o atendimento por kwarg, não por query."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


class _FakeConnComTabela:
    """Igual ao vazio, menos na query de preços da duração: a modelo tem UM preço (400) em 1h."""

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


async def _contexto(
    atendimento: dict[str, Any], conn: Any = None, *, dia_confirmado_hoje: bool = False
) -> ContextoDoTurno:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        # Relógio injetado: a escada pergunta se o encontro é HOJE, e sem âncora de tempo o
        # `data_desejada` não tem contra o que ser comparado (cai em dia desconhecido).
        agora_utc=_AGORA_UTC,
    )
    return await _resolver_variaveis(
        conn or _FakeConnVazio(),  # type: ignore[arg-type]
        ctx,
        atendimento=atendimento,
        dia_confirmado_hoje=dia_confirmado_hoje,
    )


async def _n_contrapropostas(atendimento: dict[str, Any]) -> int:
    return (await _contexto(atendimento)).n_contrapropostas


async def test_le_contador_da_coluna() -> None:
    assert await _n_contrapropostas({"n_contrapropostas": 2}) == 2


async def test_atendimento_novo_zera() -> None:
    # Recorrência: atendimento novo nasce com a coluna no default 0 (row sem a chave → 0).
    assert await _n_contrapropostas({}) == 0
    assert await _n_contrapropostas({"n_contrapropostas": 0}) == 0


# --- o VALOR da rodada disponível, e QUAL rodada é (issue 16 + decisão de 11/08/2026) -----------
# O contador diz quantas contrapropostas já saíram; o DIA do encontro diz quantas existem e qual
# vem primeiro. Encontro hoje = piso direto, uma só; outro dia = degrau e depois piso; dia ainda
# não dito = nenhum número. Tudo sai da mesma função que julga a oferta
# (`contraproposta_da_escada`, dominio/atendimentos/service) — nunca de uma segunda conta.


def _negociando(n: int, dia: date | None = None) -> dict[str, Any]:
    """Atendimento com preço na mesa e ainda não aceito — a janela da objeção de preço."""
    return {
        "estado": "Qualificado",
        "n_contrapropostas": n,
        "duracao_horas": Decimal("1"),
        "valor_acordado": Decimal("400"),
        "data_desejada": dia,
    }


async def test_encontro_hoje_oferta_o_piso_ja_na_primeira_rodada() -> None:
    """Agenda de hoje é ociosidade que não volta: o desconto cheio sai de uma vez."""
    contexto = await _contexto(_negociando(0, _HOJE), _FakeConnComTabela())

    assert contexto.contraproposta_disponivel == "300"
    assert contexto.escada_estado == "ultima"
    assert contexto.encontro_do_dia == "hoje"


async def test_encontro_hoje_nao_tem_segunda_contraproposta() -> None:
    contexto = await _contexto(_negociando(1, _HOJE), _FakeConnComTabela())

    assert contexto.contraproposta_disponivel is None
    assert contexto.escada_estado == "esgotada"


async def test_outro_dia_negocia_devagar_degrau_e_depois_piso() -> None:
    aberta = await _contexto(_negociando(0, _OUTRO_DIA), _FakeConnComTabela())
    ultima = await _contexto(_negociando(1, _OUTRO_DIA), _FakeConnComTabela())
    fim = await _contexto(_negociando(2, _OUTRO_DIA), _FakeConnComTabela())

    assert (aberta.contraproposta_disponivel, aberta.escada_estado) == ("350", "aberta")
    assert (ultima.contraproposta_disponivel, ultima.escada_estado) == ("300", "ultima")
    assert (fim.contraproposta_disponivel, fim.escada_estado) == (None, "esgotada")


async def test_dia_ainda_nao_dito_nao_desce_numero_nenhum() -> None:
    """O terceiro caso: sem o dia, a escada não abre — a cauda manda defender o valor e sondar."""
    contexto = await _contexto(_negociando(0, None), _FakeConnComTabela())

    assert contexto.contraproposta_disponivel is None
    assert contexto.escada_estado == "sem_dia"
    assert contexto.encontro_do_dia == "dia_desconhecido"


async def test_hoje_dito_na_janela_deste_turno_ja_abre_a_escada() -> None:
    """O A2 do dia: ele acabou de responder "hoje sim" e a extração deste turno ainda não gravou.
    Sem isso a escada ficaria travada justamente no turno da objeção."""
    contexto = await _contexto(_negociando(0, None), _FakeConnComTabela(), dia_confirmado_hoje=True)

    assert contexto.contraproposta_disponivel == "300"
    assert contexto.escada_estado == "ultima"


async def test_sem_duracao_fechada_nao_ha_numero_a_mostrar() -> None:
    contexto = await _contexto(
        {"n_contrapropostas": 1, "data_desejada": _OUTRO_DIA}, _FakeConnComTabela()
    )
    assert contexto.contraproposta_disponivel is None


async def test_numero_so_com_cotacao_em_aberto_na_rodada_zero() -> None:
    # Sem valor cotado não há objeção de preço a responder (e o número solto convidaria a
    # ofertar desconto antes de ele pedir)…
    contexto = await _contexto(
        {"n_contrapropostas": 0, "duracao_horas": Decimal("1"), "data_desejada": _OUTRO_DIA},
        _FakeConnComTabela(),
    )
    assert contexto.contraproposta_disponivel is None
    assert contexto.preco_na_mesa is False
    # …e com o valor aceito a negociação de preço acabou.
    contexto = await _contexto(
        {**_negociando(0, _OUTRO_DIA), "sinais_qualificacao": {"aceita_valor": True}},
        _FakeConnComTabela(),
    )
    assert contexto.contraproposta_disponivel is None
    assert contexto.preco_na_mesa is False


async def test_patamar_da_mesa_acompanha_a_escada_do_encontro() -> None:
    """O que o extra de fetiche consome (ADR-0038): com encontro hoje, a 1ª contraproposta já
    deixou o valor da mesa no PISO — o extra desce junto para o piso, não para o degrau."""
    hoje = await _contexto(_negociando(1, _HOJE), _FakeConnComTabela())
    outro = await _contexto(_negociando(1, _OUTRO_DIA), _FakeConnComTabela())
    intacto = await _contexto(_negociando(0, _HOJE), _FakeConnComTabela())

    assert hoje.patamar_da_mesa == "piso"
    assert outro.patamar_da_mesa == "degrau"
    assert intacto.patamar_da_mesa == "cheio"


# --- render do template -------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_sem_contraproposta_nao_injeta_tag() -> None:
    assert "<ja_fez_contraproposta" not in _render(n_contrapropostas=0, escada_estado="aberta")
    assert "<ja_fez_contraproposta" not in _render()


def test_render_primeira_contraproposta_permite_a_ultima_rodada() -> None:
    out = _render(n_contrapropostas=1, escada_estado="ultima")
    assert '<ja_fez_contraproposta n="1">' in out
    assert "última" in out.lower()


def test_render_leva_o_numero_calculado_da_rodada_que_sobrou() -> None:
    out = _render(n_contrapropostas=1, escada_estado="ultima", contraproposta_disponivel="300")
    assert "ÚLTIMA contraproposta, que é 300" in out
    # o percentual e a política continuam fora da cauda (o cliente vê só a oferta).
    assert "%" not in out


def test_render_sem_numero_calculado_mantem_a_tag_como_antes() -> None:
    out = _render(n_contrapropostas=1, escada_estado="ultima")
    assert "ÚLTIMA contraproposta — antes de escalar com fora_de_oferta" in out


def test_render_escada_disponivel_leva_o_numero_da_primeira() -> None:
    out = _render(
        n_contrapropostas=0,
        escada_estado="aberta",
        preco_na_mesa=True,
        contraproposta_disponivel="350",
    )
    assert "a sua primeira contraproposta é 350" in out
    assert "ainda sobra uma última" in out
    assert "não recalcule" in out
    # o percentual segue fora da cauda.
    assert "%" not in out


def test_render_encontro_hoje_anuncia_a_unica_contraproposta_no_piso() -> None:
    """Decisão de 11/08/2026: hoje vai direto ao valor final, e o bloco não pode prometer uma
    segunda rodada que não existe."""
    out = _render(
        n_contrapropostas=0,
        escada_estado="ultima",
        preco_na_mesa=True,
        contraproposta_disponivel="300",
    )
    assert "a sua contraproposta é 300" in out
    assert "ÚNICA" in out
    assert "se você vier hoje" in out
    assert "ainda sobra uma última" not in out


def test_render_dia_conhecido_sem_numero_proibe_a_conta_de_cabeca() -> None:
    """O ramo que faltava (loop-massa r2, eixo objetor): dia CONHECIDO (`ultima`/`aberta`) e
    `contraproposta_disponivel` None — o fail-closed a montante (duracao_horas NULL) apagava o
    bloco inteiro e o modelo calculou 12,5% DE CABEÇA nos dois turnos de objeção, contra
    `regras.md.j2` ("Sem número no contexto, vale a recusa educada, nunca uma conta sua"). O bloco
    novo diz a INTENÇÃO (segurar o valor, mover para horário ou subir o tempo), nunca a fala."""
    out = _render(n_contrapropostas=0, escada_estado="ultima", preco_na_mesa=True)
    assert "<escada_sem_numero>" in out
    assert "<escada_disponivel>" not in out
    assert "não monta desconto de cabeça" in out
    assert "<pacote_maior_na_sua_tabela>" in out
    # nenhum número inventado e nenhuma fala pronta de desconto na cauda
    assert "%" not in out
    # e com o número calculado presente, quem fala continua sendo a <escada_disponivel>
    com_numero = _render(
        n_contrapropostas=0,
        escada_estado="ultima",
        preco_na_mesa=True,
        contraproposta_disponivel="300",
    )
    assert "<escada_sem_numero>" not in com_numero


def test_render_sem_o_dia_nao_mostra_numero_e_manda_sondar() -> None:
    out = _render(n_contrapropostas=0, escada_estado="sem_dia", preco_na_mesa=True)
    assert "<escada_travada_sem_o_dia>" in out
    assert "Seria hoje ?" in out
    assert "<escada_disponivel>" not in out
    # eb02/eb03: a defesa do valor nunca sai sozinha — a ilustração vem JÁ composta com o
    # avanço na mesma bolha, e a negação ativa proíbe a bolha decorativa.
    assert "Poxa amor, esse é o meu valor rs / Seria hoje ?" in out
    assert "NUNCA sai sozinha" in out


def test_render_sem_preco_na_mesa_nao_fala_de_desconto() -> None:
    out = _render(n_contrapropostas=0, escada_estado="sem_dia", preco_na_mesa=False)
    assert "escada_travada_sem_o_dia" not in out
    assert "<escada_disponivel>" not in out


def test_render_numero_da_rodada_zero_nao_sai_fora_dela() -> None:
    # Cinto e suspensório do template: mesmo que o campo vaze preenchido com a escada já aberta,
    # o bloco da rodada 0 não sai — quem fala é o <ja_fez_contraproposta n="1">.
    out = _render(
        n_contrapropostas=1,
        escada_estado="ultima",
        preco_na_mesa=True,
        contraproposta_disponivel="300",
    )
    assert "<escada_disponivel>" not in out


def test_render_escada_esgotada_encerra_o_desconto() -> None:
    out = _render(n_contrapropostas=2, escada_estado="esgotada")
    assert "<escada_esgotada>" in out
    assert "fora_de_oferta" in out


def test_render_hoje_esgota_com_uma_contraproposta_so() -> None:
    """O eco que a decisão quebrou: com encontro hoje, n=1 já é o fim — e o bloco não pode dizer
    "as suas DUAS contrapropostas"."""
    out = _render(n_contrapropostas=1, escada_estado="esgotada")
    assert "<escada_esgotada>" in out
    assert "DUAS" not in out


def test_render_terceira_insistencia_trata_como_esgotado() -> None:
    # defesa: contagem acima do previsto (não deveria acontecer, mas não pode reabrir oferta).
    out = _render(n_contrapropostas=3, escada_estado="esgotada")
    assert "<escada_esgotada>" in out


# --- o aceite do valor DELE (ADR-0040) ----------------------------------------------------------
# O número que o CLIENTE nomeia acima do piso fecha no número DELE. Entra na MESMA cadeia
# condicional da escada, como PRIMEIRO ramo: dentro de um {% if %}/{% elif %} a coexistência dos
# dois blocos é impossível por construção — dois números na mesma mensagem seriam duas ofertas.
# A decisão e o detector são testados em test_aceite_do_valor_dele.py; aqui é a fiação e o render.


def _burst(*falas: str) -> list[dict[str, Any]]:
    """Linhas de `mensagens` do cliente, no formato que `traduzir_mensagens` consome."""
    return [
        {
            "id": f"m{i}",
            "direcao": DirecaoMensagem.cliente,
            "conteudo": fala,
            "tipo": "texto",
            "created_at": _AGORA_UTC,
        }
        for i, fala in enumerate(falas)
    ]


class _FakeConnCatarina2h:
    """A 2h da Catarina: tabela 800 com piso absoluto 600 (degrau 700)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = (
            [{"programa_id": "p1", "preco": Decimal("800"), "preco_minimo": Decimal("600")}]
            if "modelo_programas" in sql
            else []
        )

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                return None

            async def fetchall(self) -> list[Any]:
                return linhas

        return _R()


def _negociando_2h(n: int, dia: date | None = _HOJE) -> dict[str, Any]:
    return {
        "estado": "Qualificado",
        "n_contrapropostas": n,
        "duracao_horas": Decimal("2"),
        "valor_acordado": Decimal("800"),
        "data_desejada": dia,
    }


async def _com_burst(atendimento: dict[str, Any], *falas: str, conn: Any = None) -> ContextoDoTurno:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA_UTC,
    )
    return await _resolver_variaveis(
        conn or _FakeConnCatarina2h(),  # type: ignore[arg-type]
        ctx,
        _burst(*falas),
        atendimento=atendimento,
        precos_por_horas={2.0: [Decimal("800")]},
    )


async def test_faz_700_sobre_800_vira_aceite_e_a_escada_cala() -> None:
    """A conversa que originou a regra: a escada responderia 600 (o piso) a um cliente que
    ofereceu 700."""
    contexto = await _com_burst(_negociando_2h(0), "nossa ta caro", "faz 700?")

    assert contexto.aceite_do_valor_dele == "700"
    assert contexto.contraproposta_disponivel is None


async def test_pedido_abaixo_do_piso_devolve_a_escada_intacta() -> None:
    contexto = await _com_burst(_negociando_2h(0), "faz 550?")

    assert contexto.aceite_do_valor_dele is None
    assert contexto.contraproposta_disponivel == "600"


async def test_sem_numero_dele_nada_muda() -> None:
    contexto = await _com_burst(_negociando_2h(0), "ta caro demais amor")

    assert contexto.aceite_do_valor_dele is None
    assert contexto.contraproposta_disponivel == "600"


async def test_aceite_independe_do_dia() -> None:
    """`sem_dia` cala a oferta DELA, não o sim ao número DELE: o dia decide quanto ela desce."""
    contexto = await _com_burst(_negociando_2h(0, dia=None), "so tenho 700")

    assert contexto.escada_estado == "sem_dia"
    assert contexto.aceite_do_valor_dele == "700"


async def test_escada_esgotada_nao_aceita_mais_nada() -> None:
    """O anti-leilão no contexto: aceitar 700 consumiu a rodada de hoje (write-time), então o 650
    seguinte não vira aceite nenhum."""
    contexto = await _com_burst(
        {**_negociando_2h(1), "valor_acordado": Decimal("700")}, "vai, 650 e fechamos"
    )

    assert contexto.escada_estado == "esgotada"
    assert contexto.aceite_do_valor_dele is None


async def test_patamar_da_mesa_sai_do_valor_aceito_e_nao_do_contador() -> None:
    """Emenda do ADR-0038: com 700 na mesa e a rodada de hoje consumida, `patamar_vigente` diria
    "piso" (600) — mas ela nunca ofereceu 600. O extra de fetiche desce até o DEGRAU."""
    contexto = await _com_burst({**_negociando_2h(1), "valor_acordado": Decimal("700")})

    assert contexto.patamar_da_mesa == "degrau"


async def test_mesa_intacta_deixa_o_contador_responder() -> None:
    """ "Nada regride": `valor_acordado` é gravado já na cotação e não acompanha a contraproposta
    ainda não aceita — mesa no preço cheio não puxa o patamar de volta pra cima."""
    contexto = await _com_burst(_negociando_2h(1))

    assert contexto.patamar_da_mesa == "piso"


async def test_carimbo_do_valor_dele_espelha_o_bloco_que_ela_leu() -> None:
    """O carimbo que viaja no State até o write-time (`valor_dele_no_prompt`, estado.py).

    Ele NÃO é o campo `aceite_do_valor_dele` cru: espelha a CONDIÇÃO do template, porque é sobre
    esse carimbo que o envio decide gravar `valor_acordado`. Carimbar um número que a tag não
    mostrou diria ao write-time que a IA leu uma ordem de aceitar que ela nunca leu — e uma bolha
    com o número por coincidência viraria venda.
    """
    aceitou = await _com_burst(_negociando_2h(0), "nossa ta caro", "faz 700?")
    assert aceitou.preco_na_mesa and aceitou.escada_estado != "esgotada"
    assert _valor_dele_no_prompt(aceitou) == 700

    # Abaixo do piso: a `aceite_do_valor_dele` já devolveu `abaixo_do_piso`, a tag não renderiza e
    # o carimbo nasce None — é ASSIM que o piso segura esta porta, e não com um segundo julgamento
    # do lado do envio.
    abaixo = await _com_burst(_negociando_2h(0), "faz 550?")
    assert _valor_dele_no_prompt(abaixo) is None

    # Escada esgotada: o anti-leilão. A tag não sai, então o 650 não vira venda nem se ela o disser.
    esgotada = await _com_burst(
        {**_negociando_2h(1), "valor_acordado": Decimal("700")}, "vai, 650 e fechamos"
    )
    assert esgotada.escada_estado == "esgotada"
    assert _valor_dele_no_prompt(esgotada) is None


def test_render_aceite_leva_o_numero_dele_e_manda_fechar_nele() -> None:
    out = _render(
        n_contrapropostas=0,
        escada_estado="ultima",
        preco_na_mesa=True,
        aceite_do_valor_dele="700",
    )
    assert "<valor_dele_serve>" in out
    assert "700" in out
    # o bloco prescreve a INTENÇÃO, não uma fala: exemplo marcado e variação obrigatória.
    assert "ilustração, não fala pronta" in out
    assert "A FORMA é sua e VARIA, nunca a mesma bolha de aceite duas vezes" in out


def test_render_aceite_e_escada_nunca_coexistem() -> None:
    """A garantia estrutural: mesmo com os dois campos preenchidos (não acontece — com aceite a
    escada nem é consultada), o {% elif %} deixa sair um bloco só. Dois números na mesma mensagem
    seriam duas ofertas, e a segunda desfaria a venda que a primeira fechou."""
    out = _render(
        n_contrapropostas=0,
        escada_estado="ultima",
        preco_na_mesa=True,
        aceite_do_valor_dele="700",
        contraproposta_disponivel="600",
    )
    assert "<valor_dele_serve>" in out
    assert "<escada_disponivel>" not in out
    assert "600" not in out


def test_render_aceite_vem_antes_do_bloco_sem_dia() -> None:
    out = _render(
        n_contrapropostas=0,
        escada_estado="sem_dia",
        preco_na_mesa=True,
        aceite_do_valor_dele="700",
    )
    assert "<valor_dele_serve>" in out
    assert "<escada_travada_sem_o_dia>" not in out


def test_render_aceite_na_segunda_rodada_cala_a_memoria_da_primeira() -> None:
    """Com outro dia e uma rodada já gasta, o <ja_fez_contraproposta> lembraria da ÚLTIMA
    contraproposta dela — no turno em que o número dele já fechou a venda, isso é ruído que
    convida a contar um número a mais."""
    out = _render(
        n_contrapropostas=1,
        escada_estado="ultima",
        preco_na_mesa=True,
        aceite_do_valor_dele="700",
    )
    assert "<valor_dele_serve>" in out
    assert "<ja_fez_contraproposta" not in out


def test_render_sem_aceite_a_cadeia_da_escada_segue_como_antes() -> None:
    out = _render(
        n_contrapropostas=0,
        escada_estado="ultima",
        preco_na_mesa=True,
        contraproposta_disponivel="600",
    )
    assert "<escada_disponivel>" in out
    assert "<valor_dele_serve>" not in out


# --- oferta condicionada ao dia (ADR-0041) ------------------------------------------------------
# Com o dia desconhecido a escada continua travada; o que muda é a JOGADA. Em vez de interrogar
# ("Seria hoje ?" — o tique já medido em produção), a condição viaja DENTRO da oferta, e para isso
# os DOIS números vêm calculados. Vale só no SALTO (composição, fetiche pago, pacote maior): fora
# dele, prometer o teto a quem nunca reclamou de preço é a erosão que o ADR-0004 mandou monitorar.


def test_render_oferta_condicionada_leva_os_dois_numeros() -> None:
    out = _render(
        n_contrapropostas=0,
        escada_estado="sem_dia",
        preco_na_mesa=True,
        oferta_se_hoje="600",
        oferta_se_outro_dia="700",
    )
    assert "<oferta_condicionada_ao_dia>" in out
    assert "600" in out and "700" in out
    # intenção, não fala: o exemplo vem marcado e a variação é obrigatória.
    assert "ilustração, não fala pronta" in out
    assert "A FORMA é sua e VARIA" in out
    # e ela substitui a sonda do dia, que é a conduta revogada
    assert "<escada_travada_sem_o_dia>" not in out
    assert "%" not in out


def test_render_oferta_condicionada_e_escada_disponivel_nunca_coexistem() -> None:
    """Mesma garantia estrutural do <valor_dele_serve>: a cadeia é um {% if %}/{% elif %} só, e
    dois números de origens diferentes na mesma mensagem seriam duas ofertas."""
    out = _render(
        n_contrapropostas=0,
        escada_estado="sem_dia",
        preco_na_mesa=True,
        oferta_se_hoje="600",
        oferta_se_outro_dia="700",
        contraproposta_disponivel="300",
    )
    assert "<oferta_condicionada_ao_dia>" in out
    assert "<escada_disponivel>" not in out
    assert "300" not in out


def test_render_valor_dele_serve_vence_a_oferta_condicionada() -> None:
    """Precedência: o número que ELE nomeou fecha a venda — não há salto a condicionar depois de
    um sim. O <valor_dele_serve> é o PRIMEIRO ramo da cadeia e continua sendo."""
    out = _render(
        n_contrapropostas=0,
        escada_estado="sem_dia",
        preco_na_mesa=True,
        aceite_do_valor_dele="700",
        oferta_se_hoje="600",
        oferta_se_outro_dia="700",
    )
    assert "<valor_dele_serve>" in out
    assert "<oferta_condicionada_ao_dia>" not in out


def test_render_meio_par_nao_vira_oferta_condicionada() -> None:
    """Os dois números ou nenhum: dizer só o de hoje faz a resposta dele ("então outro dia")
    parecer aumento. Sem o par completo vale o <escada_travada_sem_o_dia> de sempre."""
    out = _render(
        n_contrapropostas=0, escada_estado="sem_dia", preco_na_mesa=True, oferta_se_hoje="600"
    )
    assert "<oferta_condicionada_ao_dia>" not in out
    assert "<escada_travada_sem_o_dia>" in out


def test_render_escada_esgotada_abre_a_carta_do_cartao() -> None:
    """Conduta 3: o cartão é a última carta antes de perder a venda — ativo, e sem falar de taxa."""
    out = _render(n_contrapropostas=2, escada_estado="esgotada")
    assert "cartão" in out
    assert "maquininha" not in out and "acréscimo" not in out
    assert "fora_de_oferta" in out


# --- subir o tempo antes de descer o preço ------------------------------------------------------
# Print de vendedora exemplar: ela não repete o número, sonda o TEMPO dele e vende 2h no preço
# CHEIO. O contexto entrega o dado (qual é o pacote maior, quanto custa, se ele já disse o tempo);
# a INTENÇÃO ("subir o tempo vem antes de descer o preço") mora no <desconto>; a fala é dela.


def test_render_pacote_maior_e_dado_puro_sem_fala_pronta() -> None:
    out = _render(pacote_maior={"horas": "2", "preco": "800"}, tempo_dele_desconhecido=True)
    assert '<pacote_maior_na_sua_tabela horas="2" preco="800"' in out
    assert 'tempo_que_ele_tem="ele ainda não disse"' in out
    # nenhuma pergunta prescrita: o bloco é uma tag de dado, não prosa
    assert "?" not in out.split("<pacote_maior_na_sua_tabela")[1].split("/>")[0]


def test_render_pacote_maior_com_o_tempo_dele_ja_dito_nao_pede_sondagem() -> None:
    """O atributo existe nos DOIS estados (13/08): a ausência dizia "não sonde" por omissão, e
    omissão não é dado — o degrau 2 do <desconto> lê o `tempo_que_ele_tem` para escolher entre
    sondar e vender. Aqui ele carrega o outro lado, e a sondagem sai de cena pelo que está escrito,
    não pelo que falta. Continua sem fala pronta: a tag é dado."""
    out = _render(pacote_maior={"horas": "2", "preco": "800"}, tempo_dele_desconhecido=False)
    assert '<pacote_maior_na_sua_tabela horas="2" preco="800"' in out
    assert "ele ainda não disse" not in out
    assert 'tempo_que_ele_tem="ele já sinalizou que tem tempo' in out


def test_render_sem_pacote_maior_nao_injeta_nada() -> None:
    assert "<pacote_maior_na_sua_tabela" not in _render()
