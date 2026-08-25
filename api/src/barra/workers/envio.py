"""Job de envio Evolution com registro em envios_evolution."""

import asyncio
import logging
import math
import random
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from arq import Retry
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.agente._disciplina import (
    contem_contraproposta,
    contem_endereco_de_encontro,
    contem_escalada_da_amiga,
    contem_hora_na_mesa_no_turno,
    contem_oferta_da_amiga,
    contem_pedido_da_foto_de_portaria,
    contem_pergunta_de_horario,
    contem_pergunta_do_motivo_do_resgate,
    contem_sondagem_dia,
    tokens_do_endereco,
)
from barra.agente.persona import brl
from barra.core.errors import ErroDominio
from barra.core.evolution import EvolutionClient
from barra.core.metrics import (
    AGENTE_ACEITE_GRAVADO,
    AGENTE_ESCALADA,
    ENVIO_DURACAO,
    ENVIO_PII_REDIGIDA,
    ENVIO_RESULTADO,
    ENVIO_RETRIES,
    QUOTE_MARCADOR_VAZADO,
)
from barra.core.tracing import sentry_sdk
from barra.dominio.atendimentos.service import (
    carimbar_cotacao_por_texto_enviado,
    gravar_valor_do_aceite,
    incrementar_contrapropostas,
    incrementar_perguntas_de_horario,
    marcar_amiga_ofertada,
    marcar_book_enviado,
    marcar_dia_sondado,
    marcar_endereco_enviado,
    marcar_foto_portaria_pedida,
    marcar_motivo_resgate_perguntado,
    precos_ofertados_na_fala,
)
from barra.dominio.escaladas.modelos import TipoEscalada, rotulo_tipo_escalada
from barra.dominio.escaladas.service import (
    ESTADOS_TERMINAIS,
    abrir_handoff,
    card_escalada_vai_ao_grupo,
    fase_do_atendimento,
    mapear_bucket,
)
from barra.settings import get_settings
from barra.workers._cards import render_card
from barra.workers._saida_guard import (
    extrair_tokens_pii,
    normalizar_emoji_voz_indexado,
    normalizar_travessao,
    normalizar_vocativo_voz,
    redigir_pii_eco,
    remover_marcador_quote,
    restaurar_interrogacao_proposta,
    tem_marcador_ia,
    tem_placeholder_eco,
)

logger = logging.getLogger(__name__)

# Teto de tentativas dos jobs de envio (enviar_card/enviar_turno), fonte única (REL-03).
# O ARQ NAO injeta max_tries no job_ctx, entao o fallback do dead-end abaixo (ctx.get) precisa
# bater com o max_tries registrado em workers/settings.py — senao a checagem job_try>=max_tries
# nunca dispara e a escalada de envio crítico exaurido some em silêncio. Mude aqui, muda nos dois.
MAX_TRIES_ENVIO = 3

# A rede determinística do carimbo de cotação (ADR 0022) vive em `dominio/atendimentos/service.py`
# (`carimbar_cotacao_por_texto_enviado`), junto do UPDATE que ela dispara: o harness e2e reaplica a
# MESMA regra ao gravar a bolha da IA, e uma segunda cópia do regex divergiria com o tempo.

# Dedupe legenda↔bolha (05 §5): o LLM às vezes emite a MESMA linha de acompanhamento da mídia
# duas vezes — como bolha de texto do turno E como `legenda` da enviar_midia — e o cliente vê a
# frase repetida (bolha "Sou eu amor" + foto com legenda "Sou eu amor 🥰"). A conduta manda UMA
# linha (<midia>); aqui está o backstop determinístico: se a legenda, normalizada, bate com uma
# bolha já enviada neste turno, a legenda cai (a bolha já disse a linha). Match EXATO normalizado
# (só alfanumérico, sem emoji/pontuação/caixa) — conservador, não descarta legenda genuinamente
# distinta do texto.
_RE_NAO_ALFANUM = re.compile(r"[^0-9a-zà-ú]", re.I)


def _norm_dedup(s: str) -> str:
    return _RE_NAO_ALFANUM.sub("", s.lower())


def _legenda_duplica_bolha(legenda: str, chunks: list[str]) -> bool:
    n = _norm_dedup(legenda)
    return bool(n) and any(_norm_dedup(c) == n for c in chunks)


async def enviar_texto_job(
    conn: AsyncConnection[Any],
    client: EvolutionClient,
    *,
    instance_id: str,
    remote_jid: str,
    texto: str,
    contexto: str,
    tipo: str,
    payload: dict[str, Any] | None = None,
) -> str:
    if not instance_id:
        raise ErroDominio("EVOLUTION_NAO_PAREADA", "Evolution nao pareada.", status_code=409)
    return await client.enviar_texto(
        conn=conn,
        instance_id=instance_id,
        remote_jid=remote_jid,
        texto=texto,
        contexto=contexto,
        tipo=tipo,
        payload=payload or {},
    )


# --- Cards no grupo de Coordenação (05 §6) ----------------------------------
# Cards são jobs ARQ diretos, enviados pelo EvolutionClient SEM passar pela humanização.
# Uma função `enviar_card` única despacha por `tipo`; cada renderer é idempotente por owner
# (06 §9): só envia se o card ainda não foi enviado e grava o id no próprio dono.


async def _card_escalada(ctx: dict[str, Any], *, escalada_id: str, **_: Any) -> None:
    """Card de handoff no grupo de Coordenação (05 §6).

    Idempotência por owner: só envia se `escaladas.card_message_id IS NULL`. O POST
    (→ envios_evolution, via `enviar_texto`) e a gravação do `card_message_id` vivem na
    MESMA transação — o retry do ARQ relê a coluna e não reenvia.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.tipo::text AS tipo, e.resumo_operacional, e.acao_esperada,
                   e.card_message_id, e.responsavel, e.observacao, e.atendimento_id,
                   a.numero_curto, a.conversa_id, cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
             WHERE e.id = %s
            """,
            (UUID(escalada_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        # Roteamento por owner (UX §9.6): escalada owner=Fernando (jailbreak/política/exaustão) não
        # vai pro grupo da modelo — é decisão do Operador e vive no painel/fila no P0. A exceção é o
        # lembrete-sem-resposta, que segue na mesma thread do Lembrete de fechamento. Sai sem gravar
        # card_message_id; a reconciliação espelha o mesmo filtro para não reprocessar em loop.
        if not card_escalada_vai_ao_grupo(e["responsavel"], e["observacao"]):
            return

        rotulo = rotulo_tipo_escalada(TipoEscalada(e["tipo"])) if e["tipo"] else "Handoff"
        texto = render_card(
            "escalada",
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            tipo_rotulo=rotulo,
            resumo_operacional=e["resumo_operacional"],
            acao_esperada=e["acao_esperada"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=e["evolution_instance_id"],
                remote_jid=e["coordenacao_chat_id"],
                texto=texto,
                contexto="grupo_coordenacao",
                tipo="card",
                atendimento_id=e["atendimento_id"],
                conversa_id=e["conversa_id"],
            )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, UUID(escalada_id)),
            )


async def _card_pix(
    ctx: dict[str, Any],
    *,
    atendimento_id: str,
    comprovante_id: str,
    **_: Any,
) -> None:
    """Card de comprovante Pix no grupo de Coordenação (06 §2.5).

    `tipo='pix_validado'` e `tipo='pix_em_revisao'` partilham o mesmo renderer: o template
    diferencia pela presenca de `motivo_em_revisao` (sinaliza a duvidez para a modelo decidir).
    Externo: card "saída confirmada" (atendimento ja `Confirmado`; Pix nunca trava, 01 §6.1).
    Remoto (ADR 0029): template proprio `pix_remoto` — o Pix e o pagamento da chamada, sem
    "saída"/Uber/endereco e sem transicao. Idempotência por owner: so envia se
    `comprovantes_pix.card_message_id IS NULL`.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT cp.card_message_id,
                   cp.decisao_pipeline::text AS decisao_pipeline,
                   cp.motivo_em_revisao,
                   cp.valor_extraido,
                   a.numero_curto, a.endereco, a.valor_acordado, a.conversa_id,
                   a.tipo_atendimento::text AS tipo_atendimento,
                   a.estado::text AS estado,
                   (b.inicio AT TIME ZONE 'America/Sao_Paulo') AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.comprovantes_pix cp
              JOIN barravips.atendimentos a ON a.id = cp.atendimento_id
              JOIN barravips.modelos      mo ON mo.id = a.modelo_id
              JOIN barravips.clientes     cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE cp.id = %s
            """,
            (UUID(comprovante_id),),
        )
        cp = await res.fetchone()
        if not cp or cp["card_message_id"]:
            return  # idempotência por owner: card já enviado

        # ATENDIMENTO TERMINAL: nao mande a modelo sair para um encontro que ja aconteceu.
        # Corrida rara mas real: o comprovante chega, o vision roda, e nesse meio-tempo o
        # atendimento e fechado (`finalizado` no grupo) ou morto por timeout. O card "saída
        # confirmada" chegaria depois do fato. Espelha a supressao que o caminho do painel ja
        # faz em `dominio/pix/routes.py` (aprovar da fila de revisao): decidir o COMPROVANTE e
        # decidir o ATENDIMENTO sao coisas separadas. O comprovante segue gravado (auditoria);
        # so o card e' suprimido. Sem marcar `card_message_id`: nao ha reconciliacao varrendo
        # `comprovantes_pix`, entao nada retenta em loop.
        if cp["estado"] in ESTADOS_TERMINAIS:
            logger.info(
                "card_pix_suprimido_atendimento_terminal",
                extra={"atendimento_id": atendimento_id, "estado": cp["estado"]},
            )
            return

        texto = render_card(
            "pix_remoto" if cp["tipo_atendimento"] == "remoto" else "pix",
            numero_curto=cp["numero_curto"],
            cliente_nome=cp["cliente_nome"] or "cliente",
            endereco=cp["endereco"],
            horario=cp["bloqueio_inicio"],
            valor_acordado=cp["valor_acordado"],
            valor_extraido=cp["valor_extraido"],
            decisao=cp["decisao_pipeline"],
            motivo_em_revisao=cp["motivo_em_revisao"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=cp["evolution_instance_id"],
                remote_jid=cp["coordenacao_chat_id"],
                texto=texto,
                contexto="grupo_coordenacao",
                tipo="card",
                atendimento_id=UUID(atendimento_id),
                conversa_id=cp["conversa_id"],
            )
            await conn.execute(
                "UPDATE barravips.comprovantes_pix SET card_message_id = %s WHERE id = %s",
                (mid, UUID(comprovante_id)),
            )


async def _card_chegada(ctx: dict[str, Any], *, atendimento_id: str, **_: Any) -> None:
    """Card "cliente chegou" no grupo de Coordenação (06 §4).

    Anexa a foto de portaria do cliente (presigned URL do MinIO, TTL 30min) — a
    modelo precisa conferir antes de abrir a porta (CONTEXT.md "Foto de portaria").
    Idempotência por owner: `handoff_foto_portaria_ia` ja criou uma escalada
    tipo='foto_portaria' responsavel='modelo' para hospedar o `card_message_id`;
    o renderer le a foto da mensagem mais recente tipo='imagem' do atendimento
    (a entrada que disparou o handoff, gravada pelo webhook). POST + UPDATE
    na MESMA transacao (espelha _card_escalada/_card_pix).
    """
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.id AS escalada_id, e.card_message_id,
                   a.numero_curto, a.endereco, a.conversa_id,
                   (b.inicio AT TIME ZONE 'America/Sao_Paulo') AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id,
                   foto.media_object_key AS foto_object_key
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos      mo ON mo.id = a.modelo_id
              JOIN barravips.clientes     cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
              LEFT JOIN LATERAL (
                  SELECT media_object_key
                    FROM barravips.mensagens
                   WHERE conversa_id = a.conversa_id
                     AND tipo = 'imagem'
                     AND direcao = 'cliente'
                     AND media_object_key IS NOT NULL
                   ORDER BY created_at DESC
                   LIMIT 1
              ) foto ON true
             WHERE e.atendimento_id = %s AND e.tipo = 'foto_portaria'
             ORDER BY e.aberta_em DESC
             LIMIT 1
            """,
            (UUID(atendimento_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        texto = render_card(
            "chegada",
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            endereco=e["endereco"],
            horario=e["bloqueio_inicio"],
        )

        url = (
            minio.presigned_get_object(
                ctx["settings"].minio_bucket_media,
                e["foto_object_key"],
                expires=timedelta(minutes=30),
            )
            if e["foto_object_key"]
            else None
        )

        async with conn.transaction():
            if url:
                mid = await evolution.enviar_midia(
                    conn=conn,
                    instance_id=e["evolution_instance_id"],
                    remote_jid=e["coordenacao_chat_id"],
                    url=url,
                    caption=texto,
                    media_type="foto",
                    contexto="grupo_coordenacao",
                    tipo="card",
                    atendimento_id=UUID(atendimento_id),
                    conversa_id=e["conversa_id"],
                )
            else:
                # Defesa: foto nao foi gravada (caso raro); manda so o texto para a modelo
                # nao perder o card "cliente chegou".
                mid = await evolution.enviar_texto(
                    conn=conn,
                    instance_id=e["evolution_instance_id"],
                    remote_jid=e["coordenacao_chat_id"],
                    texto=texto,
                    contexto="grupo_coordenacao",
                    tipo="card",
                    atendimento_id=UUID(atendimento_id),
                    conversa_id=e["conversa_id"],
                )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, e["escalada_id"]),
            )


# Escalada owner=modelo cujo card próprio é um momento "go-time" (não Handoff): tipo → template.
# A escalada (criada por timeouts.confirmar_em_execucao na hora do encontro) só hospeda o
# card_message_id; sem isto cairia no card genérico 🔔 escalada (reconciliacao._CARD_POR_TIPO).
_CARD_POR_TIPO_GO_TIME: dict[str, str] = {
    "video_chamada": "video_chamada",
}


async def _card_go_time(ctx: dict[str, Any], *, escalada_id: str, **_: Any) -> None:
    """Card "go-time" de vídeo chamada (🎥) no grupo de Coordenação (ADR 0021).

    Não é Handoff: o gatilho é "chegou a hora", como 🚪 chegada / ✅ saída confirmada. A escalada
    owner=modelo tipo='video_chamada' só hospeda o `card_message_id`. Idempotência por owner
    (= `_card_escalada`): só envia se `card_message_id IS NULL`; POST + UPDATE na MESMA
    transação. O template sai de `_CARD_POR_TIPO_GO_TIME[tipo]`.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.tipo::text AS tipo, e.card_message_id, e.atendimento_id,
                   a.numero_curto, a.endereco, a.conversa_id,
                   a.pix_status::text AS pix_status,
                   (b.inicio AT TIME ZONE 'America/Sao_Paulo') AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos      mo ON mo.id = a.modelo_id
              JOIN barravips.clientes     cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE e.id = %s
            """,
            (UUID(escalada_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        texto = render_card(
            _CARD_POR_TIPO_GO_TIME[e["tipo"]],
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            endereco=e["endereco"],
            horario=e["bloqueio_inicio"],
            pix_status=e["pix_status"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=e["evolution_instance_id"],
                remote_jid=e["coordenacao_chat_id"],
                texto=texto,
                contexto="grupo_coordenacao",
                tipo="card",
                atendimento_id=e["atendimento_id"],
                conversa_id=e["conversa_id"],
            )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, UUID(escalada_id)),
            )


async def _card_aviso_saida(ctx: dict[str, Any], *, atendimento_id: str, **_: Any) -> None:
    """Card "cliente saiu de casa" no grupo de Coordenação (06 §5).

    Sem owner (aviso_saida nao tem escalada — emenda §0 item 8): idempotencia por
    SETNX `card:aviso_saida:{atendimento_id}` com TTL 24h. Se a key ja existe,
    retorna sem enviar (replay do ARQ ou segundo "to indo" do mesmo cliente).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    evolution: EvolutionClient = ctx["evolution"]

    chave = f"card:aviso_saida:{atendimento_id}"
    if not await redis.set(chave, "1", ex=86400, nx=True):
        return  # ja enviado: replay/segundo aviso do mesmo cliente

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT a.numero_curto, a.conversa_id,
                   (b.inicio AT TIME ZONE 'America/Sao_Paulo') AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.atendimentos a
              JOIN barravips.modelos  mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE a.id = %s
            """,
            (UUID(atendimento_id),),
        )
        a = await res.fetchone()
        if not a:
            return

        texto = render_card(
            "aviso_saida",
            numero_curto=a["numero_curto"],
            cliente_nome=a["cliente_nome"] or "cliente",
            horario=a["bloqueio_inicio"],
        )
        await evolution.enviar_texto(
            conn=conn,
            instance_id=a["evolution_instance_id"],
            remote_jid=a["coordenacao_chat_id"],
            texto=texto,
            contexto="grupo_coordenacao",
            tipo="card",
            atendimento_id=UUID(atendimento_id),
            conversa_id=a["conversa_id"],
        )


async def _card_loc_pin(ctx: dict[str, Any], *, atendimento_id: str, **_: Any) -> None:
    """Pin do ponto de encontro, enviado ao CLIENTE quando o interno é reservado (04 §3.1).

    O ÚNICO renderer do `_RENDER_CARD` que fala com o cliente e não com o grupo de Coordenação — ele
    está aqui porque compartilha a mecânica (job ARQ pós-commit, idempotência por owner, bypass da
    humanização), não a audiência. Um pin é dado estruturado: abre o mapa no aparelho dele, e a IA
    não expressa isso como texto, então quem despacha é o sistema.

    Ficou como `NotImplementedError` desde o M3d, e nesse período `registrar_extracao` deixou de
    enfileirar o job para não queimar as 5 tentativas do ARQ contra um renderer morto — o efeito
    líquido é que `enviar_pin` era setado pelo domínio e ninguém consumia: o cliente do atendimento
    interno nunca recebeu o ponto de encontro como localização. Os dois lados voltam juntos.

    Idempotência por owner igual à do `_card_aviso_saida`: SETNX com TTL de 24h. Cobre o replay do
    ARQ e o re-percorrer da transição (o domínio pode sinalizar `enviar_pin` de novo se o
    atendimento voltar a Aguardando_confirmacao). A marca é armada só depois de a linha ser lida e
    validada, e desfeita se o envio falhar — quem não entregou o pin não gasta a chave.

    Sem lat/long no cadastro, sai sem enviar: o CHECK do `0028_modelos_endereco_geo` garante que
    latitude e longitude são NULL juntas, e mandar um pin em (0,0) seria pior que não mandar. O
    endereço em texto continua chegando pela fala da IA.
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    evolution: EvolutionClient = ctx["evolution"]

    chave = f"card:loc_pin:{atendimento_id}"

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT c.evolution_chat_id, a.conversa_id,
                   mo.nome AS modelo_nome, mo.nome_local, mo.latitude, mo.longitude,
                   mo.endereco_formatado, mo.evolution_instance_id
              FROM barravips.atendimentos a
              JOIN barravips.modelos   mo ON mo.id = a.modelo_id
              JOIN barravips.conversas c  ON c.id = a.conversa_id
             WHERE a.id = %s
            """,
            (UUID(atendimento_id),),
        )
        a = await res.fetchone()
        if not a:
            return
        if a["latitude"] is None or a["longitude"] is None:
            logger.warning(
                "card_loc_pin_sem_geo atendimento_id=%s (modelo sem latitude/longitude)",
                atendimento_id,
            )
            return

        # SETNX DEPOIS de carregar e validar a linha, e nao no inicio do job: a marca so pode ser
        # gasta por uma tentativa que de fato chegou ao envio. Armada antes, um erro transitorio de
        # banco no SELECT acima deixava a chave de pe por 24h e todo retry do ARQ voltava MUDO, e os
        # dois returns acima (atendimento sumido, modelo ainda sem lat/long) tambem a consumiam — a
        # modelo que ganha geo no cadastro depois nunca mais receberia o pin.
        if not await redis.set(chave, "1", ex=86400, nx=True):
            return  # ja enviado: replay do ARQ ou re-transicao do atendimento

        try:
            await evolution.enviar_localizacao(
                conn=conn,
                instance_id=a["evolution_instance_id"],
                remote_jid=a["evolution_chat_id"],
                latitude=float(a["latitude"]),
                longitude=float(a["longitude"]),
                # Rotulo do balao: o nome do local quando a modelo o cadastrou, senao o nome dela.
                # NUNCA a unidade (apartamento/quarto) — e a mesma regra do `aup_saida.md`, e
                # `nome_local` e campo de predio/hotel, nao de unidade.
                nome=a["nome_local"] or a["modelo_nome"],
                endereco=a["endereco_formatado"] or "",
                # Vai para a CONVERSA do cliente, e o tipo e o de saida da IA —
                # `envios_evolution.tipo` e um CHECK ('ia','card','confirmacao','erro_comando',
                # 'midia') e 'card' e reservado ao grupo de Coordenacao.
                contexto="conversa_cliente",
                tipo="ia",
                atendimento_id=UUID(atendimento_id),
                conversa_id=a["conversa_id"],
            )
        except Exception:
            # O SETNX marca "enviado" ANTES do envio; sem isto, uma falha da Evolution deixaria a
            # chave armada por 24h e todo replay (ARQ ou re-transicao) retornaria mudo — o cliente
            # ficaria sem o ponto de encontro sem nenhum sinal, e nao ha reconciliador para este
            # tipo de card (`reconciliar_cards_escalada` cobre so escalada). Desfeita a marca, o
            # SETNX volta a proteger apenas o replay do SUCESSO. Junto com o adiamento do SETNX
            # acima, o invariante fica completo: NENHUM caminho que nao entregou o pin gasta a
            # chave.
            await redis.delete(chave)
            raise


async def _card_parceira(ctx: dict[str, Any], *, atendimento_id: str, **_: Any) -> None:
    """Card NÃO-BLOQUEANTE da dupla vendida (fluxo B, ADR-0042).

    A modelo do canal fechou o encontro com a parceira SOZINHA — sem escalada, sem esperar. A
    parceira pode estar `inativa` e sem disponibilidade cadastrada: este card só PEDE ao Fernando
    que a confirme, e a ausência de resposta não desfaz nada. Por isso não abre escalada, não pausa
    a IA e não muda estado.

    Idempotência por owner: o carimbo `parceira_dupla_em` já é first-write-wins, e o `_job_id`
    estático do enqueue (coordenador) deduplica o replay do turno.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT a.numero_curto, a.conversa_id, a.valor_acordado,
                   a.data_desejada, a.horario_desejado,
                   cl.nome AS cliente_nome,
                   mo.nome AS modelo_nome, mo.coordenacao_chat_id, mo.evolution_instance_id,
                   pa.nome AS parceira_nome, pa.status::text AS parceira_status
              FROM barravips.atendimentos a
              JOIN barravips.modelos  mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
              JOIN barravips.modelo_parcerias p ON p.modelo_id = a.modelo_id AND p.ativo
              JOIN barravips.modelos  pa ON pa.id = p.parceira_id
             WHERE a.id = %s
            """,
            (UUID(atendimento_id),),
        )
        row = await res.fetchone()
        if not row:
            # Parceria desligada entre a venda e o card: nada a confirmar, e inventar um nome aqui
            # seria pior que o silêncio. O carimbo do atendimento segue como rastro.
            logger.warning("card_parceira_sem_parceria atendimento_id=%s", atendimento_id)
            return

        texto = render_card(
            "parceira",
            numero_curto=row["numero_curto"],
            cliente_nome=row["cliente_nome"] or "cliente",
            modelo_nome=row["modelo_nome"],
            parceira_nome=row["parceira_nome"],
            parceira_status=row["parceira_status"],
            valor_acordado=brl(row["valor_acordado"]) if row["valor_acordado"] else None,
            data_desejada=row["data_desejada"],
            horario_desejado=row["horario_desejado"],
        )
        await evolution.enviar_texto(
            conn=conn,
            instance_id=row["evolution_instance_id"],
            remote_jid=row["coordenacao_chat_id"],
            texto=texto,
            contexto="grupo_coordenacao",
            tipo="card",
            atendimento_id=UUID(atendimento_id),
            conversa_id=row["conversa_id"],
        )


_RENDER_CARD: dict[str, Callable[..., Awaitable[None]]] = {
    "escalada": _card_escalada,
    "parceira_a_confirmar": _card_parceira,
    "pix_validado": _card_pix,
    "pix_em_revisao": _card_pix,
    "chegada": _card_chegada,
    "video_chamada": _card_go_time,
    "aviso_saida": _card_aviso_saida,
    "loc_pin": _card_loc_pin,
}


async def enviar_card(ctx: dict[str, Any], *, tipo: str, **kw: Any) -> None:
    """Job ARQ: envia um card no grupo de Coordenação direto pelo Evolution, sem passar pela
    humanização (05 §6). Dispatch por `tipo`; cada renderer é idempotente por owner."""
    render = _RENDER_CARD[tipo]
    try:
        await render(ctx, **kw)
    except Exception:
        # Mesmo racional do enviar_turno: o ARQ NAO retenta excecao comum, e o max_tries de
        # settings.py (REL-03) so vale se a falha transitoria virar `Retry` explicito. A
        # idempotencia por owner (card_message_id / SETNX) cobre o re-percorrer.
        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", MAX_TRIES_ENVIO)
        if job_try < max_tries:
            logger.warning(
                "card_falha_transitoria tipo=%s request_id=%s job_try=%s/%s",
                tipo,
                ctx.get("job_id"),
                job_try,
                max_tries,
                exc_info=True,
            )
            raise Retry(defer=10 * job_try) from None
        logger.exception("card_falha_final tipo=%s request_id=%s", tipo, ctx.get("job_id"))
        raise


# --- Humanização: job único `enviar_turno` por turno (05 §1/§4) --------------
# Read receipt + reading delay, chunks de texto e depois mídias, EM ORDEM, com cancel-on-
# new-message (turno não-crítico) e dedupe mark-after-send. Um único job percorre o turno em
# laço — jobs por chunk rodariam concorrentes (`max_jobs`) e não garantiriam ordem (05 §1).


def calcular_typing_ms(texto: str) -> int:
    """Typing proporcional ao tamanho da bolha DE SAÍDA, com piso/teto e jitter (05 §4.1).

    Mudança 2026-06-18: era random plano 0.8-2.0s. A literatura de humanização (Gnewuch et al.,
    "Faster is Not Always Better") manda escalar o delay pela complexidade da RESPOSTA, não só do
    inbound (ver calcular_reading_delay_ms); e o tell mais detectável é uma bolha longa que aparece
    após ~1s de 'digitando…'. Agora a duração cresce com len(texto); o random vira só jitter.

    Como o reading delay, é DELIBERADAMENTE comprimido (~22 char/s, super-humano) para caber no
    job_timeout de 90s com até 6 chunks — 200 cpm humanos levariam ~60s numa bolha de 200 chars e
    leriam como travado. O que vende não é a velocidade absoluta bater com a humana, e sim a
    proporcionalidade monotônica: bolha maior, 'digitando…' visivelmente maior.

    Níveis (2026-06-18): piso 1.0s, +45ms/char, teto 5.5s. Calibrado pra que a bolha típica do
    corpus (~15 chars) some typing+pausa ≈ 4s, em cima do gap inter-bolha humano (p50≈4s). NÃO
    subir mais: o estudo de typing humanizado (Zhou & Hu, CUI '24) mostra que pausa pura, sem o
    self-editing visível que o WhatsApp não permite mostrar, tende a ler como 'robótico/lento'."""
    base_ms = 1000 + len(texto) * 45
    jitter_ms = random.randint(-150, 350)  # noqa: S311 -- jitter de humanização, nao cripto
    return max(1000, min(base_ms + jitter_ms, 5500))


def calcular_pausa_ms() -> int:
    """Pausa entre chunks: 800-2800ms uniform (05 §4.1).

    Calibrado com o corpus do Vendedor (mineração 2026-06-17, scripts/eval_corpus/
    mineracao_humanizacao.md): o gap real entre bolhas consecutivas dele é p50≈4s / p75≈9s.
    Somado ao composing (0.8-2s), a pausa de 0.8-2.8s coloca a mediana entre-bolhas perto dos 4s
    humanos sem estourar o job_timeout de 90s no teto de 6 chunks."""
    return random.randint(800, 2800)  # noqa: S311 -- jitter de humanização, nao cripto


def calcular_reading_delay_ms(chars_inbound: int) -> int:
    """Reading delay antes do PRIMEIRO 'composing' (humano lê → digita → responde), proporcional
    ao inbound do turno com piso e teto (05 §4.1).

    Calibrado com o corpus (mineração 2026-06-17): a latência real da 1ª resposta do Vendedor é
    p25≈14s / p50≈40s. Subimos piso e teto (1.5s / 9s) para sair do "instantâneo demais", mas
    ficamos DELIBERADAMENTE abaixo da mediana humana — 40s de silêncio num bot que acabou de ser
    acionado lê como travado, não como humano, e o teto protege o job_timeout de 90s."""
    return min(1500 + chars_inbound * 20, 9000)


def amostrar_defer_humano_s(*, chars_inbound: int, elapsed_s: float) -> int:
    """Defer 'humano' do job enviar_turno (05 §4.1): aproxima a latência de 1ª resposta do
    Vendedor (corpus 2026-06-17: p25≈14s / p50≈40s, cauda log-normal pesada) adiando o JOB via
    _defer_by — fora do job_timeout, sem segurar slot do worker. O grafo/cards/Pix já rodaram;
    só a bolha ao cliente espera, e o cancel-on-new-message segue valendo na hora do fire.

    A amostra é a latência TOTAL alvo desde a mensagem do cliente; desconta o que o pipeline já
    gastou (debounce ~12s + fila + grafo, via elapsed_s) e o reading delay que o job ainda vai
    dormir — com isso boa parte dos turnos sai com defer 0 (= comportamento atual, o piso).
    Flag OFF (default) = 0. Teto em settings (hard bound 300s, ver envio_delay_humano_teto_s)."""
    s = get_settings()
    if not s.envio_delay_humano_habilitado:
        return 0
    alvo = random.lognormvariate(
        math.log(s.envio_delay_humano_mediana_s), s.envio_delay_humano_sigma
    )
    alvo = min(alvo, float(s.envio_delay_humano_teto_s))
    ja_gasto = elapsed_s + calcular_reading_delay_ms(chars_inbound) / 1000
    return max(0, round(alvo - ja_gasto))


def _redis_eq(valor: object, esperado: str) -> bool:
    """Compara um valor lido do Redis com uma str. A ArqRedis injetada em `ctx['redis']` não usa
    `decode_responses`, então `get` devolve bytes — decodifica antes (igual a core/redis.py:59)."""
    if valor is None:
        return False
    if isinstance(valor, bytes):
        valor = valor.decode()
    return valor == esperado


async def _carregar_destino(pool: AsyncConnectionPool[Any], conversa_id: str) -> dict[str, Any]:
    """Destino do envio: instância da modelo, chat do cliente e o atendimento aberto da conversa.
    `evolution_instance_id` vive em `modelos`; `evolution_chat_id` em `conversas`. Traz junto os
    campos de lugar do cadastro (mesma leitura) p/ o carimbo A2 de `endereco_enviado_em`."""
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT mo.evolution_instance_id AS evolution_instance_id,
                   mo.endereco_formatado    AS endereco_formatado,
                   mo.nome_local            AS nome_local,
                   mo.localizacao_operacional AS localizacao_operacional,
                   c.evolution_chat_id      AS evolution_chat_id,
                   a.id                      AS atendimento_id,
                   COALESCE(a.ia_pausada, false) AS ia_pausada
              FROM barravips.conversas c
              JOIN barravips.modelos mo ON mo.id = c.modelo_id
              LEFT JOIN LATERAL (
                  SELECT id, ia_pausada
                    FROM barravips.atendimentos
                   WHERE conversa_id = c.id AND estado NOT IN ('Fechado', 'Perdido')
                   ORDER BY created_at DESC
                   LIMIT 1
              ) a ON true
             WHERE c.id = %s
            """,
            (UUID(conversa_id),),
        )
        row = await res.fetchone()
    if row is None:
        raise ErroDominio("CONVERSA_NAO_ENCONTRADA", "Conversa nao encontrada.", status_code=404)
    return cast(dict[str, Any], row)


async def _ia_pausada_agora(pool: AsyncConnectionPool[Any], atendimento_id: UUID | None) -> bool:
    """Releitura pontual de `atendimentos.ia_pausada` (point-read por PK).

    O gate de pausa do fire (`enviar_turno`) precisa ser reavaliado DENTRO do laço de bolhas: um
    turno de 3 bolhas leva 15-30s (presence + typing + jitter por bolha) e os pipelines de handoff
    (foto de portaria, Pix, pausa manual) podem pausar a IA no meio disso — o cancel-on-new-message
    não cobre, porque nenhum deles toca `turno_atual`.

    Por que BANCO e não Redis: o cancel-on-new-message só funciona porque o coordenador ESCREVE
    `turno_atual`; nenhum pipeline de handoff escreve nada no Redis (verificado em workers/media.py,
    workers/pix.py e dominio/escaladas/service.py — todos só commitam no Postgres). Um flag Redis
    exigiria mudar esses escritores; enquanto isso não existir, o Postgres é a única fonte.

    Custo: um SELECT por PK (índice primário, sem join — `_carregar_destino` é o de 3 tabelas),
    no máximo uma vez por bolha (teto de 6 por turno, MAX_CHARS/chunking) e só nos turnos
    não-críticos que não abriram a própria pausa. Contra um sleep de 1-5,5s por bolha, é ruído.
    """
    if atendimento_id is None:
        return False
    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
            (atendimento_id,),
        )
        row = await res.fetchone()
    return bool(row and row["ia_pausada"])


async def _atendimento_para_escalada(
    pool: AsyncConnectionPool[Any], conversa_id: str
) -> UUID | None:
    """Último atendimento da conversa em QUALQUER estado — fallback do handoff de exaustão
    crítica (REL-08). `_carregar_destino` só resolve atendimento não-terminal; se o aberto virou
    `Fechado`/`Perdido` entre o enqueue e a retry final, o handoff (`escaladas.atendimento_id`
    NOT NULL) precisa de um atendimento mesmo terminal, senão o efeito crítico encerra em silêncio."""
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT id
              FROM barravips.atendimentos
             WHERE conversa_id = %s
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (UUID(conversa_id),),
        )
        row = await res.fetchone()
    return cast("UUID | None", row["id"]) if row else None


# --- Rede final de saída (SEC-OUT-01 / SEC-PII-02) ----------------------------
# O output_guard (ADR 0016) é nó do grafo e só vê o caminho do LLM; os despachos canned
# (transcrição falhou) e o reengajamento enfileiram `enviar_turno` direto, pulando-o. Esta rede
# roda no `enviar_turno` e vale para TODOS os caminhos: bloqueia bolha que admite ser IA e redige
# por eco a PII do cliente. Lógica pura em `_saida_guard`; aqui ficam o I/O e a decisão.

_ACAO_ASSUMIR = "Assumir a conversa com o cliente."
_RESUMO_ENVIO_LEAK = (
    "Rede de saída barrou a bolha (auto-referência de IA detectada antes do envio)."
)
_RESUMO_ENVIO_PLACEHOLDER = (
    "Rede de saída barrou a bolha (placeholder de ensino não-substituído, ex. {valor}, "
    "antes do envio). Provável cotação sem o número — refaça a fala ao cliente."
)


async def _pii_cliente_recente(pool: AsyncConnectionPool[Any], conversa_id: str) -> set[str]:
    """Tokens de PII (CPF/RG/telefone) do inbound recente do cliente — base do gate de eco. Não
    filtra por tipo='texto': a transcrição de áudio também preenche `conteudo` (eco via STT)."""
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT conteudo FROM barravips.mensagens
             WHERE conversa_id = %s AND direcao = 'cliente' AND conteudo IS NOT NULL
             ORDER BY created_at DESC
             LIMIT 20
            """,
            (UUID(conversa_id),),
        )
        rows = await res.fetchall()
    tokens: set[str] = set()
    for r in rows:
        tokens |= extrair_tokens_pii(r["conteudo"] or "")
    return tokens


async def _bloquear_envio(
    pool: AsyncConnectionPool[Any],
    conversa_id: str,
    conv: dict[str, Any],
    *,
    resultado: str,
    resumo: str,
    observacao: str,
) -> None:
    """Bloqueia o turno na rede de saída: conta a métrica, abre handoff p/ Fernando (default seguro)
    e contabiliza a escalada (bucket=defesa). Sem atendimento_id (canned/reengajamento) só loga — a
    bolha já não sai. Fonte única do bloqueio das defesas A1 (leak de IA) e A1.5 (placeholder)."""
    ENVIO_RESULTADO.labels(resultado).inc()
    atend = conv.get("atendimento_id")
    if atend is None:
        logger.warning(
            "envio_guard barrou (%s) sem atendimento_id conversa_id=%s", observacao, conversa_id
        )
        return
    async with pool.connection() as conn:
        fase = await fase_do_atendimento(conn, atend)
        await abrir_handoff(
            conn,
            atendimento_id=atend,
            responsavel="Fernando",
            tipo=TipoEscalada.comportamento_atipico,
            resumo_operacional=resumo,
            acao_esperada=_ACAO_ASSUMIR,
            origem="agente",
            autor="sistema",
            observacao=observacao,
        )
    AGENTE_ESCALADA.labels(mapear_bucket(observacao), observacao, fase).inc()


async def _aplicar_saida_guard(
    pool: AsyncConnectionPool[Any],
    conversa_id: str,
    conv: dict[str, Any],
    chunks: list[str],
    quote_msg_ids: list[str | None],
    quote_textos: list[str | None],
) -> tuple[list[str], list[str | None], list[str | None]] | None:
    """Rede final antes da bolha. Devolve `(chunks, quote_msg_ids, quote_textos)` — os chunks com PII
    do cliente redigida por eco (se houver) e as listas de quote REALINHADAS ao descarte de bolha —
    ou None se o turno deve ser BLOQUEADO (vazamento de IA → handoff + bolha não sai).

    As três listas entram e saem PARALELAS: `normalizar_emoji_voz` pode descartar uma bolha vazia
    (era só emoji), e sem realinhar o quote sairia na bolha errada (ou sumiria)."""
    # Scrub anti-vazamento do marcador de reply [quote] (SEC-OUT): rede DURA, roda em TODOS os
    # caminhos e antes de qualquer flag — o marker é sintaxe interna que denuncia a IA e não pode
    # sair. O chunking já extrai o marker bem-formado no início da bolha; aqui pegamos o residual
    # (malformado/fora de posição a 0.7). Scrub por-bolha; bolha que ficou vazia é descartada com o
    # quote realinhado pelo ÍNDICE ORIGINAL, igual ao filtro de emoji abaixo.
    limpos: list[tuple[int, str]] = []
    for i, chunk in enumerate(chunks):
        novo, removeu = remover_marcador_quote(chunk)
        if removeu:
            QUOTE_MARCADOR_VAZADO.inc()
        if novo:
            limpos.append((i, novo))
    chunks = [c for _, c in limpos]
    quote_msg_ids = [quote_msg_ids[i] for i, _ in limpos]
    quote_textos = [quote_textos[i] for i, _ in limpos]
    # Camada de voz (independente do envio_guard de segurança): crava o whitelist de emoji {🥰,😊},
    # seca a venda e troca travessão por vírgula. Aplica em TODOS os caminhos (canned/reengajamento
    # inclusive), antes do resto.
    if get_settings().filtro_emoji_habilitado:
        # descarta bolha-só-emoji mantendo os quotes casados pelo ÍNDICE ORIGINAL da bolha.
        mantidos = normalizar_emoji_voz_indexado(chunks)
        chunks = [c for _, c in mantidos]
        quote_msg_ids = [quote_msg_ids[i] for i, _ in mantidos]
        quote_textos = [quote_textos[i] for i, _ in mantidos]
    if get_settings().filtro_travessao_habilitado:
        chunks = normalizar_travessao(chunks)  # transform por-bolha, preserva a contagem
    if get_settings().filtro_vocativo_habilitado:
        chunks = normalizar_vocativo_voz(chunks)  # transform por-bolha, preserva a contagem
    if get_settings().filtro_interrogacao_habilitado:
        # por ÚLTIMO entre as camadas de voz: o filtro de vocativo pode reescrever o fim da bolha,
        # e o "?" tem que ser a palavra final do que sai.
        chunks = restaurar_interrogacao_proposta(chunks)  # transform por-bolha, preserva a contagem
    if not get_settings().envio_guard_habilitado:
        return chunks, quote_msg_ids, quote_textos
    texto = "\n".join(chunks)

    # A1: auto-referência de IA → bloqueia o turno inteiro e escala (default seguro, A1).
    if tem_marcador_ia(texto):
        await _bloquear_envio(
            pool,
            conversa_id,
            conv,
            resultado="bloqueado_leak",
            resumo=_RESUMO_ENVIO_LEAK,
            observacao="envio_leak",
        )
        return None

    # A1.5: placeholder de ensino não-substituído ({valor}, [insira a rua]) → cotação QUEBRADA.
    # Bloqueia+escala como o A1: silenciar o token deixaria a bolha sem o dado (preço sem número),
    # então é melhor handoff p/ Fernando refazer a fala do que mandar a cotação truncada.
    if tem_placeholder_eco(texto):
        await _bloquear_envio(
            pool,
            conversa_id,
            conv,
            resultado="bloqueado_placeholder",
            resumo=_RESUMO_ENVIO_PLACEHOLDER,
            observacao="envio_placeholder",
        )
        return None

    # A2: redação por eco. Pre-check barato — sem shape de PII na saída, nem consulta o inbound.
    if not extrair_tokens_pii(texto):
        return chunks, quote_msg_ids, quote_textos
    tokens_cliente = await _pii_cliente_recente(pool, conversa_id)
    if not tokens_cliente:
        return chunks, quote_msg_ids, quote_textos
    redigidos: list[str] = []
    for chunk in chunks:
        novo, tipos = redigir_pii_eco(chunk, tokens_cliente)
        redigidos.append(novo)
        for tipo in tipos:
            ENVIO_PII_REDIGIDA.labels(tipo).inc()
    return redigidos, quote_msg_ids, quote_textos


async def enviar_turno(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict[str, Any]],
    msg_ids_cliente: list[str],
    chars_inbound: int,
    critico: bool = False,
    quote_msg_ids: list[str | None] | None = None,
    quote_textos: list[str | None] | None = None,
    ignorar_pausa: bool = False,
    valor_dele_no_prompt: int | None = None,
) -> None:
    """Envia um turno chunk-by-chunk e depois as mídias (05 §4).

    `critico` vem no PAYLOAD do job (não do Redis, cujo TTL pode expirar antes da última retry
    com backoff): turno crítico (write tool com efeito) entrega tudo ignorando o cancel; falha
    final do job + crítico → `escalar_por_exaustao` (05 §7).

    `quote_msg_ids` (opcional) tem o mesmo tamanho de `chunks`; cada posição não-None faz a
    bolha sair com reply/quote àquela mensagem (Evolution v2.3.6 `quoted.key.id`). Default
    None preserva o comportamento dos call sites canned/reengajamento. `quote_textos` é paralelo
    e carrega o conteúdo da mensagem citada de cada bolha — vai no `quoted.message.conversation`
    para o balão de reply renderizar o texto; sem ele, o WhatsApp mostra a citação vazia
    (a Evolution não faz lookup pelo id, verificado 2026-05-30).

    `valor_dele_no_prompt` é o carimbo do `<valor_dele_serve>` deste turno (ADR-0040): o número que
    o sistema já provou ser DELE e caber em `[piso, mesa)`, e que o prompt mandou ela aceitar. Aqui
    ele vira venda gravada quando — e só quando — a bolha DESPACHADA de fato o diz (ver
    `gravar_valor_do_aceite`). `None` (default) nos call sites canned/reengajamento e em todo turno
    sem o bloco: o caminho não arma. Vem no PAYLOAD do job, como `critico`, e não de uma releitura:
    a decisão é sobre o prompt que a IA leu, e reavaliá-la aqui — depois de a extração já ter mexido
    em `valor_acordado`/`n_contrapropostas` — daria outra resposta sobre uma fala que já saiu.

    `ignorar_pausa` é do turno que ABRIU a pausa (bolha de espera antes do `escalar`): ele nasce
    com `ia_pausada=true` de propósito e não pode ser cancelado pelo gate de pausa abaixo. Quem
    decide isso é o coordenador, pelo rastro do turno (`pausa_aberta_por_este_turno`) — nunca pelo
    bit `ia_pausada` do banco, que é idêntico para a pausa aberta por um pipeline externo.
    """
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    if ctx.get("job_try", 1) > 1:
        ENVIO_RETRIES.inc()

    inicio = perf_counter()
    conv: dict[str, Any] | None = None
    try:
        conv = await _carregar_destino(pool, conversa_id)

        # Gate de pausa no FIRE (não só no despacho): com o defer humano o job dorme até ~90s, e
        # nesse intervalo um pipeline sem lock (Pix, foto de portaria, handoff manual) pode pausar
        # a IA — a modelo assume e a bolha da IA sairia por cima dela. O cancel-on-new-message não
        # cobre: esses pipelines não tocam `turno_atual`. Crítico entrega sempre (chave Pix), e o
        # turno que ABRIU a pausa passa por `ignorar_pausa`.
        #
        # O mesmo predicado é reavaliado A CADA BOLHA (ver `_ia_pausada_agora`): aqui ele só
        # responde "nunca ter começado"; o laço abaixo responde "parar antes da próxima". Uma
        # entrega pela metade é ruim, mas continuar despejando bolhas em cima da modelo que já
        # está atendendo o cliente é pior — e a bolha 1 já saiu, não dá para desenviar.
        checar_pausa = not critico and not ignorar_pausa
        if checar_pausa and conv["ia_pausada"]:
            logger.info("turno_cancelado_pausa turno_id=%s", turno_id)
            ENVIO_RESULTADO.labels("cancelado").inc()
            return

        # Materializa as listas de quote ao tamanho dos chunks (None-fill) ANTES do guard, para que
        # o descarte de bolha (emoji) as realinhe em conjunto e o loop indexe sem bounds-check.
        qids: list[str | None] = [
            quote_msg_ids[i] if quote_msg_ids and i < len(quote_msg_ids) else None
            for i in range(len(chunks))
        ]
        qtxt: list[str | None] = [
            quote_textos[i] if quote_textos and i < len(quote_textos) else None
            for i in range(len(chunks))
        ]

        # Rede final de saída (SEC-OUT-01/SEC-PII-02): cobre também os caminhos canned/reengajamento
        # que pulam o output_guard do grafo. Leak de IA → bloqueia o turno; PII do cliente → redige.
        guard = await _aplicar_saida_guard(pool, conversa_id, conv, chunks, qids, qtxt)
        if guard is None:
            return  # bolha barrada: handoff já aberto, nada sai (o finally observa a duração)
        chunks, qids, qtxt = guard

        conversa_uuid = UUID(conversa_id)

        # Veto da oferta da amiga, medido sobre o TURNO (não bolha a bolha): o trilho de escalada do
        # <composicoes> sai naturalmente em duas bolhas ("Tenho uma amiga sim amor" / "Deixa eu ver com
        # ela e já te retorno amor"). Chunk a chunk, a 1ª carimbaria a oferta que a 2ª desmente —
        # queimando um convite que ela nunca fez.
        escalou_amiga = contem_escalada_da_amiga("\n".join(chunks))

        # Mesmo motivo, para o contador de perguntas de horário: o turno canônico do
        # <conducao_da_venda> ("Consigo às 21h amor" / "ou prefere que horas ?") sai partido em
        # duas bolhas, e a 2ª sozinha contaria a pergunta que a 1ª já respondeu com um horário.
        # Por BOLHA e sem a duração da cotação (`contem_hora_na_mesa_no_turno`): medido sobre o
        # turno concatenado, o "1h" de "400 1h no meu local" vetava o contador em todo turno de
        # cotação e a disciplina nunca chegou a andar em prod (diagnóstico 11/08, P1-4c).
        propos_horario = contem_hora_na_mesa_no_turno(chunks)

        # Alguma bolha DESPACHADA disse o número dele (ADR-0040)? Medido sobre o turno, escrito
        # bolha a bolha — o aceite sai numa bolha só ("Tabom, 700 então") e o horário na seguinte.
        aceite_na_bolha = False

        # 0. read receipt + reading delay (lê antes de digitar, 05 §4.2). O membro "read" do set
        #    evita re-dormir o delay no retry; markAsRead em si já é idempotente. Roda ANTES do
        #    cancel: marcar lido é inócuo mesmo que o turno seja cancelado em seguida.
        if msg_ids_cliente and not await redis.sismember(f"enviados:{turno_id}", "read"):
            await evolution.marcar_lida(
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                message_ids=msg_ids_cliente,
            )
            await asyncio.sleep(calcular_reading_delay_ms(chars_inbound) / 1000)
            await redis.sadd(f"enviados:{turno_id}", "read")
            await redis.expire(f"enviados:{turno_id}", 600)

        for idx, conteudo in enumerate(chunks):
            # 1. cancel-on-new-message (turno crítico ignora o check, 05 §3)
            if not critico and not _redis_eq(
                await redis.get(f"turno_atual:{conversa_id}"), turno_id
            ):
                logger.info("turno_cancelado turno_id=%s idx=%s", turno_id, idx)
                ENVIO_RESULTADO.labels("cancelado").inc()
                return
            # 2. dedupe: retry do job re-percorre desde idx 0 e pula o que já entregou (05 §4.3)
            if await redis.sismember(f"enviados:{turno_id}", f"chunk:{idx}"):
                continue

            # 2.5 gate de pausa POR BOLHA: o `idx` anterior dormiu typing+jitter (1,8-8,3s) e o
            #     read receipt dormiu o reading delay antes do idx 0 — nesse tempo o handoff pode
            #     ter aberto. Depois do dedupe de propósito: bolha já entregue não precisa de
            #     query. Roda ANTES do presence, senão a modelo veria "digitando…" da IA por cima.
            if checar_pausa and await _ia_pausada_agora(pool, conv["atendimento_id"]):
                logger.info("turno_interrompido_pausa turno_id=%s idx=%s", turno_id, idx)
                ENVIO_RESULTADO.labels("cancelado").inc()
                return

            # 3. presence composing
            typing_ms = calcular_typing_ms(conteudo)
            await evolution.set_presence(
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                presence="composing",
                delay_ms=typing_ms,
            )
            await asyncio.sleep(typing_ms / 1000)

            # 4 + 5. POST (→ envios_evolution) e persistência em mensagens, na MESMA transação.
            # qids/qtxt já vêm alinhados a `chunks` e do mesmo tamanho (materializados pré-guard).
            quote_target = qids[idx]
            quote_target_texto = qtxt[idx]
            async with pool.connection() as conn, conn.transaction():
                mid = await evolution.enviar_texto(
                    conn=conn,
                    instance_id=conv["evolution_instance_id"],
                    remote_jid=conv["evolution_chat_id"],
                    texto=conteudo,
                    contexto="conversa_cliente",
                    tipo="ia",
                    atendimento_id=conv["atendimento_id"],
                    conversa_id=conversa_uuid,
                    quoted_message_id=quote_target,
                    quoted_text=quote_target_texto if quote_target else None,
                )
                cur = await conn.execute(
                    """
                    INSERT INTO barravips.mensagens
                      (conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
                    VALUES (%s, %s, 'ia', 'texto', %s, %s)
                    ON CONFLICT (evolution_message_id) DO NOTHING
                    RETURNING 1
                    """,
                    (conversa_uuid, conv["atendimento_id"], conteudo, mid),
                )
                # RETURNING + ON CONFLICT DO NOTHING: linha só volta quando a bolha foi de fato
                # inserida. Num retry (mesmo evolution_message_id) o conflito não retorna nada ->
                # não recarimba nada (idempotência do contador de contrapropostas).
                inseriu = await cur.fetchone() is not None
                # Carimbo determinístico da cotação (ADR 0022): na MESMA transação do envio,
                # ancora o reengajamento só pelo que de fato saiu. Idempotente (guard IS NULL +
                # estado) — repetir entre chunks/retries é no-op.
                if conv["atendimento_id"] is not None:
                    await carimbar_cotacao_por_texto_enviado(conn, conv["atendimento_id"], conteudo)
                # Flags de disciplina (padrão A2) carimbadas no write-time, na MESMA transação —
                # prepare_context lê a coluna em vez de reescanear as falas da IA por turno. Só na
                # 1ª inserção da bolha (`inseriu`): o contador não pode dobrar no retry. Detectores
                # de agente/_disciplina.py (mesma fonte que o read-time usa na janela).
                if inseriu and conv["atendimento_id"] is not None:
                    # INVARIANTE DA ESCADA (ADR-0031 / CONTEXT.md "Insistência depois da última
                    # rodada não gera nova oferta"): `n_contrapropostas` conta rodada JOGADA — bolha
                    # que de fato SAIU ao cliente —, nunca rodada rascunhada. Uma contraproposta
                    # zerada pelo `post_process` (escalada silenciosa), dropada pelo `output_guard`
                    # ou barrada pelo `_aplicar_saida_guard` nem chega aqui, e um replay do turno
                    # cai no `ON CONFLICT` (`inseriu=False`) — nos dois casos o contador NAO anda,
                    # e e isso que mantem honesto o "depois da ultima rodada" de quem le o contador.
                    # Quem consome isso sao DOIS leitores, e o segundo entrou na r3: a escada do
                    # `prepare_context` e o gate do piso em `dominio/atendimentos/service`, que
                    # desde `_insistiu_apos_a_escada` so escala `fora_de_oferta` com
                    # `n_contrapropostas >= 1` (na rodada 0 o valor baixo e descartado em silencio,
                    # com a escada intacta). E por isso que a regra deste site — so bolha que SAIU
                    # anda com o contador — deixou de ser so contabilidade da escada: e ela que
                    # separa "insistencia do cliente" de "rodada que o sistema nunca jogou", e uma
                    # contraproposta zerada contando aqui acordaria a modelo por insistencia que
                    # nao houve.
                    if contem_contraproposta(conteudo):
                        await incrementar_contrapropostas(conn, conv["atendimento_id"])
                    if not propos_horario and contem_pergunta_de_horario(conteudo):
                        await incrementar_perguntas_de_horario(conn, conv["atendimento_id"])
                    if contem_sondagem_dia(conteudo):
                        await marcar_dia_sondado(conn, conv["atendimento_id"])
                    if contem_endereco_de_encontro(
                        conteudo,
                        tokens_do_endereco(
                            conv["endereco_formatado"],
                            conv["nome_local"],
                            conv["localizacao_operacional"],
                        ),
                    ):
                        await marcar_endereco_enviado(conn, conv["atendimento_id"])
                    if not escalou_amiga and contem_oferta_da_amiga(conteudo):
                        await marcar_amiga_ofertada(conn, conv["atendimento_id"])
                    if contem_pedido_da_foto_de_portaria(conteudo):
                        await marcar_foto_portaria_pedida(conn, conv["atendimento_id"])
                    if contem_pergunta_do_motivo_do_resgate(conteudo):
                        await marcar_motivo_resgate_perguntado(conn, conv["atendimento_id"])
                    # O VALOR da venda pela mesma porta das flags (ADR-0040): a bolha já está
                    # despachada, e é ela que fecha em cima do número DELE. As duas pernas do
                    # predicado — o carimbo do `<valor_dele_serve>` (o sistema provou o número
                    # contra a tabela) e o número saindo como OFERTA nesta bolha — vivem no
                    # docstring de `gravar_valor_do_aceite`. Sem `valor_dele_no_prompt` (todos
                    # os call sites canned/reengajamento, e todo turno sem o bloco) isto nem
                    # arma: é `None` e o `if` cai fora antes de escanear preço nenhum.
                    if valor_dele_no_prompt is not None and valor_dele_no_prompt in (
                        precos_ofertados_na_fala(conteudo)
                    ):
                        aceite_na_bolha = True
                        logger.info(
                            "aceite_do_valor_na_bolha turno_id=%s atendimento_id=%s valor=%s",
                            turno_id,
                            conv["atendimento_id"],
                            valor_dele_no_prompt,
                        )
                        await gravar_valor_do_aceite(
                            conn, conv["atendimento_id"], valor_dele_no_prompt
                        )

            # 6. MARK-AFTER-SEND: só agora idx conta como entregue (05 §4.3)
            await redis.sadd(f"enviados:{turno_id}", f"chunk:{idx}")
            await redis.expire(f"enviados:{turno_id}", 600)

            # 7. jitter
            await asyncio.sleep(calcular_pausa_ms() / 1000)

        # O turno inteiro saiu: fecha o par do ADR-0040 (o `aceito` da decisão x a venda no banco).
        # Só depois do laço, e só quando o bloco de fato entrou no prompt — turno cancelado no meio
        # sai por `return` e não conta, porque a bolha do aceite pode não ter chegado a sair.
        if valor_dele_no_prompt is not None:
            AGENTE_ACEITE_GRAVADO.labels(
                "gravado" if aceite_na_bolha else "sem_numero_na_bolha"
            ).inc()

        if await _enviar_midias(
            ctx, conversa_id, turno_id, midias, conv, critico, chunks, checar_pausa
        ):
            ENVIO_RESULTADO.labels("ok").inc()
    except Exception:
        job_try = ctx.get("job_try", 1)
        # ARQ nao popula max_tries no ctx -> o fallback É o teto efetivo; tem de ser o mesmo
        # MAX_TRIES_ENVIO registrado em settings.py (REL-03), senao o dead-end nunca dispara.
        max_tries = ctx.get("max_tries", MAX_TRIES_ENVIO)
        if job_try < max_tries:
            # O ARQ NAO retenta excecao comum (so `Retry` explicito ou shutdown do worker) —
            # sem isto o job morria na 1a falha transitoria da Evolution e o dead-end abaixo
            # era inalcancavel. O retry re-percorre o turno do zero e reusa a idempotencia ja
            # existente (mark-after-send por chunk/midia + `enviados:{turno_id}`).
            logger.warning(
                "envio_falha_transitoria turno_id=%s request_id=%s job_try=%s/%s",
                turno_id,
                ctx.get("job_id"),
                job_try,
                max_tries,
                exc_info=True,
            )
            raise Retry(defer=10 * job_try) from None
        # Falha final do job (sem nova tentativa): job_try chegou ao teto.
        # request_id = job_id do ARQ: no worker não há request_id HTTP, então o id do job é o
        # de correlação (spec §15.2) — amarra log e Sentry a esta execução.
        logger.exception(
            "envio_falha_final turno_id=%s request_id=%s critico=%s",
            turno_id,
            ctx.get("job_id"),
            critico,
        )
        if critico and conv is not None:
            # Dead-end (05 §7): efeito já no banco, mensagem pode não ter chegado → escala.
            # `_carregar_destino` só resolve atendimento não-terminal: se ele virou terminal
            # entre o enqueue e esta retry, atendimento_id é NULL e a escalada
            # (atendimento_id NOT NULL) falharia silenciosa. Recupera o último atendimento da
            # conversa em qualquer estado (REL-08); sem nenhum, alerta dedicado, nunca silêncio.
            from barra.workers.coordenador import escalar_por_exaustao

            alvo = conv["atendimento_id"] or await _atendimento_para_escalada(pool, conversa_id)
            if alvo is not None:
                await escalar_por_exaustao(pool, alvo, turno_id, motivo="envio_exaurido_critico")
                ENVIO_RESULTADO.labels("exaustao_critico").inc()
            else:
                # Conversa sem nenhum atendimento (impossível abrir handoff): não silenciar —
                # log dedicado + Sentry para a operação ver o efeito crítico que se perdeu.
                logger.error(
                    "envio_critico_sem_atendimento turno_id=%s request_id=%s conversa_id=%s",
                    turno_id,
                    ctx.get("job_id"),
                    conversa_id,
                )
                if sentry_sdk is not None:
                    sentry_sdk.capture_exception()
                ENVIO_RESULTADO.labels("exaustao_critico_sem_atendimento").inc()
        else:
            # Falha final não-crítica: a mensagem ao cliente pode ter se perdido. Sem efeito no
            # banco não há o que escalar (≠ crítico), mas a perda não pode ser silenciosa —
            # captura no Sentry (init_sentry/OBS-04) para ficar visível à operação. Não muda a
            # entrega/retry: o `raise` abaixo preserva a semântica do job.
            if sentry_sdk is not None:
                sentry_sdk.capture_exception()
            ENVIO_RESULTADO.labels("falha_evolution").inc()
        raise
    finally:
        ENVIO_DURACAO.observe(perf_counter() - inicio)


def midia_conta_como_book(item: dict[str, Any]) -> bool:
    """Esta mídia do turno é o BOOK da modelo (e portanto carimba `book_enviado_em`)? PURA.

    Foto da PARCEIRA não é (ADR-0042). Sem esta pergunta, `marcar_book_enviado` carimbava QUALQUER
    envio de mídia: mandar as fotos dela acenderia `<ja_enviou_book>` e bloquearia o book da
    própria modelo pelo resto da negociação — justamente nos dois fluxos em que a foto da parceira
    sai cedo (a dupla vende as duas; o encaminhamento mostra quem é ela).

    `de` vem do payload da tool `enviar_midia`, via coordenador. Ausente (mídia gravada antes desta
    mudança, ou caminho que não passa pela tool) = 'eu': o comportamento de sempre.
    """
    return item.get("de") != "parceira"


async def _enviar_midias(
    ctx: dict[str, Any],
    conversa_id: str,
    turno_id: str,
    midias: list[dict[str, Any]],
    conv: dict[str, Any],
    critico: bool,
    chunks: list[str],
    checar_pausa: bool = True,
) -> bool:
    """Fase de mídia do MESMO job, depois de todos os chunks de texto (05 §5). A ordem é sempre
    texto→mídia; a legenda de cada mídia carrega o contexto dela. Devolve `False` se cancelou no
    meio (não conta como envio 'ok').

    `chunks` são as bolhas de texto já enviadas neste turno — usadas só para o dedupe
    legenda↔bolha (`_legenda_duplica_bolha`), que evita a frase de acompanhamento repetida.

    `checar_pausa` (turno não-crítico que NÃO abriu a própria pausa) reavalia `ia_pausada` por
    mídia, pelo mesmo motivo do laço de texto: a foto é a bolha mais lenta do turno (presence
    "recording" + 1,5s + upload) e é a que mais frequentemente sobra para depois do handoff."""
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution: EvolutionClient = ctx["evolution"]
    conversa_uuid = UUID(conversa_id)

    for idx, item in enumerate(midias):
        if not critico and not _redis_eq(await redis.get(f"turno_atual:{conversa_id}"), turno_id):
            logger.info("turno_cancelado_midia turno_id=%s idx=%s", turno_id, idx)
            ENVIO_RESULTADO.labels("cancelado").inc()
            return False
        if await redis.sismember(f"enviados:{turno_id}", f"midia:{idx}"):
            continue
        if checar_pausa and await _ia_pausada_agora(pool, conv["atendimento_id"]):
            logger.info("midia_interrompida_pausa turno_id=%s idx=%s", turno_id, idx)
            ENVIO_RESULTADO.labels("cancelado").inc()
            return False

        async with pool.connection() as conn:
            res = await conn.execute(
                "SELECT tipo, bucket, object_key FROM barravips.modelo_midia WHERE id = %s",
                (item["midia_id"],),
            )
            m = await res.fetchone()
        if not m:
            logger.error("midia_nao_encontrada midia_id=%s", item["midia_id"])
            continue

        # presence "recording" para vídeo, "composing" para foto
        presence = "recording" if m["tipo"] == "video" else "composing"
        await evolution.set_presence(
            instance_id=conv["evolution_instance_id"],
            remote_jid=conv["evolution_chat_id"],
            presence=presence,
            delay_ms=1500,
        )
        await asyncio.sleep(1.5)

        # URL assinada regenerada NO job (TTL 30min) — nunca cachear no payload: os retries do
        # ARQ (backoff exponencial) podem ocorrer >5min depois (05 §5).
        url = minio.presigned_get_object(
            m["bucket"], m["object_key"], expires=timedelta(minutes=30)
        )
        # Dedupe legenda↔bolha: se a linha de acompanhamento já saiu como bolha de texto neste
        # turno, a legenda cai — senão o cliente vê a mesma frase duas vezes (bolha + caption).
        legenda = item.get("legenda") or None
        if legenda and _legenda_duplica_bolha(legenda, chunks):
            legenda = None
        # A legenda não passa pelo `_aplicar_saida_guard` (que só vê os chunks de texto), então
        # as redes duras são aplicadas aqui. Dropar SÓ a legenda, não abortar o turno: a mídia é
        # a entrega, a caption é acessório — e sem ela o cliente recebe a foto em silêncio, o que
        # é bem melhor que a bolha "sou uma IA" ou "{valor}" colada nela.
        if legenda and get_settings().envio_guard_habilitado:
            if tem_marcador_ia(legenda) or tem_placeholder_eco(legenda):
                logger.warning(
                    "legenda_barrada turno_id=%s midia_idx=%s",
                    turno_id,
                    idx,
                )
                legenda = None
        async with pool.connection() as conn, conn.transaction():
            mid = await evolution.enviar_midia(
                conn=conn,
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                url=url,
                caption=legenda,
                media_type=m["tipo"],
                contexto="conversa_cliente",
                # `tipo` é o enum de envios_evolution (CHECK só aceita ia/card/confirmacao/
                # erro_comando/midia) — passar m["tipo"] ('foto'/'video') estourava o CHECK
                # DEPOIS do POST: cliente recebia, transação revertia e o mark `midia:{idx}`
                # não gravava (reprocesso reenviaria). O tipo de conteúdo vai em media_type.
                tipo="midia",
                # view-once p/ TODA mídia da modelo — foto e vídeo (Mídia exclusiva, 01 §6.13;
                # decisão do Fernando 2026-07-10: a foto exclusiva também vai como visualização
                # única, não só o vídeo). O cliente só injeta `viewOnce` no body sob o toggle
                # `evolution_view_once` (off por padrão — nenhuma plataforma oficial expõe o campo
                # no envio de mídia; exige o build/fork com o patch). Marcamos sempre; o toggle decide.
                view_once=True,
                atendimento_id=conv["atendimento_id"],
                conversa_id=conversa_uuid,
            )
            await conn.execute(
                """
                INSERT INTO barravips.mensagens
                  (conversa_id, atendimento_id, direcao, tipo, conteudo,
                   media_object_key, evolution_message_id)
                VALUES (%s, %s, 'ia', 'imagem', %s, %s, %s)
                ON CONFLICT (evolution_message_id) DO NOTHING
                """,
                # `tipo` aqui é o enum de `mensagens` (tipo_mensagem_enum: texto/audio/imagem) — MESMO
                # gotcha do envios_evolution acima: passar m["tipo"] ('foto'/'video') estourava o enum
                # DEPOIS do POST (cliente recebia, a transação revertia, o mark `midia:{idx}` não
                # gravava e o retry reenviava duplicado). A distinção foto/vídeo vive em
                # `modelo_midia`/`envios_evolution`; aqui toda mídia de saída persiste como 'imagem'
                # (o CHECK exige só media_object_key IS NOT NULL, satisfeito abaixo).
                (
                    conversa_uuid,
                    conv["atendimento_id"],
                    legenda or "",
                    m["object_key"],
                    mid,
                ),
            )
            # Flag de disciplina (padrão A2): 1º book da negociação. Guard IS NULL (first-write-wins)
            # já é idempotente sob retry, dispensa checar rowcount do INSERT. prepare_context lê a
            # coluna em vez de reescanear as falas da IA (tipo='imagem') por turno.
            #
            # Foto da PARCEIRA não é o book DELA (ADR-0042) — ver `midia_conta_como_book`.
            if conv["atendimento_id"] is not None and midia_conta_como_book(item):
                await marcar_book_enviado(conn, conv["atendimento_id"])

        await redis.sadd(f"enviados:{turno_id}", f"midia:{idx}")
        await redis.expire(f"enviados:{turno_id}", 600)
        await asyncio.sleep(0.6)
    return True
