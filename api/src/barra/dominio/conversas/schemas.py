from pydantic import BaseModel, Field


class ConversaPatch(BaseModel):
    observacoes_internas: str | None = Field(default=None, max_length=2000)
