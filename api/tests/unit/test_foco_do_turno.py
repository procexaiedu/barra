"""<foco_do_turno> (re-ancoragem por turno, rodada 3): detectores + template + injeção na cauda.

Cobre as três pontas do mecanismo: os detectores determinísticos sobre o burst do cliente
(`nos/_foco_do_turno.py`), o render do bloco (`foco_do_turno.md.j2`, via o MESMO dicionário do
contexto dinâmico) e a injeção em `_anexar_contexto_dinamico` (foco entre o contexto e a fala,
fala por último — incidente 29/07). Sem DB, sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from jinja2 import meta
from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos._foco_do_turno import (
    pediu_endereco_no_burst,
    pediu_preco_no_burst,
    perguntas_do_burst,
    saudacao_do_burst,
)
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico, _spotlight_transcricao
from barra.agente.persona import _env, render_foco_do_turno

_AGORA_UTC = datetime(2026, 8, 10, 17, 30, tzinfo=UTC)

# Cardápio vazio de propósito neste arquivo: os testes de injeção medem o `<pacote_em_pauta>` e a
# re-ancoragem pela duração do burst, que saem de `precos_por_horas` (as linhas da TABELA), e o
# degrau do endereço, que sai do estado. Nenhum deles lê `cardapio_rows` — o cardápio resolvido
# contra o burst tem casa própria (test_foco_fetiches_e_menu.py, test_oferta_condicionada_ao_dia).
# `{}` afirma "esta modelo não tem cadastro de fetiche/programa"; o antigo default `None` era a
# omissão que apagava nove campos do foco sem erro nenhum.
_SEM_CARDAPIO: dict[str, list[dict[str, Any]]] = {}


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA_UTC,
    )


# --- detectores ---------------------------------------------------------------------------


def test_perguntas_do_burst_pega_todas_as_bolhas_do_burst() -> None:
    """A pergunta da bolha 1 de um burst de 3 não some — é o caso que degrada em conversa longa."""
    msgs = [
        AIMessage(content="O encontro é 500 1h", id="a1"),
        HumanMessage(content="Faz anal?", id="h1"),
        HumanMessage(content="Show", id="h2"),
        HumanMessage(content="E onde fica seu local?", id="h3"),
    ]
    assert perguntas_do_burst(msgs) == ("Faz anal?", "E onde fica seu local?")


def test_pergunta_social_nao_vira_pendencia() -> None:
    """'tudo bem?' é social — citada no foco viraria ruído ("responda 'tudo bem?'")."""
    msgs = [HumanMessage(content="oi, tudo bem?", id="h1")]
    assert perguntas_do_burst(msgs) == ()
    msgs = [HumanMessage(content="Tudo bem? Quanto é a hora?", id="h1")]
    assert perguntas_do_burst(msgs) == ("Quanto é a hora?",)


def test_pergunta_fora_do_burst_nao_conta() -> None:
    """Pergunta de um turno anterior (antes da última fala da IA) não é pendência DESTE turno."""
    msgs = [
        HumanMessage(content="Quanto é?", id="h1"),
        AIMessage(content="500 1h amor", id="a1"),
        HumanMessage(content="Show", id="h2"),
    ]
    assert perguntas_do_burst(msgs) == ()


def test_conteudo_spotlighted_nao_alimenta_o_foco() -> None:
    """Transcrição de áudio é DADO cercado (SEC-11): citá-la no foco a tiraria da moldura."""
    msgs = [
        AIMessage(content="Oi amor", id="a1"),
        HumanMessage(content=_spotlight_transcricao("Onde fica? Qual o valor?", "m1"), id="h1"),
    ]
    assert perguntas_do_burst(msgs) == ()
    assert not pediu_endereco_no_burst(msgs)
    assert not pediu_preco_no_burst(msgs)


def test_pedido_de_endereco_com_e_sem_interrogacao() -> None:
    assert pediu_endereco_no_burst([HumanMessage(content="manda a localização", id="h")])
    assert pediu_endereco_no_burst([HumanMessage(content="Onde fica?", id="h")])
    assert pediu_endereco_no_burst([HumanMessage(content="qual rua?", id="h")])
    assert not pediu_endereco_no_burst([HumanMessage(content="tudo bem amor?", id="h")])


def test_pedido_de_preco_com_e_sem_interrogacao() -> None:
    assert pediu_preco_no_burst([HumanMessage(content="quanto é a hora", id="h")])
    assert pediu_preco_no_burst([HumanMessage(content="Qual o valor?", id="h")])
    assert not pediu_preco_no_burst(
        [HumanMessage(content="quanto tempo você fica na cidade", id="h")]
    )


@pytest.mark.parametrize(
    "fala",
    [
        "Quanto vc cobra no programa?",
        "Quanto você cobra?",
        "Quanto voce custa?",
        "Quanto tu cobra?",
        "quanto cê cobra amor",
    ],
)
def test_pedido_de_preco_com_pronome_entre_quanto_e_o_verbo(fala: str) -> None:
    """loop-massa r2 (decidido_rapido): o verbo nem sempre vem colado em "quanto". Sem o slot de
    pronome, o turno em que o cliente pergunta o preço com todas as letras saía SEM
    <pergunta_de_preco> — e sem o menu da primeira cotação, que roda sob o mesmo sinal."""
    assert pediu_preco_no_burst([HumanMessage(content=fala, id="h")])


@pytest.mark.parametrize(
    "fala",
    ["quanto tempo você fica na cidade", "quanto tempo vc fica", "quanto tempo demora"],
)
def test_pronome_nao_abre_a_porta_para_pergunta_de_tempo(fala: str) -> None:
    """O slot é FECHADO (lista de pronomes, não `\\w+`): entre "quanto" e o verbo só cabe pronome,
    então "quanto TEMPO você fica" continua fora — é pergunta de agenda, não de preço."""
    assert not pediu_preco_no_burst([HumanMessage(content=fala, id="h")])


@pytest.mark.parametrize(
    "fala", ["Onde atende ?", "onde vc atende", "onde você atende ?", "onde tu atende amor"]
)
def test_pedido_de_endereco_com_pronome_opcional(fala: str) -> None:
    """Mesma família do fix de "qual seu local ?" (r1): o pronome é opcional. Sem isto,
    `_interesse_demonstrado` não acendia e o <local_de_encontro> ficava fechado no turno em que o
    cliente pede o ponto (loop-massa r2, eixo objetor)."""
    assert pediu_endereco_no_burst([HumanMessage(content=fala, id="h")])


# --- template ----------------------------------------------------------------------------


def _variaveis_base(**sobrescreve: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "perguntas_do_turno": (),
        "pediu_endereco_no_turno": False,
        "pediu_preco_no_turno": False,
        "pacote_em_pauta": None,
        "local_endereco": None,
        "local_nome": None,
        "numero_liberado": False,
        "valor_fechado": None,
        "valor_aceito": False,
        "duracao_fechada": None,
    }
    base.update(sobrescreve)
    return base


def test_template_renderiza_vazio_sem_deteccao() -> None:
    assert render_foco_do_turno(**_variaveis_base()) == ""


def test_template_entrega_o_endereco_literal_quando_pedido_e_liberado() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(
            pediu_endereco_no_turno=True,
            local_endereco="Av. Aquidabã, 130 - Centro, Campinas",
            local_nome="Hotel Sirius",
            numero_liberado=True,
        )
    )
    assert "<entregue_agora>" in saida
    assert "Hotel Sirius — Av. Aquidabã, 130 - Centro, Campinas" in saida
    assert "sem o número" not in saida


def test_template_sem_local_no_contexto_instrui_em_vez_de_silenciar() -> None:
    """Pedido detectado mas sem o dado no prompt (local_endereco None): nada de <entregue_agora> —
    o degrau do <local_de_encontro> continua mandando — mas o foco NÃO silencia.

    Antes o bloco inteiro sumia (`tem_endereco` = pedido AND dado), e o turno de maior densidade de
    decisão recebia o menor contexto: no trace 648d7f6f o modelo inventou "rua Beneventto Bellini".
    Foco que cala é o modo de falha do bloco mais obedecido do prompt — sem dado, ele diz o que
    fazer no lugar (diagnóstico 11/08, P0-1)."""
    saida = render_foco_do_turno(**_variaveis_base(pediu_endereco_no_turno=True))
    assert "<entregue_agora>" not in saida
    assert "<pedido_sem_dado>" in saida
    assert "não invente rua" in saida
    assert "Me confirma o horário que eu te passo o endereço certinho amor" in saida


def test_template_com_endereco_nao_injeta_o_ramo_sem_dado() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(
            pediu_endereco_no_turno=True,
            local_endereco="Av. Aquidabã, 130 - Centro, Campinas",
        )
    )
    assert "<entregue_agora>" in saida
    assert "<pedido_sem_dado>" not in saida


def test_template_sem_pedido_de_endereco_segue_vazio() -> None:
    assert render_foco_do_turno(**_variaveis_base(local_endereco="Av. Aquidabã, 130")) == ""


def test_template_perguntas_e_preco() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(
            perguntas_do_turno=("Faz anal?", "Onde fica?"),
            pediu_preco_no_turno=True,
            valor_fechado="500",
            duracao_fechada="1",
        )
    )
    assert "<pergunta>Faz anal?</pergunta>" in saida
    assert "<pergunta>Onde fica?</pergunta>" in saida
    assert "500" in saida and "(1h)" in saida


def test_template_pacote_em_pauta() -> None:
    saida = render_foco_do_turno(**_variaveis_base(pacote_em_pauta={"horas": "1", "preco": "500"}))
    assert "<pacote_em_pauta>" in saida
    assert "1h" in saida and "500" in saida


def test_template_servico_em_pauta_com_total_no_patamar_manda_copiar() -> None:
    """Dívida do ADR-0038 fechada: com a negociação fora do patamar cheio, o item pago carrega o
    TOTAL pré-computado (pacote no patamar + extra no mesmo patamar) e o bloco proíbe a soma."""
    saida = render_foco_do_turno(
        **_variaveis_base(
            fetiches_em_pauta=({"nome": "Inversão", "status": "extra", "total": "R$600"},)
        )
    )

    assert "R$600" in saida
    assert "não some" in saida
    assert "linha do pacote em pauta" not in saida  # o ramo da tabela cheia não sai junto


def test_template_servico_em_pauta_sem_total_aponta_a_tabela_como_antes() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(fetiches_em_pauta=({"nome": "Inversão", "status": "extra"},))
    )

    assert "o número sai do seu <fetiches>" in saida


def test_template_por_pessoa_com_total_no_patamar() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(
            fetiches_em_pauta=(
                {"nome": "Acompanhante dele — mulher", "status": "por_pessoa", "total": "R$600"},
            )
        )
    )

    assert "total para as duas" in saida and "R$600" in saida


def test_template_composicao_em_pauta_com_total_manda_copiar() -> None:
    """Dívida da composição fechada (ponto #4): com a negociação fora do cheio, o bloco carrega o
    TOTAL das duas no patamar (`composicao_total`) e MANDA cotar esse número — antes ele só sabia
    cair no "não cota → escala", que perdia a venda por cima de um pacote já descontado."""
    saida = render_foco_do_turno(
        **_variaveis_base(composicao_em_pauta=True, composicao_total="R$1000")
    )

    assert "<composicao_em_pauta>" in saida
    assert "R$1000" in saida
    assert "NO PATAMAR em que a negociação já está" in saida
    # O ramo conservador (tabela cheia / não cota) NÃO sai junto quando há número.
    assert "você NÃO cota" not in saida


def test_template_composicao_em_pauta_sem_total_mantem_o_fallback_conservador() -> None:
    """Sem `composicao_total` (patamar cheio → a tabela "Por pessoa" estática já é o número; ou sem
    total pronto), o bloco volta ao contrato antigo: aponta a tabela cheia quando o pacote está no
    valor de tabela, e no descontado sem número manda confirmar/escalar — nunca cota a linha cheia
    por cima de um pacote já descontado."""
    saida = render_foco_do_turno(**_variaveis_base(composicao_em_pauta=True))

    assert "<composicao_em_pauta>" in saida
    assert 'TOTAL da tabela "Por pessoa"' in saida
    assert "você NÃO cota" in saida


def test_contrato_variaveis_do_template_existem_no_dicionario_publicado() -> None:
    """Espelho do contrato do contexto dinâmico: variável que o foco lê sem fonte no
    `ContextoDoTurno` renderizaria vazia em silêncio."""
    fonte = _env.loader.get_source(_env, "foco_do_turno.md.j2")[0]  # type: ignore[union-attr]
    declaradas = meta.find_undeclared_variables(_env.parse(fonte))
    # O conjunto publicado é o do dataclass — mesmos campos que o contexto dinâmico recebe.
    from dataclasses import fields

    from barra.agente.nos._contexto_do_turno import ContextoDoTurno

    publicadas = {f.name for f in fields(ContextoDoTurno)}
    # `set`s locais do próprio template (os dois ramos do pedido de endereço).
    faltando = declaradas - publicadas - {"tem_endereco", "pedido_sem_dado"}
    assert not faltando, f"variáveis do foco sem fonte no ContextoDoTurno: {faltando}"


# --- injeção na cauda --------------------------------------------------------------------


async def test_foco_entra_entre_contexto_e_fala_e_a_fala_segue_por_ultimo() -> None:
    msgs = [
        AIMessage(content="500 1h amor", id="a1"),
        HumanMessage(content="Show. Onde fica?", id="h1"),
    ]
    anexadas, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        msgs,
        atendimento={"estado": "Qualificado", "tipo_atendimento": "interno"},
        local_endereco_raw="Av. Aquidabã, 130 - Centro, Campinas",
        local_nome_raw="Hotel Sirius",
        cardapio_rows=_SEM_CARDAPIO,
    )
    conteudo = anexadas[-1].content
    assert isinstance(conteudo, str)
    assert "<foco_do_turno>" in conteudo
    assert contexto.pediu_endereco_no_turno
    assert contexto.perguntas_do_turno == ("Onde fica?",)
    # Em Qualificado o degrau entrega o endereço SEM número — e o foco repete o literal do degrau.
    assert "Av. Aquidabã - Centro, Campinas" in conteudo
    # A fala do cliente continua sendo o último trecho da mensagem inflada (recency).
    assert conteudo.rstrip().endswith("Show. Onde fica?")
    # O foco fica DEPOIS do </situacao_do_atendimento>... (contexto) e ANTES da fala.
    assert conteudo.index("<foco_do_turno>") > conteudo.index("<ja_combinado>")


async def test_sem_deteccao_a_cauda_sai_sem_foco() -> None:
    # "Boa tarde" saiu do fixture na rodada 4: saudação de período agora É detecção
    # (<saudacao_dele>) — o turno sem foco precisa de fala sem pergunta, pedido ou saudação.
    msgs = [
        AIMessage(content="Oi amor", id="a1"),
        HumanMessage(content="Entendi amor", id="h1"),
    ]
    anexadas, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        msgs,
        atendimento={"estado": "Novo"},
        cardapio_rows=_SEM_CARDAPIO,
    )
    conteudo = anexadas[-1].content
    assert isinstance(conteudo, str)
    assert "<foco_do_turno>" not in conteudo
    assert contexto.perguntas_do_turno == ()


async def test_pacote_em_pauta_resolvido_do_cardapio_com_um_preco() -> None:
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="pode ser 1h então", id="h1")],
        atendimento={"estado": "Triagem", "duracao_horas": Decimal("1")},
        precos_por_horas={1.0: [Decimal("500.00")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    assert contexto.pacote_em_pauta == {"horas": "1", "preco": "500"}


async def test_pacote_em_pauta_fail_closed_com_dois_precos_ou_valor_ja_cotado() -> None:
    _msgs, ambiguo, _p = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="1h", id="h1")],
        atendimento={"estado": "Triagem", "duracao_horas": Decimal("1")},
        precos_por_horas={1.0: [Decimal("400"), Decimal("700")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    assert ambiguo.pacote_em_pauta is None

    _msgs, ja_cotado, _p = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="1h", id="h1")],
        atendimento={
            "estado": "Qualificado",
            "duracao_horas": Decimal("1"),
            "valor_acordado": Decimal("500"),
        },
        precos_por_horas={1.0: [Decimal("500")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    assert ja_cotado.pacote_em_pauta is None


# --- rodada 4: saudação espelhada + vocabulário coloquial de endereço ----------------------


def test_saudacao_do_burst_detecta_o_periodo() -> None:
    msgs = [
        AIMessage(content="Oi amor", id="a1"),
        HumanMessage(content="Boa tarde, tudo bem?", id="h1"),
    ]
    assert saudacao_do_burst(msgs) == "boa tarde"


def test_burst_sem_saudacao_devolve_none() -> None:
    msgs = [
        AIMessage(content="Oi amor", id="a1"),
        HumanMessage(content="quanto é a hora?", id="h1"),
    ]
    assert saudacao_do_burst(msgs) is None


def test_saudacao_de_burst_antigo_nao_conta() -> None:
    # A saudação foi 2 turnos atrás; o burst atual não saúda — espelhar agora seria ruído.
    msgs = [
        HumanMessage(content="bom dia", id="h1"),
        AIMessage(content="Bom dia amor", id="a1"),
        HumanMessage(content="me passa o valor", id="h2"),
    ]
    assert saudacao_do_burst(msgs) is None


def test_template_renderiza_saudacao_dele() -> None:
    texto = render_foco_do_turno(**_variaveis_base(saudacao_dele="boa tarde"))
    assert "<saudacao_dele>" in texto
    assert '"boa tarde"' in texto


def test_pedido_de_endereco_formas_coloquiais_no_foco() -> None:
    # Rodada 4: o foco cobre TAMBÉM a objeção de distância e a pergunta de acesso (injetar o
    # dado resolve); o guard de _disciplina fica só com as formas inequívocas.
    for fala in (
        "Próximo onde?",
        "não conheço esse hotel rs",
        "o seu é apartamento",
        "fica longe pra mim?",
        "ta longe daqui?",
    ):
        msgs = [AIMessage(content="Oi", id="a1"), HumanMessage(content=fala, id="h1")]
        assert pediu_endereco_no_burst(msgs), fala


# --- rodada 6: duração pedida, aceite curto, disponibilidade concreta ---------------------


def test_duracao_pedida_no_burst_formas_e_ultima_mencao() -> None:
    from barra.agente.nos._foco_do_turno import duracao_pedida_no_burst

    assert duracao_pedida_no_burst([HumanMessage(content="quanto fica 3h?")]) == 3.0
    assert duracao_pedida_no_burst([HumanMessage(content="e 30 min?")]) == 0.5
    assert duracao_pedida_no_burst([HumanMessage(content="meia hora sai quanto")]) == 0.5
    # última menção do burst vence (ele se corrige)
    assert (
        duracao_pedida_no_burst(
            [HumanMessage(content="2 horas"), HumanMessage(content="melhor 1h mesmo")]
        )
        == 1.0
    )
    # fora de faixa / sem menção → None
    assert duracao_pedida_no_burst([HumanMessage(content="cheguei faz 5 min")]) is None
    assert duracao_pedida_no_burst([HumanMessage(content="oi linda")]) is None


@pytest.mark.parametrize(
    "fala",
    [
        "Consigo chegar ai em uns 40 min",
        "chego ai em 40 min",
        "da pra chegar la em 40 min",
        "consigo chegar em 40 min",
        "chego em 40 min",
    ],
)
def test_tempo_de_chegada_com_deitico_nao_vira_duracao(fala: str) -> None:
    """loop-massa r3 (eixo apressado): "Consigo chegar ai em uns 40 min" virava
    `duracao_pedida=0.67` e o foco mandava "subir o tempo" sobre um pacote que ninguém pediu.
    Acrescentar só o infinitivo NÃO conserta — o dêitico ("ai"/"lá") entra ENTRE o verbo e o "em",
    e sem o slot o prefixo não fecha."""
    from barra.agente.nos._foco_do_turno import duracao_pedida_no_burst

    assert duracao_pedida_no_burst([HumanMessage(content=fala, id="h")]) is None


def test_chegar_seguido_de_duracao_real_continua_sendo_duracao() -> None:
    """O negativo que segura a família: o prefixo é ancorado imediatamente antes do número, então
    "quero chegar e ficar 2 horas" é duração de verdade e continua contando."""
    from barra.agente.nos._foco_do_turno import duracao_pedida_no_burst

    assert duracao_pedida_no_burst([HumanMessage(content="quero chegar e ficar 2 horas")]) == 2.0


@pytest.mark.parametrize(
    "fala",
    ["Gata seu local é casa ou prédio?", "predio ou casa?", "seu é prédio?", "é casa ou apto?"],
)
def test_pedido_de_endereco_cobre_predio(fala: str) -> None:
    """loop-massa r3 (negociacao_dura_b t4): a família de "pergunta de acesso" só dizia
    "apartamento", e a `persona.md` proíbe "prédio" na boca DELA — o que a torna a palavra mais
    provável na boca DELE."""
    assert pediu_endereco_no_burst([HumanMessage(content=fala, id="h")])


@pytest.mark.parametrize(
    "fala",
    [
        "E se eu for até vc é 400 direto né?",
        "é 400 direto né?",
        "fica 400 certo?",
        "então é 400?",
        "É 400 fechado mesmo pra 1h?",
    ],
)
def test_pedido_de_preco_na_forma_de_conferencia(fala: str) -> None:
    """loop-massa r3 (externo_b t7): o vocabulário do detector é 100% interrogativo-ABERTO e a
    forma de CONFERÊNCIA ("é 400 direto né?") ficava de fora — o cliente conferindo o número é
    pergunta de preço igual."""
    assert pediu_preco_no_burst([HumanMessage(content=fala, id="h")])


@pytest.mark.parametrize(
    "fala", ["400 1h no meu local", "fechado 400 então", "chego 21h né", "Consigo às 20h, fecha ?"]
)
def test_conferencia_nao_confunde_cotacao_aceite_nem_hora(fala: str) -> None:
    """O piso de 3-4 dígitos é o que separa preço de HORA ("chego 21h né" não acende), e nem a
    cotação nem o aceite têm token de conferência — o aceite é matéria do `_RE_CONTRAPROPOSTA`."""
    assert not pediu_preco_no_burst([HumanMessage(content=fala, id="h")])


def test_condicao_pendurada_depois_da_interrogacao_nao_e_decapitada() -> None:
    """loop-massa r3 (negociacao_dura_b): o recorte terminado em "?" descartava "Com 2
    finalizações", e a condição de preço acoplada a serviço nunca chegava ao foco — enquanto o
    belief a promovia a combinado fechado no turno seguinte."""
    msgs = [
        AIMessage(content="400 a 1h amor", id="a1"),
        HumanMessage(
            content="Gata seu local é casa ou prédio?\n"
            "Vc não consegue fazer 1 hr por 300$? Com 2 finalizações",
            id="h1",
        ),
    ]
    assert perguntas_do_burst(msgs) == (
        "Gata seu local é casa ou prédio?",
        "Vc não consegue fazer 1 hr por 300$? Com 2 finalizações",
    )


def test_cauda_longa_demais_nao_entra_na_pergunta() -> None:
    """A cauda é RESSALVA, não assunto novo: acima do teto ela deixa de ser realce e vira ruído."""
    cauda = "e eu queria saber tambem se voce atende de madrugada porque so consigo tarde"
    msgs = [HumanMessage(content=f"Quanto é 1h? {cauda}", id="h1")]
    assert perguntas_do_burst(msgs) == ("Quanto é 1h?",)


def test_aceite_curto_no_burst() -> None:
    from barra.agente.nos._foco_do_turno import aceite_curto_no_burst

    assert aceite_curto_no_burst([AIMessage(content="500 1h"), HumanMessage(content="Perfeito")])
    assert aceite_curto_no_burst([HumanMessage(content="pode ser")])
    # pergunta desarma; fala longa desarma; burst vazio (último foi a IA) desarma
    assert not aceite_curto_no_burst([HumanMessage(content="pode ser? e onde fica")])
    assert not aceite_curto_no_burst([HumanMessage(content="pode ser mas só depois das 22h")])
    assert not aceite_curto_no_burst([AIMessage(content="500 1h")])


def test_template_ele_topou_com_e_sem_agenda() -> None:
    com_hora = render_foco_do_turno(
        **_variaveis_base(aceitou_no_burst=True, livre_agora="livre hoje a partir de 18:00")
    )
    assert "<ele_topou>" in com_hora
    assert "livre hoje a partir de 18:00" in com_hora
    sem_hora = render_foco_do_turno(**_variaveis_base(aceitou_no_burst=True))
    assert "<ele_topou>" in sem_hora
    assert "livre hoje" not in sem_hora


def test_template_preco_leva_a_disponibilidade_concreta() -> None:
    saida = render_foco_do_turno(
        **_variaveis_base(pediu_preco_no_turno=True, livre_agora="livre hoje a partir de 18:00")
    )
    assert "livre hoje a partir de 18:00" in saida


async def test_duracao_do_burst_reancora_o_pacote_em_pauta() -> None:
    # belief diz 1h, mas ele pergunta as 3h → a linha das 3h entra (derrota medida: cotava 1h)
    _msgs, contexto, _p = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="quanto ficaria 3h?", id="h1")],
        atendimento={"estado": "Qualificado", "duracao_horas": Decimal("1")},
        precos_por_horas={1.0: [Decimal("500")], 3.0: [Decimal("1200")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    # `origem="ele"` porque a TROCA veio do burst dele: ela ainda não disse 1200 (loop-massa r3,
    # prompt #3 — o <valor_cotado> rotulava esse número como "preço que VOCÊ já cotou").
    assert contexto.pacote_em_pauta == {"horas": "3", "preco": "1200", "origem": "ele"}


async def test_duracao_do_burst_com_valor_fechado_de_outra_duracao_reancora() -> None:
    # 1h fechada com valor na mesa; ele pergunta o pacote de 6h → a linha das 6h entra
    _msgs, contexto, _p = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="e se for 6h?", id="h1")],
        atendimento={
            "estado": "Qualificado",
            "duracao_horas": Decimal("1"),
            "valor_acordado": Decimal("500"),
        },
        precos_por_horas={1.0: [Decimal("500")], 6.0: [Decimal("3000")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    assert contexto.pacote_em_pauta == {"horas": "6", "preco": "3000", "origem": "ele"}


async def test_duracao_do_burst_fail_closed_sem_preco_unico() -> None:
    _msgs, contexto, _p = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="quanto as 2h?", id="h1")],
        atendimento={"estado": "Triagem"},
        precos_por_horas={2.0: [Decimal("700"), Decimal("1400")]},
        cardapio_rows=_SEM_CARDAPIO,
    )
    assert contexto.pacote_em_pauta is None


def test_tempo_de_chegada_nao_e_duracao_de_pacote() -> None:
    # loop-massa r1 (eixo decidido_rapido): "daki uns 40 minutos" é QUANDO ele chega, não o pacote
    # que ele quer — lido como duração, o foco mandava "subir o tempo" sobre pacote que ninguém pediu.
    from barra.agente.nos._foco_do_turno import duracao_pedida_no_burst

    for fala in ("daki uns 40 minutos", "daqui 30 min", "chego em 40 minutos", "daqui meia hora"):
        assert duracao_pedida_no_burst([HumanMessage(content=fala)]) is None, fala
    # controle: duração de verdade segue contando
    assert duracao_pedida_no_burst([HumanMessage(content="e 40 minutos sai quanto?")]) == 40 / 60


def test_qual_seu_local_e_pedido_de_endereco() -> None:
    # loop-massa r1 (eixo objetor): "Qual seu local?" não casava e o gate do <local_de_encontro>
    # ficava fechado no turno em que o cliente pediu o local.
    for fala in ("Qual seu local?", "qual é o seu local", "qual o teu local amor"):
        msgs = [AIMessage(content="Oi", id="a1"), HumanMessage(content=fala, id="h1")]
        assert pediu_endereco_no_burst(msgs), fala
