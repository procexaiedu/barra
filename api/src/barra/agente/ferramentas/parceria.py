"""Tool de escrita `envolver_parceira` (ADR-0042): os dois fluxos da parceira, um por `modo`.

A tool NÃO decide o fluxo — quem decide é o discriminante determinístico (`agente/_parceria.py`),
que roda no `prepare_context` e injeta no máximo UMA tag de conduta no contexto do turno. O `modo`
que o LLM manda é validado contra o cadastro e contra os carimbos do atendimento; qualquer
divergência vira `ToolException` (erro recuperável, o modelo lê e segue) em vez de efeito.

`modo="encaminhar"` (fluxo A) — o cliente quer um ATO que a modelo não faz e topou falar com a
parceira. A tool carimba `parceira_encaminhada_em` e devolve `contato_anexado`; a bolha com o
telefone é montada pelo `workers/coordenador.py`, fresh do cadastro, DEPOIS do turno. **A tool não
devolve o número** — o telefone não passa pelo LLM em nenhum ponto (mesmo trilho da chave Pix).

`modo="dupla"` (fluxo B) — o cliente quer as duas e a modelo do canal fecha sozinha. A tool carimba
`parceira_dupla_em` e devolve `card_parceira`; o coordenador enfileira o card NÃO-BLOQUEANTE que
pede ao Fernando confirmar a parceira (que pode estar `inativa` e sem disponibilidade cadastrada —
a venda não espera por isso). **Nenhum contato sai neste fluxo.**

As três travas duras vivem aqui, no write-time, e não no prompt:
1. **whitelist do par** — sem linha ativa em `modelo_parcerias`, e sem a flag do modo pedido, nada
   acontece;
2. **aceite dele antes de qualquer dado** — `encaminhar` exige `amiga_ofertada_em` já carimbado, o
   que só acontece num turno ANTERIOR (o carimbo é write-time do envio): o contato nunca sai no
   mesmo turno em que ela ofereceu;
3. **uma vez por atendimento** — `parceira_encaminhada_em IS NULL`; e os dois modos são mutuamente
   exclusivos no mesmo atendimento (cada um recusa se o carimbo do outro existe).
"""

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from langchain_core.tools import ToolException, tool
from langgraph.prebuilt import ToolRuntime
from psycopg import AsyncConnection
from pydantic import Field

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL
from barra.dominio.modelos.parcerias import carregar_parceria

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente

logger = logging.getLogger(__name__)

ModoParceira = Literal["encaminhar", "dupla"]

_DESC_MODO = (
    '"dupla" — ele quer VOCÊS DUAS no mesmo encontro: você conduz e fecha sozinha, cota as duas '
    "pela SUA tabela e o sistema avisa a coordenação. "
    '"encaminhar" — ele quer um ato que você NÃO faz e topou falar com ela: o sistema manda o '
    "contato dela e a venda passa a ser dela. Use o modo que o seu contexto do turno mandar; "
    "nunca os dois."
)

# O que a tool devolve ao LLM. Sem número, sem valor: o retorno é instrução de conduta, e a única
# forma de o telefone existir é a bolha que o sistema anexa depois.
#
# NÃO DESCREVA A MECÂNICA DO SISTEMA AQUI. Medido ao vivo (12/08, rig de tools, 2 de 6 conversas de
# encaminhamento — traces 3a0363f6 e 610745d2): a versão anterior dizia "o sistema manda o telefone
# dela numa bolha própria, depois da sua fala", e o modelo obedeceu narrando isso ao cliente ("A
# Yasmin que faz amor, o contato dela já vai aí 🥰"). O judge de AUP leu o anúncio de uma entrega
# que a fala não faz como `system_leak`, ZEROU a bolha e PAUSOU a IA (motivo `aup_saida_system_leak`)
# — o cliente não recebeu nem a fala nem o contato, e a venda encaminhada morreu num handoff que
# ninguém pediu. É o mecanismo da memória `conduta_nova_no_prompt_vira_tique`: o que se prescreve é
# a INTENÇÃO da fala; o que o sistema faz por fora não é assunto do modelo. E como manda o incidente
# #36, proibir sem dar o que dizer no lugar não basta — a primeira linha diz o que FAZER.
_OK_ENCAMINHAR = (
    "Feito. Encerre a sua parte com naturalidade, como quem passa a bola: daqui em diante quem "
    "conversa com ele é a {nome}. NÃO escreva número nenhum, NÃO cote valor (preço, local e "
    "horário são com ela) e NÃO anuncie que algo está sendo enviado nem comente como ele vai "
    "receber o contato — isso não é assunto seu, e falar disso derruba a sua mensagem. Não volte "
    "ao assunto depois."
)
# Mesma disciplina, e aqui o vazamento seria PIOR: narrar "a coordenação foi avisada" entrega a
# existência de uma coordenação atrás dela. O que o modelo precisa saber é só que NÃO espera.
_OK_DUPLA = (
    "Encontro com as duas assumido por você: siga e crave o horário normalmente, sem esperar "
    "confirmação de ninguém e sem prometer retorno. O valor das duas sai da SUA tabela (o total da "
    "seção por pessoa) e o telefone dela NUNCA vai ao cliente. Não comente combinação interna, "
    "conferência nem aviso a terceiros — na conversa existem você, ela e ele."
)

_ERRO_SEM_PARCEIRA = "ERRO: você não tem parceira cadastrada. Siga sem ela."
_ERRO_MODO_NAO_LIBERADO = (
    "ERRO: este arranjo com a sua parceira não está liberado. Siga sem ela, pela sua conduta de "
    "fora do cardápio."
)
_ERRO_SEM_ACEITE = (
    "ERRO: você ainda não ofereceu a sua parceira a ele nesta conversa, ou ele ainda não topou. "
    "Ofereça primeiro e espere o sim — nenhum dado dela sai antes disso."
)
_ERRO_JA_ENCAMINHADA = (
    "ERRO: você já passou o contato dela nesta negociação. Não repita — siga a conversa."
)
_ERRO_FLUXO_CRUZADO = (
    "ERRO: nesta negociação a sua parceira já entrou pelo outro caminho. Siga com o que já está "
    "combinado, sem reabrir."
)
_ERRO_SEM_ATENDIMENTO = "ERRO: sem negociação aberta para registrar isso."


# `call_idx` fixo em 0 (ao contrário de `enviar_midia`, que é ordinal): a parceira entra UMA vez
# por turno. Se o LLM chamar duas vezes, o ON CONFLICT do `_executar_idempotente` devolve o
# resultado da primeira sem reexecutar — a segunda chamada não vira um segundo efeito.
_CALL_IDX = 0


@tool
async def envolver_parceira(
    modo: Annotated[ModoParceira, Field(description=_DESC_MODO)],
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Põe a sua parceira no encontro, do jeito que o contexto deste turno mandar.

    Use SÓ quando o seu contexto trouxer a tag da parceira — ela diz qual dos dois modos vale.
    `dupla`: ele quer vocês duas e você fecha sozinha (nunca passe o contato dela).
    `encaminhar`: ele quer algo que você não faz e topou falar com ela (o sistema manda o contato;
    você não cota valor nenhum daí em diante).

    Returns:
        Confirmação e a conduta que vale a partir daqui. Se vier "ERRO: ...", o arranjo não está
        liberado — não prometa nada ao cliente sobre a sua parceira e siga a conversa.
    """
    pool = runtime.context.db_pool
    modelo_id = runtime.context.modelo_id
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    # `not` em vez de `is None`: `ContextAgente.atendimento_id` e `str` (nao-Optional), entao o
    # `is None` era ramo morto para o type checker — e o caso real que resta e a string vazia.
    if not atendimento_id:
        _recusa("sem_atendimento")
        raise ToolException(_ERRO_SEM_ATENDIMENTO)

    async with pool.connection() as conn, conn.transaction():
        parceria = await carregar_parceria(conn, modelo_id)
        if parceria is None:
            _recusa("sem_parceira")
            raise ToolException(_ERRO_SEM_PARCEIRA)
        liberado = parceria.dupla_ativa if modo == "dupla" else parceria.encaminhamento_ativo
        if not liberado:
            _recusa("modo_nao_liberado")
            raise ToolException(_ERRO_MODO_NAO_LIBERADO)

        res = await conn.execute(
            """
            SELECT amiga_ofertada_em, parceira_encaminhada_em, parceira_dupla_em
              FROM barravips.atendimentos
             WHERE id = %s
             FOR UPDATE
            """,
            (UUID(atendimento_id),),
        )
        flags = await res.fetchone()
        if flags is None:
            _recusa("sem_atendimento")
            raise ToolException(_ERRO_SEM_ATENDIMENTO)

        # Mutuamente exclusivos POR ATENDIMENTO: quem já entrou por um caminho não entra pelo
        # outro. É a mesma invariante do discriminante (que nunca arma os dois no mesmo turno),
        # sustentada aqui contra a conversa INTEIRA, que o turno sozinho não enxerga.
        cruzado = "parceira_dupla_em" if modo == "encaminhar" else "parceira_encaminhada_em"
        if flags[cruzado] is not None:
            _recusa("fluxo_cruzado")
            raise ToolException(_ERRO_FLUXO_CRUZADO)

        if modo == "encaminhar":
            # Aceite DELE antes de qualquer dado dela. `amiga_ofertada_em` é carimbado no
            # write-time do ENVIO (workers/envio.py), então ele só existe num turno anterior —
            # o contato nunca sai na mesma resposta em que ela ofereceu a parceira.
            if flags["amiga_ofertada_em"] is None:
                _recusa("sem_aceite")
                raise ToolException(_ERRO_SEM_ACEITE)
            if flags["parceira_encaminhada_em"] is not None:
                _recusa("ja_encaminhada")
                raise ToolException(_ERRO_JA_ENCAMINHADA)

        await _executar_idempotente(
            conn,
            turno_id,
            "envolver_parceira",
            _CALL_IDX,
            payload={
                "modo": modo,
                "parceira_id": parceria.parceira_id,
                "atendimento_id": atendimento_id,
            },
            executor=_aplicar,
        )

    return (_OK_DUPLA if modo == "dupla" else _OK_ENCAMINHAR).format(nome=parceria.nome)


async def _aplicar(conn: AsyncConnection[Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Carimba a coluna do modo. Guard IS NULL (first-write-wins) — idempotente sob replay."""
    coluna = "parceira_dupla_em" if payload["modo"] == "dupla" else "parceira_encaminhada_em"
    await conn.execute(
        f"""
        UPDATE barravips.atendimentos
           SET {coluna} = now()
         WHERE id = %s AND {coluna} IS NULL
        """,
        (UUID(payload["atendimento_id"]),),
    )
    # As duas chaves do `resultado` são o contrato com o coordenador: `contato_anexado` faz a bolha
    # determinística do telefone sair; `card_parceira` enfileira o card não-bloqueante. Nunca as
    # duas — é o `modo` que escolhe, e ele é único.
    return {
        "modo": payload["modo"],
        "parceira_id": payload["parceira_id"],
        "contato_anexado": payload["modo"] == "encaminhar",
        "card_parceira": payload["modo"] == "dupla",
    }


def _recusa(motivo: str) -> None:
    AGENTE_TOOL_ERRO_RECUPERAVEL.labels("envolver_parceira", motivo).inc()
