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
Os helpers `_janela_para_extracao` e `_SYSTEM_EXTRACAO_BARATA` vivem so aqui (saíram do
`nos/llm.py` com a consolidacao deste ticket).

A janela da extracao NAO e a do chat: ela e montada aqui a partir das pecas que o prepare_context
publica no State (`conversa_crua`/`agora_turno`/`ja_registrado`) — ver `_janela_para_extracao`.
"""

import asyncio
import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime
from langgraph.types import Command

from barra.core.llm import PARADA_TRUNCADA, motivo_parada, nome_modelo, nomear_run
from barra.settings import Settings, get_settings

from .._instrumentar import instrumentar_tokens
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..persona import render_ancora_extracao

logger = logging.getLogger(__name__)

# Nome da tool de escrita que persiste o snapshot do turno.
_TOOL_EXTRACAO = "registrar_extracao"

# System prompt MINIMO da extracao forcada barata: substitui o BP_GERAL
# (~14,7k tokens) -- a extracao e nota interna estruturada, nao gera texto ao cliente. As regras de
# cada campo ja viajam na descricao da tool; a hora atual vem na ancora da cauda.
_SYSTEM_EXTRACAO_BARATA = (
    "Voce le uma conversa entre uma acompanhante e um cliente e registra o ESTADO da negociacao "
    "chamando a ferramenta registrar_extracao. Voce NAO responde ao cliente e NAO inventa dados: "
    "registre apenas o que esta claro na conversa. As regras de cada campo estao na descricao da "
    "ferramenta. A hora atual e o que ja esta registrado vem na ultima mensagem."
)


def _janela_para_extracao(
    messages: Sequence[BaseMessage], state: EstadoAgente, *, system_minimo: bool
) -> list[BaseMessage]:
    """Janela DEDICADA da extracao (spec extracao-janela-dedicada): CONSTRUTIVA, nao subtrativa.

    Antes a janela era a do chat com as SystemMessages removidas — e o strip preservava justamente
    a mensagem onde o belief inteiro e o lembrete de persona estao colados, entao o extrator lia,
    como se fosse fala do cliente, os valores dos campos que devia preencher (tipo reafirmado em
    TODOS os turnos do #34/#41; o palpite de horario do #25 voltando no payload por tres turnos).
    Agora ela e montada com exatamente tres coisas:

      1. `conversa_crua` do State — a janela do par ANTES da anexacao do contexto dinamico e do
         lembrete (prepare_context). Prefixo append-only: byte-identico entre turnos.
      2. a `ancora` temporal (as descricoes dos campos resolvem tempo relativo contra ela);
      3. o bloco `<ja_registrado>`, na CAUDA — estado do sistema rotulado (palpite x pedido dele,
         cotado x aceito) com a instrucao de delta: registre um campo so se ELE MUDOU.

    `system_minimo` troca o BP_GERAL pelo system barato (o ganho de custo da chamada barata); com
    o kill-switch `extracao_no_modelo_barato` desligado, os SystemMessages do chat sao preservados
    e so a conversa/cauda mudam.

    A conversa crua e a janela do BANCO; o que o TURNO produziu depois dela (o par
    AIMessage+ToolMessage da 1a extracao) entra logo apos — e o registro do ERRO recuperavel e o
    que faz a AUTO-REOFERTA funcionar: na 2a passagem (`extrair` -> `llm` -> `extrair`) o extrator
    precisa ver que 22h conflitou, senao repete o mesmo horario e o turno fecha mudo.

    Sem `conversa_crua` no State (o no alcancado fora do fluxo do prepare_context) cai na janela
    recebida sem os blocos system — o comportamento antigo, nunca uma extracao sem conversa.
    """
    prefixo: list[BaseMessage] = (
        [SystemMessage(content=_SYSTEM_EXTRACAO_BARATA)]
        if system_minimo
        else [m for m in messages if isinstance(m, SystemMessage)]
    )
    crua = state.get("conversa_crua")
    sem_system = [m for m in messages if not isinstance(m, SystemMessage)]
    if crua is None:
        return [*prefixo, *sem_system, *_cauda_do_estado(state)]
    do_banco = {m.id for m in crua}
    do_turno = [m for m in sem_system if m.id not in do_banco]
    return [*prefixo, *crua, *do_turno, *_cauda_do_estado(state)]


def _cauda_do_estado(state: EstadoAgente) -> list[BaseMessage]:
    """Ancora temporal + bloco `<ja_registrado>` numa unica HumanMessage de CAUDA.

    Na cauda de proposito: o volatil depois do estavel deixa o prefixo (system + conversa
    append-only) byte-identico entre turnos — antes a conversa terminava numa mensagem inchada que
    mudava todo turno. Peca vazia (turno sem relogio/bloco resolvidos) -> nenhuma cauda.
    """
    partes = [
        parte
        for parte in (render_ancora_extracao(state.get("agora_turno")), state.get("ja_registrado"))
        if parte
    ]
    return [HumanMessage(content="\n\n".join(parte.strip() for parte in partes))] if partes else []


def _impressao_da_janela(mensagens: Sequence[BaseMessage]) -> list[tuple[str, ...]]:
    """Fingerprint da janela: exatamente o que o PROVIDER vai ver (papel + conteudo + tool_calls +
    os campos de amarracao do ToolMessage, que tambem viajam no request).

    Serve para o `extrair` decidir se a Task disparada la atras foi construida sobre a MESMA janela
    que ele montaria agora (ver `DisparoExtracao`). Compara o request, nao a identidade dos objetos:
    `id` de mensagem fica DE FORA de proposito — ele nao viaja no request e a cauda
    (`_cauda_do_estado`) e reconstruida a cada chamada, entao incluir o id faria a comparacao
    divergir sempre e o paralelismo nunca valeria. Conteudo igual => request igual => a resposta
    paralela e valida.
    """
    return [
        (
            type(m).__name__,
            str(m.content),
            repr(getattr(m, "tool_calls", None) or []),
            str(getattr(m, "tool_call_id", "")),
            str(getattr(m, "name", "") or ""),
            str(getattr(m, "status", "") or ""),
        )
        for m in mensagens
    ]


class DisparoExtracao:
    """Braco PARALELO da chamada forcada (settings.extracao_paralela_habilitada).

    Dono unico dos binds forcados e da montagem da janela, compartilhado pelos dois nos que
    participam do paralelismo: o `llm` dispara (`disparar`) e o `extrair` consome ou descarta
    (`resolver`). Medicao que motivou (traces 11/08): extracao 2,56s + chat 2,51s em SERIE = ~5s;
    sobrepondo as duas, o turno sem tool call cai ~47%.

    O que torna o disparo seguro NAO e a torcida, e a comparacao: a janela da extracao inclui o que
    o TURNO produziu (`do_turno`, em `_janela_para_extracao`), entao ela so esta pronta antes do
    chat quando o turno NAO chama tool e NAO e a 2a passagem da auto-reoferta. `resolver` remonta a
    janela real e so usa a Task se a impressao bater; senao cancela e chama em SERIE.

    Dois efeitos colaterais conhecidos, aceitos e a VALIDAR ao vivo antes de ligar a flag em prod:
      1. Observabilidade: a `asyncio.Task` copia os contextvars na criacao, entao a generation da
         extracao passa a pendurar sob o span do no `llm`, nao sob o `extrair` — o trace muda de
         forma e a latencia por-no do `extrair` cai artificialmente.
      2. Provider: dobra a concorrencia de PICO contra a DeepSeek por turno (chat + extracao em
         voo juntos) — com N turnos simultaneos no worker, dobra o risco de 429 no horario de pico.
    """

    def __init__(
        self,
        chat: BaseChatModel,
        chat_extracao_barata: BaseChatModel | None,
        tool_extracao: BaseTool,
        settings: Settings | None = None,
    ) -> None:
        # Binds forcados (tool_choice): so a tool de extracao, nao o catalogo -- o no nao faz ReAct.
        # `run_name` nomeia a GENERATION no trace: sem ele toda chamada de LLM do turno aparece como
        # "ChatOpenAI" no Langfuse e quem investiga nao distingue a fala da leitura do estado.
        self._forcado = nomear_run(
            chat.bind_tools([tool_extracao], tool_choice=_TOOL_EXTRACAO), "extracao_forcada"
        )
        self._forcado_barato = (
            nomear_run(
                chat_extracao_barata.bind_tools([tool_extracao], tool_choice=_TOOL_EXTRACAO),
                "extracao_forcada_barata",
            )
            if chat_extracao_barata is not None
            else None
        )
        self._modelo_chat = nome_modelo(chat)
        self._modelo_barato = (
            nome_modelo(chat_extracao_barata) if chat_extracao_barata is not None else ""
        )
        # Kill-switch lido na CONSTRUCAO (padrao da casa: reoferta_automatica_habilitada etc.).
        # Do `settings` INJETADO, nunca do global: o `build_graph` aceita um Settings proprio, e ler
        # o global aqui faria o guard de checkpointer (graph.py) julgar uma flag diferente da que
        # vale para este grafo — deixando passar exatamente o caso que ele existe p/ barrar.
        self.habilitado = (settings or get_settings()).extracao_paralela_habilitada

    @property
    def _system_minimo(self) -> bool:
        """A janela vai com o system barato no lugar do BP_GERAL (extracao_no_modelo_barato)."""
        return self._forcado_barato is not None

    @property
    def modelo_label(self) -> str:
        """Label das metricas de token: o modelo que DE FATO produziu o forcado (o barato nao
        polui o write-rate do principal)."""
        return self._modelo_barato if self._system_minimo else self._modelo_chat

    def janela(self, mensagens: Sequence[BaseMessage], state: EstadoAgente) -> list[BaseMessage]:
        """A janela DEDICADA da extracao para estas mensagens (delega a `_janela_para_extracao`)."""
        return _janela_para_extracao(mensagens, state, system_minimo=self._system_minimo)

    async def invocar(self, janela: list[BaseMessage]) -> BaseMessage:
        """A chamada forcada em si, sobre uma janela JA montada. Sem instrumentacao: quem
        instrumenta e o no `extrair`, uma vez, independente do braco que produziu o forcado."""
        chat = self._forcado_barato if self._forcado_barato is not None else self._forcado
        return cast(BaseMessage, await chat.ainvoke(janela))

    def disparar(
        self, mensagens: Sequence[BaseMessage], state: EstadoAgente
    ) -> tuple["asyncio.Task[BaseMessage]", list[BaseMessage]] | None:
        """Dispara a chamada forcada como Task e devolve `(task, janela_de_origem)`.

        `None` quando a flag esta desligada — o chamador (no `llm`) nao publica nada no State e o
        `extrair` cai no caminho em serie de sempre. As mensagens sao as do State ANTES da fala do
        turno (no 1o invoke do `llm` a fala ainda nao existe, entao nao ha o que remover).
        """
        if not self.habilitado:
            return None
        janela = self.janela(mensagens, state)
        return asyncio.create_task(self.invocar(janela)), janela

    async def resolver(
        self, janela_agora: list[BaseMessage], state: EstadoAgente, turno_id: str | None
    ) -> BaseMessage:
        """O forcado do turno: consome a Task quando ela serve, senao chama em SERIE.

        Fallback SEMPRE presente — flag off, janela divergente, Task que estourou ou foi cancelada
        caem todas na chamada em serie. Nunca se perde a extracao do turno por causa da otimizacao.
        """
        task: asyncio.Task[BaseMessage] | None = state.get("_extracao_task")
        if task is not None:
            if _impressao_da_janela(state.get("_extracao_janela") or []) == _impressao_da_janela(
                janela_agora
            ):
                try:
                    return await task
                except asyncio.CancelledError:
                    # Distinguir "a Task ja estava cancelada" de "cancelaram NOS" e obrigatorio, e
                    # `task.cancelled()` NAO serve: quando o no e cancelado, o asyncio cancela
                    # primeiro o future esperado (o `_fut_waiter` e esta Task), entao ele da True nos
                    # DOIS casos. Engolir o segundo caso seria grave: o `asyncio.wait_for(...,
                    # timeout=60)` do coordenador (workers/coordenador.py) so vira TimeoutError se o
                    # CancelledError PROPAGAR — engolido, o turno furaria o teto em silencio, sem
                    # `escalar_por_exaustao`, e ainda emendaria uma chamada nova ao provider + uma
                    # escrita no banco dentro de um escopo ja cancelado. O sinal confiavel em 3.11+ e
                    # `cancelling()` do PROPRIO no (0 quando o cancelamento nao foi dirigido a ele).
                    eu = asyncio.current_task()
                    if eu is not None and eu.cancelling() > 0:
                        raise
                    logger.warning("extracao paralela cancelada -> serie (turno_id=%s)", turno_id)
                except Exception:
                    logger.warning(
                        "extracao paralela falhou -> serie (turno_id=%s)", turno_id, exc_info=True
                    )
            else:
                # O turno produziu mensagem depois do disparo (tool call do ReAct, ou o par
                # [forcado, ERRO] da 1a extracao na 2a passagem da reoferta): a Task leu uma janela
                # INCOMPLETA. Descarta -- silencioso seria pior, porque ela retorna sem erro nenhum.
                logger.info(
                    "janela da extracao divergiu do disparo -> serie (turno_id=%s)", turno_id
                )
                cancelar(task)
        return await self.invocar(janela_agora)


# Zera o disparo em TODA saida do `extrair`: uma Task so serve ao `extrair` que a recebeu. Sem
# isto, na auto-reoferta (`extrair` -> `llm` -> `extrair`) a Task JA CONSUMIDA continua no State
# (canal LastValue, ninguem a remove) e o unico motivo de ela nao ser reaproveitada seria a
# impressao divergir — o que hoje e verdade so porque o ramo da reoferta sempre anexa
# [forcado, nota_interna] a janela. Isso e uma invariante de OUTRO ramo: se ela mudar (mandar so o
# erro, por exemplo), a impressao volta a bater e o turno consome a extracao da 1a passagem, errada
# e sem erro nenhum — exatamente o modo de falha que o desenho existe p/ impedir. Limpando aqui, a
# garantia vira estrutural. De quebra, tira a janela (lista inteira de mensagens) do payload de
# trace dos nos seguintes e faz a 2a passagem da reoferta REDISPARAR, agora com a janela certa.
_LIMPA_DISPARO: dict[str, Any] = {"_extracao_task": None, "_extracao_janela": []}


def _descartar_resultado(task: "asyncio.Task[BaseMessage]") -> None:
    """Marca o resultado como recuperado, para o asyncio nao logar o descarte como crash.

    Uma Task descartada que tenha FALHADO (429/timeout do provider — o caso comum) imprime
    "Task exception was never retrieved" + traceback quando e coletada, e no log do worker isso se
    parece com excecao nao tratada derrubando o turno — sendo que o turno seguiu redondo, em serie.
    `exception()` consome o erro; em Task cancelada ele levantaria CancelledError, dai o guard.
    """
    if not task.cancelled():
        task.exception()


def cancelar(task: "asyncio.Task[BaseMessage] | None") -> None:
    """Cancela a Task do disparo, se houver, e engole o resultado dela. Idempotente.

    Chamado EAGER em todo caminho que sai do turno sem passar pelo `extrair` (ver nos/llm.py) e
    quando a janela diverge: sem isso a chamada fica pendurada no loop do worker gastando credito.
    Nao atrasa o turno — o coordenador aguarda o `graph.ainvoke`, nao as tasks soltas
    (workers/coordenador.py) — mas e higiene, custo e ruido de log.
    """
    if task is None:
        return
    if not task.done():
        task.cancel()
    task.add_done_callback(_descartar_resultado)


def _extracao_errou(tool_message: ToolMessage) -> bool:
    """True se a extracao inline trouxe erro RECUPERAVEL.

    ConflitoAgenda/ForaDisponibilidade/AntecedenciaInsuficiente viram ToolException
    (handle_tool_error) -> ToolMessage `status="error"` (prefixo "ERRO:").
    """
    return tool_message.status == "error" or str(tool_message.content).startswith("ERRO:")


# Etiqueta de CANAL da copia do erro que vai ao contexto do chat na auto-reoferta (prod 29/07,
# trace 06db4298): o ToolMessage de erro e uma ordem em 2a pessoa, em portugues, no mesmo registro
# da fala -- e o chat obedeceu EM VOZ ALTA, para o cliente ("Ainda nao combinei o valor com ele. Vou
# cotar agora." -- 3a pessoa, raciocinio puro; judge_rastro_llm 0.0 no turno). O `<ferramentas>` do
# regras.md.j2 ja diz que retorno "ERRO:" e instrucao interna; o que faltava era dize-lo NO PONTO DE
# USO, colado no texto que o modelo obedece. Nao e conduta client-facing (essa continua no
# regras.md.j2): e mecanica de canal, code-side por natureza (agente/CLAUDE.md, "Fronteira conduta <->
# tool description", categoria 1). Segue a moldura de `_cercar_dado_midia` (`[rotulo — …]\n{texto}`).
_NOTA_INTERNA_PARA_O_CHAT = (
    "ERRO: [nota interna do sistema — é instrução pra você, nunca fala ao cliente. Corrija o rumo "
    "na próxima bolha: NUNCA copie nem comente esta nota, NUNCA diga que deu erro nem anuncie o "
    'que vai fazer ("vou cotar", "vou verificar") — só faça, e nunca ecoe na fala um rótulo entre '
    "< > que apareça aqui. Fale COM ele, nunca SOBRE ele.]"
)


def _envelopar_nota_interna(tool_message: ToolMessage) -> ToolMessage:
    """Copia do erro com a etiqueta de canal na frente -- so p/ o contexto do `llm` (auto-reoferta).

    O corpo original segue INTACTO logo depois: o llm precisa ler o que deu errado p/ reofertar (e o
    proposito do ramo -- ver `_janela_para_extracao`). Preserva `status="error"`, o prefixo "ERRO:" e
    o `tool_call_id`: essa forma e contrato de tres consumidores que quebram em silencio se ela mudar
    (`_extracao_errou` aqui, o descarte do rascunho superado em `extrair_texto_do_turno` -- que casa
    por id -- e o `erros_tool` de `desfecho_do_turno`).

    So a copia da reoferta e envelopada. No ramo mudo o ToolMessage nao chega a contexto de chat
    nenhum (a regen do output_guard corta a janela ANTES das msgs do turno), entao a etiqueta la nao
    protegeria nada e so diluiria o `erros_tool` do trace do desfecho mais comum.
    """
    return tool_message.model_copy(
        update={"content": f"{_NOTA_INTERNA_PARA_O_CHAT}\n{tool_message.content}"}
    )


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
    disparo: DisparoExtracao | None = None,
) -> _NoExtrair:
    """Factory: liga a chamada forcada de extracao + a execucao inline ao no extrair.

    `chat` (chat principal) recebe o bind forcado (tool_choice=registrar_extracao) usado quando o
    barato nao esta injetado; `chat_extracao_barata` (settings.extracao_no_modelo_barato, pode ser
    None) forca sobre a janela SEM o BP_GERAL; `tool_extracao` e a `BaseTool` de escrita executada
    inline (com `handle_tool_error=True`, ja setado em TOOLS).

    `disparo` e a MESMA instancia de `DisparoExtracao` injetada no no `llm` (build_graph): o llm
    dispara a chamada forcada, este no a consome quando a janela bate. None (chamador antigo, teste
    de no isolado) -> constroi a sua propria e o turno roda 100% em serie, como sempre.
    """
    settings = get_settings()
    disparo = disparo or DisparoExtracao(chat, chat_extracao_barata, tool_extracao, settings)
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

        # Chamada forcada sobre a janela DEDICADA (conversa crua + ancora + <ja_registrado>): no
        # barato ela vem com o system minimo no lugar do BP_GERAL. `resolver` consome a Task que o
        # no `llm` disparou em paralelo QUANDO ela saiu desta mesma janela; senao (flag off, janela
        # divergente, Task quebrada) chama em SERIE aqui mesmo. A instrumentacao roda uma vez, DEPOIS,
        # sob o label do modelo usado (barato NAO polui o write-rate do principal) — identica nos
        # dois bracos, para o registro `[forcado, tool_message]` abaixo ficar byte-a-byte o mesmo.
        janela_extracao = disparo.janela(janela, state)
        forcado = await disparo.resolver(janela_extracao, state, runtime.context.turno_id)
        instrumentar_tokens(forcado, disparo.modelo_label)

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
            return Command(goto="post_process", update=dict(_LIMPA_DISPARO))

        # Execucao INLINE de registrar_extracao (footgun provado): a tool persiste em
        # barravips.tool_calls, aplica a FSM e enfileira o card de aviso de saida por dentro.
        tool_message = await _executar_inline(tool_extracao, tool_calls[0], state, runtime)

        # Registro da extracao (AIMessage forcada + ToolMessage) espelha o que o ToolNode
        # adicionaria ao state no caminho vivo -- deixa o post_process/output_guard/coordenador com
        # o mesmo historico. A escalada canned (guard de piso/tipo/reagendamento) retorna uma
        # `mensagem` normal (novo_estado: None), NAO um erro: cai no ramo de sucesso -> post_process,
        # e a canned de espera e solta la (o content bate MENSAGENS_GUARD_ESCALADA).
        registro: list[BaseMessage] = [forcado, tool_message]

        if _extracao_errou(tool_message):
            # Erro RECUPERAVEL (ConflitoAgenda etc.): a transacao reverteu, nenhum bloqueio nasceu. A
            # fala stale deste turno (falsa confirmacao "te espero as 22h", SEM tool_call) precisa
            # sumir -- iria ao cliente como reserva inexistente.
            remove_stale: list[BaseMessage] = (
                [RemoveMessage(id=fala.id)] if fala is not None and fala.id else []
            )
            if reoferta_ligada and not state.get("_reoferta_tentada"):
                # AUTO-REOFERTA (one-shot): volta ao no llm p/ o modelo ver o erro (no ToolMessage) e
                # REOFERTAR. O par AIMessage+ToolMessage entra no state (e do que o llm le o erro) e a
                # fala stale sai. _reoferta_tentada=True faz a 2a falha cair no mute. O erro vai
                # ENVELOPADO: este e o unico ramo em que ele chega ao contexto do chat, que ja o leu
                # como fala uma vez (ver `_envelopar_nota_interna`).
                return Command(
                    goto="llm",
                    update={
                        "messages": [forcado, _envelopar_nota_interna(tool_message), *remove_stale],
                        "_reoferta_tentada": True,
                        **_LIMPA_DISPARO,
                    },
                )
            # Reoferta desligada OU ja tentada (a reoferta tambem errou): fecha MUDO -- no dominio de
            # booking, silencio > reserva fantasma.
            return Command(
                goto="post_process",
                update={"messages": [*registro, *remove_stale], **_LIMPA_DISPARO},
            )

        # Sucesso ou escalada canned: a fala original (ja no state) segue + o registro da extracao.
        return Command(goto="post_process", update={"messages": registro, **_LIMPA_DISPARO})

    return extrair
