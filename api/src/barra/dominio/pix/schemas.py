from typing import Literal

from pydantic import BaseModel, Field


class RecusarPixRequest(BaseModel):
    motivo: str


MotivoRejeicao = Literal[
    "valor_incorreto",
    "comprovante_ilegivel",
    "conta_destino_errada",
    "duplicado",
    "fora_da_janela",
    "outro",
]


class RejeitarPixRequest(BaseModel):
    motivo: MotivoRejeicao
    observacao: str | None = Field(default=None, max_length=500)


class AprovarPixRequest(BaseModel):
    pass


class ReabrirPixRequest(BaseModel):
    pass
