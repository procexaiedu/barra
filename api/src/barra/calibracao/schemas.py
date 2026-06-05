"""DTOs HTTP da rotulagem de calibracao (borda HTTP; Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RodadaResumo(BaseModel):
    id: UUID
    nome: str
    created_at: datetime
    total_falas: int


class RodadasResponse(BaseModel):
    rodadas: list[RodadaResumo]


class MeuRotulo(BaseModel):
    passou: bool
    observacao: str | None = None


class FalaParaRotular(BaseModel):
    id: UUID  # PK da fala (calibracao_falas.id) — usada no PUT /rotulos
    fala_id: str  # conversa_id::idx
    conversa_id: str
    cenario: str
    texto_resposta: str
    historico: list[str]
    meu_rotulo: MeuRotulo | None = None  # so do rotulador logado (independencia)


class FalasResponse(BaseModel):
    rodada: RodadaResumo
    rotulador: str  # 'fernando' | 'socia'
    falas: list[FalaParaRotular]


class RotuloInput(BaseModel):
    fala_pk: UUID
    passou: bool
    observacao: str | None = Field(default=None, max_length=2000)


class ExportResponse(BaseModel):
    golden: str  # conteudo .jsonl (uma fala por linha) para salvar e alimentar calibrar.py
    total: int  # linhas no golden (falas rotuladas por AMBOS)
    avisos: list[str]  # ex.: falas rotuladas por so um — descartadas
