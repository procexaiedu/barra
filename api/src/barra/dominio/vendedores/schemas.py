"""DTOs HTTP do Vendedor (ADR 0012).

Vendedor é o respondente humano do número da modelo — NÃO é login e NUNCA é
exposto à IA conversacional. Gerido no painel (painel-only). O `nivel` define a
Comissão de vendedor (tabela `financeiro_comissao_niveis`); o percentual em si não
mora aqui — muda a config, muda a projeção (sem snapshot por vendedor).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

VendedorNivel = Literal["iniciante", "intermediario", "avancado"]


class VendedorResponse(BaseModel):
    id: UUID
    nome: str
    nivel: VendedorNivel
    ativo: bool
    created_at: str  # iso
    updated_at: str  # iso


class VendedoresListaResponse(BaseModel):
    items: list[VendedorResponse]


class VendedorCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    nivel: VendedorNivel = "iniciante"


class VendedorPatch(BaseModel):
    """Patch parcial; o service usa `model_fields_set` (exclude_unset) para só
    tocar os campos enviados. `ativo=false` é a desativação (soft-delete): o
    vendedor some dos seletores mas preserva o histórico de comissão/atendimentos.
    """

    nome: str | None = Field(default=None, min_length=1, max_length=200)
    nivel: VendedorNivel | None = None
    ativo: bool | None = None
