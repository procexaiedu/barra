"""No extrair: caminho unico da extracao no grafo vivo (02 §4).

O llm conversa; este no le o estado. Quando o llm encerra o turno SEM tool_call (resposta final
ao cliente), roteia para ca; a extracao roda SEMPRE, pos-fala: model call forcado ->
`registrar_extracao` executada INLINE (fora da aresta `tools`) -> persistencia em
`barravips.tool_calls` -> decisao de rota. `registrar_extracao` NAO esta em `TOOLS` -- seu schema e
bindado so aqui; o chat #1 nunca a chama. Substitui o antigo fallback #2 + reentry-guards que
viviam no `nos/llm.py`.

DECISAO DE DESENHO (footgun): a injecao inline FUNCIONA. Construir um `ToolRuntime` a partir do
`Runtime` do no e passa-lo em `args["runtime"]` para `tool.ainvoke` injeta corretamente
`context` + `state` -- a tool le `runtime.context.db_pool/atendimento_id/turno_id/agora_utc` e
`runtime.state["horario_minimo"]` normalmente, mesmo com a execucao acontecendo dentro do
`graph.ainvoke` mas fora de uma aresta do grafo (provado por `test_extrair_inline.py`, needs_db).
O fallback de desenho previsto no issue (extrair o corpo da tool para uma funcao pura
`executar_extracao`) NAO foi necessario.

Contrato de entrada: o no roda DEPOIS que o `llm` produziu a fala final do turno e a commitou como
ULTIMA mensagem de `state["messages"]` (uma `AIMessage` sem tool_calls). A extracao forcada roda
sobre a janela SEM essa fala final (preserva a semantica de nao ter dois assistants consecutivos).
Os helpers `_janela_para_extracao_barata`, `_SYSTEM_EXTRACAO_BARATA` e `_extracao_recente_errou`
vivem so aqui (saíram do `nos/llm.py` com a consolidacao deste ticket).
"""

import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime
from langgraph.types import Command

from barra.core.llm import PARADA_TRUNCADA, motivo_parada, nome_modelo
from barra.settings import get_settings

from .._instrumentar import instrumentar_tokens
from ..contexto import ContextAgente
from ..estado import EstadoAgente

logger = logging.getLogger(__name__)

# Nome da tool de escrita que persiste o snapshot do turno.
_TOOL_EXTRACAO = "registrar_extracao"

# System prompt MINIMO da extracao forcada barata: substitui o BP_GERAL
# (~14,7k tokens) -- a extracao e nota interna estruturada, nao gera texto ao cliente. As regras de
# cada campo ja viajam na descricao da tool; a hora atual e o periodo de trabalho vem no contexto
# dinamico anexado a ULTIMA HumanMessage (preservada pelo strip).
_SYSTEM_EXTRACAO_BARATA = (
    "Voce le uma conversa entre uma acompanhante e um cliente e registra o ESTADO da negociacao "
    "chamando a ferramenta registrar_extracao. Voce NAO responde ao cliente e NAO inventa dados: "
    "registre apenas o que esta claro na conversa. As regras de cada campo estao na descricao da "
    "ferramenta. A hora atual e o periodo de trabalho vem no contexto da ultima mensagem."
)


def _janela_para_extracao_barata(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Janela do turno SEM os blocos system gerais, prefixada pelo system minimo de extracao.

    O ganho de custo vem de NAO enviar o BP_GERAL na chamada barata. As mensagens da conversa
    (incluindo a ultima HumanMessage, que carrega o contexto dinamico) sao preservadas na ordem
    -- a request continua comecando por user apos o system.
    """
    conversa = [m for m in messages if not isinstance(m, SystemMessage)]
    return [SystemMessage(content=_SYSTEM_EXTRACAO_BARATA), *conversa]


def _extracao_recente_errou(messages: Sequence[BaseMessage]) -> bool:
    """True se a extracao recem-executada (bloco final de ToolMessages) trouxe erro RECUPERAVEL.

    ConflitoAgenda/ForaDisponibilidade/AntecedenciaInsuficiente viram ToolException
    (handle_tool_error) -> ToolMessage `status="error"` (prefixo "ERRO:"). No no extrair a
    execucao e inline: chama-se com `[tool_message]` (o resultado da unica execucao).
    """
    achou_tool = False
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            achou_tool = True
            if m.status == "error" or str(m.content).startswith("ERRO:"):
                return True
        elif achou_tool:
            break
    return False


async def _executar_inline(
    tool_extracao: BaseTool,
    tool_call: dict[str, Any],
    state: EstadoAgente,
    runtime: Runtime[ContextAgente],
) -> ToolMessage:
    """Executa `registrar_extracao` INLINE, injetando `ToolRuntime[ContextAgente]` na mao.

    Espelha o que o `ToolNode` faz (langgraph.prebuilt.tool_node): monta um `ToolRuntime` a partir
    do `Runtime` do no (context/state/store/stream_writer) e o injeta em `args["runtime"]`. O
    LangChain reconhece o `runtime` (um `_DirectlyInjectedToolArg` fora do schema do LLM) e o passa
    como kwarg -- a tool le `runtime.context.*` e `runtime.state["horario_minimo"]` normalmente.

    A execucao inline preserva DE GRACA tudo que ja vive no corpo da tool: parse dos args achatados,
    `handle_tool_error` (ToolException -> ToolMessage status="error"), idempotencia por
    `(turno_id, "registrar_extracao", 0)` via `_executar_idempotente`, e o enqueue do card de aviso
    de saida. `config={}` porque a tool nao le `runtime.config`.
    """
    tool_runtime: ToolRuntime[ContextAgente, EstadoAgente] = ToolRuntime(
        state=state,
        context=runtime.context,
        config={},
        stream_writer=runtime.stream_writer,
        tool_call_id=tool_call["id"],
        store=runtime.store,
        tools=[tool_extracao],
    )
    chamada = {
        "name": tool_call["name"],
        "args": {**tool_call["args"], "runtime": tool_runtime},
        "id": tool_call["id"],
        "type": "tool_call",
    }
    resultado = await tool_extracao.ainvoke(chamada)
    assert isinstance(resultado, ToolMessage)  # tool sem Command -> ToolMessage
    return resultado


class _NoExtrair(Protocol):
    """Forma do no extrair aceita pelo StateGraph (runtime keyword-only, como langgraph espera)."""

    def __call__(
        self, state: EstadoAgente, *, runtime: Runtime[ContextAgente]
    ) -> Coroutine[Any, Any, Command[Literal["post_process", "llm"]]]: ...


def no_extrair(
    chat: BaseChatModel,
    chat_extracao_barata: BaseChatModel | None,
    tool_extracao: BaseTool,
) -> _NoExtrair:
    """Factory: liga a chamada forcada de extracao + a execucao inline ao no extrair.

    `chat` (chat principal) recebe o bind forcado (tool_choice=registrar_extracao) usado quando o
    barato nao esta injetado; `chat_extracao_barata` (settings.extracao_no_modelo_barato, pode ser
    None) forca sobre a janela SEM o BP_GERAL; `tool_extracao` e a `BaseTool` de escrita executada
    inline (com `handle_tool_error=True`, ja setado em TOOLS).
    """
    settings = get_settings()
    # Binds forcados (tool_choice): so a tool de extracao, nao o catalogo -- o no nao faz ReAct.
    chat_forcado = chat.bind_tools([tool_extracao], tool_choice=_TOOL_EXTRACAO)
    chat_forcado_barato = (
        chat_extracao_barata.bind_tools([tool_extracao], tool_choice=_TOOL_EXTRACAO)
        if chat_extracao_barata is not None
        else None
    )
    modelo_chat = nome_modelo(chat)
    modelo_extracao_barata = (
        nome_modelo(chat_extracao_barata) if chat_extracao_barata is not None else ""
    )
    # Auto-reoferta (settings.reoferta_automatica_habilitada): erro RECUPERAVEL na extracao volta ao
    # no llm p/ o modelo reofertar um horario, em vez de fechar mudo. Lido na construcao (kill-switch).
    reoferta_ligada = settings.reoferta_automatica_habilitada

    async def extrair(
        state: EstadoAgente, runtime: Runtime[ContextAgente]
    ) -> Command[Literal["post_process", "llm"]]:
        mensagens = list(state["messages"])
        # Fala final do turno = ULTIMA msg (contrato: o no roda pos-fala; AIMessage sem tool_calls).
        # A extracao roda sobre a janela SEM ela (evita dois assistants consecutivos). Fora do
        # contrato (ultima nao e fala) -> `fala` None, janela inteira, nada stale a remover.
        fala = (
            mensagens[-1]
            if mensagens
            and isinstance(mensagens[-1], AIMessage)
            and not (mensagens[-1].tool_calls or [])
            else None
        )
        janela = mensagens[:-1] if fala is not None else mensagens

        # Chamada forcada: barato (janela sem o BP_GERAL) ou principal (janela crua). Instrumenta
        # sob o label do modelo usado (barato NAO polui o write-rate do principal).
        if chat_forcado_barato is not None:
            forcado = await chat_forcado_barato.ainvoke(_janela_para_extracao_barata(janela))
            instrumentar_tokens(forcado, modelo_extracao_barata)
        else:
            forcado = await chat_forcado.ainvoke(janela)
            instrumentar_tokens(forcado, modelo_chat)

        # Guard de qualidade: truncou (args incompletos) ou nao saiu tool_call -> descarta o forcado
        # e fecha SO com a fala original (ja no state). Nunca persiste payload parcial.
        forcado_stop = motivo_parada(forcado.response_metadata)
        tool_calls = getattr(forcado, "tool_calls", None)
        if forcado_stop in PARADA_TRUNCADA or not tool_calls:
            logger.warning(
                "extracao forcada sem tool_call util (stop=%s turno_id=%s)",
                forcado_stop,
                runtime.context.turno_id,
            )
            return Command(goto="post_process")

        # Execucao INLINE de registrar_extracao (footgun provado): a tool persiste em
        # barravips.tool_calls, aplica a FSM e enfileira o card de aviso de saida por dentro.
        tool_message = await _executar_inline(tool_extracao, tool_calls[0], state, runtime)

        # Registro da extracao (AIMessage forcada + ToolMessage) espelha o que o ToolNode
        # adicionaria ao state no caminho vivo -- deixa o post_process/output_guard/coordenador com
        # o mesmo historico. A escalada canned (guard de piso/tipo/reagendamento) retorna uma
        # `mensagem` normal (novo_estado: None), NAO um erro: cai no ramo de sucesso -> post_process,
        # e a canned de espera e solta la (o content bate MENSAGENS_GUARD_ESCALADA).
        registro: list[BaseMessage] = [forcado, tool_message]

        if _extracao_recente_errou([tool_message]):
            # Erro RECUPERAVEL (ConflitoAgenda etc.): a transacao reverteu, nenhum bloqueio nasceu. A
            # fala stale deste turno (falsa confirmacao "te espero as 22h", SEM tool_call) precisa
            # sumir -- iria ao cliente como reserva inexistente.
            remove_stale: list[BaseMessage] = (
                [RemoveMessage(id=fala.id)] if fala is not None and fala.id else []
            )
            if reoferta_ligada and not state.get("_reoferta_tentada"):
                # AUTO-REOFERTA (one-shot): volta ao no llm p/ o modelo ver o erro (no ToolMessage) e
                # REOFERTAR. O registro entra no state (o llm precisa do par AIMessage+ToolMessage p/
                # ler o erro) e a fala stale sai. _reoferta_tentada=True faz a 2a falha cair no mute.
                return Command(
                    goto="llm",
                    update={"messages": [*registro, *remove_stale], "_reoferta_tentada": True},
                )
            # Reoferta desligada OU ja tentada (a reoferta tambem errou): fecha MUDO -- no dominio de
            # booking, silencio > reserva fantasma.
            return Command(goto="post_process", update={"messages": [*registro, *remove_stale]})

        # Sucesso ou escalada canned: a fala original (ja no state) segue + o registro da extracao.
        return Command(goto="post_process", update={"messages": registro})

    return extrair
