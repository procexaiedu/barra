"""A cauda deixa de proibir a abertura que a conduta prescreve (issue 03 do refactor do prompt).

Dois sites, um mesmo bug: o bloco de contexto do turno é a última coisa que o modelo lê antes da
fala do cliente (`agente/CLAUDE.md`, "Prompt caching" — cauda = recency máxima), e ele afirmava
*sem condição* que a conversa já estava no meio, contra a `<abertura>` do `regras.md.j2` ("'Oi'
SOZINHO → só o cumprimento, em 2 bolhas curtas"). No mesmo bloco o `<proximo_passo>` nomeava a fase
com "entender o que ele procura" — exatamente a sonda-de-balcão que a `<abertura>` proíbe "em
nenhuma paráfrase".

Sem DB, sem crédito: renderiza o bloco pelo caminho real (`_anexar_contexto_dinamico`) com uma
conexão vazia, como `test_contrato_variaveis_contexto.py` já faz.
"""

import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente._texto_turno import _PREFIXO_ID_PAUSA
from barra.agente.contexto import ContextAgente
from barra.agente.nos._janela_do_turno import _conversa_em_andamento
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico
from barra.dominio.atendimentos.service import _PROXIMO_PASSO

_AGORA_UTC = datetime(2026, 7, 30, 17, 30, tzinfo=UTC)
_NAO_RECUMPRIMENTE = "não recumprimente"


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
        db_pool=None,  # type: ignore[arg-type]  # nenhuma query roda com o FakeConn
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA_UTC,
    )


async def _bloco(mensagens: list[BaseMessage], estado: str) -> str:
    """O texto que a IA recebe na cauda, pelo caminho real."""
    msgs, _contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        mensagens,
        atendimento={"estado": estado},
    )
    return "\n".join(str(m.content) for m in msgs)


def _pausa() -> HumanMessage:
    return HumanMessage(content="[pausa de 6 dias na conversa]", id=f"{_PREFIXO_ID_PAUSA}x")


# --- o detector ------------------------------------------------------------------------------


def test_primeiro_contato_nao_esta_em_andamento() -> None:
    assert _conversa_em_andamento([]) is False
    assert _conversa_em_andamento([HumanMessage(content="oi")]) is False


def test_bolha_dela_poe_a_conversa_em_andamento() -> None:
    assert (
        _conversa_em_andamento(
            [HumanMessage(content="oi"), AIMessage(content="Oii"), HumanMessage(content="quanto é")]
        )
        is True
    )


def test_pausa_longa_reabre_a_conversa() -> None:
    """A janela cruza atendimentos (CONTEXT.md, "Conversa cliente"): bolha do outro lado da marca de
    pausa não faz o "oi" de agora ser meio de conversa — é abertura de novo."""
    antes_da_pausa = [HumanMessage(content="oi"), AIMessage(content="Oii amor")]

    assert _conversa_em_andamento([*antes_da_pausa, _pausa(), HumanMessage(content="oi")]) is False
    assert (
        _conversa_em_andamento(
            [*antes_da_pausa, _pausa(), HumanMessage(content="oi"), AIMessage(content="Oii")]
        )
        is True
    )


# --- o bloco renderizado ---------------------------------------------------------------------


async def test_oi_seco_no_primeiro_contato_nao_recebe_a_proibicao_de_cumprimentar() -> None:
    """O gatilho do bug: `estado='Novo'`, janela só com o "oi" dele. A instrução que suprimia o
    cumprimento não pode estar na cauda — é ela que vence a `<abertura>` por posição."""
    bloco = await _bloco([HumanMessage(content="oi")], "Novo")

    assert _NAO_RECUMPRIMENTE not in bloco
    # o resto do <antes_de_perguntar> (anti-repergunta) é incondicional e continua de pé
    assert "não repergunte" in bloco


async def test_atendimento_com_historico_mantem_a_proibicao() -> None:
    """O outro lado: o guard existe contra a IA reabrindo com "Oii amor" no 9º turno."""
    bloco = await _bloco(
        [
            HumanMessage(content="oi"),
            AIMessage(content="Oii"),
            HumanMessage(content="quanto é 1 hora?"),
        ],
        "Triagem",
    )

    assert _NAO_RECUMPRIMENTE in bloco


# --- o <proximo_passo> -----------------------------------------------------------------------

# Paráfrases da sonda-de-balcão que a `<abertura>` proíbe ("o que você procura?", "o que ele quer").
_SONDA = re.compile(r"\bo que (ele|voc[êe]) (procura|quer|busca|deseja|precisa)", re.IGNORECASE)


def test_nenhuma_fase_nomeia_o_objetivo_com_o_lexico_da_sonda() -> None:
    """ECO MULTI-SITE (`agente/CLAUDE.md`, "Fase do funil apontada pela cauda"): o `<proximo_passo>`
    é o único texto do turno que nomeia a fase e o que a cauda põe mais perto da resposta. Descrever
    o alvo da fase com o léxico do probe punha o probe na boca dela."""
    culpadas = {estado: f for estado, f in _PROXIMO_PASSO.items() if _SONDA.search(f)}

    assert not culpadas, f"léxico de sonda-de-balcão no <proximo_passo>: {culpadas}"


async def test_o_bloco_do_primeiro_turno_nao_manda_perguntar_o_que_ele_procura() -> None:
    """Ponta a ponta no texto que chega ao modelo: a frase-guia da fase `Novo`."""
    bloco = await _bloco([HumanMessage(content="oi")], "Novo")

    proximo_passo = bloco.split("<proximo_passo>")[1].split("</proximo_passo>")[0]

    assert not _SONDA.search(proximo_passo), proximo_passo
    assert "<abertura>" in proximo_passo  # a fase continua sendo apontada
