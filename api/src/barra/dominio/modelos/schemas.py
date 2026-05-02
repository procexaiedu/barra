from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ModeloCreate(BaseModel):
    nome: str
    idade: int = Field(gt=0)
    numero_whatsapp: str
    valor_padrao: Decimal = Field(ge=0)
    percentual_repasse: Decimal | None = Field(default=None, ge=0, le=100)
    chave_pix: str | None = None
    titular_chave: str | None = None
    idiomas: list[str] = Field(default_factory=lambda: ["pt-BR"])
    localizacao_operacional: str | None = None
    tipo_atendimento_aceito: list[str]


class ModeloPatch(BaseModel):
    nome: str | None = None
    idade: int | None = Field(default=None, gt=0)
    numero_whatsapp: str | None = None
    valor_padrao: Decimal | None = Field(default=None, ge=0)
    percentual_repasse: Decimal | None = Field(default=None, ge=0, le=100)
    chave_pix: str | None = None
    titular_chave: str | None = None
    idiomas: list[str] | None = None
    localizacao_operacional: str | None = None
    tipo_atendimento_aceito: list[str] | None = None
    status: str | None = None
    coordenacao_chat_id: str | None = None


class ConectarWhatsappRequest(BaseModel):
    confirmar_rotacao: bool = False


class FaqBody(BaseModel):
    pergunta: str
    resposta: str
    tags: list[str] = Field(default_factory=list)


class ServicoBody(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    duracao_horas: Decimal = Field(gt=0)
    preco: Decimal = Field(ge=0)
    ativo: bool = True
    ordem: int = 0


class MidiaUploadUrlRequest(BaseModel):
    filename: str
    content_type: str


class MidiaCreate(BaseModel):
    tipo: str
    tag: str
    object_key: str
    aprovada: bool = True


class MidiaPatch(BaseModel):
    tipo: str | None = None
    tag: str | None = None
    aprovada: bool | None = None


class FotoPerfilPatch(BaseModel):
    object_key: str


class ModeloId(BaseModel):
    modelo_id: UUID


class ProgramaCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    categoria: str | None = Field(default=None, max_length=100)


class ProgramaPatch(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=100)
    categoria: str | None = Field(default=None, max_length=100)


class DuracaoCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=50)
    ordem: int = 0


class DuracaoPatch(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=50)
    ordem: int | None = None


class VincularProgramaBody(BaseModel):
    programa_id: UUID
    duracao_id: UUID
    preco: Decimal = Field(ge=0)


class AtualizarPrecoProgramaBody(BaseModel):
    preco: Decimal = Field(ge=0)
