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

from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Any

from barra.dominio.agenda.service import buffer_do_bloqueio_min
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

    `cand` = `fim` + `lead`, arredondado pra cima na meia-hora. Pula um bloqueio se `cand` cair
    DENTRO dele ou dentro do buffer de QUALQUER um dos dois lados dele (ADR 0025: gap >= buffer dos
    dois lados — a adjacência `fim == inicio`, e tudo a menos de um buffer, não é reservável); pula
    para o fim do bloqueio + buffer e re-arredonda, cobrindo cadeias consecutivas. Só retorna se o
    início cair numa janela de Disponibilidade (sem regra = sempre disponível).

    O buffer é POR BLOCO (emenda ADR 0025, 2026-08-14): o bloco `externo` — o compromisso na casa
    de um cliente — cobra `agenda_buffer_externo_min` dos dois lados, porque tem uma viagem colada
    nele; qualquer outro tipo, e o bloco que não declara tipo, cobra `buffer_min`. O tipo vem do
    próprio dict do bloco (`tipo_atendimento`, que a query do `prepare_context` deriva do
    atendimento vinculado); ausente = comportamento de sempre. A conta é a MESMA de
    `existe_vizinho_no_buffer` (via `buffer_do_bloqueio_min`) de propósito: o horário publicado
    aqui é o que a reserva vai aceitar lá.

    O lado DEPOIS do bloco entra no teste desde essa emenda. Sem ele havia uma zona morta: com um
    bloqueio terminando 18:30 e `agora` 18:00, o `horario_minimo` publicado era o próprio 18:30
    (`cand < b["fim"]` é falso na borda) e a reserva daquele mesmo 18:30 caía em `ConflitoAgenda` —
    o sistema publicava um horário que ele mesmo recusava. Como `cand` sai do lado de fora do
    buffer, o bloco não conflita consigo mesmo e o laço continua terminando.

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

    def _halo(bloco: dict[str, Any]) -> timedelta:
        return timedelta(
            minutes=buffer_do_bloqueio_min(bloco.get("tipo_atendimento"), buffer_min=buffer_min)
        )

    cand = _arredonda_meia_hora_acima(fim + lead)
    for _ in range(len(blocos) + 1):
        # Conflita se `cand` cai DENTRO do bloco ou no buffer de qualquer um dos dois lados dele
        # (gap < buffer). O `<`/`>` estrito deixa a adjacência de gap == buffer reservável (espelha
        # `new.inicio < f2 + buffer AND i2 < new.fim + buffer` do gate da reserva, ADR 0025).
        conflito = next(
            (b for b in blocos if b["inicio"] - _halo(b) < cand < b["fim"] + _halo(b)), None
        )
        if conflito is None:
            break
        cand = _arredonda_meia_hora_acima(conflito["fim"] + _halo(conflito))
    else:
        return None
    if not regras_cobrem(regras_disp, cand):
        return None
    return cand


def piso_com_hora_ofertada(
    piso: datetime,
    horas_em_pauta: Iterable[time],
    agora_brt: datetime,
    blocos: list[dict[str, Any]],
    regras_disp: list[dict[str, Any]],
    buffer_min: int,
    *,
    antecedencia_min: int,
) -> datetime:
    """`piso`, rebaixado até uma hora que ELA já ofertou e que segue de pé (campanha 13/08, c7).

    O `horario_minimo` é recalculado todo turno (`arredonda_acima(agora + antecedência)`) e por isso
    ANDA enquanto o cliente pensa. Em eb01:210917388210413 a IA ofertou "Consigo às 10h" quatro
    vezes com o piso em 10:00; o cliente aceitou 23 minutos depois ("10h tá ótimo") com o piso já em
    10:30, e ela negou a própria oferta no turno do fechamento ("às 10h não consigo não"). Em
    produção é pior: 40-50 min entre turnos é o normal, e o horário combinado evapora sozinho.

    O piso vale para horário NOVO; o que ela já pôs na mesa não é invalidado por ele. Uma hora em
    pauta só rebaixa o piso se sobreviver a TRÊS testes, todos determinísticos e todos por baixo:
      - é FUTURA pela régua REAL do tipo (`antecedencia_min` = `antecedencia_min_por_tipo` do tipo
        gravado, sem o bump conservador que o piso publicado aplica contra um flip de tipo dentro do
        turno): compromisso já feito se julga pela régua que a RESERVA vai aplicar, e o conservador
        existe só para a oferta espontânea (o comentário do `horario_minimo` em `prepare_context`);
      - é MENOR que o piso — subir o piso não é trabalho desta função;
      - continua reservável na agenda (`proximo_livre` com `lead_min=0` devolvendo ela mesma):
        bloqueio novo em cima dela, buffer de vizinho ou fim de expediente derrubam a exceção. O
        bloqueio do PRÓPRIO atendimento não conta — a query do `prepare_context` já o exclui.

    Sem hora em pauta que passe nos três, devolve o `piso` intacto (fail-closed). `agora_brt` e o
    retorno ficam no fuso de `agora_brt` — quem imprime aplica o filtro `brt` do mesmo jeito.
    """
    limite = agora_brt + timedelta(minutes=antecedencia_min)
    for hora in horas_em_pauta:
        cand = datetime.combine(agora_brt.date(), hora, tzinfo=agora_brt.tzinfo)
        if cand < limite or cand >= piso:
            continue
        if proximo_livre(cand, blocos, regras_disp, buffer_min, lead_min=0) != cand:
            continue
        piso = cand
    return piso
