"""Atos de estado dual-control do cliente simulado (EVAL-12 / tau2-bench, 08b §3.2).

NAO-GATE: este simulador serve para DESCOBRIR falhas que viram fixtures pre-roteirizadas de
`scripted_5/` (EVAL-01). Nunca e criterio de cutover (ver sim/README.md).

A intuicao dual-control (tau2-bench): no P0 as transicoes criticas do atendimento NAO sao
disparadas por mensagem da IA, mas por ATOS observaveis do cliente (mandar Pix, foto de portaria,
aviso de saida) ou pelo SILENCIO (timeout). O cliente simulado dispara esses atos mutando o
estado REAL no banco de TESTE, espelhando os gatilhos de producao. Cada ato recebe `conn` + ids
e e SQL puro parametrizado (psycopg3) -- nao roda contra banco aqui (needs_db).

Os atos refletem a semantica de CONTEXT.md; cada docstring cita a regra. Eles NAO inventam estado
fora dela (ex.: Pix nunca trava; foto de portaria so vale em Aguardando_confirmacao interno).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection


async def enviar_pix(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
    *,
    valido: bool,
) -> None:
    """Cliente manda o comprovante de Pix de deslocamento (CONTEXT.md "Pix de deslocamento").

    O comprovante SEMPRE faz o atendimento avancar -- "nunca trava por Pix": checagem OK valida em
    silencio (`pix_status=validado`); divergencia/suspeita marca o comprovante como DUVIDOSO
    (`pix_status=em_revisao`, fila assincrona de Fernando) mas o fluxo segue. Em ambos: card
    "saida confirmada", `ia_pausada=true` (motivo `modelo_em_atendimento`), atendimento ->
    `Confirmado` (CONTEXT.md "Estados do atendimento": Confirmado nao trava por Pix duvidoso).
    """
    pix_status = "validado" if valido else "em_revisao"
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Confirmado',
               pix_status = %s,
               ia_pausada = true,
               ia_pausada_motivo = 'modelo_em_atendimento'
         WHERE id = %s
        """,
        (pix_status, atendimento_id),
    )


async def enviar_foto_portaria(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
) -> None:
    """Cliente manda a foto de portaria no atendimento INTERNO (CONTEXT.md "Foto de portaria").

    Qualquer imagem em `Aguardando_confirmacao` interno e tratada como foto de portaria (sem vision
    automatica no P0). O recebimento dispara handoff implicito: card "cliente chegou",
    `ia_pausada=true` (motivo `modelo_em_atendimento`) e transicao automatica
    `Aguardando_confirmacao` -> `Em_execucao`, sem aprovacao humana. A IA para de responder o
    cliente apos a chegada (CONTEXT.md _Avoid_: manter IA respondendo apos a chegada).
    """
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Em_execucao',
               ia_pausada = true,
               ia_pausada_motivo = 'modelo_em_atendimento'
         WHERE id = %s
           AND estado = 'Aguardando_confirmacao'
        """,
        (atendimento_id,),
    )


async def enviar_aviso_saida(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
) -> None:
    """Cliente avisa que saiu de casa rumo ao endereco (CONTEXT.md "Aviso de saida").

    Primeiro aviso operacional da sequencia interna: prepara a modelo (card simples) mas NAO
    confirma o atendimento e NAO muda o estado -- segue em `Aguardando_confirmacao`, e a IA
    continua respondendo o cliente normalmente. Apenas seta `aviso_saida_em` (de onde conta o
    timeout determinista de 45 min -> `Perdido(sumiu)` se nao chegar a foto de portaria).
    """
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET aviso_saida_em = now()
         WHERE id = %s
        """,
        (atendimento_id,),
    )


async def modelo_fecha_card(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
    *,
    valor_final: str = "800",
) -> None:
    """A MODELO fecha a venda respondendo o card na Coordenacao com o Valor final (CONTEXT.md
    "Registro de resultado").

    Unico ato dual-control de um 3o ator (a modelo, nao o cliente): a transicao final
    `Em_execucao -> Fechado` nao e disparada por turno da IA nem por ato do cliente, mas pela modelo
    respondendo o card. Espelha exatamente o gatilho de producao -- `aplicar_comando registrar_fechado`
    pela porta `grupo_coordenacao`/`modelo` (a mesma que o webhook chama ao resolver um card, provada
    isolada na F0.8): grava o Valor final, conclui o bloqueio vinculado (trigger sync_bloqueio_estado)
    e despausa a IA. O `valor_final` e REPRESENTATIVO (a cardapio do sim cota 1h=800) -- o valor
    negociado correto e qualidade-de-venda, sob revisao humana, fora do escopo deterministico (F4.2).

    Import LAZY de `aplicar_comando` (igual ao `loop.py` com `barra.core.tracing`): mantem `atos.py`
    importavel nos testes puros sem arrastar o dominio.
    """
    from barra.dominio.escaladas.service import aplicar_comando

    await aplicar_comando(
        conn,
        origem="grupo_coordenacao",
        autor="modelo",
        atendimento_id=atendimento_id,
        comando="registrar_fechado",
        payload={"valor_final": valor_final},
    )


async def cliente_some_timeout(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
) -> None:
    """O cliente avisou que saiu mas SOME e nunca chega: apos 45 min o timeout determinista o marca
    `Perdido(sumiu)` (CONTEXT.md "Aviso de saida" / "timeout interno"; ramo "nao volta").

    Unico ato que representa a passagem do TEMPO + o cron de prod (nao um turno da IA nem um ato
    sincrono do cliente): o `aviso_saida_em` ja foi setado por `enviar_aviso_saida` na jornada -- aqui
    ENVELHECEMOS o aviso (o relogio do sim nao espera os 45 min reais) e disparamos o MESMO
    `aplicar_timeout_interno` de producao (workers/timeouts.py), que varre o interno em
    `Aguardando_confirmacao` com aviso vencido e sem foto de portaria -> `Perdido`, motivo `sumiu`,
    bloqueio cancelado. Nao reimplementa a transicao: chama a funcao de prod, como `modelo_fecha_card`
    chama `aplicar_comando`. So envelhece se o aviso ja foi enviado (`aviso_saida_em IS NOT NULL`); se
    nao, o timeout nao tem o que varrer e nada muda (conservador).

    Import LAZY de `aplicar_timeout_interno` (igual ao `modelo_fecha_card`): mantem `atos.py`
    importavel nos testes puros sem arrastar os workers.
    """
    from barra.workers.timeouts import aplicar_timeout_interno

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET aviso_saida_em = now() - interval '46 minutes'
         WHERE id = %s AND aviso_saida_em IS NOT NULL
        """,
        (atendimento_id,),
    )
    await aplicar_timeout_interno(conn)


def ficar_em_silencio() -> None:
    """Cliente nao faz nada -- deixa o TIMEOUT determinista decidir (no-op, sem DB).

    Espelha o silencio que o roadmap lista como ato dual-control (`ficar_em_silencio`): nenhum
    estado muda agora. Quem transiciona e o worker de timeout (ex.: 24h sem msg do cliente em
    Triagem/Qualificado -> `Perdido(sumiu)`; 45 min do aviso de saida sem foto -> idem). O loop da
    jornada apenas avanca o relogio/turnos sem inserir mensagem nem aplicar mutacao.
    """
    # No-op proposital: o silencio e a ausencia de ato. Mantido como funcao nomeada para a jornada
    # poder enumera-lo como uma acao possivel do cliente (paridade com os demais atos).
    return None


def gerar_id_mensagem() -> UUID:
    """Id de mensagem novo (uuid4) -- usado quando um ato precisa de uma linha sintetica."""
    return uuid4()
