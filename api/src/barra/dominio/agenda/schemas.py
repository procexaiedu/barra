from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, model_validator


class BloqueioCreate(BaseModel):
    modelo_id: UUID
    inicio: datetime
    fim: datetime
    observacao: str | None = None
    atendimento_id: UUID | None = None
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
    confirmar_edicao_vinculada: bool = False
    confirmar_fora_disponibilidade: bool = False
    confirmar_buffer: bool = False


class CancelarBloqueio(BaseModel):
    confirmar: bool = Field(
        default=False,
        validation_alias=AliasChoices("confirmar", "confirmar_em_atendimento"),
    )
