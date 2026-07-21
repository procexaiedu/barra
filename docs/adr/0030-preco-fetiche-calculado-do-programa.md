---
status: accepted
supersedes: parte do ADR 0014 (preço cadastrado por modelo×fetiche)
---

# ADR-0030 — Preço do Fetiche calculado a partir do programa, não cadastrado

## Contexto

O ADR-0014 modelou `modelo_fetiches.preco` como um valor **livre**, digitado por modelo, com `NULL` = incluso e um número = extra pago. Na reunião de colocação da IA em produção (2026-07-20, grillada em `grill-with-docs`), o dono do domínio descreveu uma regra de precificação distinta: todo fetiche pago vale **o preço-hora efetivo do pacote que o cliente está comprando naquele atendimento** — não um valor fixo por modelo. Exemplo dado: completo a R$500/h + um extra = +R$500 (o extra "conta como mais uma hora"); "beijo grego" a R$600/h descrito como "o dobro" = base + 1h ao preço-hora, mesma aritmética.

## Decisão

- **`modelo_fetiches.preco` vira flag, não valor.** A tabela para de guardar um número; guarda só se o fetiche é **incluso** ou **pago** por aquela modelo (`booleano` ou `preco NULL`/`not NULL` sem uso do valor — detalhe de schema fica para o /to-spec).
- **Valor do extra é sempre calculado, nunca gravado por modelo:** `preco_extra = preco_tabela_do_programa_vendido ÷ duracao_horas_vendida` (preço-hora efetivo do pacote no atendimento), somado **uma vez por fetiche pedido**. Uniforme entre fetiches — nenhum fetiche vale mais que outro.
- **Multi-hora usa o preço-hora efetivo do pacote, não uma duração-base de 1h.** Pernoite (12h) a R$3.600 → cada fetiche soma +R$300, não o preço de uma combinação `programa×1h` separada. Consistente com upsell de pacote maior = preço/hora menor (ADR 0004).
- Mantém-se do ADR-0014: sem duração própria, snapshot no atendimento (`atendimento_fetiches`), **não auto-soma o Valor final** (segue manual, entra só no breakdown), **Desconto de fechamento** incide sobre o pacote (programa + extras).

## Alternativas rejeitadas

- **Preço absoluto cadastrado por modelo×fetiche (status quo do ADR-0014).** Rejeitado — não é o que o dono do domínio descreveu na reunião; a intenção é o valor variar com o programa/duração vendidos, não ficar fixo.
- **Multiplicador por fetiche (1x default, 2x para casos como "dobro").** Rejeitado por ora: todos os exemplos concretos da reunião reduzem à mesma aritmética (+1x o preço-hora do pacote). Adicionar um multiplicador por fetiche seria grau de liberdade não pedido — reabrir se aparecer um fetiche que realmente precise valer mais que os outros.

## Consequências

- Migration em `modelo_fetiches`: `preco` deixa de ser lido como valor monetário; vira flag incluso/pago (campo pode ser reaproveitado como booleano ou mantido `NULL`-vs-`NOT NULL` sem o número importar — decisão de schema no /to-spec).
- Cálculo do preço do extra passa a depender do programa/duração escolhidos no atendimento — precisa entrar na cotação da IA e no cálculo de piso/desconto (`_abaixo_do_piso`, ADR 0004) como valor derivado, não lido de coluna.
- `agente/nos/prepare_context` (BP3) não muda o que expõe (fetiche que a modelo faz, incluso/pago) — só o `+R$X` que a IA cota passa a ser calculado em vez de lido.
