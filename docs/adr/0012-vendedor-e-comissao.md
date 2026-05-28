---
status: accepted
---

# Vendedor e comissão

A task 5 (comissões por nível de vendedor) revelou que a operação que de fato fatura é conduzida por **vendedores humanos** que respondem o cliente no WhatsApp se passando pela modelo — o `CONTEXT.md` assumia que "a **IA por modelo** atende o cliente". Reconciliamos: humanos atendem hoje, a IA é o futuro do mesmo assento (o respondente do número da modelo). Decidimos introduzir o **Vendedor** como ator de domínio (não login) e a **Comissão de vendedor** como custo projetado no Módulo Financeiro, sem reescrever o modelo da IA.

## Decisões

- **Vendedor é entidade de domínio, não login.** Tabela `vendedores` gerida no painel. Só Fernando e a sócia operam o sistema, com **permissão idêntica** (sem RBAC novo — ver `core/auth.py:103`). O vendedor não acessa o painel e **nunca é exposto à IA conversacional** (não é dado de persona). Distinto do papel `vendedor_read_only` do `papel_usuario_enum` (login read-only planejado para o P1); se um dia o mesmo indivíduo precisar de acesso, o vínculo entidade↔usuário vira ADR próprio.
- **Atribuição híbrida.** `modelos.vendedor_id` é o responsável padrão (nullable, FK → `vendedores`); o atendimento herda esse vendedor na criação (`atendimentos.vendedor_id`, setado em `criar_atendimento`/`garantir_atendimento_aberto`) e Fernando/sócia podem **sobrescrever por atendimento** quando outro cobriu o turno. Roster fixo (sem override) foi rejeitado — turnos variam e um vendedor cobre vários números.
- **IA conduz → sem vendedor → sem comissão.** Atendimento conduzido pela IA fica com `vendedor_id` nulo. Na transição, quando a IA assume uma modelo, seu `modelos.vendedor_id` vira nulo e os novos atendimentos não geram comissão. Transição limpa, sem flag extra.
- **Comissão por nível, percentual configurável.** O vendedor tem um nível (`iniciante|intermediario|avancado`); o percentual é configurável por nível (referência 4/5/6%), não por vendedor no P0. Override por vendedor fica para depois.
- **Base = valor líquido de taxa de cartão.** A comissão incide sobre o que entra de fato (mesma base do repasse da modelo): pix/dinheiro = `valor_final`; cartão = `valor_final` menos a taxa (que só cobre a maquininha). É um custo **independente** do repasse — ambos saem do mesmo valor, nenhum desconta o outro. Comissão sobre o bruto inflado pela taxa foi rejeitada.
- **Cálculo por projeção, não por lançamento.** A comissão devida é projetada sobre os `atendimentos WHERE estado='Fechado'` com `vendedor_id` no período — mesmo padrão da receita do **Módulo Financeiro** (ADR 0011), single source of truth, zero sincronização. Vive em `dominio/financeiro/` (painel-only; `agente/` não importa).
- **Pagamento de comissão em pagamentos livres**, espelhando `financeiro_repasses_pagos` (ADR 0011): tabela `financeiro_comissoes_pagas (vendedor, data, valor, forma, observacao, comprovante?)`, saldo do vendedor = `calculado − pago` por janela, pode ficar negativo após estorno (badge, sem trava). Estado `pendente/pago/parcial` por atendimento foi rejeitado — a operação paga em lote por pessoa.

## Consequences

- **Migration manual no prod self-hosted** (nunca `make migrate` — ver memória `migrations_pendentes_prod_selfhosted`): `vendedores` + enum de nível, `modelos.vendedor_id`, `atendimentos.vendedor_id`, `financeiro_comissoes_pagas`, e a config de percentual por nível.
- **Acoplamento com a taxa de cartão (task 6 / ADR a definir).** A base "líquido de taxa" só fica correta quando a taxa de cartão existir; **enquanto a task 6 não entrar, a comissão calcula sobre `valor_final`**. Sequenciar: taxa de cartão antes (ou junto) da comissão, para não recalcular dobrado.
- **Sem backfill.** Atendimentos pré-existentes ficam com `vendedor_id` nulo; Fernando atribui retroativo no painel se quiser comissionar histórico.
- `CONTEXT.md` ganhou os termos **Vendedor** e **Comissão de vendedor**, relações e uma Flagged ambiguity reconciliando IA × humano.
- O contexto `dominio/atendimentos/` passa a herdar o vendedor da modelo na criação; a UI de atendimento ganha o seletor de vendedor (com o padrão pré-preenchido).
