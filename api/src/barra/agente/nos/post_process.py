"""No post_process.

M0: refetch de ia_pausada (cinto-suspensorio, 04 §3.5); se a IA foi pausada por um pipeline
    sem lock (Pix/foto portaria) no meio do turno, descarta o texto das AIMessages do turno
    (conteudo "") -- o coordenador detecta a resposta vazia e nao despacha humanizacao.
    Excecoes: bolha pre-`escalar` preservada, e pausa nascida de GUARDA do registrar_extracao
    ganha uma canned de espera no lugar do texto descartado (escalada silenciosa, prod 22/07).
M3+: extrai tambem a lista de midias dos tool_calls. Humanizacao real (chunking, presence,
    jitter, dedupe) entra em M4 como worker ARQ separado.
"""

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

from barra.core.db import conexao
from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA

from .._canned import escolher_espera_escalada
from .._texto_turno import mensagens_do_turno
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
    vazias: list[AIMessage] = [AIMessage(id=m.id, content="") for m in alvo]

    # Escalada silenciosa (analise prod 22/07): quando a pausa nasce de uma GUARDA dentro do
    # registrar_extracao (piso de desconto, tipo nao aceito, reagendamento pos-bloqueio), nao
    # houve bolha de espera do `escalar` — zerar tudo deixaria o cliente no vacuo. Solta uma
    # canned de espera no lugar (usage_metadata zerado marca como gerada NESTE turno, mesmo
    # padrao da negacao do intercept_disclosure). Pausa de pipeline externo (Pix/foto portaria)
    # nao casa com as mensagens de guarda e segue silenciosa, como antes.
    escalada_de_guarda = corte is None and any(
        isinstance(m, ToolMessage) and str(m.content) in MENSAGENS_GUARD_ESCALADA
        for m in state["messages"]
    )
    if escalada_de_guarda:
        espera = AIMessage(
            content=escolher_espera_escalada(seed=runtime.context.turno_id),
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return {"messages": [*vazias, espera]}
    return {"messages": vazias}
