"""DTOs HTTP do Módulo de Tarefas (ADR 0017).

Tarefas internas da operação (estilo ClickUp), painel-only. Ator
(criador/responsável) é polimórfico `(tipo, id)` — ver `tarefa_ator_tipo`. No P0
só `usuario`/`modelo` são resolvíveis (a tabela `vendedores` do ADR 0012 ainda
não existe); `vendedor` fica reservado no enum para quando entrar.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

StatusTarefa = Literal["a_fazer", "fazendo", "feita"]
PrioridadeTarefa = Literal["baixa", "media", "alta"]
AtorTipo = Literal["usuario", "modelo", "vendedor"]
PrazoFiltro = Literal["hoje", "semana", "atrasadas", "todos"]


class AtorRef(BaseModel):
    """Referência a um ator, com nome resolvido por JOIN na leitura.

    `nome` é None quando o ator foi removido (integridade na app, sem FK).
    """

    tipo: AtorTipo
    id: UUID
    nome: str | None


class TarefaResponse(BaseModel):
    id: UUID
    titulo: str
    descricao: str | None
    status: StatusTarefa
    prioridade: PrioridadeTarefa
    prazo: date | None
    criado_por: AtorRef
    atribuido: AtorRef | None
    concluida_em: str | None  # iso
    created_at: str
    updated_at: str


class TarefasListaResponse(BaseModel):
    items: list[TarefaResponse]


class TarefaCriar(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    descricao: str | None = Field(default=None, max_length=4000)
    prioridade: PrioridadeTarefa = "media"
    prazo: date | None = None
    # Responsável opcional: ambos preenchidos ou ambos nulos (validado no service).
    atribuido_tipo: AtorTipo | None = None
    atribuido_id: UUID | None = None


class TarefaPatch(BaseModel):
    """Patch parcial. O service usa `model_fields_set` para distinguir
    "campo não enviado" de "campo enviado como null" (permite limpar prazo/responsável).
    """

    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = Field(default=None, max_length=4000)
    status: StatusTarefa | None = None
    prioridade: PrioridadeTarefa | None = None
    prazo: date | None = None
    atribuido_tipo: AtorTipo | None = None
    atribuido_id: UUID | None = None


class ResponsavelOpcao(BaseModel):
    """Opção do seletor de responsável (rótulo de execução; não controla acesso)."""

    tipo: AtorTipo
    id: UUID
    nome: str


class ResponsaveisResponse(BaseModel):
    items: list[ResponsavelOpcao]
