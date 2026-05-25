from pydantic import BaseModel, Field


class ClienteCreate(BaseModel):
    nome: str | None = Field(default=None, max_length=200)
    telefone: str = Field(min_length=1, max_length=32)
    perfis_preferidos: list[str] = Field(default_factory=list)


class ClientePatch(BaseModel):
    nome: str | None = Field(default=None, max_length=200)
    telefone: str | None = Field(default=None, max_length=32)
    perfis_preferidos: list[str] | None = None
