"""DTOs HTTP do contexto Conversas (request/response da API)."""

from uuid import UUID

from pydantic import BaseModel

from barra.dominio.conversas.modelos import Conversa, Mensagem


class ConversaResposta(BaseModel):
    conversa: Conversa
    mensagens: list[Mensagem]


class DevolverParaIA(BaseModel):
    conversa_id: UUID
    autor: str  # "fernando" | "modelo:<modelo_id>"
