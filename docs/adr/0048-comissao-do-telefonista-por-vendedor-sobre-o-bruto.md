---
data: 2026-08-20
status: aceito
relaciona: ADR-0012 (revisa "comissão por nível" e a base de cálculo), ADR-0045, spec 0006
---

# ADR-0048 — Comissão do telefonista: percentual por vendedor, sobre o bruto vendido

## Contexto

O ADR-0012 já introduziu o **Vendedor** como entidade de domínio e a **Comissão de vendedor** como
custo projetado, com duas decisões que a reunião de 20/08/2026 desfaz:

- *"Comissão por nível, percentual configurável. O vendedor tem um nível
  (`iniciante|intermediario|avancado`); o percentual é configurável por nível (referência 4/5/6%),
  não por vendedor no P0. **Override por vendedor fica para depois.**"*
- *"Base = valor líquido de taxa de cartão."*

O "depois" chegou. O Rossi pediu, sem que ninguém puxasse o assunto:

> *"Lá no sistema tem a comissão do telefonista? (…) A gente pode colocar uma porcentagem pro
> telefonista que a gente possa alterar, de 1% a 10%. (…) Isso vai depender da experiência do
> vendedor."*

E fixou a base sem ambiguidade:

> — *"E essa porcentagem é do valor do atendimento ou do valor que fica para vocês?"*
> — *"Do valor da venda. Valor total que ele vendeu."*
> — *"É por atendimento, não seria por temporada?"*
> — *"Seria por faturamento. Faturamento bruto."*

A referência que ele deu foi **7%**, contra os 4/5/6% que a tabela de níveis traz hoje.

Há também um pedido de painel junto: *"a gente pode colocar aqui em cadastro, telefonista também,
cadastrar o nome deles (…) pra vocês também conseguirem alterar os valores da comissão deles"* —
uma aba ao lado de Modelos.

## Decisão

**1. O percentual é do vendedor, não do nível.** `vendedores.percentual_comissao numeric(5,2)`,
faixa operacional 1–10%, default 7%. A tabela `financeiro_comissao_niveis` e o enum de nível
sobrevivem como **default de cadastro** (o nível preenche o percentual na criação) e param de ser
consultados no cálculo. Ninguém perde histórico e nada precisa de backfill.

**2. A base é o bruto vendido**, não o valor do serviço líquido de taxa. Isso alinha a comissão do
telefonista com a comissão da modelo, que o ADR-0045 §3 já pôs sobre o bruto ("taxa de cartão não é
descontada"). O `comissao_vendedor()` de `dominio/financeiro/calculos.py` passa a receber a taxa
como `None` por decisão, não por ausência de dado — e a docstring tem que dizer isso, porque a
função continua aceitando o parâmetro para o histórico pré-agosto.

**3. Deslocamento não entra na base**, pela mesma razão que não entra na comissão da modelo
(ADR-0045 §5): é reembolso de custo. O `Valor antecipado` que o cliente manda pelo Uber não é venda.

**4. A comissão passa a incidir também sobre a Venda registrada**, não só sobre `atendimentos`. Hoje
ela é projetada sobre `atendimentos WHERE estado='Fechado'`; a receita do grupo financeiro é a outra
fonte do ADR-0043, e é dela que sai o faturamento do telefonista no fluxo novo. As duas somam sem
dupla contagem enquanto a IA de venda não estiver em produção — quando estiver, vale a decisão de
precedência que o ADR-0043 já deixou para depois.

**5. Quem é o telefonista da venda vem do autor da mensagem.** A ficha é postada por uma pessoa, e o
JID do participante identifica quem. `vendedores.whatsapp_jid` (único, nullable) é o vínculo.
Autor desconhecido → venda sem vendedor → sem comissão, exatamente como o ADR-0012 já trata o
atendimento conduzido pela IA. Nunca chuta.

**6. O cálculo continua por projeção, não por lançamento** — o ADR-0012 acertou nisso e nada mudou:
sem snapshot por venda, mudou a config, mudou a projeção. Coerente com o resto do Módulo Financeiro.

## Alternativas rejeitadas

- **Manter o nível e só ajustar as alíquotas para 7%.** Mais barato, mas o Rossi pediu explicitamente
  "que a gente possa alterar" por pessoa, e a granularidade de três degraus não cobre 1–10%.
- **Snapshot do percentual na venda**, como se faz com o percentual da modelo. A modelo precisa de
  snapshot porque o número dela é negociado com ela e temporada passada não pode ser reescrita; o
  do telefonista é decisão unilateral da casa sobre desempenho, e o ADR-0012 já concluiu que
  projeção é o padrão do módulo.
- **Comissão sobre o que fica para a casa** (o bruto menos o repasse da modelo). Foi a hipótese
  levantada na reunião e negada na hora: *"do valor da venda, valor total que ele vendeu"*.
- **`CHECK (percentual BETWEEN 1 AND 10)`.** O próprio Rossi disse *"ou até 100%"* ao divagar sobre o
  cálculo. A faixa 1–10 é operacional, não invariante; o CHECK fica em `0..100` como já está.

## Consequências

- Migration: `vendedores.percentual_comissao` e `vendedores.whatsapp_jid`, mais o backfill do
  percentual a partir do nível atual de cada vendedor (4/5/6 → o número, não 7 — o 7 é default de
  cadastro novo, não reprecificação retroativa de quem já existe).
- `calculos.py` ganha uma docstring que explica por que a taxa entra como `None`, e os testes de
  `comissao_vendedor` passam a cobrir a base bruta.
- O painel ganha a aba **Telefonistas** ao lado de Modelos, com nome, percentual e ativo — pedido
  explícito, e é onde o Rossi vai mexer no número.
- O extrato da temporada da modelo **não** mostra comissão de telefonista. São duas contas de
  pessoas diferentes, e a modelo lê o grupo dela.
