"""DTOs do relatorio de graduacao (ADR-0034).

`atende` e tri-estado de proposito: `True`/`False` quando o dado responde, `None` quando o
criterio e INDETERMINAVEL (sem baseline registrado, sem semana suficiente para tendencia, piloto
sem trafego). Colapsar indeterminavel em `False` faria o relatorio mentir na direcao mais cara:
"nao atende" convida a esperar mais dados, enquanto o problema real e que falta INSTRUMENTO --
e instrumento que falta ninguem descobre esperando.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Tendencia = Literal["caindo", "estavel", "subindo", "indeterminada"]
# Como o inicio da janela do piloto foi obtido: derivado do banco, passado na linha de comando,
# ou inexistente (nenhum turno da IA para cliente real -- a porta ainda esta fechada).
OrigemInicio = Literal["derivado", "informado", "ausente"]


class CriterioConversas(BaseModel):
    """Criterio 1 -- >= 100 conversas completas conduzidas pela IA."""

    atende: bool | None
    limiar: int
    # "Completa" = a conversa tem pelo menos um Atendimento que chegou a estado TERMINAL
    # (Fechado/Perdido) -- o ciclo comercial rodou inteiro. Ver o gap `conversa_completa`.
    completas: int
    # Superconjunto: conversas com QUALQUER atendimento na janela, terminal ou nao.
    com_atendimento: int
    # Conversas cujo unico atendimento ainda esta em curso -- viram `completas` quando fecharem.
    em_curso: int


class CriterioIncidentes(BaseModel):
    """Criterio 2 -- zero incidente critico nao-contido."""

    atende: bool | None
    # Turnos JA ENVIADOS em que o judge pos-envio viu rastro de LLM (`julgamentos_turno`).
    total: int
    # Recorte de triagem: `tratado_em IS NULL` vs preenchido. O criterio do ADR e "zero"
    # historico, entao gateia pelo TOTAL; a quebra existe para o leitor ver o que ja foi diagnosticado.
    abertos: int
    triados: int
    # Denominador da amostra: turnos que o judge conseguiu julgar na janela.
    turnos_julgados: int


class SemanaGate(BaseModel):
    """Uma semana da serie da taxa do gate."""

    semana: date
    aborts: int
    julgados: int
    universo: int
    taxa: float


class CriterioTaxaGate(BaseModel):
    """Criterio 3 -- taxa do gate estavel ou caindo."""

    atende: bool | None
    tendencia: Tendencia
    # Inclinacao da reta de minimos quadrados sobre a serie semanal, em PONTOS PERCENTUAIS
    # por semana. Positiva = gate abortando mais.
    inclinacao_pp_semana: float | None
    taxa_atual: float | None
    semanas: list[SemanaGate]


class CriterioConversao(BaseModel):
    """Criterio 4 -- conversao da IA >= 80% do baseline do vendedor."""

    atende: bool | None
    fechados: int
    terminais: int
    conversao_pct: float | None
    baseline_pct: float | None
    baseline_fonte: str | None
    baseline_amostra_n: int | None
    baseline_registrado_em: datetime | None
    # conversao_pct / baseline_pct. O criterio bate com razao >= `limiar_razao`.
    razao: float | None
    limiar_razao: float


class RelatorioGraduacao(BaseModel):
    """Os quatro criterios do ADR-0034 num retrato do momento."""

    gerado_em: datetime
    # Inicio da janela do piloto efetivamente usado (derivado ou informado -- ver service).
    piloto_inicio_em: datetime | None
    piloto_inicio_origem: OrigemInicio
    # True so quando os QUATRO criterios respondem `atende=True`. Indeterminavel nao gradua.
    apto: bool
    conversas: CriterioConversas
    incidentes: CriterioIncidentes
    taxa_gate: CriterioTaxaGate
    conversao: CriterioConversao
    # O que o dado atual NAO responde. Cresce quando um criterio fica indeterminavel.
    gaps: list[str]
