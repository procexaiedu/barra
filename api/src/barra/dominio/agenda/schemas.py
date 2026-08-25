from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, model_validator

# Onde o compromisso acontece, no vocabulario de `atendimentos.tipo_atendimento` (o enum do banco).
# `externo` = ela se desloca -> gap maior ao redor do bloqueio (emenda ADR 0025, 2026-08-14). None
# = desconhecido: o bloqueio VINCULADO deriva do atendimento e so o AVULSO (ou um override) precisa
# declarar aqui.
TipoAtendimentoBloqueio = Literal["interno", "externo", "remoto"]


class BloqueioCreate(BaseModel):
    modelo_id: UUID
    inicio: datetime
    fim: datetime
    observacao: str | None = None
    atendimento_id: UUID | None = None
    tipo_atendimento: TipoAtendimentoBloqueio | None = None
    confirmar_fora_disponibilidade: bool = False
    confirmar_buffer: bool = False

    @model_validator(mode="after")
    def intervalo_valido(self) -> "BloqueioCreate":
        if self.inicio >= self.fim:
            raise ValueError("inicio deve ser anterior ao fim")
        return self


class BloqueioPatch(BaseModel):
    inicio: datetime | None = None
    fim: datetime | None = None
    observacao: str | None = None
    atendimento_id: UUID | None = None
    tipo_atendimento: TipoAtendimentoBloqueio | None = None
    confirmar_edicao_vinculada: bool = False
    confirmar_fora_disponibilidade: bool = False
    confirmar_buffer: bool = False


class CancelarBloqueio(BaseModel):
    confirmar: bool = Field(
        default=False,
        validation_alias=AliasChoices("confirmar", "confirmar_em_atendimento"),
    )
