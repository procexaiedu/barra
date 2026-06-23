import re
from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

CorPele = Literal["branca", "parda", "negra", "asiatica", "outra"]
CorCabelo = Literal["loiro", "castanho", "preto", "ruivo", "colorido", "outro"]
Signo = Literal[
    "aries",
    "touro",
    "gemeos",
    "cancer",
    "leao",
    "virgem",
    "libra",
    "escorpiao",
    "sagitario",
    "capricornio",
    "aquario",
    "peixes",
]
NivelModelo = Literal["A", "B", "C"]


def _normalizar_instagram(valor: str | None) -> str | None:
    """Normaliza @/URL para o handle '@usuario'. None/vazio → None."""
    if valor is None:
        return None
    bruto = valor.strip()
    if not bruto:
        return None
    # Tira protocolo/domínio/caminho de URLs do Instagram, mantendo só o usuário.
    bruto = re.sub(r"^https?://", "", bruto, flags=re.IGNORECASE)
    bruto = re.sub(r"^(www\.)?instagram\.com/", "", bruto, flags=re.IGNORECASE)
    handle = bruto.strip("/").split("/", 1)[0].split("?", 1)[0].lstrip("@").strip()
    if not handle:
        return None
    return f"@{handle}"


def _validar_email(valor: str | None) -> str | None:
    """Validação leve de formato de e-mail. None/vazio → None."""
    if valor is None:
        return None
    bruto = valor.strip()
    if not bruto:
        return None
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", bruto):
        raise ValueError("E-mail inválido")
    return bruto


InstagramField = Annotated[str | None, AfterValidator(_normalizar_instagram)]
EmailField = Annotated[str | None, AfterValidator(_validar_email)]


def _validar_cpf(valor: str | None) -> str | None:
    """Normaliza para 11 dígitos e valida os dígitos verificadores (ADR 0007)."""
    if valor is None:
        return None
    digitos = "".join(ch for ch in valor if ch.isdigit())
    if not digitos:
        return None
    if len(digitos) != 11:
        raise ValueError("CPF deve ter 11 dígitos")
    if digitos == digitos[0] * 11:
        raise ValueError("CPF inválido")

    def _dv(base: str) -> int:
        peso = len(base) + 1
        soma = sum(int(d) * (peso - i) for i, d in enumerate(base))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    if _dv(digitos[:9]) != int(digitos[9]) or _dv(digitos[:10]) != int(digitos[10]):
        raise ValueError("CPF inválido")
    return digitos


CpfField = Annotated[str | None, AfterValidator(_validar_cpf)]


class ModeloCreate(BaseModel):
    nome: str
    idade: int = Field(gt=0)
    numero_whatsapp: str
    valor_padrao: Decimal = Field(ge=0)
    percentual_repasse: Decimal | None = Field(default=None, ge=0, le=100)
    # Vendedor padrão (ADR 0012): o atendimento herda na criação. NULL = IA conduz (sem comissão).
    vendedor_id: UUID | None = None
    chave_pix: str | None = None
    titular_chave: str | None = None
    idiomas: list[str] = Field(default_factory=lambda: ["pt-BR"])
    localizacao_operacional: str | None = None
    endereco_formatado: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = None
    tipo_atendimento_aceito: list[str]
    tipo_fisico: str | None = None
    # Ficha cadastral pessoal (ADR 0007) — painel-only, não alimenta breakdown/persona.
    rg: str | None = None
    cpf: CpfField = None
    endereco_residencial_formatado: str | None = None
    place_id_residencial: str | None = None
    cor_pele: CorPele | None = None
    cor_cabelo: CorCabelo | None = None
    altura_cm: int | None = Field(default=None, ge=100, le=230)
    tamanho_pe: int | None = Field(default=None, ge=28, le=50)
    peso_kg: Decimal | None = Field(default=None, ge=30, le=200)
    cintura_cm: int | None = Field(default=None, ge=40, le=120)
    signo: Signo | None = None
    instagram: InstagramField = None
    email: EmailField = None


class ModeloPatch(BaseModel):
    nome: str | None = None
    idade: int | None = Field(default=None, gt=0)
    numero_whatsapp: str | None = None
    valor_padrao: Decimal | None = Field(default=None, ge=0)
    percentual_repasse: Decimal | None = Field(default=None, ge=0, le=100)
    # Vendedor padrão (ADR 0012). Enviar null limpa (IA conduz, sem comissão).
    vendedor_id: UUID | None = None
    chave_pix: str | None = None
    titular_chave: str | None = None
    idiomas: list[str] | None = None
    localizacao_operacional: str | None = None
    endereco_formatado: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = None
    tipo_atendimento_aceito: list[str] | None = None
    tipo_fisico: str | None = None
    status: str | None = None
    coordenacao_chat_id: str | None = None
    # Ficha cadastral pessoal (ADR 0007).
    rg: str | None = None
    cpf: CpfField = None
    endereco_residencial_formatado: str | None = None
    place_id_residencial: str | None = None
    cor_pele: CorPele | None = None
    cor_cabelo: CorCabelo | None = None
    altura_cm: int | None = Field(default=None, ge=100, le=230)
    tamanho_pe: int | None = Field(default=None, ge=28, le=50)
    peso_kg: Decimal | None = Field(default=None, ge=30, le=200)
    cintura_cm: int | None = Field(default=None, ge=40, le=120)
    signo: Signo | None = None
    instagram: InstagramField = None
    email: EmailField = None
    # Nível A/B/C — atribuído na edição, painel-only. NUNCA entra na persona/contexto da IA.
    nivel: NivelModelo | None = None


class ConectarWhatsappRequest(BaseModel):
    confirmar_rotacao: bool = False


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


class DisponibilidadeRegra(BaseModel):
    data_inicio: date
    data_fim: date | None = None  # None = período aberto/indefinido
    dia_semana: int = Field(ge=0, le=6)  # 0=domingo .. 6=sábado (EXTRACT(DOW))
    hora_inicio: time
    hora_fim: time

    @model_validator(mode="after")
    def periodo_valido(self) -> "DisponibilidadeRegra":
        if self.data_fim is not None and self.data_fim < self.data_inicio:
            raise ValueError("data_fim deve ser maior ou igual a data_inicio")
        # hora_fim <= hora_inicio é permitido: janela cruza a meia-noite (ADR 0005).
        return self


class DisponibilidadeReplace(BaseModel):
    regras: list[DisponibilidadeRegra]


class VincularProgramaBody(BaseModel):
    programa_id: UUID
    duracao_id: UUID
    preco: Decimal = Field(ge=0)


class AtualizarPrecoProgramaBody(BaseModel):
    preco: Decimal = Field(ge=0)


class FeticheCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    ordem: int = 0


class FetichePatch(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=100)
    ordem: int | None = None


class VincularFeticheBody(BaseModel):
    fetiche_id: UUID
    # None = incluso (a modelo faz, sem custo extra); preenchido = extra pago.
    preco: Decimal | None = Field(default=None, ge=0)


class AtualizarPrecoFeticheBody(BaseModel):
    # None zera o preço (vira "incluso"); preenchido define o extra.
    preco: Decimal | None = Field(default=None, ge=0)
