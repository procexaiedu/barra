"""build_graph() compoe os nos em StateGraph (sem checkpointer no P0).

Grafo de 7 nos; o no llm e real (chama DeepSeek V4 Flash) e o roteamento e por Command(goto=...) --
nao por arestas condicionais nem flags de state (09 §4.1). Wiring:
    START -(estatica)-> prepare_context -(Command)-> intercept_disclosure | END
          intercept_disclosure -(Command)-> llm -(Command)-> tools | post_process | extrair
          tools -(estatica)-> llm   (loop ReAct)
          extrair -(Command)-> post_process | llm   (extracao pos-fala; volta ao llm na reoferta)
          post_process -(estatica)-> output_guard -(Command)-> END   (ADR 0016, antes da bolha)
O loop ReAct esta ATIVO a partir do M1: o llm roteia p/ "tools" (Command) quando ha tool_calls,
o ToolNode executa as tools de TOOLS e devolve ao llm pela aresta "tools" -> "llm"; o teto e o
`recursion_limit` (config de invocacao, nao constante aqui -- 03 §8, 09 §4.7). Quando o llm encerra
SEM tool_call (resposta final), roteia p/ "extrair" (02 §4): a extracao roda SEMPRE, pos-fala, num
no proprio -- `registrar_extracao` saiu de TOOLS (o chat #1 nunca a chama; ver nos/extrair.py).

Decisao 01 §6.7 (grilling 2026-05-22): SEM checkpointer no P0. O grafo compila com
`builder.compile()` (checkpointer=None); o prompt e montado do zero a cada turno a partir
de `mensagens` (sliding window), nao de checkpoint. O parametro `checkpointer` segue
opcional so para reintroducao futura (P1, se vier interrupt/time-travel) -- nao usar no P0.

Handoff: nao usa interrupt(); ia_pausada=true em dominio/atendimentos e early exit no
prepare_context (Command(goto=END), 02 §1). Devolucao via Devolucao para IA (comando
explicito, ver CONTEXT.md).
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import START, StateGraph

from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings, get_settings

from ._instrumentar import medir_no
from .contexto import ContextAgente
from .estado import EstadoAgente
from .ferramentas import TOOLS
from .ferramentas.extracao import registrar_extracao
from .nos import (
    DisparoExtracao,
    intercept_disclosure,
    no_extrair,
    no_llm,
    output_guard,
    post_process,
    prepare_context,
    tools_node,
)


def _cronometrado(nome: str, no: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Envolve um no do grafo para medir sua duracao em `AGENTE_NO_DURACAO{no=nome}`.

    `functools.wraps` NAO e cosmetico aqui: o LangGraph decide se injeta `runtime`/`config` lendo
    `inspect.signature(func).parameters` (langgraph/_internal/_runnable.py). `signature` segue
    `__wrapped__`, entao o wrapper preserva a injecao; sem o `wraps`, os nos passariam a receber
    so `state` e o `runtime` sumiria em silencio. (`inspect.getfullargspec` NAO segue `__wrapped__`
    -- se uma versao futura do LangGraph trocar de metodo, o teste do grafo pega.)

    Vale para os 6 nos que sao FUNCAO; o `tools` e um `ToolNode` e se cronometra no proprio
    `ainvoke` (nos/tools.py).
    """

    @functools.wraps(no)
    async def _medido(*args: Any, **kwargs: Any) -> Any:
        with medir_no(nome):
            return await no(*args, **kwargs)

    return _medido


def _criar_chat_principal(settings: Settings) -> Any:
    """Chat principal (#1): ChatOpenAI DIRETO na API DeepSeek (api.deepseek.com).

    DeepSeek-only (sem alternativa de provider): cache automático garantido + modelo/quant cravados.
    thinking segue `settings.deepseek_thinking_chat` — default "low", ou seja PROD e rigs raciocinam
    antes de falar; "disabled" no Env volta ao regime non-thinking. Em thinking a temperatura é
    omitida pela factory (o provider a ignora) e o teto de tokens vira `llm_max_tokens_thinking`.
    Devolve um BaseChatModel; o nó llm só usa bind_tools/ainvoke/nome_modelo.
    """
    return criar_chat_deepseek(
        settings,
        temperature=settings.chat_temperature,
        thinking=settings.deepseek_thinking_chat,
    )


def _criar_chat_extracao_barata(settings: Settings) -> Any:
    """Chat da extracao forcada barata (#2): ChatOpenAI DIRETO na API DeepSeek (deepseek_model_chat).

    DeepSeek-only. thinking travado em disabled (extra_body) — nao corrompe o structured output da
    extracao (tool_choice); o cache automatico do DeepSeek barateia o prefixo curto (system minimo +
    janela). Devolve um BaseChatModel; o no llm so usa bind_tools/ainvoke/.model.

    `temperature=judge_temperature` (0.0) EXPLICITO: ate 12/08/2026 a chamada era sem parametro e
    isso NAO era determinismo — a factory omite o campo quando None e vale o default do provider
    (~1.0). Ler o estado da negociacao e classificacao, nao voz (loop-massa r3, achado 1).
    """
    return criar_chat_deepseek(settings, temperature=settings.judge_temperature)


def build_graph(settings: Settings | None = None, checkpointer: Any | None = None) -> Any:
    """Constroi o StateGraph do agente.

    Args:
        settings: configuracao da app. None -> get_settings() (09 §4.5). Usada para construir
            o chat DeepSeek (criar_chat_deepseek) injetado no no llm via factory no_llm.
        checkpointer: AsyncPostgresSaver. None no P0 (01 §6.7); reservado p/ P1.

    Returns:
        Grafo compilado, pronto para `await graph.ainvoke(state, context=ContextAgente(...))`.
    """
    if settings is None:
        settings = get_settings()
    chat = _criar_chat_principal(settings)
    # Extracao forcada barata (settings.extracao_no_modelo_barato): chat injetado no no llm. None
    # quando desligado -> o no forca com o prefixo inteiro. Sempre DeepSeek V4 Flash direto
    # (criar_chat_deepseek), igual ao chat #1; o barateamento vem da JANELA minima, nao de outro modelo.
    chat_extracao_barata = (
        _criar_chat_extracao_barata(settings) if settings.extracao_no_modelo_barato else None
    )
    # Braco PARALELO da extracao (settings.extracao_paralela_habilitada): UMA instancia para os dois
    # nos que participam -- o `llm` dispara a chamada forcada como asyncio.Task, o `extrair` a
    # consome se a janela bater. Compartilhar a instancia e o que garante que os dois bracos montem
    # a MESMA janela e usem o MESMO bind.
    disparo = DisparoExtracao(chat, chat_extracao_barata, registrar_extracao, settings)
    if checkpointer is not None and disparo.habilitado:
        # O disparo guarda uma `asyncio.Task` no State (estado.py), que so e legitimo porque o P0
        # compila sem checkpointer. Com saver ligado o serializer estoura no meio de um turno de
        # producao -- melhor estourar aqui, na construcao do grafo.
        raise ValueError(
            "extracao_paralela_habilitada e incompativel com checkpointer: o State carrega uma "
            "asyncio.Task nao-serializavel (_extracao_task). Desligue a flag ou tire a Task do State."
        )

    # context_schema: deps de runtime + ids de escopo via Runtime Context API (04 §1.1).
    # Nao usar config["configurable"] p/ pool/redis (legado; quebra ao ligar checkpointer).
    builder = StateGraph(EstadoAgente, context_schema=ContextAgente)

    builder.add_node("prepare_context", _cronometrado("prepare_context", prepare_context))
    builder.add_node(
        "intercept_disclosure", _cronometrado("intercept_disclosure", intercept_disclosure)
    )
    builder.add_node("llm", _cronometrado("llm", no_llm(chat, TOOLS, disparo)))
    builder.add_node("tools", tools_node)  # ToolNode: cronometra a si mesmo no `ainvoke`
    # No `extrair`: le o estado da negociacao pos-fala (02 §4). Forca 1 registrar_extracao, executa
    # a tool INLINE (schema bindado so aqui -- registrar_extracao NAO esta em TOOLS) e decide a rota
    # (post_process no sucesso/escalada canned; volta ao llm na reoferta de erro recuperavel). O bind
    # barato (chat_extracao_barata) corta o BP_GERAL da chamada de extracao quando ligado.
    builder.add_node(
        "extrair",
        _cronometrado(
            "extrair", no_extrair(chat, chat_extracao_barata, registrar_extracao, disparo)
        ),
    )
    builder.add_node("post_process", _cronometrado("post_process", post_process))
    builder.add_node("output_guard", _cronometrado("output_guard", output_guard))

    builder.add_edge(START, "prepare_context")
    # prepare_context, intercept_disclosure e llm roteiam SO por Command(goto=...) -- sem aresta
    # estatica de saida. Uma aresta estatica em prepare_context faria fan-out com o Command(goto=END)
    # da pausa (o turno chamaria o llm mesmo pausado), por isso o caminho normal tambem e Command
    # (goto="intercept_disclosure"). Ver nos/prepare_context.py (M0-T4).
    builder.add_edge("tools", "llm")  # loop ReAct: ToolNode executou as tool_calls -> volta ao llm
    # Output-guard antes da bolha (ADR 0016): post_process (que so refaz o gate de pausa, retorna
    # dict) tem aresta estatica UNICA -> output_guard. O output_guard roteia SO por Command(goto=END)
    # -- sem aresta estatica de saida (mesma armadilha do fan-out: bloquear+seguir nao podem coexistir).
    builder.add_edge("post_process", "output_guard")

    return builder.compile(checkpointer=checkpointer)
