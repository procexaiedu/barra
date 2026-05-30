"""Configuração structlog: stdout JSON + correlation id por requisição."""

from __future__ import annotations

import logging
import sys

import structlog

from barra.settings import Settings

# Processadores compartilhados entre logs nativos do structlog e logs vindos do logging
# stdlib (coordenador, libs). merge_contextvars expõe o que foi vinculado por turno via
# structlog.contextvars.bind_contextvars (turno_id/atendimento_id) como campos do JSON.
_PRE_CHAIN: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]


def setup_logging(settings: Settings) -> None:
    """Configura structlog + logging stdlib para emitir JSON em stdout no nível log_level.

    Idempotente: substitui os handlers do root a cada chamada. Roda no startup da API
    (build_app) e do worker (workers/settings.startup) — os dois entrypoints de produção.
    Logs do stdlib (ex.: o INFO do coordenador) passam a sair, em JSON, em vez de cair no
    nível WARNING default do root.
    """
    structlog.configure(
        processors=[
            *_PRE_CHAIN,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_PRE_CHAIN,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    # getattr + default "INFO" (mesmo default de Settings.log_level) p/ tolerar settings
    # stub incompletos no startup do worker em testes; produção sempre traz log_level.
    root.setLevel(getattr(settings, "log_level", "INFO"))

    # A CLI do arq instala um StreamHandler de TEXTO no logger "arq" (default_log_config),
    # aplicado ANTES do on_startup onde este setup roda. Sem zerar, os logs do worker (job
    # start/finish) sairiam DUPLICADOS — texto plano pelo handler do arq e JSON pela
    # propagacao ao root. Encaminha tudo pelo root JSON (handler unico, propagate default).
    logging.getLogger("arq").handlers = []
