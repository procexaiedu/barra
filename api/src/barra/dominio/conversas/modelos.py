"""Entidades e value objects do contexto Conversas.

Conversa cliente: par cliente-modelo no número da modelo. IA conduz até handoff.
Vide CONTEXT.md e docs/mvp/06-dados-interfaces.md.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class DirecaoMensagem(StrEnum):
    cliente = "cliente"
    ia = "ia"
    modelo_manual = "modelo_manual"


class Conversa(BaseModel):
    id: UUID
    cliente_id: UUID
    modelo_id: UUID
    ia_pausada: bool = False
    criada_em: datetime
    atualizada_em: datetime


class Mensagem(BaseModel):
    id: UUID
    conversa_id: UUID
    direcao: DirecaoMensagem
    texto: str | None
    midia_url: str | None = None
    criada_em: datetime
