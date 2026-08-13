"""Agregacao das AIMessages GERADAS NO TURNO (criterio: usage_metadata is not None).

Fonte unica do criterio "o que o LLM gerou agora" vs historico re-injetado pelo
prepare_context (AIMessages do banco, sem usage_metadata). Compartilhado pelo coordenador
(extrai o texto que vai ao cliente) e pelo output_guard (escaneia/zera EXATAMENTE o mesmo
texto antes do envio) — duplicar o filtro nos dois lados ja divergiu uma vez (o guard so via
a ultima AIMessage enquanto o coordenador despachava o agregado do turno).

Mora aqui tambem a convencao da MARCA DE PAUSA da janela (`e_marca_pausa`): mesmo papel de
fonte unica, para o pedaco injetado no historico nao ser confundido com fala de ninguem.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def mensagens_do_turno(messages: Sequence[BaseMessage]) -> list[AIMessage]:
    """AIMessages geradas NESTE turno (com usage_metadata; exclui historicas re-injetadas)."""
    return [m for m in messages if isinstance(m, AIMessage) and m.usage_metadata is not None]


def texto_da_mensagem(msg: AIMessage) -> str:
    """Texto plano de uma AIMessage. content pode ser str ou lista de blocos (1.x)."""
    if isinstance(msg.content, str):
        return msg.content
    partes = [
        bloco.get("text", "")
        for bloco in msg.content
        if isinstance(bloco, dict) and bloco.get("type") == "text"
    ]
    return "".join(partes)


def _tool_use_ids(msg: AIMessage) -> set[str]:
    """IDs dos tool_calls de uma AIMessage -- de `.tool_calls` (LLM real) e dos blocos `tool_use`
    do content (cobre mensagens cruas/testes onde `.tool_calls` nao foi populado)."""
    ids: set[str] = set()
    for tc in msg.tool_calls or []:
        tid = tc.get("id")
        if tid:
            ids.add(tid)
    if isinstance(msg.content, list):
        for b in msg.content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
                ids.add(b["id"])
    return ids


def extrair_texto_do_turno(messages: Sequence[BaseMessage]) -> str:
    """Agrega texto das AIMessages GERADAS pelo LLM neste turno, separadas por \\n\\n.

    No padrao ReAct, o LLM e chamado de novo depois de cada ToolMessage; quando ja respondeu
    o cliente na 1a passagem (texto + tool_call), a 2a passagem volta com `content=[]` —
    pegar so a ultima AIMessage daria "" e disparava `turno_sem_resposta`.

    O `prepare_context` re-injeta AIMessages historicas (mensagens previas da IA do banco)
    no input do LLM (`nos/prepare_context.py:188`); essas vem SEM `usage_metadata`. Filtrar
    por `usage_metadata` mantem so o que o LLM gerou agora — agregar historicas duplicaria
    a resposta anterior junto com a nova (bug observado em prod 2026-05-27).

    Erro recuperavel + retry (2026-06-03): quando uma tool falha de forma recuperavel, o LLM
    RE-EMITE o texto e re-chama a tool na passagem seguinte. O texto da passagem cujo tool_call
    ERROU e um rascunho SUPERADO pela retentativa -- agrega-lo duplicaria a fala ao cliente (bug
    externo_pix). Descartamos o texto das AIMessages cujo tool_call resultou em ToolMessage de
    erro: `status == "error"` cobre ToolException com handle_tool_error (ferramentas/, prefixo
    "ERRO:") E erro de args do ToolNode (ToolInvocationError, ex. data invalida pos-tipagem
    `date` -- sem o prefixo); o startswith fica de cinto de seguranca p/ ToolMessage construida
    a mao com status default.
    """
    ids_com_erro = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage)
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
        and m.tool_call_id
    }
    partes: list[str] = []
    for m in mensagens_do_turno(messages):
        if ids_com_erro and (_tool_use_ids(m) & ids_com_erro):
            # rascunho superado por retentativa de tool-com-erro recuperavel. Premissa: no maximo
            # UMA tool de escrita com erro recuperavel por passagem -- as tools de mídia (fan-out
            # multi-call por turno) NAO retornam "ERRO:" agregavel a texto, entao nao acionam isto.
            #
            # A premissa e que o LLM RE-EMITE a fala. Quando ele COMPLEMENTA (raciocinando que a
            # bolha anterior ja foi ao cliente), o turno perde o rascunho inteiro -- e por isso o
            # texto de erro das tools MANDA re-emitir a fala completa (`parceria.py:_ERRO_*`).
            continue
        texto = texto_da_mensagem(m)
        if texto:
            partes.append(texto)
    return "\n\n".join(partes)



# Marca de pausa longa da janela: a HumanMessage SINTETICA que `traduzir_mensagens`
# (nos/prepare_context) insere entre duas bolhas separadas por um gap grande de `created_at`. Nao e
# fala de ninguem — e fronteira ESTRUTURAL — e quem a distingue e o PREFIXO DETERMINISTICO do id
# (o conteudo e texto livre, o id nao). Mora neste modulo, e nao junto dos detectores que a
# consomem (`nos/_janela_do_turno`), porque `nos/__init__` importa o `output_guard`, que importa
# este modulo: a seta so pode apontar de `nos/` para ca.
_PREFIXO_ID_PAUSA = "pausa-"


def e_marca_pausa(msg: BaseMessage) -> bool:
    """True se `msg` e a marca de pausa longa inserida na janela (ver `_PREFIXO_ID_PAUSA`).

    Todo detector que caminha um burst contiguo de HumanMessages PARA nela: as bolhas do outro
    lado sao de outro momento da Conversa cliente, nao fala do cliente agora.
    """
    return bool(msg.id) and str(msg.id).startswith(_PREFIXO_ID_PAUSA)


# Campos de `registrar_extracao` que resumem a leitura do turno (a "mecanica" que importa num
# trace, sem PII). `proxima_acao_esperada`/`sinais_qualificacao` ficam de fora -- verbosos e nao
# acionaveis de relance.
_CAMPOS_EXTRACAO = (
    "intencao",
    "urgencia",
    "tipo_atendimento",
    "data_desejada",
    "horario_desejado",
    "valor_acordado",
    "duracao_horas",
    "cotacao_apresentada",
)


def mensagens_cliente_do_turno(resultado: dict[str, Any]) -> list[str]:
    """Texto das falas do CLIENTE que dispararam o turno: o burst final de HumanMessages da
    `conversa_crua` do State, parando na marca de pausa (`e_marca_pausa`).

    So para o `input` legivel do trace (observabilidade): da ao leitor o que o cliente disse neste
    turno sem garimpar a janela re-injetada. Sem `conversa_crua` (turno que morreu no gate de
    pausa), retorna [].

    Le a `conversa_crua` e nao `messages` porque a cauda que o chat recebe e UMA HumanMessage
    inchada de `contexto dinamico + fala do cliente` (`_anexar_contexto_dinamico`): filtrar por
    prefixo de texto reportaria o belief inteiro como fala do cliente. A crua e a janela LIMPA,
    publicada pelo prepare_context antes de qualquer anexacao — e foi este campo do trace que
    permitiu diagnosticar o incidente de 29/07.
    """
    crua: Sequence[BaseMessage] = resultado.get("conversa_crua") or []
    out: list[str] = []
    for m in reversed(crua):
        # Mesma mecanica de `_burst_do_cliente` (nos/_janela_do_turno): para na 1a bolha que nao e
        # dele (AIMessage) e na marca de pausa, que fecha o burst por ser de outro momento.
        if not isinstance(m, HumanMessage) or e_marca_pausa(m):
            break
        out.append(m.content if isinstance(m.content, str) else str(m.content))
    out.reverse()
    return out


def raciocinio_do_turno(resultado: dict[str, Any]) -> list[str]:
    """Cadeias de raciocinio (`reasoning_content`) que o chat #1 produziu NESTE turno.

    So existe em modo thinking (`settings.deepseek_thinking_chat` != "disabled", default "low"):
    `core.llm._ChatDeepSeekThinking` captura o campo da resposta do DeepSeek em
    `additional_kwargs["reasoning_content"]`, porque o wrapper langchain-openai nao o extrai. Em
    non-thinking a lista sai vazia — o mesmo caminho serve aos dois regimes.

    Uma entrada por passagem do LLM no turno (o loop ReAct chama de novo apos cada ToolMessage, e a
    regen do output_guard adiciona a sua). Mesmo criterio de "gerado agora" das outras funcoes do
    modulo (`mensagens_do_turno`): historico re-injetado nao tem `usage_metadata` e fica de fora.

    Serve a observabilidade (`core.tracing.resumir_trace_turno` publica no root span do trace): o
    raciocinio e a peca que explica POR QUE a fala saiu como saiu, e sem isto ele fica enterrado no
    `additional_kwargs` de uma observation `ChatOpenAI` no meio do grafo. NUNCA vai para o cliente —
    o `extrair_texto_do_turno` (o que e despachado) le `content`, nunca este campo.
    """
    fora: list[str] = []
    for m in mensagens_do_turno(resultado.get("messages", [])):
        rc = (m.additional_kwargs or {}).get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            fora.append(rc)
    return fora


def desfecho_do_turno(resultado: dict[str, Any]) -> dict[str, Any]:
    """Resumo nao-PII da mecanica do turno p/ o metadata/output do trace (observabilidade).

    Le o que o GRAFO produziu (nao o pos-processamento do coordenador): a extracao da ULTIMA
    `registrar_extracao` do turno (subset acionavel), os erros de tool recuperaveis (ex.:
    "ERRO: horario cedo demais"), e os flags efemeros do State (reoferta/disclosure/
    horario_minimo). Tudo determinístico e sem conteudo de mensagem do cliente.
    """
    messages = resultado.get("messages", [])
    desfecho: dict[str, Any] = {}

    extracao: dict[str, Any] = {}
    for m in mensagens_do_turno(messages):
        for tc in m.tool_calls or []:
            if tc.get("name") == "registrar_extracao":
                args = tc.get("args") or {}
                extracao = {c: args[c] for c in _CAMPOS_EXTRACAO if args.get(c) is not None}
    if extracao:
        desfecho["extracao"] = extracao

    erros = [
        str(m.content)
        for m in messages
        if isinstance(m, ToolMessage)
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
    ]
    if erros:
        desfecho["erros_tool"] = erros

    if resultado.get("_reoferta_tentada"):
        desfecho["reoferta_tentada"] = True
    if resultado.get("_categoria"):
        desfecho["disclosure"] = resultado["_categoria"]
    hmin = resultado.get("horario_minimo")
    if hmin is not None:
        desfecho["horario_minimo"] = hmin.isoformat() if hasattr(hmin, "isoformat") else str(hmin)

    return desfecho


def tags_do_turno(resultado: dict[str, Any]) -> list[str]:
    """Tags FILTRAVEIS do turno para o trace (Langfuse), derivadas do mesmo `desfecho_do_turno`.

    As tags que ja existiam sao os IDs de escopo (modelo/atendimento/cliente): servem para SEGUIR um
    caso que voce ja conhece, e nao para ACHAR casos. Estas sao de baixa cardinalidade e respondem a
    pergunta inversa — "me mostra os turnos que sairam mudos", "os que erraram tool", "os de
    agendamento" — que e como se investiga sem ter o UUID na mao.

    Vocabulario (estavel; `docs/agente/12-observabilidade-langfuse.md` e o guia de consulta):
      - `intencao:<valor>` / `sem_extracao` — a leitura que o turno fez do estado da negociacao.
      - `sem_resposta` — nenhum texto saiu para o cliente (turno mudo: guard zerou, LLM devolveu
        vazio, ou o turno morreu num gate). E o sintoma mais caro do agente.
      - `erro_tool` — alguma tool devolveu erro recuperavel (ex.: "ERRO: horario cedo demais").
      - `reoferta` — a auto-reoferta entrou.
      - `disclosure:<categoria>` — o intercept de disclosure classificou a fala do cliente.
    """
    desfecho = desfecho_do_turno(resultado)
    tags: list[str] = []
    intencao = (desfecho.get("extracao") or {}).get("intencao")
    tags.append(f"intencao:{intencao}" if intencao else "sem_extracao")
    if not extrair_texto_do_turno(resultado.get("messages", [])).strip():
        tags.append("sem_resposta")
    if desfecho.get("erros_tool"):
        tags.append("erro_tool")
    if desfecho.get("reoferta_tentada"):
        tags.append("reoferta")
    if desfecho.get("disclosure"):
        tags.append(f"disclosure:{desfecho['disclosure']}")
    return tags
