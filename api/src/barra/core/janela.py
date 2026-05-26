"""Helpers de janela temporal compartilhados entre dashboard e financeiro.

Antes vivia em ``dominio/dashboard/routes.py``; movido para ``core`` quando o
módulo Financeiro (ADR 0011) passou a precisar do mesmo helper (`mes` adicionado).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from barra.core.errors import EntradaInvalida

BRT = timezone(timedelta(hours=-3))
JANELA_CUSTOM_MAXIMA_DIAS = 90


@dataclass(frozen=True)
class Janela:
    de: date
    ate: date
    inicio: datetime
    fim: datetime

    def dias(self) -> int:
        return (self.ate - self.de).days + 1


def resolver_janela(periodo: str, de: date | None, ate: date | None) -> Janela:
    """Converte um período nomeado (hoje/7d/30d/mes/tudo/custom) numa Janela BRT.

    'mes' = 1º do mês corrente até hoje (ADR 0011, item K).
    """
    hoje = datetime.now(BRT).date()

    if periodo == "custom":
        if de is None or ate is None:
            raise EntradaInvalida(
                "PERIODO_CUSTOM_INVALIDO",
                "Período custom exige 'de' e 'ate'.",
            )
        if de > ate:
            raise EntradaInvalida("PERIODO_CUSTOM_INVALIDO", "'de' deve ser <= 'ate'.")
        if ate > hoje:
            raise EntradaInvalida("PERIODO_CUSTOM_INVALIDO", "'ate' não pode estar no futuro.")
        if (ate - de).days + 1 > JANELA_CUSTOM_MAXIMA_DIAS:
            raise EntradaInvalida(
                "PERIODO_CUSTOM_INVALIDO",
                f"Janela custom limitada a {JANELA_CUSTOM_MAXIMA_DIAS} dias.",
            )
        return janela_de_datas(de, ate)

    if periodo == "hoje":
        return janela_de_datas(hoje, hoje)
    if periodo == "7d":
        return janela_de_datas(hoje - timedelta(days=6), hoje)
    if periodo == "30d":
        return janela_de_datas(hoje - timedelta(days=29), hoje)
    if periodo == "mes":
        return janela_de_datas(hoje.replace(day=1), hoje)
    if periodo == "tudo":
        return janela_de_datas(date(2020, 1, 1), hoje)

    raise EntradaInvalida("PERIODO_INVALIDO", f"periodo desconhecido: {periodo}")


def janela_de_datas(de: date, ate: date) -> Janela:
    inicio = datetime.combine(de, time.min, tzinfo=BRT)
    fim = datetime.combine(ate, time.max, tzinfo=BRT)
    return Janela(de=de, ate=ate, inicio=inicio, fim=fim)


def janela_anterior(janela: Janela) -> Janela | None:
    """Janela imediatamente anterior à atual, com a mesma duração."""
    duracao_dias = janela.dias()
    ate_anterior = janela.de - timedelta(days=1)
    de_anterior = ate_anterior - timedelta(days=duracao_dias - 1)
    return janela_de_datas(de_anterior, ate_anterior)


def filtro_aplicado_dict(
    periodo: str, janela: Janela, modelo_ids: list[UUID] | None
) -> dict[str, Any]:
    return {
        "periodo": periodo,
        "de": janela.de.isoformat(),
        "ate": janela.ate.isoformat(),
        "modelo_ids": [str(m) for m in modelo_ids] if modelo_ids else [],
    }
