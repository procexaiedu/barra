"""Extracao PARALELA (settings.extracao_paralela_habilitada): o no `llm` dispara a chamada forcada
como asyncio.Task e o no `extrair` a consome — quando ela serve.

Medicao que motivou (traces 11/08): extracao 2,56s + chat 2,51s em SERIE = ~5s por turno. O que
torna o paralelismo LEGITIMO e a janela dedicada da extracao (`_janela_para_extracao`), que exclui a
fala do turno; o que o torna PERIGOSO e o `do_turno` da mesma funcao, que inclui o que o turno
produziu (ToolMessages do ReAct, e o par [forcado, ERRO] da 1a extracao na 2a passagem da reoferta).
Por isso o `extrair` compara a impressao da janela antes de consumir a Task.

Chat FAKE + tool de extracao FAKE (sem API real nem banco), no estilo de test_extrair_no.py. O
turno e montado a mao (llm -> aplica o update -> extrair) porque o grafo inteiro exigiria o
prepare_context contra o Postgres — o assunto aqui e o handoff da Task entre os dois nos.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from barra.agente.contexto import ContextAgente
from barra.agente.estado import EstadoAgente
from barra.agente.nos.extrair import DisparoExtracao, no_extrair
from barra.agente.nos.llm import no_llm
from barra.settings import get_settings

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_TIMEOUT = 2.0  # teto de qualquer espera: deadlock vira falha legivel, nao suite pendurada


class _FakeChatLLM:
    """Chat #1 fake. `porteiro`: quando setado, `ainvoke` SO responde depois que alguem o abrir —
    e como a suite prova que a extracao ja estava em voo ANTES de o chat terminar."""

    model = "deepseek-chat-test"

    def __init__(self, resp: AIMessage, porteiro: asyncio.Event | None = None) -> None:
        self._resp = resp
        self._porteiro = porteiro
        self.chamadas: list[Any] = []

    def bind_tools(self, _tools: Any, **_kw: Any) -> _FakeChatLLM:
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.chamadas.append(messages)
        if self._porteiro is not None:
            await asyncio.wait_for(self._porteiro.wait(), _TIMEOUT)
        return self._resp


class _FakeChatExtracao:
    """Bind forcado fake. Registra as janelas recebidas e marca se foi cancelado no meio.

    Os gatilhos (`iniciou`/`solta`/`erro`) valem SO para a primeira chamada — a do braco paralelo.
    A segunda e a da SERIE, que tem de passar limpa: e ela que garante a extracao do turno quando o
    paralelo nao serve. `forcados` em ordem: 1a chamada, 2a chamada, ... (a ultima se repete).
    """

    model = "deepseek-extracao-test"

    def __init__(
        self,
        *forcados: AIMessage,
        iniciou: asyncio.Event | None = None,
        solta: asyncio.Event | None = None,
        erro: BaseException | None = None,
    ) -> None:
        self._forcados = list(forcados)
        self._iniciou = iniciou
        self._solta = solta
        self._erro = erro
        self.janelas: list[Any] = []
        self.cancelada = False

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _FakeChatExtracao:
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        i = len(self.janelas)
        self.janelas.append(messages)
        if i == 0:  # so o braco paralelo passa pelos gatilhos
            if self._iniciou is not None:
                self._iniciou.set()
            try:
                if self._solta is not None:
                    await asyncio.wait_for(self._solta.wait(), _TIMEOUT)
            except asyncio.CancelledError:
                self.cancelada = True
                raise
            if self._erro is not None:
                raise self._erro
        return self._forcados[min(i, len(self._forcados) - 1)]


class _FakeToolExtracao:
    name = "registrar_extracao"

    def __init__(self, tool_message: ToolMessage) -> None:
        self._tm = tool_message
        self.chamadas: list[Any] = []

    async def ainvoke(self, chamada: Any) -> ToolMessage:
        self.chamadas.append(chamada)
        return self._tm


async def _drenar() -> None:
    """Devolve o controle ao loop algumas vezes p/ o cancelamento chegar na Task."""
    for _ in range(3):
        await asyncio.sleep(0)


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        context=SimpleNamespace(turno_id="t-1", turno_deadline_mono=None),
        stream_writer=None,
        store=None,
    )


def _fala(content: str = "às 22h te serve?", id_: str = "resp-1") -> AIMessage:
    return AIMessage(id=id_, content=content, usage_metadata=_USAGE, tool_calls=[])  # type: ignore[arg-type]


def _pede_tool() -> AIMessage:
    """Resposta do chat que abre o loop ReAct (roteia p/ o no `tools`)."""
    return AIMessage(
        id="ai-tc",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        tool_calls=[
            {
                "name": "consultar_agenda",
                "args": {"data_inicio": "2026-08-20", "data_fim": "2026-08-21"},
                "id": "ag1",
                "type": "tool_call",
            }
        ],
    )


def _forcado(marca: str = "cotacao") -> AIMessage:
    return AIMessage(
        id="forc-1",
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[
            {
                "name": "registrar_extracao",
                "args": {"intencao": marca},
                "id": "ex1",
                "type": "tool_call",
            }
        ],
    )


def _tool_ok() -> ToolMessage:
    return ToolMessage(
        content="Extracao registrada.", tool_call_id="ex1", name="registrar_extracao"
    )


def _tool_erro() -> ToolMessage:
    return ToolMessage(
        content="ERRO: o horário escolhido já está reservado para a modelo. Ofereça outro.",
        tool_call_id="ex1",
        name="registrar_extracao",
        status="error",
    )


def _estado_do_turno(*extras: BaseMessage) -> dict[str, Any]:
    """State como o prepare_context o deixa: conversa crua + a mesma janela em `messages` (com a
    cauda do belief colada na ULTIMA HumanMessage, MESMO id — senao ela vazaria p/ o `do_turno`)."""
    crua: list[BaseMessage] = [
        HumanMessage(content="oi quanto é 1 hora?", id="m1"),
        AIMessage(content="700 amor", id="m2"),
        HumanMessage(content="fecha pra hoje 22h", id="m3"),
    ]
    messages: list[BaseMessage] = [
        *crua[:-1],
        HumanMessage(content="<situacao_do_atendimento/>\n\nfecha pra hoje 22h", id="m3"),
        *extras,
    ]
    return {
        "messages": messages,
        "conversa_crua": crua,
        "agora_turno": None,
        "ja_registrado": "<ja_registrado><tipo>interno</tipo></ja_registrado>",
    }


def _aplicar(state: dict[str, Any], comando: Any) -> dict[str, Any]:
    """Merge do update do Command no State, como o LangGraph faria (messages append-only)."""
    update = dict(comando.update or {})
    novas = update.pop("messages", [])
    return {**state, **update, "messages": [*state["messages"], *novas]}


def _montar(
    chat: _FakeChatLLM,
    extracao: _FakeChatExtracao,
    tool: _FakeToolExtracao,
    *,
    tools: list[Any] | None = None,
) -> tuple[Any, Any, DisparoExtracao]:
    """Os dois nos compartilhando a MESMA instancia de DisparoExtracao (como o build_graph faz)."""
    disparo = DisparoExtracao(chat, extracao, tool)  # type: ignore[arg-type]
    no_l = no_llm(chat, tools or [], disparo)  # type: ignore[arg-type]
    no_e = no_extrair(chat, extracao, tool, disparo)  # type: ignore[arg-type]
    return no_l, no_e, disparo


@pytest.fixture(autouse=True)
def _strict_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # `extracao_strict_habilitada` e ON por default desde 13/08/2026, e `DisparoExtracao` normaliza
    # a declaracao via `tool_strict_deepseek` — que nao converte a tool FAKE deste arquivo. O
    # assunto aqui e o PARALELISMO do disparo, nao a declaracao (pinada com a tool real em
    # test_extracao_strict.py); desligar aqui e o mesmo kill-switch que o operador tem por env.
    monkeypatch.setattr(get_settings(), "extracao_strict_habilitada", False)


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "extracao_paralela_habilitada", True)


@pytest.fixture
def flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "extracao_paralela_habilitada", False)


# --- (1) flag OFF: nada de Task, caminho identico ao de hoje ----------------------------------


async def test_flag_off_nao_dispara_task_e_extrai_em_serie(flag_off: None) -> None:
    chat = _FakeChatLLM(_fala())
    extracao = _FakeChatExtracao(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, disparo = _montar(chat, extracao, tool)

    assert disparo.habilitado is False
    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())

    assert cmd_llm.goto == "extrair"
    assert "_extracao_task" not in (cmd_llm.update or {})  # nenhuma Task publicada no State
    assert extracao.janelas == []  # a extracao NAO foi chamada durante o chat

    cmd_extrair = await no_e(_aplicar(state, cmd_llm), _runtime())

    assert len(extracao.janelas) == 1  # chamada em SERIE, no `extrair`, como sempre
    assert cmd_extrair.goto == "post_process"
    assert [type(m).__name__ for m in cmd_extrair.update["messages"]] == [
        "AIMessage",
        "ToolMessage",
    ]
    assert tool.chamadas  # a execucao inline seguiu igual


# --- (2) flag ON: dispara ANTES de o chat responder e o `extrair` consome a MESMA resposta -----


async def test_flag_on_dispara_antes_do_chat_e_extrair_consome_a_mesma_resposta(
    flag_on: None,
) -> None:
    """O chat so responde depois que a extracao ja entrou (porteiro): se o disparo fosse serie, o
    `wait_for` do chat estouraria. E a extracao roda UMA vez — o `extrair` consome a Task, nao
    refaz a chamada."""
    iniciou_extracao = asyncio.Event()
    chat = _FakeChatLLM(_fala(), porteiro=iniciou_extracao)
    extracao = _FakeChatExtracao(_forcado("agendamento"), iniciou=iniciou_extracao)
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())

    task = (cmd_llm.update or {}).get("_extracao_task")
    assert isinstance(task, asyncio.Task)  # Task publicada no State p/ o `extrair`
    assert len(extracao.janelas) == 1  # ja estava em voo enquanto o chat respondia

    state = _aplicar(state, cmd_llm)
    cmd_extrair = await no_e(state, _runtime())

    assert len(extracao.janelas) == 1  # NAO refez a chamada: consumiu a Task
    forcado, tool_message = cmd_extrair.update["messages"]
    assert forcado.tool_calls[0]["args"] == {"intencao": "agendamento"}  # a MESMA resposta
    assert isinstance(tool_message, ToolMessage)
    assert cmd_extrair.goto == "post_process"


async def test_janela_do_disparo_e_a_mesma_que_o_extrair_montaria(flag_on: None) -> None:
    """O contrato que sustenta o paralelismo: no turno sem tool call, a janela disponivel no 1o
    invoke do `llm` e byte-a-byte a que o `extrair` montaria depois da fala."""
    chat = _FakeChatLLM(_fala())
    extracao = _FakeChatExtracao(_forcado())
    no_l, _, disparo = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    depois = _aplicar(state, cmd_llm)

    # a janela que o `extrair` monta = messages SEM a fala final
    janela_extrair = disparo.janela(depois["messages"][:-1], depois)  # type: ignore[arg-type]
    assert [(type(m).__name__, m.content) for m in cmd_llm.update["_extracao_janela"]] == [
        (type(m).__name__, m.content) for m in janela_extrair
    ]
    # e a fala do turno NAO entra na janela da extracao (contrato do no)
    assert all("te serve" not in str(m.content) for m in janela_extrair)


# --- (3) Task que estoura -> fallback em SERIE, turno integro ---------------------------------


async def test_task_com_excecao_cai_em_serie_e_turno_segue_integro(flag_on: None) -> None:
    """Primeira chamada (a paralela) explode; o `extrair` refaz em serie e o turno fecha igual —
    nunca se perde a extracao por causa da otimizacao."""
    iniciou = asyncio.Event()
    forcado = _forcado()
    extracao = _FakeChatExtracao(forcado, iniciou=iniciou, erro=RuntimeError("provider caiu"))
    chat = _FakeChatLLM(_fala())
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)
    await asyncio.wait_for(iniciou.wait(), _TIMEOUT)  # a paralela rodou (e estourou)

    cmd_extrair = await no_e(state, _runtime())

    assert len(extracao.janelas) == 2  # paralela (falhou) + serie (valeu)
    assert cmd_extrair.goto == "post_process"
    assert cmd_extrair.update["messages"][0] is forcado
    assert tool.chamadas  # a extracao do turno foi persistida do mesmo jeito


async def test_task_cancelada_cai_em_serie(flag_on: None) -> None:
    """Cancelamento da Task nao pode derrubar o turno: cai em serie igual."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    no_l, no_e, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)
    state["_extracao_task"].cancel()
    await _drenar()

    cmd_extrair = await no_e(state, _runtime())

    assert extracao.cancelada is True
    assert cmd_extrair.goto == "post_process"
    assert len(extracao.janelas) == 2  # a cancelada + a da serie


# --- (4) turno que nao chega ao `extrair`: nenhuma Task disparada nem orfa ---------------------


async def test_turno_pausado_antes_do_llm_nao_dispara_nada(flag_on: None) -> None:
    """Pausa (`ia_pausada`) e bloqueio de disclosure encerram o turno com Command(goto=END) ANTES
    do no `llm` (prepare_context / intercept_disclosure) — e o `llm` e o UNICO ponto de disparo.
    Construir os nos, por si so, nao poe nada em voo."""
    antes = asyncio.all_tasks()
    chat = _FakeChatLLM(_fala())
    extracao = _FakeChatExtracao(_forcado())
    _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))  # so a construcao, sem invocar o no

    assert extracao.janelas == []
    assert asyncio.all_tasks() == antes


async def test_extrair_alcancado_sem_passar_pelo_llm_chama_em_serie(flag_on: None) -> None:
    """Caminho que chega ao `extrair` sem Task no State (fora do fluxo do `llm`): o fallback
    sincrono esta SEMPRE la, com a flag ligada ou nao."""
    extracao = _FakeChatExtracao(_forcado())
    tool = _FakeToolExtracao(_tool_ok())
    _, no_e, _ = _montar(_FakeChatLLM(_fala()), extracao, tool)

    state = _estado_do_turno(_fala())
    assert "_extracao_task" not in state
    cmd = await no_e(state, _runtime())

    assert len(extracao.janelas) == 1
    assert cmd.goto == "post_process"
    assert tool.chamadas


async def test_ramo_tools_cancela_a_task_eager(flag_on: None) -> None:
    """Loop ReAct: as ToolMessages do turno VAO mudar a janela, entao a Task ja nasceu invalida.
    Cancela no proprio `llm` (nao la no `extrair`) p/ nao pagar a chamada em paralelo com a 2a
    volta do chat — e nao publica a Task, senao ela vazaria p/ o State."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_pede_tool(), porteiro=iniciou)  # o chat so responde com a extracao em voo
    no_l, _, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()), tools=[])

    cmd = await no_l(_estado_do_turno(), _runtime())
    await _drenar()

    assert cmd.goto == "tools"
    assert "_extracao_task" not in (cmd.update or {})  # nao vaza p/ o State
    assert extracao.cancelada is True  # cortada no `llm`, sem esperar o `extrair`


async def test_midia_esgotada_cancela_a_task_da_passagem_anterior(flag_on: None) -> None:
    """Cap de midia: o turno fecha DIRETO no post_process, sem passar pelo `extrair`. A Task de uma
    passagem anterior do ReAct (que veio no State) nao pode ficar pendurada."""
    solta = asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), solta=solta)
    chat = _FakeChatLLM(_fala())
    no_l, _, disparo = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno(
        *[
            ToolMessage(
                content="ERRO: sem midia",
                tool_call_id=f"mid{i}",
                name="enviar_midia",
                status="error",
            )
            for i in range(2)
        ]
    )
    disparado = disparo.disparar(state["messages"], state)  # type: ignore[arg-type]
    assert disparado is not None
    state["_extracao_task"], state["_extracao_janela"] = disparado

    cmd = await no_l(state, _runtime())

    assert cmd.goto == "post_process"
    assert cmd.update["_midia_esgotada"] is True
    solta.set()
    await asyncio.sleep(0)
    assert state["_extracao_task"].cancelled()  # nao ficou orfa


# --- cancelamento do TURNO tem de atravessar (o teto de 60s do coordenador depende disso) -----


async def test_cancelamento_do_turno_propaga_e_nao_vira_chamada_nova(flag_on: None) -> None:
    """Se o turno inteiro e cancelado enquanto o `extrair` espera a Task, o CancelledError tem de
    PROPAGAR. Engoli-lo faria duas coisas graves: o `asyncio.wait_for(graph.ainvoke, timeout=60)` do
    coordenador nunca viraria TimeoutError (sem `escalar_por_exaustao`, turno furando o orcamento em
    silencio) e o no emendaria uma chamada NOVA ao provider + escrita no banco dentro de um escopo
    ja cancelado. `task.cancelled()` NAO serve p/ detectar isto: da True nos dois casos."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)

    turno = asyncio.ensure_future(no_e(state, _runtime()))
    await _drenar()
    turno.cancel()

    with pytest.raises(asyncio.CancelledError):
        await turno
    assert len(extracao.janelas) == 1  # NAO emendou a chamada em serie
    assert tool.chamadas == []  # nem escreveu no banco depois de cancelado


async def test_wait_for_do_coordenador_ainda_estoura_com_a_extracao_em_voo(flag_on: None) -> None:
    """O contrato acima visto de fora, como o coordenador o exerce: `wait_for` com teto tem de
    levantar TimeoutError mesmo com a extracao paralela pendurada."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    no_l, no_e, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno()
    state = _aplicar(state, await no_l(state, _runtime()))

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(no_e(state, _runtime()), timeout=0.05)


async def test_cancelamento_durante_o_chat_nao_deixa_extracao_orfa(flag_on: None) -> None:
    """Cancelamento do grafo DURANTE o `ainvoke` do chat (teto do coordenador, shutdown do worker):
    a Task e destacada (`create_task`), entao o cancelamento do no nao a alcanca sozinho — ela
    sobreviveria ao turno morto pagando o request. Quem fecha esse buraco e o `finally` do nó."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    nunca = asyncio.Event()  # o chat trava e nunca responde
    chat = _FakeChatLLM(_fala(), porteiro=nunca)
    no_l, _, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    turno = asyncio.ensure_future(no_l(_estado_do_turno(), _runtime()))
    await asyncio.wait_for(iniciou.wait(), _TIMEOUT)  # extracao em voo, chat travado
    turno.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turno
    await _drenar()

    assert extracao.cancelada is True  # nao ficou em voo depois do turno morto


# --- o State REAL do Pregel aguenta a Task ----------------------------------------------------


async def test_task_sobrevive_ao_merge_do_state_num_stategraph_real(flag_on: None) -> None:
    """O handoff da Task passa pelo merge de State do Pregel, nao pelo dict do teste. Se o LangGraph
    copiasse o State (uma `asyncio.Task` nao e deep-copiavel) isso so apareceria em producao — este
    teste roda os dois nos num StateGraph de verdade, com Command(goto=...) como no grafo vivo."""
    iniciou = asyncio.Event()
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    extracao = _FakeChatExtracao(_forcado("agendamento"), iniciou=iniciou)
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    async def post_process(_state: Any) -> dict[str, Any]:
        return {}

    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)
    builder.add_node("llm", no_l)
    builder.add_node("extrair", no_e)
    builder.add_node("post_process", post_process)
    # `tools` existe so p/ satisfazer os alvos declarados no Command dos nos (o turno nao passa la).
    builder.add_node("tools", post_process)
    builder.add_edge(START, "llm")
    builder.add_edge("post_process", END)
    grafo = builder.compile()  # sem checkpointer, como o build_graph real

    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="m",
        atendimento_id="a",
        cliente_id="c",
        turno_id="t-1",
    )
    resultado = await grafo.ainvoke(_estado_do_turno(), context=ctx)

    assert len(extracao.janelas) == 1  # o `extrair` consumiu a Task, nao refez a chamada
    tipos = [type(m).__name__ for m in resultado["messages"]]
    assert tipos[-2:] == ["AIMessage", "ToolMessage"]  # registro da extracao intacto
    assert tool.chamadas


async def test_flag_vem_do_settings_injetado_nao_do_global(flag_off: None) -> None:
    """`build_graph(settings=...)` aceita um Settings proprio. Ler a flag do global aqui faria o
    guard de checkpointer (graph.py) julgar uma flag DIFERENTE da que vale para o grafo — deixando
    passar exatamente o caso que ele existe p/ barrar (Task nao-serializavel + saver)."""
    proprio = get_settings().model_copy(update={"extracao_paralela_habilitada": True})
    disparo = DisparoExtracao(
        _FakeChatLLM(_fala()),  # type: ignore[arg-type]
        _FakeChatExtracao(_forcado()),  # type: ignore[arg-type]
        _FakeToolExtracao(_tool_ok()),  # type: ignore[arg-type]
        proprio,
    )

    assert get_settings().extracao_paralela_habilitada is False  # o global diz o contrario
    assert disparo.habilitado is True  # vale o injetado


# --- (5) fingerprint diverge -> SERIE, extracao identica a de hoje ----------------------------


async def test_react_no_turno_faz_a_janela_divergir_e_cai_em_serie(flag_on: None) -> None:
    """Turno com tool call: a Task disparada no 1o invoke leu uma janela SEM o par
    AIMessage(tool_calls)+ToolMessage. O `extrair` tem de perceber e refazer em serie — a Task
    voltaria sem erro nenhum, entao so a comparacao da janela pega isso."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    forcado_paralelo, forcado_serie = _forcado("cotacao"), _forcado("agendamento")
    extracao = _FakeChatExtracao(forcado_paralelo, forcado_serie, iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)
    # o turno tambem passou pelo ReAct: o par entra no State DEPOIS do disparo
    state["messages"] = [
        *state["messages"][:-1],
        _pede_tool(),
        ToolMessage(
            content="Bloqueios: 20/08 22:00-23:00", tool_call_id="ag1", name="consultar_agenda"
        ),
        state["messages"][-1],
    ]

    cmd_extrair = await no_e(state, _runtime())
    await _drenar()

    assert len(extracao.janelas) == 2  # paralela descartada + serie
    assert cmd_extrair.update["messages"][0] is forcado_serie  # venceu a da JANELA COMPLETA
    assert extracao.cancelada is True
    # e a janela da serie de fato carrega o que o turno produziu
    janela_serie = extracao.janelas[-1]
    assert any(isinstance(m, ToolMessage) for m in janela_serie)


async def test_passagem_seguinte_do_react_redispara_com_a_janela_completa(flag_on: None) -> None:
    """Depois do `tools`, a 2a passagem do `llm` REDISPARA (o ramo `tools` cancelou e nao publicou
    a Task) — agora com as ToolMessages ja no State, que e a janela certa. O `extrair` consome: o
    turno com ReAct tambem ganha o paralelismo, so que uma volta depois."""
    iniciou = asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    tool = _FakeToolExtracao(_tool_ok())
    no_l, no_e, _ = _montar(chat, extracao, tool)

    # State como o ToolNode o deixa: o par do ReAct ja no messages, nenhuma Task no State
    state = _estado_do_turno(
        _pede_tool(),
        ToolMessage(
            content="Bloqueios: 20/08 22:00-23:00", tool_call_id="ag1", name="consultar_agenda"
        ),
    )
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)

    assert isinstance((cmd_llm.update or {}).get("_extracao_task"), asyncio.Task)
    cmd_extrair = await no_e(state, _runtime())

    assert len(extracao.janelas) == 1  # consumiu a Task: a janela do disparo ja estava completa
    assert any(isinstance(m, ToolMessage) for m in extracao.janelas[0])
    assert cmd_extrair.goto == "post_process"


async def test_task_descartada_que_falhou_nao_vira_crash_no_log(flag_on: None) -> None:
    """Task paralela que FALHOU e foi descartada por janela divergente nao pode deixar o asyncio
    logar "Task exception was never retrieved" + traceback: no log do worker isso se parece com
    excecao nao tratada derrubando o turno, sendo que o turno seguiu redondo em serie."""
    iniciou = asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, erro=RuntimeError("429"))
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    no_l, no_e, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)
    task = state["_extracao_task"]
    # janela diverge (ReAct entrou depois do disparo) -> o `extrair` descarta a Task
    state["messages"] = [*state["messages"][:-1], _pede_tool(), state["messages"][-1]]

    await no_e(state, _runtime())
    await _drenar()

    assert task.done() and not task.cancelled()
    # `_log_traceback` e a flag que o asyncio consulta no `__del__` do future p/ decidir se grita.
    # Tem de ser checada ANTES de qualquer `.exception()`: chamar `exception()` a zera por si so, e
    # um assert do tipo `isinstance(task.exception(), RuntimeError)` passaria com ou sem o fix —
    # o teste suprimiria justamente o aviso que diz estar verificando.
    assert task._log_traceback is False
    assert isinstance(task.exception(), RuntimeError)
    assert len(extracao.janelas) == 2  # e a serie salvou a extracao do turno


async def test_reoferta_2a_passagem_cai_em_serie_com_o_erro_na_janela(flag_on: None) -> None:
    """2a passagem da auto-reoferta: a janela PRECISA carregar o par [forcado, ERRO] da 1a extracao
    (senao o modelo repete o horario que conflitou e o turno fecha mudo). A Task da 1a passagem nao
    tem esse par -> impressao diverge -> serie."""
    iniciou, solta = asyncio.Event(), asyncio.Event()
    extracao = _FakeChatExtracao(_forcado(), iniciou=iniciou, solta=solta)
    chat = _FakeChatLLM(_fala(), porteiro=iniciou)
    no_l, no_e, _ = _montar(chat, extracao, _FakeToolExtracao(_tool_ok()))

    state = _estado_do_turno()
    cmd_llm = await no_l(state, _runtime())
    state = _aplicar(state, cmd_llm)
    # estado da 2a passagem: o par da 1a extracao ja esta no State, a fala stale saiu, veio outra
    state["messages"] = [
        *state["messages"][:-1],
        _forcado(),
        _tool_erro(),
        _fala("23h te serve?", id_="resp-2"),
    ]
    state["_reoferta_tentada"] = True

    cmd_extrair = await no_e(state, _runtime())

    assert len(extracao.janelas) == 2  # nao reaproveitou a Task da 1a passagem
    janela_serie = extracao.janelas[-1]
    assert any("ERRO:" in str(m.content) for m in janela_serie)  # o erro chegou ao extrator
    assert cmd_extrair.goto == "post_process"
