"""Orquestracao do relatorio de graduacao do piloto (ADR-0034).

Le os quatro criterios do banco (via `repo`), aplica os limiares do ADR e devolve o retrato --
sem decidir nada: `apto=True` significa "os quatro criterios batem NO DADO", nao "gradue". A
decisao continua humana, mesma divisao do `rollback_watch` (alerta, nunca pausa sozinho).

Mudar um limiar aqui e decisao de PLANO, nao tuning: emende o ADR-0034 antes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from . import repo
from .schemas import (
    CriterioConversao,
    CriterioConversas,
    CriterioIncidentes,
    CriterioTaxaGate,
    OrigemInicio,
    RelatorioGraduacao,
    SemanaGate,
    Tendencia,
)

# Limiares do ADR-0034 ("Graduacao para mais modelos"). Fonte unica: o ADR.
LIMIAR_CONVERSAS = 100
LIMIAR_INCIDENTES = 0
LIMIAR_RAZAO_CONVERSAO = 0.80

# Tolerancia da tendencia da taxa do gate. O ADR pede "estavel ou caindo", e "estavel" precisa de
# uma faixa: numa serie curta, ruido de +0,2pp/semana nao e deterioracao. 0,5pp/semana e uma
# semana de folga sobre o proprio limiar do gatilho de rollback (20%) em 40 semanas -- larga o
# suficiente para nao reprovar por ruido, estreita o suficiente para pegar deriva real.
TOLERANCIA_INCLINACAO_PP = 0.5

# Semanas sem NENHUM turno (nem julgado, nem abortado) nao entram na serie: taxa 0/0 nao e "gate
# saudavel", e ausencia de trafego -- e uma sequencia dessas puxaria a inclinacao para baixo,
# fabricando "caindo" de um piloto parado.
_MIN_SEMANAS_TENDENCIA = 2


def _inclinacao_pp(semanas: list[SemanaGate]) -> float | None:
    """Inclinacao (pontos percentuais por semana) da reta de minimos quadrados sobre a serie.

    Indice da semana como x (a serie ja vem ordenada e so tem semanas com trafego), taxa em pp
    como y. Menos de duas semanas -> None: reta de um ponto nao tem direcao.
    """
    n = len(semanas)
    if n < _MIN_SEMANAS_TENDENCIA:
        return None
    xs = [float(i) for i in range(n)]
    ys = [s.taxa * 100.0 for s in semanas]
    media_x = sum(xs) / n
    media_y = sum(ys) / n
    denom = sum((x - media_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - media_x) * (y - media_y) for x, y in zip(xs, ys, strict=True)) / denom


def _classificar_tendencia(inclinacao: float | None) -> Tendencia:
    if inclinacao is None:
        return "indeterminada"
    if inclinacao > TOLERANCIA_INCLINACAO_PP:
        return "subindo"
    if inclinacao < -TOLERANCIA_INCLINACAO_PP:
        return "caindo"
    return "estavel"


def _montar_taxa_gate(linhas: list[dict[str, Any]]) -> CriterioTaxaGate:
    semanas: list[SemanaGate] = []
    for linha in linhas:
        # Universo = julgados + aborts. O abort nao vira julgamento (o turno nao saiu), entao os
        # dois somam em vez de um conter o outro -- mesma conta do rollback_watch.
        universo = linha["julgados"] + linha["aborts"]
        if universo == 0:
            continue
        semanas.append(
            SemanaGate(
                semana=linha["semana"],
                aborts=linha["aborts"],
                julgados=linha["julgados"],
                universo=universo,
                taxa=linha["aborts"] / universo,
            )
        )
    inclinacao = _inclinacao_pp(semanas)
    tendencia = _classificar_tendencia(inclinacao)
    return CriterioTaxaGate(
        atende=None if tendencia == "indeterminada" else tendencia in ("caindo", "estavel"),
        tendencia=tendencia,
        inclinacao_pp_semana=inclinacao,
        taxa_atual=semanas[-1].taxa if semanas else None,
        semanas=semanas,
    )


def _montar_conversao(
    numeros: dict[str, int], baseline: dict[str, Any] | None
) -> tuple[CriterioConversao, list[str]]:
    gaps: list[str] = []
    terminais = numeros["terminais"]
    fechados = numeros["fechados"]
    conversao = (fechados / terminais * 100.0) if terminais else None

    baseline_pct = baseline["conversao_pct"] if baseline else None
    razao: float | None = None
    atende: bool | None = None
    if conversao is None:
        gaps.append(
            "conversao: nenhum atendimento TERMINAL na janela do piloto -- sem denominador, a "
            "conversao da IA nao existe (nao e 0%)."
        )
    elif not baseline_pct:
        gaps.append(
            "conversao: sem baseline do vendedor registrado em `barravips.graduacao_baseline` "
            "(ou baseline igual a zero). O 4o criterio do ADR-0034 e uma RAZAO -- sem o "
            "denominador ele nao e computavel, so o numerador. Apure o percentual fora do "
            "sistema e registre-o com procedencia."
        )
    else:
        razao = conversao / baseline_pct
        atende = razao >= LIMIAR_RAZAO_CONVERSAO

    return (
        CriterioConversao(
            atende=atende,
            fechados=fechados,
            terminais=terminais,
            conversao_pct=conversao,
            baseline_pct=baseline_pct,
            baseline_fonte=baseline["fonte"] if baseline else None,
            baseline_amostra_n=baseline["amostra_n"] if baseline else None,
            baseline_registrado_em=baseline["registrado_em"] if baseline else None,
            razao=razao,
            limiar_razao=LIMIAR_RAZAO_CONVERSAO,
        ),
        gaps,
    )


# Gaps ESTRUTURAIS: valem em toda corrida, com ou sem dado. Ficam no relatorio (e nao so no ADR)
# porque quem le o numero precisa ler junto o que ele nao cobre -- foi exatamente a leitura "a
# olho" que o ADR registrou como divida.
_GAPS_ESTRUTURAIS = [
    "incidente critico: so e derivavel a leitura do judge pos-envio (`julgamentos_turno."
    "rastro_llm`) -- turno enviado com rastro de LLM. Incidente critico de OUTRA natureza "
    "(vazamento cross-modelo que o judge nao pontua, dano operacional, reclamacao do cliente "
    "fora do WhatsApp) nao tem rastro no banco e NAO entra nesta conta. 'Zero' aqui significa "
    "'zero do que o judge ve'.",
    "incidente critico: o ADR diz 'nao-contido', e a contagem cobre exatamente isso (turno JA "
    "enviado). O que o gate segurou antes do envio nunca vira julgamento -- por construcao, nao "
    "por falta de dado.",
    "taxa do gate: SUBCONTADA por construcao (ADR-0034, Consequencias) -- abort sem "
    "`atendimento_id` e abort cujo handoff ja estava aberto nao deixam linha em `escaladas`. A "
    "taxa real e >= a medida; fechar o gap exige rastro proprio em `eventos`.",
    "taxa do gate: o denominador e 'turnos julgados', nao 'turnos enviados'. Judge instavel "
    "(queda de LLM, fila parada) encolhe o denominador e INFLA a taxa -- confira a saude do "
    "judge antes de ler uma semana ruim.",
]


async def gerar_relatorio(
    conn: AsyncConnection[Any],
    *,
    desde: datetime | None = None,
) -> RelatorioGraduacao:
    """Computa os 4 criterios de graduacao do ADR-0034 sobre a janela do piloto.

    `desde` sobrescreve o inicio da janela (para reapurar um recorte); sem ele, o inicio e
    DERIVADO do primeiro turno da IA para cliente real -- ver `repo._SQL_PILOTO_INICIO`.
    """
    inicio = desde or await repo.piloto_inicio(conn)
    origem: OrigemInicio = "informado" if desde else ("derivado" if inicio else "ausente")
    gaps = list(_GAPS_ESTRUTURAIS)

    if inicio is None:
        # A porta ainda esta fechada (ADR-0034): nenhum cliente real falou com o agente. Zero aqui
        # e AUSENCIA DE SINAL, nao saude -- devolver criterios "atende=False" seria convidar a
        # esperar por dado que nao esta sendo gerado.
        gaps.append(
            "piloto: nenhum turno da IA para cliente real no banco -- a porta ainda esta fechada "
            "(JID_PERMITIDO com os grupos de teste). Sem trafego real nao ha o que graduar: os "
            "quatro criterios ficam INDETERMINADOS, nao zerados."
        )
        return RelatorioGraduacao(
            gerado_em=datetime.now(UTC),
            piloto_inicio_em=None,
            piloto_inicio_origem="ausente",
            apto=False,
            conversas=CriterioConversas(
                atende=None, limiar=LIMIAR_CONVERSAS, completas=0, com_atendimento=0, em_curso=0
            ),
            incidentes=CriterioIncidentes(
                atende=None, total=0, abertos=0, triados=0, turnos_julgados=0
            ),
            taxa_gate=CriterioTaxaGate(
                atende=None,
                tendencia="indeterminada",
                inclinacao_pp_semana=None,
                taxa_atual=None,
                semanas=[],
            ),
            conversao=CriterioConversao(
                atende=None,
                fechados=0,
                terminais=0,
                conversao_pct=None,
                baseline_pct=None,
                baseline_fonte=None,
                baseline_amostra_n=None,
                baseline_registrado_em=None,
                razao=None,
                limiar_razao=LIMIAR_RAZAO_CONVERSAO,
            ),
            gaps=gaps,
        )

    conv = await repo.conversas(conn, inicio)
    criterio_conversas = CriterioConversas(
        atende=conv["completas"] >= LIMIAR_CONVERSAS,
        limiar=LIMIAR_CONVERSAS,
        completas=conv["completas"],
        com_atendimento=conv["com_atendimento"],
        em_curso=conv["com_atendimento"] - conv["completas"],
    )

    inc = await repo.incidentes(conn, inicio)
    criterio_incidentes = CriterioIncidentes(
        atende=inc["total"] <= LIMIAR_INCIDENTES,
        total=inc["total"],
        abertos=inc["abertos"],
        triados=inc["triados"],
        turnos_julgados=inc["turnos_julgados"],
    )
    if inc["turnos_julgados"] == 0:
        # `total=0` sem NENHUM turno julgado nao e "zero incidente": e judge sem amostra. Sem esta
        # ressalva o criterio mais duro do ADR passaria de graca num piloto sem telemetria.
        criterio_incidentes = criterio_incidentes.model_copy(update={"atende": None})
        gaps.append(
            "incidente critico: nenhum turno julgado na janela -- o judge pos-envio nao produziu "
            "amostra. 'Zero incidente' aqui e ausencia de medida, nao ausencia de incidente."
        )

    criterio_taxa = _montar_taxa_gate(await repo.taxa_gate_semanal(conn, inicio))
    if criterio_taxa.tendencia == "indeterminada":
        gaps.append(
            "taxa do gate: menos de duas semanas com turno (julgado ou abortado) na janela -- "
            "sem duas leituras nao ha tendencia para chamar de estavel ou de caindo."
        )

    criterio_conversao, gaps_conversao = _montar_conversao(
        await repo.conversao_agente(conn, inicio), await repo.baseline_vendedor(conn)
    )
    gaps.extend(gaps_conversao)

    criterios = (criterio_conversas, criterio_incidentes, criterio_taxa, criterio_conversao)
    return RelatorioGraduacao(
        gerado_em=datetime.now(UTC),
        piloto_inicio_em=inicio,
        piloto_inicio_origem=origem,
        apto=all(c.atende is True for c in criterios),
        conversas=criterio_conversas,
        incidentes=criterio_incidentes,
        taxa_gate=criterio_taxa,
        conversao=criterio_conversao,
        gaps=gaps,
    )
