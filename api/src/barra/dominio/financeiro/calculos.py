"""Fórmulas canônicas do Módulo Financeiro (ADRs 0011 / 0012 / 0013).

Single source of truth das fórmulas de **valor do serviço**, **repasse da modelo** e
**Comissão de vendedor**. Funções puras (testáveis offline) + a expressão SQL equivalente do
valor do serviço, para os repos não divergirem da versão Python.

Regras (CONTEXT.md / ADR 0013 §13 / ADR 0012 §15):
- Valor final = bruto pago pelo cliente, INCLUI a taxa de cartão quando cobrada.
- Valor do serviço = `valor_final / (1 + taxa/100)` (taxa NULL/0 → serviço == bruto).
- Repasse e comissão incidem SOBRE O SERVIÇO, nunca sobre o bruto inflado pela taxa,
  nunca sobre o Pix de deslocamento (que não entra em valor_final).
- Repasse e comissão são custos INDEPENDENTES: nenhum desconta o outro.
- Só `Fechado` conta (garantido pelo filtro de estado nas queries que chamam isto).
"""

from __future__ import annotations

# Expressão SQL do valor do serviço a partir de (valor_final, taxa_cartao_snapshot).
# Idêntica à `valor_servico()` abaixo — manter sincronizadas, divergir = bug (ADR 0013).
# `a` é o alias da tabela atendimentos na query que interpola isto.
VALOR_SERVICO_SQL = "(a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100))"


def valor_servico(valor_final: float, taxa_cartao_pct: float | None) -> float:
    """Valor do serviço = bruto descontada a taxa de cartão (ADR 0013).

    `taxa_cartao_pct` None ou 0 → serviço == bruto (pix/dinheiro, ou cartão isento).
    """
    taxa = taxa_cartao_pct or 0.0
    return valor_final / (1 + taxa / 100.0)


def repasse_modelo(
    valor_final: float, taxa_cartao_pct: float | None, percentual_repasse: float | None
) -> float:
    """Repasse da modelo = percentual_repasse x valor do serviço (ADR 0011 + 0013).

    `percentual_repasse` None (sem snapshot) → 0.0 (fecha com repasse pendente; ADR 0011).
    """
    servico = valor_servico(valor_final, taxa_cartao_pct)
    return servico * (percentual_repasse or 0.0) / 100.0


def comissao_vendedor(
    valor_final: float, taxa_cartao_pct: float | None, percentual_comissao: float | None
) -> float:
    """Comissão de vendedor = percentual do nível x valor do serviço (ADR 0012).

    Mesma base do repasse (líquido de taxa) e INDEPENDENTE dele — nenhum desconta o outro.
    `percentual_comissao` None (atendimento conduzido pela IA, sem vendedor → sem nível) → 0.0.
    """
    servico = valor_servico(valor_final, taxa_cartao_pct)
    return servico * (percentual_comissao or 0.0) / 100.0
