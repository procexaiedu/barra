"""Job ARQ `fechar_via_comprovante` — auto-fechamento por comprovante de Pix no grupo.

A modelo responde o card de fechamento (ou poe `#N` na legenda) com a FOTO do comprovante de Pix;
o webhook (`webhook/routes._processar_comprovante_grupo`) resolve o `#N`, sobe a imagem ao MinIO e
enfileira este job. Aqui: baixa do MinIO, faz OCR (reusa `_extrair_via_openrouter` do pipeline de
Pix) e fecha o atendimento pelo valor lido via a porta unica `aplicar_comando(registrar_fechado)`.
E o MESMO fechamento do `fechado [valor]` de texto — so que o valor vem do comprovante.

Auto-baixa SEM rede (decisao de produto): qualquer valor lido fecha; leitura errada e corrigida
depois no painel (`corrigir_registro`). O que NAO da pra fechar e a ausencia de valor legivel
(constraint `valor_final` obrigatorio) — nesse caso pede o valor por texto. Dedup: o `_job_id` por
`evolution_message_id` (no enfileiramento) + o guard de estado do `_registrar_fechado` (atendimento
ja Fechado -> no-op). Escopo: SO Pix — dinheiro/cartao seguem no `fechado [valor]` manual.

Robustez do OCR espelha o `validar_pix` (Pix nunca trava): qualquer falha/inconclusivo de vision
NAO propaga — vira "sem valor" e pede o valor por texto, em vez de crashar o job.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from barra.core.errors import ConflitoEstado, ErroDominio
from barra.core.evolution import EvolutionClient
from barra.dominio.escaladas.service import aplicar_comando
from barra.webhook.respostas import texto_confirmacao, texto_erro_comando, texto_erro_dominio
from barra.workers.pix import (
    _baixar_minio,
    _detectar_mime_imagem,
    _extrair_via_openrouter,
)

logger = logging.getLogger(__name__)


async def fechar_via_comprovante(
    ctx: dict[str, Any],
    *,
    atendimento_id: str,
    object_key: str,
    evolution_message_id: str,
) -> None:
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    settings = ctx["settings"]
    evolution: EvolutionClient = ctx["evolution"]
    vision_client: AsyncOpenAI | None = ctx["vision_client"]

    # 1. contexto: grupo destino (isolamento por par) + numero curto + guard de ja-finalizado.
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT a.numero_curto, a.estado::text AS estado, a.conversa_id,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.atendimentos a
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
             WHERE a.id = %s
            """,
            (UUID(atendimento_id),),
        )
        row = await res.fetchone()
    if row is None:
        logger.error("fechar_via_comprovante atendimento inexistente id=%s", atendimento_id)
        return

    numero = row["numero_curto"]
    instance_id = row["evolution_instance_id"]
    grupo_jid = row["coordenacao_chat_id"]

    async def _avisar(texto: str, tipo: str) -> None:
        """Eco best-effort no grupo de Coordenacao da modelo dona (nunca sucesso/erro silencioso).

        Uma falha de envio nao pode derrubar o job (o fechamento ja committou); sem instance/JID
        (Evolution off em teste) vira no-op."""
        if not (instance_id and grupo_jid):
            return
        try:
            async with pool.connection() as conn, conn.transaction():
                await evolution.enviar_texto(
                    conn=conn,
                    instance_id=instance_id,
                    remote_jid=grupo_jid,
                    texto=texto,
                    contexto="grupo_coordenacao",
                    tipo=tipo,
                    atendimento_id=UUID(atendimento_id),
                    conversa_id=row["conversa_id"],
                )
        except Exception:
            logger.warning(
                "fechar_via_comprovante aviso falhou atendimento=%s", atendimento_id, exc_info=True
            )

    if row["estado"] in ("Fechado", "Perdido"):
        # Dedup / 2a foto num atendimento ja finalizado: nao refecha (CONTEXT "Registro de
        # resultado" — correcao e no painel). No-op com eco de recuperacao.
        await _avisar(texto_erro_comando("atendimento_nao_encontrado"), "erro_comando")
        return

    # 2. OCR — nunca propaga (Pix nunca trava): erro/inconclusivo/sem-credencial -> valor None.
    valor: Decimal | None = None
    if vision_client is None:
        logger.warning("fechar_via_comprovante sem vision_client atendimento=%s", atendimento_id)
    else:
        try:
            bytes_img = await _baixar_minio(minio, settings.minio_bucket_media, object_key)
            media_type = _detectar_mime_imagem(bytes_img)
            extracao = await _extrair_via_openrouter(
                bytes_img,
                media_type=media_type,
                client=vision_client,
                modelo=settings.openrouter_model_vision_pix or "google/gemini-3-flash-preview",
            )
            valor = extracao.valor
            # "Sem rede": plausibilidade/legibilidade NAO gateiam o fechamento (decisao de produto).
            # So observa para telemetria — a modelo/Fernando corrige depois no painel se preciso.
            if not extracao.plausibilidade_visual or extracao.confianca == "baixa":
                logger.info(
                    "fechar_via_comprovante leitura fraca atendimento=%s plausivel=%s confianca=%s",
                    atendimento_id,
                    extracao.plausibilidade_visual,
                    extracao.confianca,
                )
        except Exception as exc:
            logger.warning(
                "fechar_via_comprovante OCR falhou atendimento=%s erro=%s",
                atendimento_id,
                type(exc).__name__,
            )

    # 3. Sem valor legivel: nao da pra fabricar valor_final (constraint). Pede o valor por texto.
    if valor is None or valor <= 0:
        await _avisar(texto_erro_comando("valor_final_obrigatorio"), "erro_comando")
        return

    # 4. Fecha pela porta unica (mesmo caminho do `fechado [valor]` de texto). autor='modelo' (a
    #    modelo agiu enviando o comprovante); forma_pagamento='pix' (comprovante de Pix, sem taxa
    #    de cartao). Campos de auditoria (fonte/ids) viajam no evento `fechado_registrado`.
    try:
        async with pool.connection() as conn:
            await aplicar_comando(
                conn,
                origem="grupo_coordenacao",
                autor="modelo",
                atendimento_id=UUID(atendimento_id),
                comando="registrar_fechado",
                payload={
                    "valor_final": valor,
                    "forma_pagamento": "pix",
                    "fonte": "comprovante_grupo",
                    "evolution_message_id": evolution_message_id,
                    "object_key": object_key,
                },
            )
    except ConflitoEstado:
        # Corrida: outra foto/comando fechou entre o SELECT e o UPDATE. No-op (nao refecha).
        await _avisar(texto_erro_comando("atendimento_nao_encontrado"), "erro_comando")
        return
    except ErroDominio as exc:
        logger.warning(
            "fechar_via_comprovante dominio erro=%s atendimento=%s", exc.code, atendimento_id
        )
        await _avisar(texto_erro_dominio(exc.code), "erro_comando")
        return

    await _avisar(
        texto_confirmacao("registrar_fechado", {"valor_final": valor}, numero), "confirmacao"
    )
    logger.info("fechar_via_comprovante fechado atendimento=%s numero=%s", atendimento_id, numero)


__all__ = ["fechar_via_comprovante"]
