---
status: accepted
---

# ADR-0036 — Remoção do cancelamento automático do piloto

## Contexto

O ADR-0033 criou uma salvaguarda temporária para o piloto de teste: um cron que, depois de o cliente confirmar o horário (`Aguardando_confirmacao`), matava o Atendimento antes de ele virar encontro real — desculpa canned ao cliente, `Perdido`/`outro` e IA pausada. Gatilho por tipo (interno: Aviso de saída ou perto do horário combinado; externo/remoto: 10 min após o crava), mais um backstop que reenfileirava a desculpa quando o envio evaporava.

O próprio ADR-0033 previa o fim: "controlado por flag de settings, ligada por padrão agora, desligável sem deploy quando o piloto evoluir para atendimento real com modelo de verdade". A decisão de 2026-08-07 (dono do produto) foi além do desligar: **remover o mecanismo inteiro**, código e schema.

## Decisão

Revogar o ADR-0033. Nenhum Atendimento é cancelado automaticamente — o funil segue até `Fechado`/`Perdido` pelas portas que já existiam antes do piloto (registro humano, timeout de 24h, timeout interno do ADR-0024).

Sai tudo:

- `cancelar_piloto_teste` (`workers/timeouts.py`) e seu cron, `reconciliar_desculpa_piloto` (`workers/reconciliacao.py`) e o dele.
- Pool `CANCELAMENTO_PILOTO_CANNED` + `escolher_cancelamento_piloto` (`agente/_canned.py`).
- Flags `piloto_auto_cancela_ativo` / `piloto_cancela_antes_min` e a métrica `barra_piloto_cancelamento_total`.
- Colunas `atendimentos.piloto_cancelado_em` e `atendimentos.aguardando_confirmacao_em` (a segunda existia só para ancorar o timer de 10 min), mais os dois carimbos que as escreviam (`dominio/atendimentos/service.py` e `routes.py`).
- Valor `auto_cancelamento_piloto` de `fonte_decisao_enum` — o Postgres não remove valor de enum, então a migration `20260808020458_remove_cancelamento_piloto.sql` recria o tipo.

## Alternativas rejeitadas

- **Desligar pela flag (`PILOTO_AUTO_CANCELA_ATIVO=false`).** Reversível e sem deploy, mas deixa em pé um cron que mata atendimento e um pool de desculpas a um Env de distância de disparar em produção real. Rejeitada em favor da remoção explícita.
- **Remover só o braço externo/remoto** (o timer de 10 min pós-confirmação, pendência aberta do ADR-0033). Rejeitada — resolveria a pendência, não o pedido.
- **Preservar `auto_cancelamento_piloto` no enum e a coluna de auditoria.** Rejeitada na mesma decisão ("limpar tudo, inclusive schema"): os atendimentos mortos pelo cron durante o piloto perdem a fonte da transição (viram `NULL`); seguem `Perdido`/`outro` com a observação "cancelamento automático — piloto de teste", e os eventos em `eventos` (jsonb) não são tocados.

## Consequências

- **O risco que o ADR-0033 cobria volta:** enquanto a operação rodar sem modelo real, um cliente pode negociar até o fim, receber a solicitação de Pix e pagar por um encontro que ninguém pretende cumprir. O freio passa a ser inteiramente humano (Handoff manual do ADR-0032, `pausar_ia` pelo grupo ou painel).
- A pendência aberta do ADR-0033 (suprimir a solicitação de Pix durante o piloto) deixa de ser sobre o gatilho do cancelamento e vira, se ainda importar, uma decisão isolada sobre o Pix.
- Migration `20260808020458_remove_cancelamento_piloto.sql`: schema-only, idempotente, aplicada manualmente em produção (nunca via `make migrate`).
- CONTEXT.md perde o termo **Cancelamento automático do piloto**; `docs/dominio/operacao-e-financeiro.md` e `docs/specs/0004` ficam como registro histórico do mecanismo revogado.
