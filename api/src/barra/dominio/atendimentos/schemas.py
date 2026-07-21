from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalizar_tipo_local(v: str | None) -> str | None:
    if v is None:
        return None
    limpo = v.strip().lower()
    return limpo or None


class DevolverRequest(BaseModel):
    observacao: str | None = None


class PausarRequest(BaseModel):
    observacao: str | None = None


class FecharRequest(BaseModel):
    valor_final: Decimal = Field(ge=0)
    # Taxa de cartão (ADR 0013): o backend carimba taxa_cartao_snapshot a partir de
    # settings.taxa_cartao_padrao_pct quando forma_pagamento='cartao' e a taxa não é isenta.
    # forma_pagamento confirma a forma no fechamento (alimenta o mix do Financeiro); isentar_taxa
    # zera a taxa (caso VIP/valor alto). O comando do grupo (`fechado [valor]`) não envia nada
    # disso — Fernando ajusta a taxa depois no painel (correção, que aceita % numérico).
    forma_pagamento: Literal["pix", "dinheiro", "cartao"] | None = None
    isentar_taxa: bool = False


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
    # Taxa de cartão (ADR 0013): ajustada na correção do painel (recalcula o financeiro).
    # None = sem taxa. Só faz sentido com novo_resultado=Fechado.
    taxa_cartao_snapshot: Decimal | None = Field(default=None, ge=0, le=100)
    motivo: (
        Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None
    ) = None
    observacao: str | None = None
    confirmar_alteracao_bloqueio_finalizado: bool = False


class AlterarEstadoRequest(BaseModel):
    estado: Literal["Qualificado", "Aguardando_confirmacao", "Em_execucao"]


class EditarDadosRequest(BaseModel):
    tipo_atendimento: Literal["interno", "externo", "remoto"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = None
    duracao_horas: Decimal | None = Field(default=None, ge=0)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: str | None = None
    forma_pagamento: str | None = None
    valor_acordado: Decimal | None = Field(default=None, ge=0)
    endereco_formatado: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    place_id: str | None = None

    @field_validator("tipo_local")
    @classmethod
    def _norm_tipo_local(cls, v: str | None) -> str | None:
        return _normalizar_tipo_local(v)


class AdicionarServicoRequest(BaseModel):
    programa_id: UUID
    duracao_id: UUID


class AdicionarFeticheRequest(BaseModel):
    fetiche_id: UUID


class MidiaInternaResponse(BaseModel):
    id: UUID
    tipo: Literal["imagem", "audio", "documento"]
    nome_arquivo: str
    media_object_key: str
    media_url: str | None = None
    created_at: datetime


class CriarAtendimentoRequest(BaseModel):
    cliente_id: UUID
    modelo_id: UUID
