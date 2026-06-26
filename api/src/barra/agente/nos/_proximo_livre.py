"""Pré-cálculo determinístico do próximo slot reservável após um bloqueio (CONTEXT.md "Bloqueio").

Quando o horário que o cliente pede cai num bloqueio, a IA oferece o próximo horário logo após
aquele compromisso terminar — sem revelar que está com outro cliente. A aritmética (somar o buffer,
arredondar pra hora social, pular bloqueios seguintes, validar contra a Disponibilidade) é o que o
LLM erra, então roda aqui em Python puro e chega pronta como atributo `proximo_livre` por bloqueio
no contexto dinâmico. É camada de conversa: a reserva em si segue checando só sobreposição.

Os datetimes vêm crus do psycopg (mesma sessão, mesmo tzinfo de `inicio`/`fim`), então o resultado
renderiza consistente com eles. O gate de Disponibilidade converte pra BRT internamente; arredondar
pra :00/:30 é invariante ao offset BRT (-03:00, horas cheias).
"""

from datetime import datetime, timedelta
from typing import Any

from barra.dominio.modelos.disponibilidade import regras_cobrem


def _arredonda_meia_hora_acima(dt: datetime) -> datetime:
    """Próximo múltiplo de 30min >= `dt` (22:47→23:00; 23:17→23:30; 22:30→22:30; 22:30:05→23:00)."""
    truncado = dt.replace(second=0, microsecond=0)
    resto = truncado.minute % 30
    if resto == 0 and truncado == dt:
        return truncado
    return truncado + timedelta(minutes=(30 - resto) if resto else 30)


def proximo_livre(
    fim: datetime,
    blocos: list[dict[str, Any]],
    regras_disp: list[dict[str, Any]],
    buffer_min: int,
    *,
    lead_min: int | None = None,
) -> datetime | None:
    """Próximo horário reservável após `fim`, ou None se não couber na Disponibilidade.

    `cand` = `fim` + `lead`, arredondado pra cima na meia-hora. Pula um bloqueio seguinte se `cand`
    cair DENTRO dele OU dentro do buffer ANTES dele (ADR 0025: gap >= buffer dos dois lados — a
    adjacência `fim == inicio`, e tudo a menos de um buffer, não é reservável); some o buffer e
    re-arredonda, cobrindo cadeias consecutivas. Só retorna se o início cair numa janela de
    Disponibilidade (sem regra = sempre disponível).

    `lead_min` (emenda ADR 0025, 2026-06-26) separa o offset inicial do gap entre atendimentos:
    `lead` = offset a partir de `fim` (default = `buffer_min`, retrocompatível); `buffer_min` = o
    gap em torno dos vizinhos, sempre. O `horario_minimo` (lead a partir de AGORA) passa a
    antecedência por-tipo aqui (sem deslocamento da modelo -> ~0); o `proximo_livre` por-bloqueio
    (lead a partir do fim de um compromisso = gap entre atendimentos) mantém o default.

    É camada de conversa: oferece o início respeitando o buffer dos dois lados, como a reserva
    exige (`existe_vizinho_no_buffer`, ADR 0025). A reserva re-valida na criação (sobreposição +
    buffer + a duração efetiva, que este pré-cálculo não conhece).
    """
    lead = timedelta(minutes=buffer_min if lead_min is None else lead_min)
    buffer = timedelta(minutes=buffer_min)
    cand = _arredonda_meia_hora_acima(fim + lead)
    for _ in range(len(blocos) + 1):
        # Conflita se `cand` cai DENTRO do bloco ou no buffer ANTES dele (gap < buffer). O `>`
        # estrito deixa a adjacência de gap == buffer reservável (espelha `i2 < new.fim + buffer`
        # do gate da reserva, ADR 0025).
        conflito = next((b for b in blocos if b["inicio"] - buffer < cand < b["fim"]), None)
        if conflito is None:
            break
        cand = _arredonda_meia_hora_acima(conflito["fim"] + buffer)
    else:
        return None
    if not regras_cobrem(regras_disp, cand):
        return None
    return cand
