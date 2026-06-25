"""no_llm: fallback deterministico de extracao por turno (#2, diagnostico E2E 2026-06-09).

Quando o LLM encerra o turno SEM chamar registrar_extracao, o no forca 1 chamada (tool_choice)
antes de fechar -- a FSM nao defasa. Sem API real (chat FAKE) nem banco: cobre so o roteamento
do no `llm`. Roda no gate `-m "not needs_key and not needs_db"`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from barra.agente.ferramentas.extracao import registrar_extracao
from barra.agente.nos.llm import no_llm
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeBound:
    """ainvoke devolve um AIMessage fixo e registra as mensagens com que foi chamado."""

    def __init__(self, resp: AIMessage | None) -> None:
        self._resp = resp
        self.chamadas: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        assert self._resp is not None
        return self._resp


class _FakeChat:
    """bind_tools devolve binds distintos p/ o caminho normal e o forcado (tool_choice)."""

    model = "claude-test"

    def __init__(self, resp_normal: AIMessage, resp_forcado: AIMessage | None) -> None:
        self.normal = _FakeBound(resp_normal)
        self.forcado = _FakeBound(resp_forcado)

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeBound:
        return self.forcado if tool_choice is not None else self.normal


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))


def _texto_final() -> AIMessage:
    """Resposta final ao cliente: texto, sem tool_calls (o caso que defasava a FSM)."""
    return AIMessage(
        content="às 10h15 te serve?",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


def _texto_mais_extracao() -> AIMessage:
    """1a passagem inline do DeepSeek: texto client-facing + registrar_extracao na MESMA AIMessage.

    Padrao que o Sonnet nao faz no abridor (responde OU extrai), mas o DeepSeek V4 Flash faz --
    e que, sem o curto-circuito, deixa a reentrada do ReAct reinvocar o modelo (2a bolha espuria,
    trace 022e0a70 de 2026-06-18). finish_reason=tool_calls (formato OpenRouter).
    """
    return AIMessage(
        content="Oii\n\ntudo sim, e você",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )


def _texto_mais_leitura() -> AIMessage:
    """ReAct legitimo: texto + tool de LEITURA (consultar_agenda). A reentrada deve reinvocar
    (o modelo precisa do resultado da agenda p/ seguir) -- nao pode cair no curto-circuito."""
    return AIMessage(
        content="deixa eu ver minha agenda",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[{"name": "consultar_agenda", "args": {}, "id": "ca1", "type": "tool_call"}],
    )


def _extracao(
    motivo_parada: str = "tool_use", *, com_tool: bool = True, chave: str = "stop_reason"
) -> AIMessage:
    # chave="stop_reason" (Anthropic) ou "finish_reason" (OpenRouter): o no le os dois via
    # core.llm.motivo_parada.
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={chave: motivo_parada},
        tool_calls=(
            [{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}]
            if com_tool
            else []
        ),
    )


async def test_forca_extracao_quando_llm_esquece() -> None:
    """LLM encerra sem registrar_extracao -> forca 1 chamada e despacha pelo `tools`."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="daqui uma hr")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_extracao_forcada"] is True
    # texto ao cliente preservado + extracao forcada anexada, nessa ordem
    assert cmd.update["messages"] == [chat.normal._resp, chat.forcado._resp]
    # forcado roda sobre o contexto SEM o `resp` assistant (senao 2 assistant consecutivas = 400)
    assert chat.forcado.chamadas == [state["messages"]]


async def test_reentrada_pos_forca_fecha_sem_reinvocar_modelo() -> None:
    """Guard `_extracao_forcada`: pós-`tools`, fecha no post_process sem chamar o modelo de novo."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")], "_extracao_forcada": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []  # modelo NAO reinvocado (sem bolha dupla, sem custo)
    assert chat.forcado.chamadas == []


async def test_nao_forca_quando_ja_extraiu_no_turno() -> None:
    """registrar_extracao ja rodou neste turno (AIMessage com usage) -> sem forcamento."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    # janela ja contem uma extracao deste turno (usage_metadata != None)
    state = {"messages": [HumanMessage(content="oi"), _extracao()]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]
    assert chat.forcado.chamadas == []  # nao forcou


async def test_extracao_forcada_truncada_e_descartada() -> None:
    """Forcado trunca (args incompletos) -> descarta e fecha; nunca persiste payload parcial."""
    chat = _FakeChat(_texto_final(), _extracao("max_tokens"))
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]  # so o texto; forcado descartado
    assert "_extracao_forcada" not in cmd.update


async def test_extracao_forcada_openrouter_length_descartada() -> None:
    """Forcado no provider OpenRouter trunca como finish_reason=length (com tool_call presente) ->
    o no descarta via PARADA_TRUNCADA, igual ao max_tokens da Anthropic. Prova o mapeamento
    provider-aware do motivo de parada na #2."""
    chat = _FakeChat(_texto_final(), _extracao("length", chave="finish_reason"))
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert cmd.update["messages"] == [chat.normal._resp]  # forcado truncado descartado
    assert "_extracao_forcada" not in cmd.update


async def test_kill_switch_desliga_forcamento(monkeypatch: pytest.MonkeyPatch) -> None:
    """forcar_extracao_por_turno=False -> chat_forcado None, comportamento antigo (sem força)."""
    monkeypatch.setattr(get_settings(), "forcar_extracao_por_turno", False)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.forcado.chamadas == []


async def test_extracao_forcada_roteia_pro_chat_barato_sem_system() -> None:
    """chat_extracao_barata injetado -> forca no Haiku sobre a janela SEM o SystemMessage geral."""
    chat = _FakeChat(_texto_final(), _extracao())
    barato = _FakeChat(_extracao(), _extracao())  # so o bind forcado (tool_choice) e usado
    node = no_llm(chat, [registrar_extracao], chat_extracao_barata=barato)
    system = SystemMessage(content="PERSONA GIGANTE ~14k tokens")
    state = {"messages": [system, HumanMessage(content="daqui uma hr")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_extracao_forcada"] is True
    # texto do Sonnet preservado + extracao do chat BARATO, nessa ordem
    assert cmd.update["messages"] == [chat.normal._resp, barato.forcado._resp]
    # o Sonnet NAO foi chamado p/ a extracao; o barato foi
    assert chat.forcado.chamadas == []
    assert len(barato.forcado.chamadas) == 1
    # janela do barato: system minimo de extracao (nao o gigante) + a conversa preservada
    janela = barato.forcado.chamadas[0]
    systems = [m for m in janela if isinstance(m, SystemMessage)]
    assert len(systems) == 1 and systems[0].content != system.content
    assert HumanMessage(content="daqui uma hr") in janela


async def test_tool_call_normal_segue_react_sem_forcar() -> None:
    """Regressao: resposta COM tool_call (loop ReAct) nao aciona o fallback."""
    chat = _FakeChat(_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert "_extracao_forcada" not in cmd.update
    assert chat.forcado.chamadas == []


async def test_texto_mais_extracao_inline_marca_turno_concluido() -> None:
    """Bug DeepSeek (1/2): texto + registrar_extracao na MESMA msg -> marca o turno concluido.

    A extracao ainda roteia pelo `tools` (FSM intacta), mas a flag sinaliza a reentrada a fechar
    sem reinvocar (espelha _extracao_forcada). NAO forca: a extracao ja veio inline."""
    chat = _FakeChat(_texto_mais_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert cmd.update["_resposta_inline_concluida"] is True
    assert cmd.update["messages"] == [chat.normal._resp]
    assert chat.forcado.chamadas == []  # extracao veio inline -> sem forcamento


async def test_reentrada_pos_extracao_inline_nao_reinvoca_modelo() -> None:
    """Bug DeepSeek (2/2): pos-`tools`, a reentrada do ReAct NAO pode reinvocar o modelo.

    Sem o guard, o DeepSeek tagarela "deixou ele conduzir" (2a bolha espuria, trace 022e0a70).
    Com a flag, fecha direto no post_process -- mesma protecao do _extracao_forcada."""
    chat = _FakeChat(_texto_mais_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="oi")], "_resposta_inline_concluida": True}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []  # modelo NAO reinvocado -> sem 2a bolha
    assert chat.forcado.chamadas == []


async def test_texto_mais_tool_de_leitura_nao_curto_circuita() -> None:
    """ReAct legitimo: texto + tool de LEITURA (consultar_agenda) deve reinvocar normalmente --
    o curto-circuito so vale p/ a tool write-only de extracao."""
    chat = _FakeChat(_texto_mais_leitura(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {"messages": [HumanMessage(content="amanha 10h tem?")]}

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "tools"
    assert "_resposta_inline_concluida" not in cmd.update  # nao curto-circuita


def _tool_erro(tool_call_id: str = "ex1") -> ToolMessage:
    """ToolMessage de erro recuperavel (ConflitoAgenda -> ToolException -> status=error)."""
    return ToolMessage(
        content=(
            "ERRO: o horário escolhido já está reservado para a modelo. "
            "Ofereça outro horário ao cliente."
        ),
        tool_call_id=tool_call_id,
        status="error",
    )


async def test_forcada_com_erro_recuperavel_remove_falsa_confirmacao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH (bughunt #1): pos-`tools`, a extracao FORCADA errou recuperavel (ConflitoAgenda) -> a
    transacao reverteu (sem bloqueio). O `resp` (texto que confirmou o horario, SEM tool_call) esta
    numa msg separada do `forcado` que errou, entao extrair_texto_do_turno NAO o filtraria -> iria
    ao cliente como FALSA CONFIRMACAO. O guard remove o rascunho stale -> turno fecha mudo."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", False)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    resp = AIMessage(
        id="resp-1",
        content="combinado, te espero às 22h",  # falsa confirmacao
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[],
    )
    forcado = AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )
    state = {
        "messages": [HumanMessage(content="22h"), resp, forcado, _tool_erro("ex1")],
        "_extracao_forcada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []  # NAO reinvoca (este passe nao faz auto-reoferta)
    ids_removidos = {m.id for m in cmd.update["messages"]}
    assert "resp-1" in ids_removidos  # falsa confirmacao removida
    assert "forc-1" not in ids_removidos  # forcado (tem tool_call) preservado


async def test_inline_com_erro_recuperavel_fecha_sem_remover_texto_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH (bughunt #2): inline (texto+extracao na MESMA msg) errou recuperavel -> fecha sem
    reinvocar; o texto inline carrega o proprio tool_call que errou, entao extrair_texto_do_turno
    ja o filtra downstream (cliente nao recebe a falsa confirmacao). Aqui remocoes fica vazio."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", False)
    chat = _FakeChat(_texto_mais_extracao(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    inline = AIMessage(
        id="inline-1",
        content="combinado, te espero às 22h",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )
    state = {
        "messages": [HumanMessage(content="22h"), inline, _tool_erro("ex1")],
        "_resposta_inline_concluida": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == []
    ids_removidos = {m.id for m in (cmd.update or {}).get("messages", [])}
    assert (
        "inline-1" not in ids_removidos
    )  # tem tool_call -> filtrado downstream, nao removido aqui


async def test_forcada_com_sucesso_nao_remove_texto() -> None:
    """Regressao: extracao forcada com SUCESSO (ToolMessage status default) -> curto-circuito normal,
    NAO remove o texto (ele e a resposta legitima do turno). Blast radius do fix = so o caso de erro."""
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    resp = AIMessage(
        id="resp-1",
        content="às 10h te serve?",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[],
    )
    forcado = AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )
    state = {
        "messages": [
            HumanMessage(content="10h"),
            resp,
            forcado,
            ToolMessage(content="ok", tool_call_id="ex1"),
        ],
        "_extracao_forcada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert not (cmd.update or {}).get("messages")  # nada removido


# ============================================================================
# Auto-reoferta (#1/#2 follow-up, settings.reoferta_automatica_habilitada): em vez de fechar MUDO
# num erro recuperavel pos-extracao, a IA reoferta um horario. One-shot via _reoferta_tentada.
# ============================================================================


def _resp_reoferta() -> AIMessage:
    """Reoferta gerada na reentrada: texto client-facing, sem tool_call."""
    return AIMessage(
        content="ah amor, 22h não vai dar; 23h te serve?",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


def _forcado_msg() -> AIMessage:
    return AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex1", "type": "tool_call"}],
    )


async def test_reoferta_off_forcada_erro_fecha_mudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """flag OFF (pinado explicitamente): erro recuperavel pos-extracao fecha MUDO, sem reofertar --
    comportamento antigo preservado pelo kill-switch (silencio > reserva fantasma)."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", False)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    resp = AIMessage(id="resp-1", content="te espero às 22h", usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]
    state = {
        "messages": [HumanMessage(content="22h"), resp, _forcado_msg(), _tool_erro("ex1")],
        "_extracao_forcada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"  # mute, NAO reoferta
    assert "resp-1" in {m.id for m in cmd.update["messages"]}  # falsa confirmacao removida
    assert chat.normal.chamadas == []  # nao reinvoca


async def test_reoferta_on_e_o_default() -> None:
    """Trava o DEFAULT ON (sem monkeypatch): erro recuperavel forcado reoferta (goto=llm) com os
    settings de fabrica. Se o default reverter p/ False, este teste pega -- senao todos os testes
    do flag pinam o valor e nenhum assertaria o default real (code-review 2026-06-25)."""
    assert get_settings().reoferta_automatica_habilitada is True  # contrato do default
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    resp = AIMessage(id="resp-1", content="te espero às 22h", usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]
    state = {
        "messages": [HumanMessage(content="22h"), resp, _forcado_msg(), _tool_erro("ex1")],
        "_extracao_forcada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "llm"  # reoferta por default, NAO mute
    assert cmd.update["_reoferta_tentada"] is True


async def test_reoferta_on_forcada_volta_pro_llm_limpando_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flag ON: erro recuperavel forcado -> volta ao no llm (goto=llm), limpa os guards, marca
    _reoferta_tentada e remove o rascunho stale (falsa confirmacao). NAO reinvoca neste passe."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", True)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    resp = AIMessage(id="resp-1", content="te espero às 22h", usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]
    state = {
        "messages": [HumanMessage(content="22h"), resp, _forcado_msg(), _tool_erro("ex1")],
        "_extracao_forcada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "llm"
    assert cmd.update["_reoferta_tentada"] is True
    assert cmd.update["_extracao_forcada"] is False
    assert cmd.update["_resposta_inline_concluida"] is False
    ids_removidos = {m.id for m in cmd.update["messages"]}
    assert "resp-1" in ids_removidos  # stale removido (sai das mensagens E nao vai ao cliente)
    assert "forc-1" not in ids_removidos  # forcado (tem tool_call) preservado p/ a re-invocacao
    assert chat.normal.chamadas == []  # a re-invocacao acontece na REENTRADA, nao neste passe


async def test_reoferta_reentrada_reinvoca_e_reoferta(monkeypatch: pytest.MonkeyPatch) -> None:
    """flag ON, reentrada pos-reoferta (guards limpos, _reoferta_tentada=True, stale ja removido):
    o fluxo normal reinvoca o modelo (com as msgs validas) e ele REOFERTA. Sem re-forcamento (a
    extracao que errou ja conta em _extraiu_no_turno)."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", True)
    chat = _FakeChat(_resp_reoferta(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    state = {
        "messages": [HumanMessage(content="22h"), _forcado_msg(), _tool_erro("ex1")],
        "_reoferta_tentada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"
    assert chat.normal.chamadas == [state["messages"]]  # reinvocou com as msgs limpas (validas)
    assert cmd.update["messages"] == [chat.normal._resp]  # a reoferta vai ao cliente
    assert chat.forcado.chamadas == []  # nao re-forcou (ja extraiu no turno)


async def test_reoferta_one_shot_segundo_erro_fecha_mudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """flag ON mas _reoferta_tentada ja True (a reoferta TAMBEM errou): NAO reoferta de novo,
    fecha MUDO. Bounded: no maximo uma reoferta por turno."""
    monkeypatch.setattr(get_settings(), "reoferta_automatica_habilitada", True)
    chat = _FakeChat(_texto_final(), _extracao())
    node = no_llm(chat, [registrar_extracao])
    inline = AIMessage(
        id="re-1",
        content="23h então",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[{"name": "registrar_extracao", "args": {}, "id": "ex2", "type": "tool_call"}],
    )
    state = {
        "messages": [HumanMessage(content="22h"), inline, _tool_erro("ex2")],
        "_resposta_inline_concluida": True,
        "_reoferta_tentada": True,
    }

    cmd = await node(state, _runtime())  # type: ignore[arg-type]

    assert cmd.goto == "post_process"  # mute, nao reoferta de novo
    assert chat.normal.chamadas == []
    assert not {m.id for m in (cmd.update or {}).get("messages", [])}  # inline filtrado downstream
