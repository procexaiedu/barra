"""no_extrair: roteamento do turno com a extracao executada INLINE (issue 01).

Prova os 4+1 caminhos de decisao do no `extrair` com chat FAKE + tool de extracao FAKE (sem API
real nem banco): a EXECUCAO da tool e substituida por um ToolMessage roteirizado, entao o assunto
aqui e so a decisao de rota. A injecao real do ToolRuntime + persistencia vive em
tests/integracao/test_extrair_inline.py (needs_db). Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from barra.agente._texto_turno import desfecho_do_turno, extrair_texto_do_turno
from barra.agente.nos.extrair import _envelopar_nota_interna, _extracao_errou, no_extrair
from barra.dominio.atendimentos.service import _MSG_GUARD_PISO
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeForcado:
    """Bind forcado fake: ainvoke devolve o AIMessage forcado fixo e registra as janelas recebidas."""

    def __init__(self, forcado: AIMessage) -> None:
        self._forcado = forcado
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        return self._forcado


class _FakeChat:
    """bind_tools(tool_choice=...) -> o bind forcado. `model` p/ o label das metricas de token."""

    model = "deepseek-test"

    def __init__(self, forcado: AIMessage) -> None:
        self.forcado = _FakeForcado(forcado)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeForcado:
        return self.forcado


class _FakeToolExtracao:
    """Tool de extracao fake: `ainvoke` devolve um ToolMessage roteirizado (nao toca o DB).

    Registra as chamadas p/ os testes provarem que o guard de qualidade NAO executa a tool.
    """

    name = "registrar_extracao"

    def __init__(self, tool_message: ToolMessage) -> None:
        self._tm = tool_message
        self.chamadas: list[Any] = []

    async def ainvoke(self, chamada: Any) -> ToolMessage:
        self.chamadas.append(chamada)
        return self._tm


def _runtime() -> SimpleNamespace:
    # _executar_inline le context/stream_writer/store do Runtime do no.
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"), stream_writer=None, store=None)


def _fala(id_: str = "resp-1", content: str = "às 22h te serve?") -> AIMessage:
    """Fala final do turno: texto client-facing, sem tool_calls (ultima msg do state, contrato)."""
    return AIMessage(id=id_, content=content, usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]


def _forcado(
    *, stop: str = "tool_calls", chave: str = "finish_reason", com_tool: bool = True
) -> AIMessage:
    return AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={chave: stop},
        tool_calls=(
            [
                {
                    "name": "registrar_extracao",
                    "args": {"intencao": "cotacao"},
                    "id": "ex1",
                    "type": "tool_call",
                }
            ]
            if com_tool
            else []
        ),
    )


def _tool_ok(content: str = "Extracao registrada.") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="ex1", name="registrar_extracao")


def _tool_erro() -> ToolMessage:
    return ToolMessage(
        content="ERRO: o horário escolhido já está reservado para a modelo. Ofereça outro.",
        tool_call_id="ex1",
        name="registrar_extracao",
        status="error",
    )


# --- sucesso / escalada canned -> post_process -----------------------------------------------


async def test_sucesso_roteia_post_process_com_registro() -> None:
    """Extracao OK -> post_process carregando o AIMessage forcado + o ToolMessage; a fala original
    ja esta no state (nao e re-emitida nem removida)."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    fala = _fala()
    state = {"messages": [HumanMessage(content="22h"), fala]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.forcado._forcado, tool._tm]
    # a extracao rodou sobre a janela SEM a fala final (so a HumanMessage)
    assert chat.forcado.chamadas == [[HumanMessage(content="22h")]]
    assert len(tool.chamadas) == 1  # tool executada inline


async def test_escalada_canned_roteia_post_process() -> None:
    """Escalada canned (guard de piso/tipo/reagendamento) retorna `mensagem` normal (novo_estado:
    None), NAO erro -> mesmo ramo do sucesso (post_process). A canned de espera e solta la (o
    content bate MENSAGENS_GUARD_ESCALADA)."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok(content=_MSG_GUARD_PISO))
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="faz 300?"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.forcado._forcado, tool._tm]


# --- guard de qualidade: forcado truncado / sem tool_call -> post_process (so a fala) ---------


async def test_forcado_truncado_descarta_e_fecha_com_fala() -> None:
    """Forcado trunca (finish_reason=length) -> descarta, fecha SO com a fala original (ja no
    state), e NAO executa a tool (nunca persiste payload parcial)."""
    chat = _FakeChat(_forcado(stop="length"))
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert not cmd.update  # sem messages: a fala ja esta no state
    assert tool.chamadas == []  # tool NAO executada


async def test_forcado_sem_tool_call_descarta_e_fecha_com_fala() -> None:
    """Forcado sem tool_call (raro) -> mesmo guard: descarta e fecha so com a fala; tool intacta."""
    chat = _FakeChat(_forcado(com_tool=False, stop="stop"))
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert not cmd.update
    assert tool.chamadas == []


# --- erro recuperavel: auto-reoferta (goto=llm) e 2a falha (mute) -----------------------------


async def test_erro_recuperavel_reoferta_on_volta_pro_llm() -> None:
    """Default ON: erro recuperavel -> goto=llm, seta _reoferta_tentada, remove a fala stale (falsa
    confirmacao) e carrega o par forcado+ToolMessage p/ o llm ler o erro e reofertar."""
    assert get_settings().reoferta_automatica_habilitada is True  # contrato do default
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    fala = _fala(content="combinado, te espero às 22h")  # falsa confirmacao
    state = {"messages": [HumanMessage(content="22h"), fala]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "llm"
    assert cmd.update["_reoferta_tentada"] is True
    msgs = cmd.update["messages"]
    # par p/ o llm ver o erro; o ToolMessage vai ENVELOPADO (mesmo tool_call_id, corpo na cauda)
    assert chat.forcado._forcado in msgs
    (tm,) = [m for m in msgs if isinstance(m, ToolMessage)]
    assert tm.tool_call_id == tool._tm.tool_call_id
    assert str(tm.content).endswith(str(tool._tm.content))
    remocoes = [m for m in msgs if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]  # fala stale removida


async def test_erro_recuperavel_reoferta_off_fecha_mudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """flag OFF: erro recuperavel fecha MUDO (post_process) removendo a fala stale -- silencio >
    reserva fantasma. NAO volta ao llm."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", False)
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert "_reoferta_tentada" not in cmd.update
    remocoes = [m for m in cmd.update["messages"] if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]


async def test_erro_recuperavel_segunda_falha_fecha_mudo() -> None:
    """flag ON mas _reoferta_tentada ja True (a reoferta TAMBEM errou): NAO reoferta de novo, fecha
    MUDO. Bounded: no maximo uma reoferta por turno."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()], "_reoferta_tentada": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"  # mute, nao reoferta de novo
    remocoes = [m for m in cmd.update["messages"] if isinstance(m, RemoveMessage)]
    assert [m.id for m in remocoes] == ["resp-1"]


# --- envelope de canal do erro que vai ao chat (prod 29/07, trace 06db4298) --------------------


async def test_reoferta_envelopa_o_erro_como_nota_interna() -> None:
    """O ToolMessage de erro e uma ordem em 2a pessoa no registro da fala; ao chegar ao contexto do
    chat sem moldura, o chat a obedeceu EM VOZ ALTA ("Vou cotar agora."). A copia que vai ao `llm`
    leva a etiqueta de nota interna ANTES do corpo -- que segue intacto na cauda, senao o llm nao
    sabe o que reofertar."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "llm"
    (tm,) = [m for m in cmd.update["messages"] if isinstance(m, ToolMessage)]
    texto = str(tm.content)
    assert texto.startswith("ERRO: [nota interna do sistema")
    assert "nunca fala ao cliente" in texto
    assert texto.endswith(str(_tool_erro().content))  # corpo do erro intacto, na cauda
    assert str(tool._tm.content) == str(_tool_erro().content)  # o original nao foi mutado


async def test_ramo_mudo_manda_o_erro_cru_ao_state() -> None:
    """No mute o erro nao chega a contexto de chat nenhum -- vai cru, e o `erros_tool` do trace do
    desfecho mais comum fica sem a etiqueta."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_erro())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="22h"), _fala()], "_reoferta_tentada": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert tool._tm in cmd.update["messages"]


def test_erro_envelopado_segue_casando_os_tres_consumidores() -> None:
    """A FORMA e contrato: `status="error"`, prefixo "ERRO:" e `tool_call_id` sobrevivem ao envelope.
    Sem eles, (1) `_extracao_errou` para de ver o erro, (2) `extrair_texto_do_turno` para de
    descartar o rascunho superado pela retentativa -- a fala DUPLICA ao cliente -- e (3) o trace
    perde `erros_tool`. Os tres quebram em silencio."""
    envelopado = _envelopar_nota_interna(_tool_erro())

    assert envelopado.status == "error"
    assert str(envelopado.content).startswith("ERRO:")
    assert envelopado.tool_call_id == "ex1"
    assert _extracao_errou(envelopado) is True

    rascunho = AIMessage(
        id="draft",
        content="combinado, te espero às 22h",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )
    assert extrair_texto_do_turno([rascunho, envelopado]) == ""  # (2) rascunho descartado por id
    erros = desfecho_do_turno({"messages": [rascunho, envelopado]})["erros_tool"]
    assert len(erros) == 1 and "já está reservado" in erros[0]  # (3) erro legivel no trace


# --- extracao barata: janela sem o BP_GERAL --------------------------------------------------


async def test_extracao_barata_roda_sem_system_geral() -> None:
    """chat_extracao_barata injetado -> forca no barato sobre a janela SEM o SystemMessage geral
    (system minimo de extracao no lugar), a fala final excluida."""
    chat = _FakeChat(_forcado())  # nao usado p/ a extracao (barato tem prioridade)
    barato = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, barato, tool)  # type: ignore[arg-type]
    system = SystemMessage(content="PERSONA GIGANTE ~14k tokens")
    state = {"messages": [system, HumanMessage(content="22h"), _fala()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.forcado.chamadas == []  # o principal NAO foi chamado
    assert len(barato.forcado.chamadas) == 1
    janela = barato.forcado.chamadas[0]
    systems = [m for m in janela if isinstance(m, SystemMessage)]
    assert len(systems) == 1 and systems[0].content != system.content  # system minimo
    assert HumanMessage(content="22h") in janela
    assert _fala() not in janela  # a fala final foi excluida da janela de extracao


# --- janela DEDICADA da extracao (spec extracao-janela-dedicada) ------------------------------


def _state_com_pecas(cauda_do_chat: str) -> dict[str, Any]:
    """State como o prepare_context o deixa: `messages` com a cauda INCHADA (lembrete + msg do
    cliente + contexto dinamico, fundidos) e as pecas da janela dedicada em canais proprios. Os
    `id` sao os do banco (uuid da linha em `mensagens`), como `traduzir_mensagens` os poe."""
    return {
        "messages": [
            SystemMessage(content="PERSONA GIGANTE ~14k tokens"),
            HumanMessage(content="e quanto fica?", id="m1"),
            AIMessage(content="600 amor 🥰", id="m2", usage_metadata=_USAGE),  # type: ignore[arg-type]
            HumanMessage(content=cauda_do_chat, id="m3"),
            _fala(),
        ],
        "conversa_crua": [
            HumanMessage(content="e quanto fica?", id="m1"),
            AIMessage(content="600 amor 🥰", id="m2", usage_metadata=_USAGE),  # type: ignore[arg-type]
            HumanMessage(content="vc faz massagem?", id="m3"),
        ],
        "agora_turno": datetime(2026, 7, 25, 14, 30),
        "ja_registrado": "<ja_registrado>\n<tipo>interno</tipo>\n</ja_registrado>\n",
    }


async def test_janela_dedicada_troca_a_cauda_inchada_pela_conversa_crua() -> None:
    """A extracao recebe a conversa CRUA + a cauda de estado, nunca a mensagem inchada do chat: o
    contexto dinamico e o lembrete de persona (de onde o extrator copiava os proprios campos) nao
    chegam nela."""
    barato = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(_FakeChat(_forcado()), barato, tool)  # type: ignore[arg-type]
    inchada = (
        "<lembrete_silencioso>segure firme quem você é</lembrete_silencioso>\n\n"
        "vc faz massagem?\n\n"
        "<situacao_do_atendimento><ja_combinado><tipo>interno</tipo></ja_combinado>"
        "<proximo_passo>confirmar o horário</proximo_passo></situacao_do_atendimento>"
    )

    cmd = await node(_state_com_pecas(inchada), _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    texto = "\n".join(str(m.content) for m in barato.forcado.chamadas[0])
    assert "vc faz massagem?" in texto  # a fala do cliente sobrevive, crua
    assert "<lembrete_silencioso>" not in texto
    assert "<situacao_do_atendimento>" not in texto
    assert "<proximo_passo>" not in texto


async def test_janela_dedicada_poe_ancora_e_estado_na_cauda() -> None:
    """Ancora temporal + `<ja_registrado>` numa unica HumanMessage no FIM: o prefixo (system +
    conversa append-only) fica estavel e o bloco volatil vai na cauda."""
    barato = _FakeChat(_forcado())
    node = no_extrair(_FakeChat(_forcado()), barato, _FakeToolExtracao(_tool_ok()))  # type: ignore[arg-type]

    await node(_state_com_pecas("vc faz massagem?"), _runtime())  # type: ignore[arg-type]

    janela = barato.forcado.chamadas[0]
    cauda = str(janela[-1].content)
    assert isinstance(janela[-1], HumanMessage)
    assert '<agenda hoje="2026-07-25" agora="14:30"/>' in cauda
    assert "<ja_registrado>" in cauda
    # o bloco fica SO na cauda: a conversa que o precede nao carrega estado nenhum
    assert all("<ja_registrado>" not in str(m.content) for m in janela[:-1])


async def test_janela_dedicada_vale_tambem_sem_o_modelo_barato() -> None:
    """Kill-switch do modelo barato desligado: muda o prefixo (o BP_GERAL do chat volta), nao a
    dieta da extracao — a conversa segue crua e a cauda de estado segue no fim."""
    chat = _FakeChat(_forcado())
    node = no_extrair(chat, None, _FakeToolExtracao(_tool_ok()))  # type: ignore[arg-type]

    await node(_state_com_pecas("vc faz massagem?\n\n<situacao_do_atendimento/>"), _runtime())  # type: ignore[arg-type]

    janela = chat.forcado.chamadas[0]
    assert isinstance(janela[0], SystemMessage)
    assert "PERSONA GIGANTE" in str(janela[0].content)  # prefixo do chat preservado
    texto = "\n".join(str(m.content) for m in janela)
    assert "<situacao_do_atendimento" not in texto
    assert "<ja_registrado>" in str(janela[-1].content)


async def test_prefixo_da_janela_dedicada_e_estavel_entre_turnos() -> None:
    """A disciplina de bytes que motiva a cauda: com a conversa append-only, a janela do turno
    seguinte COMECA com a janela do turno anterior menos a cauda — o volátil (âncora + estado)
    fica todo no fim, então o prefixo da chamada barata sai byte-idêntico e o cache casa."""
    barato = _FakeChat(_forcado())
    node = no_extrair(_FakeChat(_forcado()), barato, _FakeToolExtracao(_tool_ok()))  # type: ignore[arg-type]
    turno1 = _state_com_pecas("vc faz massagem?")
    turno2 = _state_com_pecas("e às 22h?")
    turno2["conversa_crua"] = [
        *turno1["conversa_crua"],
        AIMessage(content="Faço sim amor 🥰", id="m4", usage_metadata=_USAGE),  # type: ignore[arg-type]
        HumanMessage(content="e às 22h?", id="m5"),
    ]
    turno2["agora_turno"] = datetime(2026, 7, 25, 14, 35)
    turno2["ja_registrado"] = (
        "<ja_registrado>\n<tipo>interno</tipo>\n<hora>22:00</hora>\n</ja_registrado>\n"
    )

    await node(turno1, _runtime())  # type: ignore[arg-type]
    await node(turno2, _runtime())  # type: ignore[arg-type]

    def _bytes(janela: list[Any]) -> list[str]:
        return [f"{m.type}:{m.content}" for m in janela]

    prefixo_turno1 = _bytes(barato.forcado.chamadas[0])[:-1]  # tudo menos a cauda
    assert _bytes(barato.forcado.chamadas[1])[: len(prefixo_turno1)] == prefixo_turno1


async def test_reoferta_ve_o_registro_de_erro_da_primeira_extracao() -> None:
    """A auto-reoferta (`extrair` -> `llm` -> `extrair`) depende de o extrator VER que o horário
    conflitou: sem o par AIMessage+ToolMessage do erro ele repetiria o mesmo horário e o turno
    fecharia mudo. A conversa crua é a janela do BANCO — o que o turno produziu depois dela entra
    logo após, antes da cauda de estado."""
    barato = _FakeChat(_forcado())
    node = no_extrair(_FakeChat(_forcado()), barato, _FakeToolExtracao(_tool_ok()))  # type: ignore[arg-type]
    state = _state_com_pecas("vc faz massagem?")
    erro = ToolMessage(
        content="ERRO: o horário escolhido já está reservado para a modelo. Ofereça outro.",
        tool_call_id="ex1",
        name="registrar_extracao",
        id="tm-1",
        status="error",
    )
    state["messages"] = [*state["messages"][:-1], _forcado(), erro, _fala(id_="resp-2")]
    state["_reoferta_tentada"] = True

    await node(state, _runtime())  # type: ignore[arg-type]

    janela = barato.forcado.chamadas[0]
    assert erro in janela  # o extrator vê o conflito
    assert "<ja_registrado>" in str(janela[-1].content)  # e o estado segue sendo a última coisa


async def test_sem_pecas_no_state_cai_na_janela_recebida() -> None:
    """Sem as pecas (no alcancado fora do fluxo do prepare_context): comportamento antigo — janela
    recebida sem os blocos system e sem cauda. Nunca uma extracao sem conversa."""
    barato = _FakeChat(_forcado())
    node = no_extrair(_FakeChat(_forcado()), barato, _FakeToolExtracao(_tool_ok()))  # type: ignore[arg-type]
    state = {"messages": [SystemMessage(content="PERSONA"), HumanMessage(content="22h"), _fala()]}

    await node(state, _runtime())  # type: ignore[arg-type]

    janela = barato.forcado.chamadas[0]
    assert [str(m.content) for m in janela[1:]] == ["22h"]


# --- o no nao julga mais `intencao` (spec extracao-promocao-intencao) -------------------------


async def test_no_repassa_a_intencao_do_extrator_sem_corrigir() -> None:
    """O piso de `intencao` que vivia aqui foi absorvido pela derivacao por evidencia, no dominio
    (dominio/atendimentos/service.py): mesmo com a janela evidenciando o horario, o no repassa
    INTACTO o que o extrator julgou — quem promove e o dominio, lendo a marca (regressao em
    tests/integracao/test_promocao_intencao.py)."""
    chat = _FakeChat(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    node = no_extrair(chat, None, tool)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="sim"), _fala()], "horario_evidenciado": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert tool.chamadas[0]["args"]["intencao"] == "cotacao"
    # a flag do State segue chegando na tool (e dali ao dominio), so nao mexe mais na intencao aqui
    assert tool.chamadas[0]["args"]["runtime"].state["horario_evidenciado"] is True
