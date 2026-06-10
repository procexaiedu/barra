"""Tool de escrita `pedir_pix_deslocamento` (04 §3.2).

Solicita o Pix de deslocamento do fluxo externo: move o atendimento para
`Aguardando_confirmacao` com `pix_status='aguardando'` e RESERVA o slot (bloqueio prévio).
Só o `valor` é persistido no payload de `tool_calls`/`eventos`; a chave/titular do Pix NUNCA
vão em claro para a persistência (guard-rail de dado sensível) — quando a humanização (M4)
anexar a chave, deve lê-la fresh do cadastro da modelo. A tool NÃO chama Evolution e NÃO
escreve a chave no retorno, mantendo o string crítico (chave de 32+ chars) fora do LLM.
Invariante: externo SEM cliente_busca em Aguardando_confirmacao ⟹ Pix solicitado (01 §6.1,
emendada pelo ADR 0020 — o pickup é promovido pela extração, sem Pix).
"""

import json
from typing import Any

from langchain_core.tools import ToolException, tool
from langgraph.prebuilt import ToolRuntime
from psycopg import AsyncConnection

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL
from barra.core.moeda import formatar_brl
from barra.dominio.agenda.service import (
    ConflitoAgenda,
    ForaDisponibilidade,
    HorarioNaoDefinido,
    criar_bloqueio_previo,
)
from barra.settings import get_settings

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente


class _TipoNaoExterno(Exception):
    """Tool chamada num atendimento que nao esta registrado como externo (CONTEXT.md "Pix de
    deslocamento": sem Pix no interno). Guarda determinística sobre a instrucao da docstring:
    gravar pix_status='aguardando' num interno desviaria a proxima imagem do branch
    foto-portaria para o branch pix em rotear_imagem (media.py avalia pix primeiro)."""


class _ClienteBusca(Exception):
    """Tool chamada num externo-pickup (cliente_busca=true, ADR 0020): o cliente busca a modelo,
    nao ha deslocamento dela — Pix de deslocamento nao existe nesse caso. Guarda determinística
    sobre a instrucao da docstring/prompt (<externo_cliente_busca>)."""


@tool
async def pedir_pix_deslocamento(runtime: ToolRuntime[ContextAgente]) -> str:
    """Solicita o Pix de deslocamento, de valor fixo (ref. R$100), para saída externa.

    Sem parâmetros — o valor é fixo (definido pela agência), chave/titular vêm do cadastro da
    modelo.
    Após chamada: pix_status=aguardando, atendimento → Aguardando_confirmacao,
    cria bloqueio prévio do horário (reserva o slot). A humanização ANEXA a
    chave/titular/valor exatos à sua mensagem — você NÃO redigita a chave.

    Escreva o pedido em UMA só bolha, só DEPOIS desta tool retornar sucesso ("pra eu já chamar
    o uber e ir te encontrar, manda o pixzinho do deslocamento") — não pré-anuncie numa passagem
    anterior nem repita. Enquadre como custo da SUA saída, nunca como "garantir/segurar teu
    horário" (o horário já fica combinado antes; ver a conduta de Pix nas suas regras).
    Use APENAS para atendimento externo após acordar horário e endereço.
    Use APENAS quando VOCÊ se desloca por conta própria (uber até o cliente). Se o cliente vem
    te BUSCAR de carro, não há deslocamento seu — NÃO chame esta tool, não existe Pix nesse caso.
    Use APENAS UMA vez por atendimento (segunda chamada é idempotente, não duplica mensagem).

    Returns:
        Confirmação de que o Pix foi solicitado e o slot reservado. O retorno NÃO traz a chave —
        você NUNCA digita a chave Pix; o sistema anexa chave/titular/valor exatos depois da sua
        mensagem.
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    modelo_id = runtime.context.modelo_id
    turno_id = runtime.context.turno_id

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT chave_pix, titular_chave FROM barravips.modelos WHERE id = %s",
            (modelo_id,),
        )
        m = await res.fetchone()
        if m is None or not m["chave_pix"] or not m["titular_chave"]:
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("pedir_pix_deslocamento", "chave_pix_ausente").inc()
            raise ToolException(
                "ERRO: a modelo não tem chave Pix cadastrada — não dá pra pedir o Pix. "
                'Use escalar(motivo="politica_nova_necessaria") para Fernando resolver o cadastro.'
            )

        # Fonte unica do valor (settings.pix_deslocamento_valor): a mesma usada na validacao do
        # comprovante (workers/pix.py) e na bolha da chave (coordenador) — payload de auditoria
        # e retorno nunca driftam do cobrado.
        valor = get_settings().pix_deslocamento_valor
        try:
            await _executar_idempotente(
                conn,
                turno_id,
                "pedir_pix_deslocamento",
                0,
                payload={"valor": str(valor)},
                executor=lambda c, p: _aplicar_pedido_pix(c, atendimento_id, p),
            )
        except _TipoNaoExterno:
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("pedir_pix_deslocamento", "tipo_nao_externo").inc()
            raise ToolException(
                "ERRO: o Pix de deslocamento é só de atendimento EXTERNO (quando você se "
                "desloca) — este atendimento não está registrado como externo. No interno o "
                "cliente confirma chegando (foto da portaria), sem Pix. Se a saída é mesmo "
                "externa, registre tipo_atendimento='externo' (registrar_extracao) antes de "
                "pedir o Pix."
            ) from None
        except _ClienteBusca:
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("pedir_pix_deslocamento", "cliente_busca").inc()
            raise ToolException(
                "ERRO: este atendimento está registrado como pickup (o CLIENTE vem te buscar) — "
                "não existe Pix de deslocamento nesse caso, o deslocamento não é seu. Siga sem "
                "Pix: combine o ponto de encontro (ver <externo_cliente_busca> nas suas regras). "
                "Se na verdade VOCÊ vai de uber até ele, corrija com registrar_extracao "
                "(cliente_busca=false) antes de pedir o Pix."
            ) from None
        except ConflitoAgenda:
            # Branch 13 (04 §6): a RESERVA do slot falhou (outro cliente já o tomou). O turno
            # inteiro reverteu (pix_status volta a nao_solicitado) — instrua a IA a re-ofertar.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("pedir_pix_deslocamento", "agenda_conflito").inc()
            raise ToolException(
                "ERRO: o horário combinado acabou de ficar indisponível. Ofereça outro horário "
                "ao cliente com uma desculpa pessoal (ver sua conduta de indisponibilidade) — "
                "NUNCA revele que o horário foi reservado — antes de pedir o Pix de novo."
            ) from None
        except ForaDisponibilidade:
            # Trava dura (ADR 0005): horário fora do período de trabalho. O turno reverteu
            # (pix_status volta a nao_solicitado). Conduta de período de trabalho, não a
            # desculpa pessoal do conflito (fora do período não há outro cliente a esconder).
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels(
                "pedir_pix_deslocamento", "fora_disponibilidade"
            ).inc()
            raise ToolException(
                "ERRO: o horário combinado cai FORA do seu período de trabalho — o sistema não "
                "reserva o slot. Assuma que está fora, diga quando volta e combine a primeira "
                "data/horário dentro do período (veja <periodo_de_trabalho> no contexto) antes "
                "de pedir o Pix de novo."
            ) from None
        except HorarioNaoDefinido:
            # A IA pediu o Pix antes de o horário estar combinado (ex.: cliente pede o Pix e só
            # depois fala a hora). Sem horário não dá pra reservar o slot — o turno reverteu
            # (pix_status volta a nao_solicitado); instrua a IA a confirmar o horário primeiro.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("pedir_pix_deslocamento", "horario_ausente").inc()
            raise ToolException(
                "ERRO: o horário ainda não está combinado — não dá pra reservar o slot nem pedir o "
                "Pix. Confirme o horário com o cliente primeiro, depois peça o Pix de deslocamento."
            ) from None

    # Retorno NÃO inclui a chave — a humanização a anexa deterministicamente após o texto da IA.
    return (
        f"Pix de {formatar_brl(valor)} solicitado e slot reservado. Escreva o pedido no seu tom, "
        "SEM digitar a chave — o sistema anexa chave/titular/valor exatos após sua mensagem."
    )


async def _aplicar_pedido_pix(
    conn: AsyncConnection[Any], atendimento_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    res = await conn.execute(
        """
        SELECT id, modelo_id, tipo_atendimento::text AS tipo_atendimento, cliente_busca,
               bloqueio_id, data_desejada, horario_desejado, duracao_horas
          FROM barravips.atendimentos
         WHERE id = %s
        """,
        (atendimento_id,),
    )
    atendimento = await res.fetchone()
    assert atendimento is not None
    # Guarda determinística (CONTEXT.md "Pix de deslocamento": sem Pix no interno) ANTES de
    # qualquer escrita: tipo ausente ou interno aborta a transação inteira (erro recuperável).
    if atendimento["tipo_atendimento"] != "externo":
        raise _TipoNaoExterno(atendimento["tipo_atendimento"] or "nao_registrado")
    # Pickup (ADR 0020): cliente busca a modelo — sem Pix de deslocamento.
    if atendimento["cliente_busca"]:
        raise _ClienteBusca()

    # Guarda WHERE pix_status='nao_solicitado': idempotência de estado (não re-transiciona um
    # atendimento que já saiu de nao_solicitado). A idempotência por turno fica no tool_calls.
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET pix_status = 'aguardando',
               estado = 'Aguardando_confirmacao',
               fonte_decisao_ultima_transicao = 'extracao_ia'
         WHERE id = %s AND pix_status = 'nao_solicitado'
        """,
        (atendimento_id,),
    )
    # Bloqueio prévio do externo nasce AQUI (simétrico ao interno em registrar_extracao):
    # reserva o slot ao entrar em Aguardando_confirmacao e fecha a janela de double-booking.
    # Exceção: atendimento que JÁ tem bloqueio (ex.: pickup promovido pela extração e depois
    # corrigido para Uber, ADR 0020) — recriar colidiria com o próprio bloqueio (EXCLUDE).
    if atendimento["bloqueio_id"] is None:
        await criar_bloqueio_previo(conn, atendimento=atendimento)

    await conn.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (%s, 'pix_solicitado', 'agente', 'IA', %s::jsonb)
        """,
        (atendimento_id, json.dumps(payload, default=str)),
    )
    return {"mensagem": "Pix solicitado."}
