"""No post_process.

M0: refetch de ia_pausada (cinto-suspensorio, 04 §3.5); se a IA foi pausada por um pipeline
    sem lock (Pix/foto portaria) no meio do turno, descarta o texto das AIMessages do turno
    (conteudo "") -- o coordenador detecta a resposta vazia e nao despacha humanizacao.
    Excecoes: bolha pre-`escalar` preservada, e toda escalada que sairia MUDA ao cliente ganha
    uma canned de espera no lugar do texto descartado -- a de GUARDA do registrar_extracao
    (escalada silenciosa, prod 22/07) e a que a propria IA decide sem escrever a bolha que o
    <quando_usar_escalar> pede. Excecao da excecao: `motivo=conteudo_ilegal`, onde a espera nao
    existe (a recusa seca fica sozinha).
M3+: extrai tambem a lista de midias dos tool_calls. Humanizacao real (chunking, presence,
    jitter, dedupe) entra em M4 como worker ARQ separado.
"""

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

from barra.core.db import conexao
from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA

from .._canned import escolher_espera_escalada
from .._texto_turno import extrair_texto_do_turno, kwargs_preservados, mensagens_do_turno
from ..contexto import ContextAgente
from ..estado import EstadoAgente


async def post_process(state: EstadoAgente, runtime: Runtime[ContextAgente]) -> dict[str, Any]:
    """Refetch ia_pausada; se pausou durante o turno, zera o texto da resposta."""
    # Webhook fino (atendimento_id None): nada a pausar — espelha o gate do prepare_context.
    if runtime.context.atendimento_id is None:
        return {}
    async with conexao(runtime.context.db_pool) as conn:
        result = await conn.execute(
            "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
            (runtime.context.atendimento_id,),
        )
        row = await result.fetchone()

    if not (row and row["ia_pausada"]):
        return {}

    # Zera TODAS as AIMessages geradas no turno (mesmo id -> o reducer add_messages substitui por
    # vazia), nao so a ultima: na reentrada pos-tools o `[-1]` e uma ToolMessage, e quando ja houve
    # texto na 1a passagem (extracao/resposta inline) zerar so o ultimo deixaria essa fala viva p/ o
    # coordenador despachar APOS a pausa. Mesmo criterio (`mensagens_do_turno`) do output_guard.
    mensagens = mensagens_do_turno(state["messages"])

    # Excecao: quando a pausa e do PROPRIO turno (`escalar`), o prompt manda deixar uma bolha de
    # espera antes de chamar a tool -- zerar tudo faria toda escalada virar silencio ao cliente. O
    # corte fica DEPOIS da AIMessage que carrega o tool_call: o que a IA escrever pos-escalar (a
    # desobediencia que 04 §3.5 barra) continua descartado.
    corte = next(
        (
            i
            for i, m in enumerate(mensagens)
            if any(tc.get("name") == "escalar" for tc in (m.tool_calls or []))
        ),
        None,
    )
    alvo = mensagens if corte is None else mensagens[corte + 1 :]
    # PRESERVA usage_metadata + response_metadata, mesma invariante do `_zerar_turno` do
    # output_guard: `add_messages` SUBSTITUI a mensagem de mesmo id (nao faz merge), entao recriar
    # sem o usage apagava os tokens do turno do State. `custo_chat_turno_brl` soma justamente por
    # `usage_metadata` -> dava 0 -> `acumular_custo_atendimento` virava no-op (exige custo > 0) e o
    # turno pausado queimava DeepSeek sem entrar em `atendimentos.custo_ia_brl`. De quebra, sem o
    # usage essas mensagens sumiam de `mensagens_do_turno` e o trace perdia desfecho/raciocinio.
    # Pelo mesmo motivo o `additional_kwargs` vem junto (menos o espelho cru dos tool_calls): e
    # onde mora o `reasoning_content`, que o trace publica e que nunca vai ao cliente
    # (loop-massa r2 — a mesma perda foi medida do lado do output_guard).
    vazias: list[AIMessage] = [
        AIMessage(
            id=m.id,
            content="",
            usage_metadata=m.usage_metadata,
            response_metadata=m.response_metadata,
            additional_kwargs=kwargs_preservados(m),
        )
        for m in alvo
    ]

    if corte is None:
        # Escalada silenciosa (analise prod 22/07): quando a pausa nasce de uma GUARDA dentro do
        # registrar_extracao (piso de desconto, tipo nao aceito, reagendamento pos-bloqueio), nao
        # houve bolha de espera do `escalar` — zerar tudo deixaria o cliente no vacuo. Solta uma
        # canned de espera no lugar (usage_metadata zerado marca como gerada NESTE turno, mesmo
        # padrao da negacao do intercept_disclosure). Pausa de pipeline externo (Pix/foto portaria)
        # nao casa com as mensagens de guarda e segue silenciosa, como antes.
        precisa_espera = any(
            isinstance(m, ToolMessage) and str(m.content) in MENSAGENS_GUARD_ESCALADA
            for m in state["messages"]
        )
    else:
        # Escalada decidida pela IA: a bolha de espera do <quando_usar_escalar> era SO prosa, e
        # quando a IA chama a tool sem escrever nada o turno sai mudo com a IA pausada — o mesmo
        # vacuo da escalada de guarda. O canned entra so quando o turno sairia mudo; a excecao vem
        # do arg `motivo` da propria tool_call (enum fechado, `ferramentas/escalada.py`): em
        # conteudo_ilegal "um momento" leria como "deixa eu ver se consigo", entao a recusa seca
        # fica sozinha — e a prosa segue sendo o unico site que cobre esse caso.
        motivos = {
            (tc.get("args") or {}).get("motivo")
            for tc in (mensagens[corte].tool_calls or [])
            if tc.get("name") == "escalar"
        }
        # O texto de antes do corte passa pelo MESMO filtro do coordenador
        # (`extrair_texto_do_turno`): o rascunho de uma passagem cuja tool ERROU nao chega ao
        # cliente, e conta-lo como bolha deixaria o vacuo de pe. As ToolMessages entram so para
        # esse conjunto de erros — a ordem delas nao afeta o texto agregado.
        texto_antes = extrair_texto_do_turno(
            [*mensagens[: corte + 1], *(m for m in state["messages"] if isinstance(m, ToolMessage))]
        )
        precisa_espera = "conteudo_ilegal" not in motivos and not texto_antes.strip()

    if precisa_espera:
        espera = AIMessage(
            content=escolher_espera_escalada(seed=runtime.context.turno_id),
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return {"messages": [*vazias, espera]}
    return {"messages": vazias}
