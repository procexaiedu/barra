from datetime import date, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

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


class AlterarEstadoRequest(BaseModel):
    estado: Literal["Qualificado", "Aguardando_confirmacao", "Em_execucao"]


class EditarDadosRequest(BaseModel):
    tipo_atendimento: Literal["interno", "externo"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = None
    duracao_horas: Decimal | None = Field(default=None, ge=0)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: str | None = None
    forma_pagamento: str | None = None
    valor_acordado: Decimal | None = Field(default=None, ge=0)


class AdicionarServicoRequest(BaseModel):
    programa_id: UUID
    duracao_id: UUID
