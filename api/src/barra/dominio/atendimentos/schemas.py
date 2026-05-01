from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DevolverRequest(BaseModel):
    observacao: str | None = None


class FecharRequest(BaseModel):
    valor_final: Decimal = Field(ge=0)


class PerderRequest(BaseModel):
    motivo: Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"]
    observacao: str | None = None

    @model_validator(mode="after")
    def validar_outro(self) -> "PerderRequest":
        if self.motivo == "outro" and not self.observacao:
            raise ValueError("observacao obrigatoria quando motivo=outro")
        return self


class CorrigirRegistroRequest(BaseModel):
    novo_resultado: Literal["Fechado", "Perdido"]
    valor_final: Decimal | None = Field(default=None, ge=0)
    motivo: Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None = None
    observacao: str | None = None
    confirmar_alteracao_bloqueio_finalizado: bool = False
