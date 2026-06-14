"""DTOs HTTP do contexto Observabilidade (borda HTTP — ver dominio/CLAUDE.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

VereditoAvaliacao = Literal["bom", "ruim"]


class MensagemTurno(BaseModel):
    conteudo: str
    created_at: datetime


class AvaliacaoResposta(BaseModel):
    veredito: VereditoAvaliacao
    nota: int | None = None
    comentario: str | None = None
    avaliado_em: datetime


class TurnoObservabilidade(BaseModel):
    """Uma resposta da IA no seu contexto, com a avaliacao humana (se houver)."""

    resposta_ia_id: UUID  # mensagens.id da resposta da IA — chave da avaliacao
    atendimento_id: UUID | None
    numero_curto: int | None
    cliente_nome: str | None
    cliente_telefone: str
    modelo_nome: str
    mensagem_cliente: MensagemTurno | None  # a ultima msg do cliente antes da resposta
    resposta_ia: MensagemTurno
    avaliacao: AvaliacaoResposta | None


class TurnosObservabilidadeResponse(BaseModel):
    items: list[TurnoObservabilidade]
    next_cursor: str | None = None


class AvaliarRequest(BaseModel):
    veredito: VereditoAvaliacao
    nota: int | None = Field(default=None, ge=1, le=5)
    comentario: str | None = Field(default=None, max_length=2000)
