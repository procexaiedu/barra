"""O ouvido do Agente financeiro (spec 0005, ticket 06): audio do grupo -> texto.

A modelo responde por audio porque e assim que ela usa o WhatsApp — "foi pix", "600", "é a Duda"
chegam falados tanto quanto digitados. Aqui mora so a IDA AO PROVIDER; a decisao do que fazer
com o texto (ou com a falta dele) e da porta unica, que trata o audio transcrito como se tivesse
sido digitado.

Duas escolhas que separam este caminho do STT do agente de venda, e o porque de cada uma:

* **Sincrono, dentro da porta.** O agente de venda deferre a transcricao para a fila ARQ porque o
  turno dele espera a transcricao para responder ao cliente em tempo real, e o coordenador precisa
  acordar com o texto pronto. Aqui nao ha turno esperando: a mensagem ou vira registro ou vira
  silencio. Enfileirar significaria uma segunda entrada no modulo (um job que reprocessa a
  mensagem depois) — exatamente o caminho paralelo que a spec proibe, e que faria o comportamento
  testado deixar de ser o de producao.
* **Sem MinIO.** O byte ja esta na mao de quem chama (o webhook baixou/decodificou); guardar o
  arquivo so para le-lo de volta acumularia a voz da modelo sem uso nenhum previsto.

Custo e latencia sao os do trilho de sempre (`core/stt.py`): ~R$0,0016 e ~1,7 s por audio.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from barra.agente._custo import calcular_custo_stt_brl
from barra.core.metrics import AGENTE_CUSTO_STT_BRL
from barra.core.stt import MODELO_STT_PADRAO, formato_por_mimetype, transcrever
from barra.dominio.grupo_financeiro.modelos import AudioDoGrupo

_logger = logging.getLogger(__name__)

TranscreverAudio = Callable[[AudioDoGrupo], Awaitable[str | None]]
"""Ouvir um audio do grupo. `None` = nao deu para ouvir (falha ou audio sem fala) — e a porta
trata os dois casos igual, porque para ela o efeito e o mesmo: a mensagem nao diz nada."""

_BASE_URL_OPENROUTER = "https://openrouter.ai/api/v1"

# Teto de espera do provider. Mais curto que os 60 s do job do agente de venda de proposito: este
# caminho e sincrono dentro do webhook, e um POST pendurado vira reentrega da Evolution — audio
# duplicado, nao audio transcrito. 15 s e ~9x o p95 medido do trilho (1,7 s).
_TIMEOUT_S = 15.0

# UMA tentativa extra, e nao zero: diferente do job do agente de venda, aqui a falha e definitiva
# (nao ha fila que reprocesse o audio depois, e os bytes nao ficam guardados em lugar nenhum), e
# 429/5xx do provider sao comuns o bastante para valerem a segunda chance. O custo do par
# timeout+retry e o pior caso de ~30 s no webhook — o mesmo orcamento que o download de midia
# inline ja assume hoje.
_MAX_RETRIES = 1

_cliente_cache: dict[str, AsyncOpenAI] = {}


def _cliente(api_key: str) -> AsyncOpenAI:
    """Um cliente por chave, reusado pelo processo (o da API nao tem `ctx` de worker onde morar).

    Reuso importa: `AsyncOpenAI` carrega um pool httpx, e construir um por audio abriria conexao
    nova a cada mensagem de voz do grupo.
    """
    cliente = _cliente_cache.get(api_key)
    if cliente is None:
        cliente = AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL_OPENROUTER,
            timeout=_TIMEOUT_S,
            max_retries=_MAX_RETRIES,
        )
        _cliente_cache[api_key] = cliente
    return cliente


def ouvinte_do_grupo(settings: Any) -> TranscreverAudio | None:
    """Monta o transcritor que a porta usa, ou `None` quando nao ha provider configurado.

    `None` explicito em vez de um transcritor que sempre falha: quem chama (o webhook) passa o
    valor adiante e a porta CONTA a diferenca entre "nao tenho ouvido" e "tentei e nao consegui" —
    a primeira e configuracao faltando (o `OPENROUTER_API_KEY` que sumiu num redeploy e derrubou
    o OCR do Pix em prod, 24/07), a segunda e o provider tendo um dia ruim.
    """
    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        return None
    modelo = getattr(settings, "openrouter_model_audio_transcribe", None) or MODELO_STT_PADRAO
    cotacao = getattr(settings, "usd_brl_cotacao", 0.0)
    cliente = _cliente(api_key)

    async def ouvir(audio: AudioDoGrupo) -> str | None:
        resultado = await transcrever(
            cliente,
            audio.conteudo,
            formato=formato_por_mimetype(audio.mimetype),
            modelo=modelo,
        )
        # Mesmo criterio do agente de venda (CUSTO-02): observa o custo ANTES de olhar o texto —
        # audio sem fala tambem queimou tokens, e e justamente o caso que se quer ver crescer.
        AGENTE_CUSTO_STT_BRL.labels(modelo).observe(
            calcular_custo_stt_brl(resultado.usage, cotacao)
        )
        if resultado.texto is None:
            _logger.info(
                "grupo_financeiro_audio_sem_fala modelo=%s bytes=%d", modelo, len(audio.conteudo)
            )
        return resultado.texto

    return ouvir
