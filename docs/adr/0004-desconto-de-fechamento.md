---
data: 2026-05-23
status: aceito
---

# ADR-0004 — Desconto de fechamento permitido até piso percentual

## Contexto

A documentação de produto e de agente afirmava, em cinco lugares, que **a IA não negocia preço — escala**: `mvp/02` e `mvp/03` ("não negociar exceções complexas"), `mvp/04 §98` ("não negocia deslocamento"), `mvp/05 §14` ("desconto não autorizado / valor abaixo do mínimo → escala em vez de negociar") e `docs/agente/03 §3.3` + `04 §3.4` (`escalar(motivo="fora_de_oferta")`). O schema reforça isso: `modelo_programas` só tem `preco`, sem campo de mínimo ou desconto — o preço de tabela é, na prática, o piso.

A ata fundacional, porém, descreve a IA usando preço como alavanca de fechamento: oferecer pacotes maiores com preço/hora melhor e, no reengajamento de cliente que esfriou, "fazer um preço melhor". Há uma tensão real entre **posicionamento premium** (Fernando é enfático no preço firme como sinal de exclusividade) e **conversão** (recuperar venda em risco).

Decidido em sabatina (`grill-with-docs`, 2026-05-23) descendo a árvore: tipo de desconto → gatilho → piso → anti-leilão → enforcement.

## Decisão

A IA pode conceder **Desconto de fechamento** (termo em `CONTEXT.md`), cercado:

1. **Upsell de pacote é livre** — oferecer duração maior com preço/hora menor já está no **Preço de tabela** (`modelo_programas`); não é desconto e não precisa de trava.
2. **Desconto real abaixo da tabela é permitido**, com gatilho **reativo** (cliente pede) **e proativo** (no reengajamento — mecanismo definido à parte, item #3 da revisão).
3. **Piso = percentual global** em `settings` (`desconto_max_pct`, default a calibrar ~15%), aplicado sobre o **Preço de tabela** do programa. Incide **só sobre o programa**, nunca sobre o **Pix de deslocamento** (R$100 fixo, segue inegociável).
4. **Anti-leilão one-shot:** a IA faz **uma única** contraproposta, no piso, enquadrada como final; se o cliente recusa ou insiste por menos, **escala** (`fora_de_oferta`) em vez de baixar mais. Não há regateio em passos.
5. **Enforcement em duas camadas:** a regra do **percentual** vai no prompt **geral** (BP1, idêntico para todas as modelos — não quebra o cache global); o valor mínimo **nunca** é escrito no prompt. A guarda determinística vive no código: ao registrar `valor_acordado` (ou no fechamento) abaixo do piso (`preco_tabela × (1 − desconto_max_pct)`), o sistema escala em vez de gravar. Padrão defesa-em-profundidade já adotado no projeto (`03 §9`).

## Alternativas rejeitadas

- **(a) Manter "IA não negocia" (status quo).** Fiel ao premium, mas ignora a ata e deixa conversão na mesa em todo cliente sensível a preço. Rejeitada — o dono do domínio quer a alavanca.
- **(b) Só upsell, sem desconto real.** Resolve metade do pedido sem risco, mas não recupera o cliente que esfriou no preço. Rejeitada como insuficiente.
- **(c) Piso por (modelo, programa) ou por modelo (schema).** Mais granular (respeitaria repasses diferentes), mas exige migration + cadastro por combinação para um piloto de 1 modelo. Prematuro — fica como caminho P1 se o repasse por modelo justificar.
- **(d) Regateio multi-passo.** Captura margem de quem fecha com pouco desconto, mas ensina o cliente que insistir baixa o preço — exatamente o leilão que se quer evitar num produto premium. Rejeitada.
- **(e) Expor o piso no prompt.** Simplifica a aritmética para o LLM, mas arrisca a IA vazar o mínimo ("meu mínimo é X") ou ancorar nele, e polui o BP3 por-modelo. Rejeitada.

## Consequências

**Positivas**
- Atende a ata sem abrir negociação livre; o premium é protegido pelo one-shot + piso.
- Reversível por configuração: `desconto_max_pct = 0` faz a IA voltar a escalar todo desconto, sem mudar código.
- Regra geral mantém o cache de prompt global intacto (escalável para N modelos).

**Negativas / a acompanhar**
- Reverte uma regra repetida em 5 docs — exige atualizar `persona/regras.md.j2`, `programas.md.j2`, `04 §3.1`/`§3.4`, `settings.py` e os evals (fixtures de "tem-que-escalar" passam a distinguir "pediu desconto dentro do piso" de "abaixo do piso"). `mvp/05 §14` fica como contexto histórico; a verdade corrente é este ADR + `CONTEXT.md`.
- Risco residual de erosão do premium pelo gatilho reativo — monitorar no error analysis weekly (`08 §5.4`) e no eval; se aparecer, restringir reativo é ajuste de prompt.
- `% global` ignora que repasses diferentes (30/40/50%) toleram descontos diferentes — aceitável no piloto de 1 modelo; granularizar é P1 (alternativa c).
