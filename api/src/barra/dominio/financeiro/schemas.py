"""DTOs HTTP do Módulo Financeiro (ADR 0011).

Receita é projeção de `atendimentos` (sem tabela própria). Repasses pagos têm
tabela própria; ver `infra/sql/{ts}_financeiro.sql`. Despesas foram removidas
do escopo do módulo (ver nota de Update no ADR 0011).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    fechamentos_total: int
    fechamentos_sem_snapshot: int


class JanelaComparacao(BaseModel):
    de: str
    ate: str


class ImportadosSemData(BaseModel):
    """Fechados sem data (sem evento `fechado_registrado`) — ficam fora do recorte
    por período. Bruto total, independente da janela e respeitando só o modelo."""

    contagem: int
    valor_bruto_brl: float


class FinanceiroResumoResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    janela_comparacao: JanelaComparacao | None
    resumo: FinanceiroResumo
    resumo_anterior: FinanceiroResumo | None
    importados_sem_data: ImportadosSemData


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


# ----------------------- Contexto do inspector ------------------------------


class ContextoCliente(BaseModel):
    """Agregados cross-modelo do cliente — painel-only (ADR 0008)."""

    cliente_id: UUID
    nome: str
    total_atendimentos: int
    total_fechados: int
    valor_total_brl: float
    ultima_atividade_iso: str | None
    modelos_distintas: int


class ContextoModeloDia(BaseModel):
    dia: str  # AAAA-MM-DD
    bruto: float


class ContextoModelo(BaseModel):
    """Agregados da modelo: posição no período + sparkline 30d (absolutos)."""

    modelo_id: UUID
    nome: str
    fechamentos_periodo: int
    valor_bruto_periodo: float
    valor_repasse_periodo: float
    serie_30d: list[ContextoModeloDia]


class ReceitaContextoResponse(BaseModel):
    """Contexto completo da linha de receita (inspector lateral)."""

    atendimento_id: UUID
    cliente: ContextoCliente
    modelo: ContextoModelo


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


# ----------------------- Série / visão geral analítica ----------------------


class FinanceiroSerieDia(BaseModel):
    """Agregado diário do período. Dias sem fechamento aparecem com zeros."""

    dia: str  # AAAA-MM-DD (BRT)
    bruto: float
    repasse_calculado: float
    liquido: float
    fechamentos: int


class FinanceiroMixForma(BaseModel):
    """Distribuição da receita bruta por forma de pagamento (apenas Fechado)."""

    forma_pagamento: str  # pix | dinheiro | cartao | outro | indefinido
    valor_bruto: float
    fechamentos: int


class FinanceiroTopModelo(BaseModel):
    """Top contribuintes do período, ordenado por bruto decrescente."""

    modelo_id: UUID
    modelo_nome: str
    bruto: float
    liquido: float
    repasse_calculado: float
    fechamentos: int


class FinanceiroSerieResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    serie_diaria: list[FinanceiroSerieDia]
    mix_forma_pagamento: list[FinanceiroMixForma]
    top_modelos: list[FinanceiroTopModelo]


# ----------------------- Comissão de vendedor (ADR 0012) --------------------


class SaldoVendedor(BaseModel):
    """Saldo de comissão por vendedor (espelha SaldoModelo do repasse)."""

    vendedor_id: UUID
    vendedor_nome: str
    nivel: str
    fechamentos_total: int
    valor_servico: float  # base liquida de taxa de cartao (ADR 0013)
    valor_comissao_calculada: float
    valor_comissao_paga: float
    saldo: float  # calc - pago; pode ser negativo apos estorno


class ComissoesPorVendedorResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[SaldoVendedor]
