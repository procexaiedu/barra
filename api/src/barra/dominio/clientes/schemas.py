from pydantic import BaseModel, Field


class ClientePatch(BaseModel):
    nome: str | None = Field(default=None, max_length=200)
