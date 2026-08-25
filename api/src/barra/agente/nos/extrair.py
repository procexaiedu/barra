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
import json
import logging
import re
import unicodedata
from collections.abc import Coroutine, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
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

from barra.core.llm import (
    PARADA_INSEGURA,
    motivo_parada,
    nome_modelo,
    nomear_run,
    tool_strict_deepseek,
)
from barra.core.metrics import (
    AGENTE_EXTRACAO_APELIDO,
    AGENTE_EXTRACAO_CAMPO_DESCARTADO,
    AGENTE_EXTRACAO_PERDIDA,
    AGENTE_EXTRACAO_RETENTADA,
)
from barra.settings import Settings, get_settings

from .._instrumentar import instrumentar_tokens, medir_llm
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
        # `strict` (Beta) so entra no braco BARATO: e o unico com chat proprio, entao o endpoint
        # `/beta` que o strict exige nao contamina o chat #1. Binda o DICT normalizado
        # (`tool_strict_deepseek`) em vez da BaseTool — so o dict carrega `strict`/`required`
        # completos; a EXECUCAO segue na BaseTool (`_executar_extracao`), que nao passa por ali.
        # Com a flag OFF nada muda: mesma BaseTool, mesmo endpoint, schema byte-identico ao de antes.
        cfg = settings or get_settings()
        declaracao: Any = (
            tool_strict_deepseek(tool_extracao) if cfg.extracao_strict_habilitada else tool_extracao
        )
        self._forcado_barato = (
            nomear_run(
                chat_extracao_barata.bind_tools([declaracao], tool_choice=_TOOL_EXTRACAO),
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
        # vale para este grafo — deixando passar exatamente o caso que ele existe p/ barrar. Mesmo
        # `cfg` da declaracao acima, pela mesma razao.
        self.habilitado = cfg.extracao_paralela_habilitada

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


def _propriedades(sub_schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any] | None:
    """As `properties` de um campo do JSON Schema, atravessando o `anyOf` do Optional e o `$ref`
    que o pydantic gera para o objeto aninhado (`sinais_qualificacao` -> `$defs/…`)."""
    candidatos = [sub_schema, *(a for a in sub_schema.get("anyOf") or [] if isinstance(a, dict))]
    for candidato in candidatos:
        ref = candidato.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            candidato = defs.get(ref.removeprefix("#/$defs/"), {})
        if isinstance(candidato.get("properties"), dict):
            return cast(dict[str, Any], candidato["properties"])
    return None


_ENUM_LIMIAR = 0.85
# Limiar do apelido de CAMPO (`_reconduzir_apelidos`). Mais alto que o de enum: errar um valor de
# enum reescreve um rotulo, errar o campo escreve o dado na coluna errada -- e "hora"/"valor"/"data"
# ja entram pelo casamento por prefixo, sem depender do fuzzy.
_APELIDO_LIMIAR = 0.90


def _enum_permitido(sub_schema: dict[str, Any], defs: dict[str, Any]) -> list[str] | None:
    """Os valores fechados que o campo aceita, ou `None` quando ele aceita texto livre.

    Atravessa o `anyOf` do Optional (`{"anyOf": [{"enum": [...]}, {"type": "null"}]}`, a forma que o
    pydantic gera para `Literal[...] | None`) e o `$ref`. Basta UM ramo aberto (`type: string`,
    `number`) para o campo nao ter enum: `endereco` e `duracao_horas` nao sao domínio fechado.
    """
    candidatos = [sub_schema, *(a for a in sub_schema.get("anyOf") or [] if isinstance(a, dict))]
    permitidos: list[str] = []
    for candidato in candidatos:
        ref = candidato.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            candidato = defs.get(ref.removeprefix("#/$defs/"), {})
        enum = candidato.get("enum")
        if isinstance(enum, list):
            permitidos += [e for e in enum if isinstance(e, str)]
        elif candidato is not sub_schema and candidato.get("type") not in (None, "null"):
            return None
    return permitidos or None


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _valor_do_enum(valor: Any, permitidos: list[str]) -> Any | None:
    """O valor canonico do enum, corrigindo caixa/acento/typo — `None` quando nao da p/ salvar.

    O modelo erra a grafia do proprio enum ("imediatio" por "imediato", visto ao vivo em 12/08) e o
    `Literal` levanta `ValidationError`, que derruba o turno inteiro (mesma familia de
    `_podar_ao_schema`). Um typo de uma letra e recuperavel; o que nao casa com NENHUM valor — ou
    casa com dois (`interno`/`externo` sao vizinhos perto demais para chutar) — e descartado.
    """
    if valor in permitidos:
        return valor
    if not isinstance(valor, str):
        return None
    alvo = _sem_acento(valor)
    for permitido in permitidos:
        if _sem_acento(permitido) == alvo:
            return permitido
    quase = [
        p for p in permitidos if SequenceMatcher(None, alvo, _sem_acento(p)).ratio() >= _ENUM_LIMIAR
    ]
    return quase[0] if len(quase) == 1 else None


# Sentinela de "nao da para converter" na coercao de tipos. `None` nao serve: `None` e um valor
# LEGITIMO em todo campo Optional do schema (e o que preserva o anterior no UPSERT).
_DESCARTAR = object()

# Espelha o `min_length` de `proxima_acao_esperada` na assinatura da tool (ferramentas/extracao.py).
# Duas cópias do numero é o preço de não importar a tool aqui; quem as amarra é
# `test_min_proxima_acao_espelha_o_schema_da_tool` (tests/agente/test_extracao_args_invalidos.py),
# que lê o `minLength` do schema em vez de repetir o número uma terceira vez.
_MIN_PROXIMA_ACAO = 3


def _formato_do_campo(sub_schema: dict[str, Any], defs: dict[str, Any]) -> tuple[str, ...]:
    """Os `type`/`format` que o campo aceita, atravessando o `anyOf` do Optional e o `$ref`.

    Devolve rotulos normalizados (`"date"`, `"time"`, `"number"`, `"array"`, `"object"`, `"string"`,
    `"boolean"`) — a chave de despacho de `_coagir_valor`. O `null` do Optional fica de fora: quem
    quer apagar campo usa `limpar`, nao `None`.
    """
    candidatos = [sub_schema, *(a for a in sub_schema.get("anyOf") or [] if isinstance(a, dict))]
    rotulos: list[str] = []
    for candidato in candidatos:
        ref = candidato.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            candidato = defs.get(ref.removeprefix("#/$defs/"), {})
        formato = candidato.get("format")
        tipo = candidato.get("type")
        if isinstance(candidato.get("properties"), dict):
            rotulos.append("object")
        elif isinstance(formato, str) and formato in ("date", "time", "date-time"):
            rotulos.append(formato)
        elif isinstance(tipo, str) and tipo != "null":
            rotulos.append(tipo)
    return tuple(dict.fromkeys(rotulos))


# `"22h"`, `"22 h"`, `"22hs"`, `"22h30"`, `"22:30hs"`, `"22.30"`, `"22:00:00"` -> hora + minuto.
# O sufixo de hora e o separador solto sao a forma como a pessoa FALA a hora -- e a forma que as
# proprias descricoes da tool usam nos exemplos (`'22h'`, `'meio-dia'`), entao o extrator a copia.
#
# Os SEGUNDOS entram porque `HH:MM:SS` e o `repr` de um `datetime.time`, e o que o extrator le como
# estado gravado sai desse formato: achado ao vivo (12/08, roteiro `dado_na_mesa`, sessao paralela) —
# o `<ja_registrado>` imprimia `17:00:00`, o extrator ecoou `horario_desejado='17:00:00'` e o campo
# era DESCARTADO em silencio. A raiz foi corrigida no template, mas a defesa fica: qualquer eco de
# `time` volta a passar por aqui, e perder o horario e o pior desfecho do turno. Segundos != 0 sao
# ignorados de proposito (a agenda e meia-hora-granular; nao existe encontro as 22:00:30).
_RE_HORA_FALADA = re.compile(
    r"^(\d{1,2})\s*(?:[:.h]\s*(\d{1,2}))?(?::\d{1,2})?\s*(?:h|hs|hrs|horas?)?$"
)
# Numero dentro de texto de dinheiro/duracao: "R$ 300", "300 reais", "1h", "1,5h", "2.500,00".
_RE_NUMERO_SOLTO = re.compile(r"-?\d[\d.,]*")


def _coagir_hora(bruto: str) -> str | None:
    """`"22h"` -> `"22:00"`. `None` quando nao da para ler uma hora de relogio dali."""
    m = _RE_HORA_FALADA.match(bruto.strip().lower().replace(" ", ""))
    if m is None:
        return None
    hora, minuto = int(m.group(1)), int(m.group(2) or 0)
    if hora == 24 and minuto == 0:  # "24h" = meia-noite, forma comum na fala
        hora = 0
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return f"{hora:02d}:{minuto:02d}"


def _limites_do_campo(
    sub_schema: dict[str, Any], defs: dict[str, Any]
) -> tuple[Decimal | None, Decimal | None]:
    """`(minimum, maximum)` do campo numerico, atravessando o `anyOf` do Optional e o `$ref`.

    O pydantic pinta os limites SO no ramo `number` do `anyOf` (o ramo `string` do `Decimal` vem com
    `pattern` e sem limite), mas o `ge`/`le` do `Field` vale para o valor FINAL, qualquer que tenha
    sido o ramo — entao ler de qualquer ramo e correto e ler do primeiro que os tiver basta.
    """
    candidatos = [sub_schema, *(a for a in sub_schema.get("anyOf") or [] if isinstance(a, dict))]
    for candidato in candidatos:
        ref = candidato.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            candidato = defs.get(ref.removeprefix("#/$defs/"), {})
        minimo, maximo = candidato.get("minimum"), candidato.get("maximum")
        if minimo is not None or maximo is not None:
            return (
                Decimal(str(minimo)) if minimo is not None else None,
                Decimal(str(maximo)) if maximo is not None else None,
            )
    return None, None


def _numero_nos_limites(valor: Any, limites: tuple[Decimal | None, Decimal | None]) -> bool:
    """O numero cabe no `ge`/`le` do campo? Fora dos limites o pydantic levanta e o turno morre.

    Os dois casos reais: `valor_acordado` negativo (`ge=0`) e `duracao_horas` acima de 48 (o span do
    relogio somado errado, ou horas de um pacote inventado). Descartar o campo custa um dado; deixar
    passar custa a resposta ao cliente.
    """
    minimo, maximo = limites
    if minimo is None and maximo is None:
        return True
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return True  # nao e numero: quem julga e o pydantic, nao esta guarda
    return not (
        (minimo is not None and numero < minimo) or (maximo is not None and numero > maximo)
    )


def _coagir_numero(bruto: str) -> str | None:
    """`"300 reais"`/`"R$ 1.200,50"`/`"1,5h"` -> a string decimal que o pydantic aceita.

    Formato pt-BR: o ponto e separador de milhar e a virgula e decimal. Um numero negativo e
    descartado (o `ge=0` do campo o rejeitaria de qualquer forma) e texto sem digito nenhum
    ('pernoite') tambem — a duracao do pacote nao se adivinha do nome dele.
    """
    m = _RE_NUMERO_SOLTO.search(bruto)
    if m is None:
        return None
    corpo = m.group(0)
    if "," in corpo:
        corpo = corpo.replace(".", "").replace(",", ".")
    elif corpo.count(".") > 1:  # so separador de milhar ("2.500.000")
        corpo = corpo.replace(".", "")
    try:
        valor = Decimal(corpo)
    except InvalidOperation:
        return None
    return None if valor < 0 else str(valor)


def _coagir_valor(
    valor: Any,
    rotulos: tuple[str, ...],
    sub_props: dict[str, Any] | None,
    limites: tuple[Decimal | None, Decimal | None] = (None, None),
) -> Any:
    """O valor no formato que o campo aceita, ou `_DESCARTAR` quando nao da para converter.

    Só toca no que ESTA no formato errado: valor ja valido passa intocado (o `isinstance` de cada
    ramo e a guarda). O criterio de conversao e o mesmo de `_valor_do_enum` — corrigir o barato,
    descartar o resto, nunca chutar. `limites` cobre o outro jeito de o campo numerico derrubar o
    turno: o formato certo com o valor FORA do `ge`/`le` (ver `_numero_nos_limites`).
    """
    if "number" in rotulos or "integer" in rotulos:
        if isinstance(valor, str):
            convertido = _coagir_numero(valor)
            if convertido is None:
                return _DESCARTAR
            valor = convertido
        if not _numero_nos_limites(valor, limites):
            return _DESCARTAR
        return valor
    if "date" in rotulos and isinstance(valor, str):
        # Data relativa ("amanha") NAO se resolve aqui de proposito: o `agora` que ancora o relativo
        # vive no prompt (`<agenda hoje=...>`) e reconstrui-lo aqui duplicaria a fonte de verdade.
        try:
            date.fromisoformat(valor.strip())
        except ValueError:
            return _DESCARTAR
        return valor.strip()
    if "time" in rotulos and isinstance(valor, str):
        return _coagir_hora(valor) or _DESCARTAR
    if "array" in rotulos:
        # `limpar`/`fetiches_em_pauta` com um nome so, escrito cru em vez de em lista.
        if isinstance(valor, str):
            limpo = valor.strip()
            return [limpo] if limpo else _DESCARTAR
        if isinstance(valor, list):
            # Itens sao `string` no schema; um numero na lista derruba o turno igual (`string_type`
            # no indice). Nome de campo/fetiche escrito como numero nao existe, mas o custo de
            # normalizar e zero e o de nao normalizar e o turno.
            return [item if isinstance(item, str) else str(item) for item in valor]
        return _DESCARTAR
    if "object" in rotulos and isinstance(valor, str) and sub_props:
        # `sinais_qualificacao="aceita_valor"`: o nome do sinal no lugar do objeto. Vale converter
        # porque `aceita_valor` e o UNICO sinal de aceite do contrato — o mesmo motivo que sustenta
        # o `_reencaixar_achatados`. Só para campo booleano, e só com o nome exato do schema.
        chave = _sem_acento(valor)
        for nome, sub in sub_props.items():
            if _sem_acento(nome) == chave and "boolean" in _formato_do_campo(sub, {}):
                return {nome: True}
        return _DESCARTAR
    if "boolean" in rotulos and isinstance(valor, str):
        marcado = _sem_acento(valor)
        if marcado in ("true", "sim", "1", "yes"):
            return True
        if marcado in ("false", "nao", "0", "no"):
            return False
        return _DESCARTAR
    if "string" in rotulos and not isinstance(valor, str):
        # Campo de texto livre (`endereco`, `bairro`, `proxima_acao_esperada`) recebendo numero:
        # pydantic e estrito com `str` e `123` levanta `string_type`. Aqui a conversao e trivial e
        # sem perda — o campo e prosa para o painel ler, nao dado tipado.
        return str(valor)
    return valor


def _podar_ao_schema(
    args: dict[str, Any], propriedades: dict[str, Any], defs: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Args do LLM alinhados ao schema: sem chave desconhecida, sem enum errado, sem tipo errado.

    Os TRES modos de falha aqui sao o mesmo acidente com nomes diferentes, e todos custam o TURNO:
    o schema da extracao e `extra="forbid"` (strict tool use, §7) e os campos sao tipados, entao
    chave inventada (`sinais_qualificacao.fecha_valor`), enum com typo (`"imediatio"`) e valor no
    formato da FALA (`horario_desejado="22h"`, `duracao_horas="12h"`, `limpar="horario_desejado"`)
    todos viram `ValidationError` — que NAO e `ToolException`, escapa do `handle_tool_error` da
    tool, sobe pelo `graph.ainvoke` e deixa o cliente sem resposta por causa de uma nota interna.
    Todos vistos ao vivo (12/08). Alinhar antes de invocar troca o turno perdido por um campo
    corrigido ou descartado, que e exatamente o que aquele campo vale.

    Ordem dos tres passos: poda (a chave existe?) -> enum (o valor esta na lista?) -> tipo (o valor
    esta no formato?). Enum antes de tipo porque campo de enum e `string` no schema e a coercao de
    tipo nao teria o que fazer com ele.
    """
    defs = defs or {}
    limpo: dict[str, Any] = {}
    descartadas: list[str] = []
    for chave, valor in args.items():
        sub = propriedades.get(chave)
        if sub is None:
            descartadas.append(chave)
            # Label FIXA aqui: o nome vem do modelo e e cauda longa infinita (uma serie Prometheus
            # nova por invencao dele). O nome real fica no `logger.warning` de `_args_saneados`; a
            # serie precisa so do volume. Nos outros dois ramos a chave e do SCHEMA, logo fechada.
            AGENTE_EXTRACAO_CAMPO_DESCARTADO.labels("(fora_do_schema)", "chave_desconhecida").inc()
            continue
        sub_props = _propriedades(sub, defs) if isinstance(sub, dict) else None
        if isinstance(valor, dict) and sub_props is not None:
            valor, descartadas_do_filho = _podar_ao_schema(valor, sub_props, defs)
            descartadas += [f"{chave}.{d}" for d in descartadas_do_filho]
        permitidos = _enum_permitido(sub, defs) if isinstance(sub, dict) else None
        if permitidos is not None and valor is not None:
            canonico = _valor_do_enum(valor, permitidos)
            if canonico is None:
                descartadas.append(f"{chave}={valor!r}")
                AGENTE_EXTRACAO_CAMPO_DESCARTADO.labels(chave, "enum_invalido").inc()
                continue
            if canonico != valor:
                logger.info(
                    "extracao com valor de enum corrigido: %s %r -> %r", chave, valor, canonico
                )
            valor = canonico
        elif valor is not None and isinstance(sub, dict):
            coagido = _coagir_valor(
                valor, _formato_do_campo(sub, defs), sub_props, _limites_do_campo(sub, defs)
            )
            if coagido is _DESCARTAR:
                descartadas.append(f"{chave}={valor!r}")
                AGENTE_EXTRACAO_CAMPO_DESCARTADO.labels(chave, "formato_invalido").inc()
                continue
            if coagido != valor:
                logger.info("extracao com tipo coagido: %s %r -> %r", chave, valor, coagido)
                # Objeto reconstruido da string: poda o filho tambem (o schema do filho e forbid).
                if isinstance(coagido, dict) and sub_props is not None:
                    coagido, _ = _podar_ao_schema(coagido, sub_props, defs)
            valor = coagido
        limpo[chave] = valor
    return limpo, descartadas


def _tool_calls_uteis(forcado: BaseMessage) -> list[dict[str, Any]]:
    """Os `tool_calls` da forcada — recuperando os que o LangChain rejeitou por JSON quebrado.

    `tool_choice` garante que o provider VAI chamar a tool, mas nao que os args cheguem parseaveis:
    com `finish_reason=tool_calls` e um JSON malformado, `.tool_calls` vem VAZIO e o payload inteiro
    do turno se perdia. O texto cru fica em `.invalid_tool_calls[*]["args"]`; quando ele carrega um
    objeto JSON valido (o erro comum e lixo DEPOIS do objeto), a chamada e recuperada de graca.
    """
    validos = list(getattr(forcado, "tool_calls", None) or [])
    if validos:
        return validos
    recuperados: list[dict[str, Any]] = []
    for invalida in getattr(forcado, "invalid_tool_calls", None) or []:
        bruto = invalida.get("args")
        if not isinstance(bruto, str) or invalida.get("name") != _TOOL_EXTRACAO:
            continue
        try:
            args = json.loads(bruto[: bruto.rindex("}") + 1] if "}" in bruto else bruto)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(args, dict):
            recuperados.append(
                {
                    "name": _TOOL_EXTRACAO,
                    "args": args,
                    "id": invalida.get("id") or "recuperado",
                    "type": "tool_call",
                }
            )
    if recuperados:
        logger.info("extracao recuperada de invalid_tool_calls (json quebrado no args)")
    return recuperados


def _reencaixar_achatados(
    args: dict[str, Any], propriedades: dict[str, Any], defs: dict[str, Any]
) -> dict[str, Any]:
    """Devolve os campos do objeto aninhado que o modelo escreveu ACHATADOS no topo.

    O erro e sistematico e caro: `aceita_valor` sai como chave de primeiro nivel em vez de dentro
    de `sinais_qualificacao` (visto ao vivo em 12/08). Podar por poda perderia o UNICO sinal de
    aceite do contrato — sem ele a escada de desconto nao fecha e o atendimento nao avanca. O
    destino nao e chutado: e o pai cujo sub-schema declara aquela chave, e so quando o proprio
    objeto nao trouxe o campo (o que o modelo pos no lugar certo sempre vence).
    """
    destino = {
        chave_filha: pai
        for pai, sub in propriedades.items()
        for chave_filha in (_propriedades(sub, defs) or {})
        if isinstance(sub, dict)
    }
    # Pai PREENCHIDO e nao-dict (o objeto veio como string JSON, p.ex.) bloqueia o reencaixe: o
    # `else {}` que morava no laco abaixo descartava esse valor e o sobrescrevia com o achatado --
    # `sinais_qualificacao='{"aceita_valor": true, ...}'` + `envia_pix` no topo virava
    # `{"envia_pix": True}`, apagando em silencio o UNICO sinal de aceite e ainda logando sucesso.
    # Trocar um ValidationError ruidoso pela perda muda do campo mais caro e o pior negocio possivel.
    # Preservando o pai, ele segue para a coercao/validacao, que sabe o que fazer com ele.
    achatados = {
        k: v
        for k, v in args.items()
        if k not in propriedades
        and k in destino
        and (args.get(destino[k]) is None or isinstance(args.get(destino[k]), dict))
    }
    if not achatados:
        return args
    reencaixado = {k: v for k, v in args.items() if k not in achatados}
    for chave, valor in achatados.items():
        pai = destino[chave]
        filho = dict(reencaixado.get(pai) or {})
        filho.setdefault(chave, valor)
        reencaixado[pai] = filho
    logger.info("extracao com campos achatados reencaixados: %s", sorted(achatados))
    return reencaixado


def _schema_da_extracao(tool_extracao: BaseTool) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """`(properties, $defs)` do schema que o LLM ve — lido UMA vez, na construcao do no.

    `None` quando a tool nao expoe schema (fakes de teste de no): sem schema nao ha o que podar, e
    a garantia de `proxima_acao_esperada` continua valendo."""
    modelo = getattr(tool_extracao, "tool_call_schema", None)
    if modelo is None:
        return None
    gerar = getattr(modelo, "model_json_schema", None)
    if gerar is None:  # schema declarado como dict cru (nao e o caso da tool de prod)
        schema = cast(dict[str, Any], modelo)
    else:
        schema = cast(dict[str, Any], gerar())
    return schema.get("properties") or {}, schema.get("$defs") or {}


def _reconduzir_apelidos(args: dict[str, Any], propriedades: dict[str, Any]) -> dict[str, Any]:
    """Leva ao campo certo a chave que o modelo escreveu com APELIDO (`hora` -> `horario_desejado`).

    A poda ao schema salva o turno da morte por `ValidationError`, mas o preco dela e o dado: visto
    ao vivo em 12/08 (roteiro duas_portas), o payload trouxe `hora` e a poda descartou -- o turno
    respondeu normalmente e o HORARIO DO ENCONTRO sumiu em silencio, que e o mesmo dano do
    `AGENTE_EXTRACAO_PERDIDA`, so que num campo. Apelidar campo e erro de vocabulario, nao de
    intencao: o extrator sabia o que queria dizer.

    Casamento pelo mesmo criterio conservador de `_valor_do_enum`: prefixo (em qualquer direcao) ou
    fuzzy alto, e so quando bate em UM campo. `tipo` de proposito nao passa -- casa com
    `tipo_atendimento` e `tipo_local` ao mesmo tempo, e chutar entre "ela vai ate ele" e "o encontro
    e num motel" inventaria fato. Campo que ja veio no lugar certo vence o apelido, e o valor ainda
    passa por `_podar_ao_schema` depois (enum/tipo), entao reconduzir nao reintroduz o crash.
    """
    candidatos = {k: v for k, v in args.items() if k not in propriedades}
    if not candidatos:
        return args
    reconduzido = dict(args)
    for chave, valor in candidatos.items():
        alvos = [
            campo
            for campo in propriedades
            if campo not in args
            and (
                campo.startswith(chave)
                or chave.startswith(campo)
                or SequenceMatcher(None, chave, campo).ratio() >= _APELIDO_LIMIAR
            )
        ]
        if len(alvos) != 1:
            continue
        reconduzido.pop(chave)
        reconduzido[alvos[0]] = valor
        AGENTE_EXTRACAO_APELIDO.labels(alvos[0]).inc()
        logger.info("extracao com campo reconduzido por apelido: %s -> %s", chave, alvos[0])
    return reconduzido


def _args_saneados(
    tool_call: dict[str, Any], schema: tuple[dict[str, Any], dict[str, Any]] | None
) -> dict[str, Any]:
    """Os args do forcado prontos para a tool: alinhados ao schema + `proxima_acao_esperada` garantida.

    Os modos de falha vistos ao vivo (12/08, 2 turnos em ~20 conversas) sao o mesmo acidente: o
    payload nao casa com o schema e o `ValidationError` derruba o TURNO. Chave inventada, enum com
    typo e valor no formato da fala moram em `_podar_ao_schema`; aqui fica o outro, a tool chamada
    sem a unica obrigatoria. A nota interna ausente (ou curta demais para o `min_length=3` do campo,
    que e o mesmo turno morto por outro caminho) vira um texto neutro — os demais campos do payload
    (a hora, o valor) sao o que importa, e a nota e para o painel ler.
    """
    args = dict(tool_call.get("args") or {})
    if schema is not None:
        args = _reencaixar_achatados(args, schema[0], schema[1])
        args = _reconduzir_apelidos(args, schema[0])
        args, descartadas = _podar_ao_schema(args, schema[0], schema[1])
        if descartadas:
            logger.warning("extracao com campos fora do schema (descartados): %s", descartadas)
    if len(str(args.get("proxima_acao_esperada") or "").strip()) < _MIN_PROXIMA_ACAO:
        args["proxima_acao_esperada"] = "(o extrator nao registrou a proxima acao neste turno)"
    return args


def _sem_horario_espelho_do_relogio(args: dict[str, Any], state: EstadoAgente) -> dict[str, Any]:
    """Descarta `horario_desejado` quando ele e o RELOGIO copiado e ninguem falou de tempo.

    Origem do P0 da prova r3 (`diagnostico_externo_a.md` Q1): num turno em que o cliente so
    perguntou "vc atende em domicilio?" — zero token de tempo — a extracao barata gravou
    `horario_desejado="20:41"`, exatamente o `agora` da ancora `<agenda agora="20:41"/>`, o unico
    numero da janela. Esse palpite abriu o gate do fallback de tempo imediato, cravou uma hora que
    o dominio recusou e matou seis turnos.

    A `_DESC_HORARIO` JA proibia isso em prosa ("o relogio sozinho nunca e a resposta") e falhou —
    a chamada barata roda com um system de tres linhas, sem persona nem `<foco_do_turno>`, e a
    ancora fica na MESMA mensagem que o `<ja_registrado>`, isto e, no lugar onde o modelo le "dados
    a registrar". Proibicao verificavel sem LLM nao mora em description: mora aqui, junto de
    `_podar_ao_schema`/`_valor_do_enum`.

    Gate por EVIDENCIA, nao pelo valor: se o detector deterministico do turno diz que a janela tem
    fala do cliente sustentando um horario (`horario_evidenciado`, prepare_context), o valor passa —
    inclusive quando ele coincide com o relogio (o cliente pode ter dito a hora que e agora). Sem
    evidencia, hora == relogio e palpite por construcao, e o caminho legitimo do "agora" continua
    aberto pelo `urgencia=imediato` (o fallback de tempo imediato ancora no `<horario_minimo>`, que
    e agenda-coerente — o relogio cru nem passaria na guarda de antecedencia).
    """
    bruto = args.get("horario_desejado")
    agora = state.get("agora_turno")
    if bruto is None or agora is None or state.get("horario_evidenciado"):
        return args
    if str(bruto).strip()[:5] != agora.strftime("%H:%M"):
        return args
    logger.warning(
        "extracao gravou o RELOGIO como horario_desejado (%s) sem fala de tempo do cliente -> "
        "descartado",
        bruto,
    )
    AGENTE_EXTRACAO_CAMPO_DESCARTADO.labels("horario_desejado", "espelho_do_relogio").inc()
    return {k: v for k, v in args.items() if k != "horario_desejado"}


async def _executar_inline(
    tool_extracao: BaseTool,
    tool_call: dict[str, Any],
    state: EstadoAgente,
    runtime: Runtime[ContextAgente],
    schema: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> tuple[ToolMessage, dict[str, Any]]:
    """Executa `registrar_extracao` INLINE, injetando `ToolRuntime[ContextAgente]` na mao.

    Devolve `(ToolMessage, args)` -- os args SANEADOS, os que de fato foram registrados. Eles
    viram o CARIMBO da extracao no State (`_extracao_registrada`): a observabilidade lia a extracao
    varrendo `tool_calls` das AIMessages do turno, e o `output_guard` tem o direito de reescrever
    essas mensagens (`_zerar_turno` no despacho da regen) -- o payload sumia do trace e a tag
    `sem_extracao` mentia num turno que registrou tudo (loop-massa r2). Carimbo no State, nao
    inferencia sobre mensagem que outro no pode trocar.

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
    args = _sem_horario_espelho_do_relogio(_args_saneados(tool_call, schema), state)
    chamada = {
        "name": tool_call["name"],
        "args": {**args, "runtime": tool_runtime},
        "id": tool_call["id"],
        "type": "tool_call",
    }
    resultado = await tool_extracao.ainvoke(chamada)
    assert isinstance(resultado, ToolMessage)  # tool sem Command -> ToolMessage
    return resultado, args


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
    # Schema lido UMA vez (a montagem do JSON Schema do pydantic nao e barata p/ rodar por turno).
    schema_da_tool = _schema_da_extracao(tool_extracao)
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
        with medir_llm("extracao"):
            forcado = await disparo.resolver(janela_extracao, state, runtime.context.turno_id)
        instrumentar_tokens(forcado, disparo.modelo_label)

        # Guard de qualidade: truncou (args incompletos) ou nao saiu tool_call -> descarta o forcado
        # e fecha SO com a fala original (ja no state). Nunca persiste payload parcial.
        #
        # Antes de descartar, DUAS recuperacoes — o custo de perder este payload e alto e assimetrico:
        # o turno em que o cliente crava a hora ("pode ser 22h hoje") passa sem registro nenhum, o
        # encontro nao e reservado e a conversa segue como se ele nao tivesse dito nada (medido ao
        # vivo em 12/08). Primeiro o `invalid_tool_calls` (o provider mandou a chamada, o JSON dos
        # args e que veio quebrado — o LangChain guarda o texto cru ali); depois UMA retentativa em
        # serie da mesma janela. Só entao o descarte.
        #
        # A retentativa e barrada por TODA parada insegura, nao so pela truncada: RECUSA do provider
        # (`refusal`/`content_filter`) nunca se retenta -- e regra da casa, e vale aqui pelo mesmo
        # motivo dos outros caminhos (`_julgar_aup`, no llm): a segunda chamada e a mesma janela ao
        # mesmo filtro, entao ela so paga latencia e token para ser recusada de novo. Recusa vai
        # direto ao descarte (o turno fecha com a fala, sem extracao).
        forcado_stop = motivo_parada(forcado.response_metadata)
        tool_calls = _tool_calls_uteis(forcado)
        if not tool_calls and forcado_stop not in PARADA_INSEGURA:
            logger.warning(
                "extracao forcada sem tool_call util (stop=%s turno_id=%s) -> retentando",
                forcado_stop,
                runtime.context.turno_id,
            )
            AGENTE_EXTRACAO_RETENTADA.inc()
            # `try/except` porque esta e uma SEGUNDA chamada ao provider num ponto onde antes o
            # codigo so logava e seguia. `disparo.invocar` e `chat.ainvoke` cru: uma falha
            # persistente do provider subiria pelo no ate o coordenador, que escala
            # (`erro_interno`/`modelo_indisponivel`) e PAUSA a IA — trocando "perdi a extracao, o
            # cliente foi atendido" por "cliente sem resposta e IA pausada". Cair no descarte logo
            # abaixo mantem a retentativa estritamente nao-pior que nao ter retentativa nenhuma.
            try:
                with medir_llm("extracao_retry"):
                    forcado = await disparo.invocar(janela_extracao)
            except Exception:
                logger.warning(
                    "extracao retentada falhou no provider (turno_id=%s) -> descarta a extracao",
                    runtime.context.turno_id,
                    exc_info=True,
                )
                AGENTE_EXTRACAO_PERDIDA.inc()
                return Command(goto="post_process", update=dict(_LIMPA_DISPARO))
            instrumentar_tokens(forcado, disparo.modelo_label)
            forcado_stop = motivo_parada(forcado.response_metadata)
            tool_calls = _tool_calls_uteis(forcado)
        if forcado_stop in PARADA_INSEGURA or not tool_calls:
            logger.warning(
                "extracao forcada descartada (stop=%s turno_id=%s)",
                forcado_stop,
                runtime.context.turno_id,
            )
            AGENTE_EXTRACAO_PERDIDA.inc()
            return Command(goto="post_process", update=dict(_LIMPA_DISPARO))

        # Execucao INLINE de registrar_extracao (footgun provado): a tool persiste em
        # barravips.tool_calls, aplica a FSM e enfileira o card de aviso de saida por dentro.
        tool_message, args_registrados = await _executar_inline(
            tool_extracao, tool_calls[0], state, runtime, schema_da_tool
        )

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
            #
            # Os dois ramos daqui pra baixo carimbam `_extracao_registrada: None` EXPLICITO. Nao e
            # cosmetico: eles anexam ao State a AIMessage forcada com o tool_call CRU, e o fallback
            # de varredura do `extracao_do_turno` (que existe p/ State montado a mao) leria esse
            # tool_call como a extracao do turno -- publicando no trace um payload que a transacao
            # REVERTEU. Com o carimbo, a leitura e por presenca da chave: quem carimbou decidiu,
            # inclusive quando decidiu "nada" (revisao da r2 do loop de massa).
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
                        "_extracao_registrada": None,
                        **_LIMPA_DISPARO,
                    },
                )
            # A REOFERTA JA FOI GASTA e errou de novo. A fala deste turno NAO e mais stale: o `llm`
            # a produziu DEPOIS de ler o ToolMessage de erro (ramo acima), entao ela e a
            # auto-reoferta -- a conduta certa, e o unico texto do turno que o cliente pode receber.
            # Ela PASSA, e o output_guard a julga com a bateria inteira de detectores (leak,
            # repeticao, preco/servico fantasma). Bounded do mesmo jeito: nao ha 2a reoferta, so
            # nao ha mais mute em cima de uma bolha informada.
            #
            # Foi este mute que transformou um turno quebrado em atendimento morto na prova r3
            # (`diagnostico_externo_a.md` Q3d): as SEIS bolhas apagadas continham a reoferta correta
            # ("Consigo as 22h pra dar tempo de eu me arrumar, fecha ?") e o valor certo. E a mudez
            # ainda realimentava o proprio gatilho -- sem AIMessage o burst do cliente nao fecha e o
            # detector de horario re-evidenciava a hora velha todo turno.
            #
            # O que segura a reserva fantasma aqui e o TEXTO do erro (todo handler recuperavel de
            # `ferramentas/extracao.py` carrega o "NUNCA diga que confirmou/reservou") somado ao
            # estado: o palpite recusado ja saiu do snapshot (`retirar_horario_palpite`), entao nao
            # ha mais valor envenenado para o turno seguinte re-tentar.
            if state.get("_reoferta_tentada") and fala is not None:
                return Command(
                    goto="post_process",
                    update={
                        "messages": registro,
                        "_extracao_registrada": None,
                        **_LIMPA_DISPARO,
                    },
                )
            # Reoferta DESLIGADA (kill-switch) ou turno sem fala: aqui a bolha e mesmo STALE — foi
            # escrita antes de qualquer erro existir e pode afirmar uma reserva que a transacao
            # reverteu. Fecha MUDO: no dominio de booking, silencio > reserva fantasma.
            #
            # `_mute_por_erro_de_tool` CARIMBA a decisao p/ o output_guard: sem ele o gatilho `mudo`
            # do guard via so "turno sem texto", regenerava e o modelo -- que nao le o ToolMessage
            # de erro, cortado da janela da regen por desenho -- respondia "Confirmado amor",
            # justamente a reserva fantasma (trace 71c7196e, 12/08). O silencio aqui e uma decisao,
            # nao uma falha a recuperar.
            return Command(
                goto="post_process",
                update={
                    "messages": [*registro, *remove_stale],
                    "_mute_por_erro_de_tool": True,
                    "_extracao_registrada": None,
                    **_LIMPA_DISPARO,
                },
            )

        # Sucesso ou escalada canned: a fala original (ja no state) segue + o registro da extracao.
        # O CARIMBO com PAYLOAD sai so por aqui -- o ramo de erro reverteu a transacao, e o que nao
        # foi gravado nao pode aparecer no trace como se tivesse sido (la o carimbo vale `None`).
        return Command(
            goto="post_process",
            update={
                "messages": registro,
                "_extracao_registrada": args_registrados,
                **_LIMPA_DISPARO,
            },
        )

    return extrair
