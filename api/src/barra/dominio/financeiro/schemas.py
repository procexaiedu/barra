"""DTOs HTTP do Módulo Financeiro (ADR 0011).

Receita é projeção de `atendimentos` (sem tabela própria). Despesas e repasses
têm tabelas; ver `infra/sql/{ts}_financeiro.sql`.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

CategoriaDespesa = Literal[
    "anuncios",
    "software",
    "infraestrutura",
    "juridico",
    "taxas",
    "deslocamento",
    "pessoal",
    "outro",
]

# Repasse à modelo: enum SQL é forma_pagamento_enum (pix/dinheiro/cartao/outro);
# para repasse restringimos cartão via Pydantic (ADR 0011).
FormaPagamentoRepasse = Literal["pix", "dinheiro", "outro"]
FormaPagamentoReceita = Literal["pix", "dinheiro", "cartao", "outro"]


# ----------------------- Resumo / visão geral -------------------------------


class FinanceiroResumo(BaseModel):
    valor_bruto_brl: float
    valor_liquido_brl: float
    valor_repasse_calculado_brl: float
    valor_sem_repasse_definido_brl: float
    valor_repasse_pago_brl: float
    valor_saldo_repasse_brl: float
    valor_despesas_brl: float
    fechamentos_total: int
    fechamentos_sem_snapshot: int


class JanelaComparacao(BaseModel):
    de: str
    ate: str


class FinanceiroResumoResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    janela_comparacao: JanelaComparacao | None
    resumo: FinanceiroResumo
    resumo_anterior: FinanceiroResumo | None


# ----------------------- Receitas (projeção) --------------------------------


class ReceitaLinha(BaseModel):
    atendimento_id: UUID
    numero_curto: int
    fechado_em: str  # iso BRT
    modelo_id: UUID
    modelo_nome: str
    cliente_id: UUID
    cliente_nome: str
    forma_pagamento: FormaPagamentoReceita | None
    valor_bruto: float
    percentual_repasse_snapshot: float | None
    valor_repasse_calculado: float


class ReceitasListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[ReceitaLinha]
    next_cursor: str | None


# ----------------------- Despesas (pontuais + recorrentes) ------------------


class DespesaCriar(BaseModel):
    categoria: CategoriaDespesa
    valor: Decimal = Field(gt=0)
    data: date
    descricao: str | None = None


class DespesaPatch(BaseModel):
    categoria: CategoriaDespesa | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    data: date | None = None
    descricao: str | None = None


class DespesaLinha(BaseModel):
    """Despesa exibida na lista. Pode ser:
    - pontual: `recorrente_id`/`competencia_mes` NULL, `origem='pontual'`;
    - materializada: ambos preenchidos, `origem='recorrente_materializada'`;
    - projetada: linha sintetizada de template (sem id real), `origem='recorrente_projetada'`.
    """

    id: UUID | None  # NULL para linhas projetadas
    categoria: CategoriaDespesa
    valor: Decimal
    data: date
    descricao: str | None
    recorrente_id: UUID | None
    competencia_mes: date | None
    origem: Literal["pontual", "recorrente_materializada", "recorrente_projetada"]
    # quando projetada, valor pode divergir do template (não, mas inclui para futura mudança)
    valor_template: Decimal | None = None


class DespesasListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[DespesaLinha]
    next_cursor: str | None


class DespesaRecorrenteCriar(BaseModel):
    categoria: CategoriaDespesa
    valor: Decimal = Field(gt=0)
    descricao: str = Field(min_length=1)
    dia_do_mes: int = Field(ge=1, le=28)
    ativo_desde: date  # validamos 1º do mês no service para mensagem clara

    @model_validator(mode="after")
    def ativo_desde_no_primeiro_dia(self) -> "DespesaRecorrenteCriar":
        if self.ativo_desde.day != 1:
            raise ValueError("ativo_desde deve ser o primeiro dia do mês")
        return self


class DespesaRecorrentePatch(BaseModel):
    categoria: CategoriaDespesa | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    descricao: str | None = Field(default=None, min_length=1)
    dia_do_mes: int | None = Field(default=None, ge=1, le=28)


class DespesaRecorrenteResponse(BaseModel):
    id: UUID
    categoria: CategoriaDespesa
    valor: Decimal
    descricao: str
    dia_do_mes: int
    ativo_desde: date
    inativo_em: date | None
    created_at: str
    updated_at: str


# Materialização: Fernando edita uma projeção (template + mês) → criar pontual amarrada.
class MaterializarRecorrenteBody(BaseModel):
    recorrente_id: UUID
    competencia_mes: date  # validamos 1º do mês no service

    @model_validator(mode="after")
    def competencia_no_primeiro_dia(self) -> "MaterializarRecorrenteBody":
        if self.competencia_mes.day != 1:
            raise ValueError("competencia_mes deve ser o primeiro dia do mês")
        return self


# ----------------------- Repasses pagos -------------------------------------


class RepassePagoCriar(BaseModel):
    modelo_id: UUID
    data_pagamento: date
    valor: Decimal = Field(gt=0)
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None = None
    comprovante_object_key: str | None = None  # opcional; upload separado


class RepassePagoPatch(BaseModel):
    data_pagamento: date | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    forma_pagamento: FormaPagamentoRepasse | None = None
    observacao: str | None = None
    comprovante_object_key: str | None = None


class RepassePagoResponse(BaseModel):
    id: UUID
    modelo_id: UUID
    modelo_nome: str | None  # JOIN
    data_pagamento: date
    valor: Decimal
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None
    comprovante_object_key: str | None
    created_at: str
    updated_at: str


class RepassesPagamentosListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[RepassePagoResponse]
    next_cursor: str | None


# ----------------------- Repasses: saldo por modelo -------------------------


class SaldoModelo(BaseModel):
    modelo_id: UUID
    modelo_nome: str
    fechamentos_total: int
    valor_bruto: float
    valor_repasse_calculado: float
    valor_repasse_pago: float
    saldo: float  # calc - pago; pode ser negativo apos estorno (decisao T)
    fechamentos_sem_snapshot: int
    valor_sem_snapshot: float


class RepassesPorModeloResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[SaldoModelo]


# ----------------------- Preencher percentual retroativo --------------------


class AtendimentoSemSnapshotLinha(BaseModel):
    atendimento_id: UUID
    numero_curto: int
    fechado_em: str
    cliente_nome: str
    valor_bruto: float


class AtendimentosSemSnapshotResponse(BaseModel):
    modelo_id: UUID
    items: list[AtendimentoSemSnapshotLinha]


class PreencherRepasseRetroativoBody(BaseModel):
    atendimento_ids: list[UUID] = Field(min_length=1)
    percentual: Decimal = Field(ge=0, le=100)


class PreencherRepasseRetroativoResponse(BaseModel):
    atualizados: int


# ----------------------- Upload de comprovante ------------------------------


class ComprovanteUploadResponse(BaseModel):
    object_key: str
    put_url: str  # presigned PUT


class ComprovanteUrlResponse(BaseModel):
    url: str  # presigned GET, expira
