"""Canário de entrega fim-a-fim — cron do worker (default DESLIGADO).

Existe por causa do apagão 24-27/07: a Evolution aceitou os POSTs por 3 dias e não entregou nada,
com TODA métrica verde. Nenhuma das métricas existentes pega isso porque todas medem o que a
stack **produziu** (turno, trace, envio aceito), não o que o WhatsApp **entregou**. O canário é a
única sonda que fecha o laço inteiro:

    Barra → POST /send/text → Evolution → WhatsApp → webhook `fromMe` → `barravips.mensagens`

**Como a prova é obtida** (o detalhe que faz o desenho funcionar): a sonda sai por
`enviar_texto_avulso`, que **não** grava em `envios_evolution`. Sem esse registro, o eco `fromMe`
não bate no guard `envio_existe` do webhook (que ignora o próprio outbound) e cai no ramo
`modelo_manual` — persistido em `barravips.mensagens` com o MESMO `evolution_message_id` que o
`/send/text` devolveu. Essa linha é escrita pelo **webhook**, não por nós: ela só existe se a
mensagem realmente saiu no WhatsApp e voltou. Um envio registrado em `envios_evolution` provaria
apenas que a Evolution respondeu 200 — exatamente o que ficou verde durante o apagão.

Efeito colateral aceito e contido: a conversa com o número de controle acumula uma linha
`modelo_manual` por ciclo. Ela NÃO enfileira turno (o webhook devolve `modelo_manual` e sai), não
cria Atendimento, não gasta crédito de LLM e não entra em nenhum gatilho do piloto (o
`rollback_watch` conta `direcao='cliente'`). Por isso o `canario_jid` tem de ser um número de DEV.

**Ciclo** (um cron faz os dois passos, sem estado novo no banco):
  1. verifica os ids pendentes no hash Redis `canario:pendentes` — eco chegou → `ok`; passou do
     `canario_prazo_eco_min` sem eco → `sem_eco` + alerta;
  2. dispara a sonda seguinte e guarda o id devolvido.

**Alerta fora da Evolution**: métrica + log ERROR + **Telegram** (bot API, httpx). O relay padrão
entrega por Alertmanager → barra-api → Evolution → WhatsApp; alerta sobre a Evolution caída não se
auto-entrega. Sem token/chat_id configurado, degrada para métrica + log.

Semântica ARQ: nada aqui levanta `Retry`, então nada retenta (ARQ só re-executa em `Retry`
explícito) — falha de envio já É o sinal, não algo a mascarar com retentativa. Idempotente:
reexecução no mesmo ciclo apenas reavalia pendentes e manda mais uma sonda.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from arq import ArqRedis
from psycopg import AsyncConnection

from barra.core.evolution import EvolutionClient
from barra.core.metrics import CANARIO_ENTREGA, CANARIO_ENTREGA_OK
from barra.settings import Settings

logger = logging.getLogger(__name__)

# Hash Redis id→epoch dos envios aguardando eco. Fica naturalmente com ~1 entrada: cada ciclo
# resolve (eco) ou vence (prazo) as anteriores antes de inserir a nova. Redis é externo ao
# processo, então o pendente sobrevive a force-update do worker (que é rotina em deploy de prompt).
CHAVE_PENDENTES = "canario:pendentes"

# Texto inócuo: vai para um WhatsApp real. Sem nada que pareça a persona, sem PII, com o instante
# em ISO para quem olhar o celular saber o que é.
PREFIXO_SONDA = "canario barra"

_URL_TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"

_SQL_ECO = "SELECT 1 FROM barravips.mensagens WHERE evolution_message_id = %s"


def canario_ligado(settings: Settings) -> bool:
    """Ligado só com destino E instância configurados — os dois defaults vazios são o kill-switch."""
    return bool(settings.canario_jid and settings.canario_instance_id)


def minutos_do_intervalo(intervalo_min: int) -> set[int]:
    """Set de minutos do cron ARQ a partir do intervalo em minutos. 60 → {0} (uma vez por hora)."""
    passo = max(1, min(intervalo_min, 60))
    return set(range(0, 60, passo))


def _texto(valor: object) -> str:
    """ArqRedis não decodifica respostas: hash volta em bytes."""
    if isinstance(valor, bytes | bytearray):
        return bytes(valor).decode()
    return str(valor)


async def _notificar_telegram(settings: Settings, mensagem: str) -> bool:
    """Alerta pelo canal que NÃO passa pela Evolution. Best-effort: falha do Telegram nunca pode
    derrubar o cron (a métrica e o log ERROR continuam de pé)."""
    token = settings.canario_telegram_token
    chat_id = settings.canario_telegram_chat_id
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resposta = await client.post(
                _URL_TELEGRAM.format(token=token),
                json={"chat_id": chat_id, "text": mensagem},
            )
            resposta.raise_for_status()
    except Exception:
        logger.warning("canario_telegram_falhou", exc_info=True)
        return False
    return True


async def _alertar(settings: Settings, motivo: str, detalhe: str) -> None:
    msg = f"CANARIO_ENTREGA {motivo}: {detalhe}"
    logger.error(msg)
    await _notificar_telegram(settings, msg)


async def _verificar_pendentes(
    conn: AsyncConnection[Any],
    redis: ArqRedis,
    settings: Settings,
    agora: float,
) -> int:
    """Julga os ids pendentes; devolve quantos venceram o prazo sem eco.

    Pendente ainda DENTRO do prazo fica pendente (não é veredito) — e por isso não mexe no gauge:
    manter o último veredito conhecido evita o flap RESOLVED/FIRING a cada ciclo.
    """
    pendentes = await cast(Awaitable[dict[Any, Any]], redis.hgetall(CHAVE_PENDENTES))
    prazo_s = settings.canario_prazo_eco_min * 60
    falhas = 0
    for id_bruto, ts_bruto in dict(pendentes).items():
        message_id = _texto(id_bruto)
        try:
            enviado_em = float(_texto(ts_bruto))
        except ValueError:  # entrada corrompida: descarta em vez de travar o ciclo
            await cast(Awaitable[int], redis.hdel(CHAVE_PENDENTES, message_id))
            continue
        idade = agora - enviado_em
        res = await conn.execute(_SQL_ECO, (message_id,))
        if await res.fetchone() is not None:
            await cast(Awaitable[int], redis.hdel(CHAVE_PENDENTES, message_id))
            CANARIO_ENTREGA.labels("ok").inc()
            CANARIO_ENTREGA_OK.set(1.0)
            logger.info("canario eco recebido id=%s em %.0fs", message_id, idade)
        elif idade >= prazo_s:
            await cast(Awaitable[int], redis.hdel(CHAVE_PENDENTES, message_id))
            CANARIO_ENTREGA.labels("sem_eco").inc()
            CANARIO_ENTREGA_OK.set(0.0)
            falhas += 1
            await _alertar(
                settings,
                "sem_eco",
                f"sonda {message_id} enviada ha {idade / 60:.0f} min e o eco fromMe NAO voltou "
                f"pelo webhook (prazo {settings.canario_prazo_eco_min} min). O laco de entrega "
                f"esta quebrado: checar a instancia {settings.canario_instance_id} na Evolution "
                f"(pareamento/device) e o webhook da barra-api ANTES de olhar agente ou prompt.",
            )
    return falhas


async def _enviar_sonda(
    redis: ArqRedis,
    evolution: EvolutionClient,
    settings: Settings,
    agora: float,
) -> int:
    """Manda a sonda do ciclo e registra o id como pendente. Devolve 1 se o envio já falhou aqui."""
    texto = f"{PREFIXO_SONDA} {datetime.fromtimestamp(agora, UTC).isoformat(timespec='seconds')}"
    try:
        message_id = await evolution.enviar_texto_avulso(
            instance_id=settings.canario_instance_id,
            remote_jid=settings.canario_jid,
            texto=texto,
        )
    except Exception as exc:
        # Falha no POST já é o sinal — e é o caso FÁCIL (o apagão foi o difícil: 200 sem entrega).
        CANARIO_ENTREGA.labels("envio_falhou").inc()
        CANARIO_ENTREGA_OK.set(0.0)
        await _alertar(settings, "envio_falhou", f"POST /send/text da sonda falhou: {exc!r}")
        return 1
    if not message_id:
        # Sem `evolution_base_url` o cliente devolve None: configuração incompleta, não apagão.
        CANARIO_ENTREGA.labels("envio_falhou").inc()
        CANARIO_ENTREGA_OK.set(0.0)
        await _alertar(
            settings, "envio_falhou", "Evolution nao devolveu id da sonda (base_url configurada?)"
        )
        return 1
    await cast(Awaitable[int], redis.hset(CHAVE_PENDENTES, message_id, str(agora)))
    logger.info("canario sonda enviada id=%s destino=%s", message_id, settings.canario_jid)
    return 0


async def rodar_canario(
    conn: AsyncConnection[Any],
    redis: ArqRedis,
    evolution: EvolutionClient,
    settings: Settings,
) -> int:
    """Um ciclo do canário: julga os pendentes, depois dispara a sonda seguinte.

    Devolve o nº de falhas detectadas no ciclo (0 = laço saudável). Inofensivo desligado: sai
    antes de qualquer I/O.
    """
    if not canario_ligado(settings):
        return 0
    agora = datetime.now(UTC).timestamp()
    falhas = await _verificar_pendentes(conn, redis, settings, agora)
    falhas += await _enviar_sonda(redis, evolution, settings, agora)
    return falhas
