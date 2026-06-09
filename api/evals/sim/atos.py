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


class _SettingsLembrete:
    """So o que `cobrar_valor_final` le (ativo/tolerancia/intervalo/max_toques) -- espelha o stub
    `_Settings` da F0.9. Valores deterministicos: com `toques=0` a acao e sempre 'enviar', entao a
    unica config que importa e a tolerancia (o alvo precisa estar vencido, e o ato envelhece o
    bloqueio bem alem dela)."""

    lembrete_valor_ativo = True
    lembrete_valor_tolerancia_min = 15
    lembrete_valor_intervalo_min = 30
    lembrete_valor_max_toques = 3


class _EvolutionSim:
    """Stub de EvolutionClient p/ a jornada: pula o HTTP da Evolution mas PERSISTE o envio em
    `envios_evolution` pela MESMA porta que o cliente real usa apos o POST (`registrar_envio`).
    Assim o card proativo do Lembrete de fechamento deixa rastro auditavel (`card_kind`) -- a prova
    de que a cobranca disparou -- sem rede. So `enviar_texto` e exercitado pelo cron."""

    async def enviar_texto(
        self,
        *,
        conn: AsyncConnection[dict[str, Any]],
        instance_id: str,
        remote_jid: str,
        texto: str,
        contexto: str,
        tipo: str,
        atendimento_id: UUID | None = None,
        conversa_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        **_ignorado: Any,
    ) -> str:
        from barra.core.evolution import registrar_envio

        message_id = f"sim-card-{uuid4().hex}"
        await registrar_envio(
            conn,
            evolution_message_id=message_id,
            instance_id=instance_id,
            remote_jid=remote_jid,
            contexto=contexto,
            tipo=tipo,
            atendimento_id=atendimento_id,
            conversa_id=conversa_id,
            payload=payload or {},
        )
        return message_id


async def lembrete_cobra_valor_e_fecha(
    conn: AsyncConnection[dict[str, Any]],
    atendimento_id: UUID,
    *,
    valor_final: str = "800",
) -> None:
    """Lembrete de fechamento: a COBRANCA PROATIVA do Valor final fecha a venda (CONTEXT.md "Lembrete
    de fechamento" / ADR-0009; F0.9).

    Caminho-irmao do `modelo_fecha_card` (F4.2) para o MESMO desfecho `Em_execucao -> Fechado`. La a
    modelo fecha por impulso proprio; AQUI o SISTEMA cobra primeiro: passado o fim do atendimento e
    ainda em `Em_execucao`, o cron de prod `cobrar_valor_final` (workers/lembrete_valor.py) manda um
    card no grupo de Coordenacao pedindo o valor; a modelo responde ESSE card com o valor -> Fechado.
    O fecho vem em RESPOSTA a cobranca, nao espontaneo.

    Como o `cliente_some_timeout` envelhece o aviso e dispara o cron real, aqui ENVELHECEMOS o
    `bloqueios.fim` (o relogio do sim nao espera o atendimento acabar) para o alvo ficar elegivel,
    garantimos o canal de Coordenacao da modelo (senao `_enviar_card` viraria 'canal ausente') e
    disparamos o MESMO `cobrar_valor_final` de prod -- nao reimplementa o card. Em seguida a modelo
    fecha pela mesma porta `aplicar_comando registrar_fechado` do `modelo_fecha_card`. O `valor_final`
    e REPRESENTATIVO (cardapio do sim cota 1h=800); o valor negociado correto e qualidade-de-venda,
    sob revisao humana, fora do escopo deterministico (F4.7).

    Imports LAZY (igual ao `modelo_fecha_card`/`cliente_some_timeout`): mantem `atos.py` importavel
    nos testes puros sem arrastar workers/dominio.
    """
    from barra.dominio.escaladas.service import aplicar_comando
    from barra.workers.lembrete_valor import cobrar_valor_final

    # Envelhece a JANELA inteira do bloqueio vinculado para o passado (o relogio do sim nao espera o
    # programa real terminar): o atendimento fica vencido alem da tolerancia e entra no conjunto de
    # alvos do lembrete. Move inicio E fim (nao so o fim) preservando `fim > inicio` -- a constraint
    # `bloqueios_intervalo_valido`; so envelhecer o fim o deixaria antes do inicio seedado/reservado.
    await conn.execute(
        """
        UPDATE barravips.bloqueios
           SET inicio = now() - interval '180 minutes',
               fim = now() - interval '60 minutes'
         WHERE atendimento_id = %s
        """,
        (atendimento_id,),
    )
    # Garante o canal de Coordenacao da modelo dona do atendimento (o seed minimo do runner nao o
    # popula) -- sem instance/grupo, `_enviar_card` levanta 'canal ausente' e o card nao sai.
    await conn.execute(
        """
        UPDATE barravips.modelos
           SET evolution_instance_id = COALESCE(evolution_instance_id, %s),
               coordenacao_chat_id = COALESCE(coordenacao_chat_id, %s)
         WHERE id = (SELECT modelo_id FROM barravips.atendimentos WHERE id = %s)
        """,
        (f"sim-inst-{uuid4().hex}", f"sim-coord-{uuid4().hex}@g.us", atendimento_id),
    )
    # Cobranca proativa: o cron de prod manda o card pedindo o valor final (rastro em envios_evolution).
    await cobrar_valor_final(conn, _EvolutionSim(), _SettingsLembrete())  # type: ignore[arg-type]
    # A modelo responde o card com o valor final -> Fechado (mesma porta do modelo_fecha_card).
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
