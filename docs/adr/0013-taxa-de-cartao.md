---
status: accepted
---

# Taxa de cartão

O cliente que paga no cartão é cobrado ~10% a mais para cobrir o custo da maquininha ("quando o cara vai passar no cartão, eu já cobro ele 10% que é a taxa"), e às vezes essa taxa é isentada (cliente VIP, valor alto). Decidimos registrar a taxa como **snapshot por atendimento** (espelhando `percentual_repasse_snapshot`), manter o **Valor final** como o bruto pago pelo cliente, e calcular repasse da modelo e **Comissão de vendedor** sobre o **valor do serviço** (Valor final − taxa) — não sobre o bruto inflado. O custo real do gateway fica **fora do sistema** no P0, então não decidimos aqui se a taxa vira margem (Fernando: "não sei") — o sistema só registra o que foi cobrado.

## Decisões

- **Taxa configurável, cobrada por cima, isentável por atendimento.** Default ~10% (configurável); o cliente paga `serviço × (1 + taxa/100)`. Toggle "isentar taxa" por atendimento para casos especiais. Só se aplica quando `forma_pagamento='cartao'` (valor já existente no enum — migration `20260525210732`).
- **`Valor final` continua sendo o bruto pago pelo cliente** (definição do CONTEXT.md, intocada), incluindo a taxa quando cobrada. Adicionamos `atendimentos.taxa_cartao_snapshot numeric` (percentual aplicado; NULL/0 quando não houve taxa) — mesmo padrão de snapshot do `percentual_repasse_snapshot`, para o histórico não mudar se o default da taxa mudar depois.
- **Repasse e comissão incidem sobre o valor do serviço**, não sobre o bruto: `serviço = valor_final / (1 + taxa_cartao_snapshot/100)`. Repasse da modelo = `serviço × percentual_repasse_snapshot/100`; **Comissão de vendedor** (ADR 0012) idem. A taxa nunca entra nessas bases.
- **A taxa cobrada do cliente é registrada e exibida como linha informativa**, não como receita garantida. O custo real do gateway não é modelado no P0 (vive fora do sistema; Fernando não sabe a alíquota real), então "margem do cartão" não é calculável agora e fica para o P1 (modelar o custo do gateway).
- **Parcelamento deferido (P1).** Cronograma de recebimento por parcela não entra no P0 — registra-se o fechamento como um valor único, como hoje.

## Considered Options

- **Redefinir `Valor final` como valor do serviço + campo separado de bruto pago.** Rejeitado: `Valor final = bruto pago` é o contrato do CONTEXT.md e a base de toda a projeção do **Módulo Financeiro** (ADR 0011) e do snapshot de repasse; mudar o significado quebra essas queries. Snapshot da taxa + derivar o serviço é menos invasivo.
- **Taxa fixa não configurável.** Rejeitado: Fernando isenta em casos VIP/valor alto — precisa ser por-atendimento, com default configurável.
- **Repasse/comissão sobre o `Valor final` bruto.** Rejeitado: repassaria/comissionaria a taxa da maquininha; a base correta é o serviço vendido.
- **Modelar o custo do gateway agora para apurar margem do cartão.** Rejeitado no P0: Fernando não sabe a alíquota real e ela vive fora do sistema; sem ela a margem não é calculável. Deferido.

## Consequences

- **`atendimentos` ganha `taxa_cartao_snapshot`** (migration manual no prod self-hosted — nunca `make migrate`; ver memória `migrations_pendentes_prod_selfhosted`). O default da taxa fica em config (settings no P0; tabela editável se a UI exigir).
- **Pré-requisito da Comissão de vendedor (ADR 0012):** a base "líquido de taxa" depende deste snapshot. **Sequenciar a task 6 (taxa) antes da task 5 (comissão)**; enquanto a taxa não existir, repasse/comissão usam o `valor_final` direto.
- **Módulo Financeiro (ADR 0011) muda a fórmula:** onde hoje usa `valor_final` como bruto, passa a usar o **valor do serviço** (`valor_final − taxa`) como receita e base de repasse; a taxa cobrada vira linha informativa separada (não receita no P0). Atualizar `dominio/financeiro/repo.py` e alinhar com o bloco financeiro do dashboard (mesmo número).
- **UI do fechamento:** ao escolher cartão, mostra o breakdown ("serviço R$X + taxa Y% = total R$Z") e o toggle "isentar taxa".
- **Pagamento parcial (parte cartão, parte dinheiro/pix)** não é tratado no P0 — uma forma por atendimento, como hoje.
