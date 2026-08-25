"""Fórmulas canônicas do Módulo Financeiro (ADRs 0011 / 0012 / 0013 / 0048).

Single source of truth das fórmulas de **valor do serviço**, **repasse da modelo** e
**Comissão do telefonista** (o "Vendedor" do ADR 0012). Funções puras (testáveis offline) + as
expressões SQL equivalentes, para os repos não divergirem da versão Python.

Regras (CONTEXT.md / ADR 0013 §13 / ADR 0012 §15):
- Valor final = bruto pago pelo cliente, INCLUI a taxa de cartão quando cobrada.
- Valor do serviço = `valor_final / (1 + taxa/100)` (taxa NULL/0 → serviço == bruto).
- Repasse da modelo incide SOBRE O SERVIÇO, nunca sobre o bruto inflado pela taxa,
  nunca sobre o Pix de deslocamento (que não entra em valor_final).
- Repasse e comissão são custos INDEPENDENTES: nenhum desconta o outro.
- Só `Fechado` conta (garantido pelo filtro de estado nas queries que chamam isto).

⚠️ **A comissão do telefonista deixou de usar a base líquida em 20/08/2026** (ADR-0048 §2): ela
passa a incidir sobre o **bruto vendido**, e o percentual passa a ser o do vendedor
(`vendedores.percentual_comissao`), não o do nível. A aritmética não mudou de forma — mudou o que
os chamadores passam: `comissao_sobre_o_bruto()` é o caminho novo, e `comissao_vendedor()` com
taxa continua existindo para o histórico pré-agosto, que foi pago sobre o serviço. Duas contas de
duas épocas, uma função só; ver a docstring de `comissao_vendedor`.
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
    """Comissão do telefonista = percentual DELE x base (ADR 0012, revisto pelo ADR-0048).

    Duas decisões mudaram em 20/08/2026 e **nenhuma das duas está na assinatura** — por isso esta
    docstring é o lugar onde elas ficam legíveis:

    * **o percentual é do vendedor**, não do nível dele (ADR-0048 §1). Quem chama lê
      `vendedores.percentual_comissao`; `financeiro_comissao_niveis` sobrevive como default de
      cadastro (o nível preenche o número na criação) e parou de ser consultada no cálculo;
    * **a base é o bruto vendido** (§2), não o serviço líquido de taxa — *"do valor da venda,
      valor total que ele vendeu (…) faturamento bruto"*. É a mesma base da comissão da modelo
      (ADR-0045 §3), e o fluxo novo chega aqui por `comissao_sobre_o_bruto()`.

    **Por que a taxa entra como `None` no caminho novo:** por DECISÃO, não por ausência de dado.
    A linha tem `taxa_cartao_snapshot` preenchido e o cálculo a ignora de propósito — quem ler
    `taxa=None` no chamador não está olhando um dado que faltou, está olhando a regra do ADR-0048.

    **Por que o parâmetro sobrevive:** pelo histórico **pré-agosto/2026**. Os atendimentos
    fechados sob o ADR-0013 foram comissionados sobre o serviço líquido, e reprojetar aqueles
    meses com base bruta reescreveria comissão já paga. Quem projeta período antigo passa a taxa;
    quem projeta o fluxo novo passa `None`. Não é parâmetro morto, é a chave da época.

    **Deslocamento nunca entra na base** (§3): é reembolso de custo, não serviço vendido. Ele nem
    aparece aqui — não está em `atendimentos.valor_final` nem em `vendas_registradas.valor`, mora
    em `deslocamentos_da_venda`. Somar um "valor total" que já inclua o Uber é o único jeito de
    inflar esta conta, e é o que a base do chamador tem que evitar.

    `percentual_comissao` None → 0.0: atendimento conduzido pela IA, ou autor da mensagem que o
    cadastro não conhece (§5). Venda sem vendedor não gera comissão — nunca se chuta o percentual.

    Projeção, sem snapshot por venda (§6): mudou a config, mudou a projeção, inclusive a das
    vendas passadas. É o padrão do Módulo Financeiro e o oposto do `percentual_repasse_snapshot`
    da modelo, que é negociado com ela.

    INDEPENDENTE do repasse: nenhum dos dois desconta o outro.
    """
    servico = valor_servico(valor_final, taxa_cartao_pct)
    return servico * (percentual_comissao or 0.0) / 100.0


def comissao_sobre_o_bruto(valor_bruto: float, percentual_comissao: float | None) -> float:
    """A comissão do telefonista do fluxo novo: percentual dele x **bruto vendido** (ADR-0048 §2).

    Um nome para a decisão, e não um `None` solto repetido em cada chamador: aqui a taxa de cartão
    é ignorada de propósito (a linha tem o dado), e é isso que o nome diz. `valor_bruto` é
    `vendas_registradas.valor` ou `atendimentos.valor_final` — o que o cliente pagou, taxa dentro,
    deslocamento fora.
    """
    return comissao_vendedor(valor_bruto, None, percentual_comissao)


def comissao_sql(bruto: str, percentual: str) -> str:
    """A expressão SQL equivalente a `comissao_sobre_o_bruto` — divergir das duas é bug (ADR 0013).

    Existe pelo mesmo motivo de `VALOR_SERVICO_SQL`: a soma é do Postgres (`SUM` sobre milhares de
    linhas), a regra é daqui. Recebe os identificadores das colunas porque as duas fontes do
    ADR-0048 §4 têm alias diferente — `atendimentos.valor_final` e `vendas_registradas.valor`.

    O `COALESCE(..., 0)` é o `None → 0.0` da função pura: com LEFT JOIN em `vendedores`, venda sem
    vendedor rende comissão zero em vez de NULL contaminando a soma inteira.

    NÃO arredonda: quem agrega decide onde o `round(…, 2)` entra (uma vez, no fim), porque
    arredondar linha a linha e somar dá outro centavo.
    """
    return f"({bruto} * COALESCE({percentual}, 0) / 100)"
