"""Judge assíncrono PÓS-ENVIO — telemetria de 100% dos turnos enviados (produção assistida).

Job ARQ enfileirado pelo coordenador logo após despachar a humanização (só turnos que realmente
saíram ao cliente), com defer curto para o envio humanizado terminar. Pontua o turno no DeepSeek
(mesmo padrão do judge de AUP do output_guard) em 3 eixos fixos do plano do piloto:

  - `rastro_llm` (bool)  — um cliente atento perceberia rastro de IA? true = incidente
                           NÃO-CONTIDO (o gate pré-envio não segurou);
  - `voz` (1-5)          — fidelidade à voz da persona;
  - `conduta` (1-5)      — coerência de conduta comercial no contexto.

Destinos: `barravips.julgamentos_turno` (fonte durável do rollback_watch e do digest semanal),
scores no trace do Langfuse (`judge_rastro_llm`/`judge_voz`/`judge_conduta`, mesmo trace do turno)
e Prometheus (JUDGE_POS_ENVIO). Telemetria dev PURA: nunca pausa a IA, nunca gera tarefa para
Fernando, nunca volta ao contexto da IA ao vivo. Falha do judge = warning + métrica, sem retry
(ARQ não retenta exceção comum — de propósito: telemetria não re-queima crédito).

Invariante de isolamento: o contexto é carregado por `conversa_id` (a conversa É o par
cliente-modelo); nada cross-modelo entra no prompt do judge.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from barra.core.metrics import JUDGE_POS_ENVIO
from barra.core.tracing import registrar_feedback_online
from barra.settings import Settings

logger = logging.getLogger(__name__)

# Mensagens recentes da conversa que dão contexto ao eixo `conduta` (janela curta de propósito:
# o judge avalia o turno, não a conversa inteira).
_CONTEXTO_MENSAGENS = 10


class VeredictoTurno(BaseModel):
    """Saída estruturada do judge pós-envio (3 eixos do plano de produção assistida)."""

    rastro_llm: bool = Field(
        description="true se um cliente atento perceberia rastro de IA/LLM neste turno"
    )
    voz: int = Field(ge=1, le=5, description="fidelidade à voz da persona (1=robótica, 5=dela)")
    conduta: int = Field(
        ge=1,
        le=5,
        description="coerência de conduta comercial no contexto (1=incoerente, 5=impecável)",
    )
    comentario: str = Field(default="", description="1 frase: o principal problema, ou 'ok'")


_SQL_JA_JULGADO = "SELECT 1 FROM barravips.julgamentos_turno WHERE turno_id = %s"

_SQL_MODELO_DA_CONVERSA = "SELECT modelo_id FROM barravips.conversas WHERE id = %s"

# Contexto recente do par (mais novas primeiro; invertido no Python). Exclui as bolhas do PRÓPRIO
# turno julgado (já persistidas pelo enviar_turno no momento em que o job roda, por causa do
# defer): sem o filtro, o judge veria o turno duplicado (contexto + turno) e flagraria repetição
# espúria. O match é por conteúdo (mensagens não tem turno_id), então uma bolha idêntica de turno
# ANTERIOR também some do contexto — ponto cego aceito: nunca gera falso-positivo, e a repetição
# literal real é coberta pelo detector determinístico do gate pré-envio (output_guard).
_SQL_CONTEXTO = """
SELECT direcao::text AS direcao, conteudo
  FROM barravips.mensagens
 WHERE conversa_id = %s
   AND conteudo <> ''
   AND NOT (direcao = 'ia' AND conteudo = ANY(%s))
 ORDER BY created_at DESC, id DESC
 LIMIT %s
"""

_SQL_INSERT = """
INSERT INTO barravips.julgamentos_turno
  (turno_id, conversa_id, modelo_id, rastro_llm, voz, conduta, comentario)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (turno_id) DO NOTHING
"""


class _JudgeIndisponivel(RuntimeError):
    """Judge não produziu veredito confiável (recusa/truncado/parse) — telemetria perde o turno."""


async def _julgar(contexto: str, turno: str, settings: Settings) -> VeredictoTurno:
    """Veredito estruturado no DeepSeek (espelha `output_guard._julgar_aup`: thinking disabled,
    function_calling explícito, `include_raw` p/ checar a parada, retry 1x SÓ em parse)."""
    from barra.agente._instrumentar import instrumentar_tokens
    from barra.agente.persona import render_judge_pos_envio
    from barra.core.llm import PARADA_INSEGURA, criar_chat_deepseek, motivo_parada

    chat = criar_chat_deepseek(settings).with_structured_output(
        VeredictoTurno, include_raw=True, method="function_calling"
    )
    mensagens = [
        {"role": "system", "content": render_judge_pos_envio()},
        {
            "role": "user",
            "content": (
                f"CONTEXTO (mensagens recentes, mais antiga primeiro):\n{contexto or '(vazio)'}\n\n"
                f"TURNO ENVIADO (a avaliar):\n{turno}"
            ),
        },
    ]
    parada: str | None = None
    for tentativa in (1, 2):
        # callbacks=[]: job fora do grafo, sem trace próprio — o veredito entra como SCORE no
        # trace do turno (registrar_feedback_online), não como spans de sub-chain.
        resultado = await chat.ainvoke(mensagens, config={"callbacks": []})
        assert isinstance(resultado, dict)
        bruto = resultado.get("raw")
        if bruto is not None:
            instrumentar_tokens(bruto, settings.deepseek_model_chat)
        parada = motivo_parada(getattr(bruto, "response_metadata", None))
        if parada in PARADA_INSEGURA:
            raise _JudgeIndisponivel(f"judge pos-envio sem veredito (parada={parada})")
        if resultado.get("parsing_error") is None:
            veredito = resultado.get("parsed")
            assert isinstance(veredito, VeredictoTurno)
            return veredito
        if tentativa == 1:
            logger.warning("judge_pos_envio parse falhou (tentativa 1, parada=%s) -> retry", parada)
    raise _JudgeIndisponivel(f"judge pos-envio sem veredito (parsing_error=True, parada={parada})")


async def julgar_turno_pos_envio(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    trace_id: str | None = None,
) -> int:
    """Julga um turno já enviado e persiste a telemetria. Devolve 1 quando julgou, 0 caso contrário."""
    settings: Settings = ctx["settings"]
    pool = ctx.get("db_pool")
    if not settings.judge_pos_envio_ativo or pool is None:
        return 0

    # Só julga o que REALMENTE saiu ao cliente: o enviar_turno marca cada chunk despachado em
    # `enviados:{turno_id}` (mark-after-send, TTL 600s — o defer de 120s cai dentro). Turno
    # barrado pela rede final (`envio_leak`/`envio_placeholder`), cancelado ou ainda não enviado
    # fica SEM marcador -> pula, senão um incidente CONTIDO viraria `rastro_llm=true` espúrio e
    # dispararia o gatilho de rollback `nao_contidos` (o mais sensível). Sem Redis no ctx (não
    # acontece no worker real), confia no payload — melhor telemetria a mais que a menos.
    redis = ctx.get("redis")
    if redis is not None:
        marcados = await redis.smembers(f"enviados:{turno_id}")
        marcadores = {m.decode() if isinstance(m, bytes | bytearray) else str(m) for m in marcados}
        chunks = [c for i, c in enumerate(chunks) if f"chunk:{i}" in marcadores]
        if not chunks:
            JUDGE_POS_ENVIO.labels("nao_enviado").inc()
            return 0

    turno = "\n\n".join(c for c in chunks if c.strip()).strip()
    if not turno:
        return 0

    async with pool.connection() as conn:
        res = await conn.execute(_SQL_JA_JULGADO, (turno_id,))
        if await res.fetchone() is not None:
            JUDGE_POS_ENVIO.labels("pulado").inc()
            return 0
        res = await conn.execute(_SQL_MODELO_DA_CONVERSA, (conversa_id,))
        row = await res.fetchone()
        if row is None:
            logger.warning("judge_pos_envio conversa inexistente conversa_id=%s", conversa_id)
            return 0
        modelo_id = row["modelo_id"]
        res = await conn.execute(_SQL_CONTEXTO, (conversa_id, chunks, _CONTEXTO_MENSAGENS))
        recentes = list(await res.fetchall())

    # `modelo_manual` = a modelo (humana) escreveu no handoff; pro cliente, IA e modelo são a
    # MESMA "ela" (mesmo assento) — rotular diferente entregaria o rótulo interno ao judge.
    rotulo = {"cliente": "cliente", "ia": "ela", "modelo_manual": "ela"}
    contexto = "\n".join(
        f"{rotulo.get(m['direcao'], m['direcao'])}: {m['conteudo']}" for m in reversed(recentes)
    )

    try:
        veredito = await _julgar(contexto, turno, settings)
    except Exception:
        logger.warning("judge_pos_envio indisponivel turno_id=%s", turno_id, exc_info=True)
        JUDGE_POS_ENVIO.labels("indisponivel").inc()
        return 0

    async with pool.connection() as conn:
        await conn.execute(
            _SQL_INSERT,
            (
                turno_id,
                conversa_id,
                modelo_id,
                veredito.rastro_llm,
                veredito.voz,
                veredito.conduta,
                veredito.comentario[:500],
            ),
        )

    if trace_id:
        # Mesmo trace do turno (trace_id determinístico por seed=turno_id no coordenador):
        # o veredito vira score legível ao lado do próprio trace. Best-effort (sync SDK).
        for nome, score in (
            ("judge_rastro_llm", 0.0 if veredito.rastro_llm else 1.0),
            ("judge_voz", veredito.voz / 5.0),
            ("judge_conduta", veredito.conduta / 5.0),
        ):
            await asyncio.to_thread(registrar_feedback_online, trace_id, nome, score)

    if veredito.rastro_llm:
        # Incidente NÃO-CONTIDO: o cliente pode ter percebido a IA. WARNING de propósito —
        # a revisão diária do dev grepa isto; a agregação semanal é o rollback_watch.
        logger.warning(
            "judge_pos_envio RASTRO NAO-CONTIDO turno_id=%s conversa_id=%s voz=%d conduta=%d: %s",
            turno_id,
            conversa_id,
            veredito.voz,
            veredito.conduta,
            veredito.comentario,
        )
        JUDGE_POS_ENVIO.labels("rastro").inc()
    else:
        JUDGE_POS_ENVIO.labels("ok").inc()
    return 1
