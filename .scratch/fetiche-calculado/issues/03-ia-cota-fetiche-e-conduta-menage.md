# 03 — IA cota o fetiche certo por programa + conduta de Menage

**What to build:** Na conversa de venda, a IA cota o valor correto de um fetiche pago considerando qual programa a modelo oferece — sem depender de um valor fixo desatualizado. Menage passa a ser tratado como extra pago (dobra o pacote) e a IA escala para Fernando quando o pedido envolve outra modelo junto (em vez do cliente trazer sua própria acompanhante, caso que a IA cota normalmente).

**Blocked by:** Ticket 01 (reusa a função de cálculo do preço do extra).

**Status:** ready-for-agent

- [ ] O contexto por-modelo (BP3) lista, para cada fetiche pago, o valor correspondente a cada programa que a modelo oferece — calculado no momento do render.
- [ ] O render do BP3 continua **byte-idêntico** entre modelos com o mesmo cadastro de fetiches/programas — não varia por turno/conversa (preserva o prefixo cacheável do prompt).
- [ ] Menage está marcado como pago no catálogo (correção de dado) e a IA cota corretamente o dobro do pacote quando perguntada sobre o serviço.
- [ ] Quando o cliente pede menage com "outra modelo"/"amiga dela", a IA escala para Fernando em vez de tentar fechar sozinha.
- [ ] Quando o cliente pede para trazer sua própria acompanhante, a IA cota o dobro do pacote sem tratar a acompanhante como um cadastro novo no sistema.

Ver spec: `docs/specs/0001-fetiche-calculado.md` (issue [#94](https://github.com/procexaiedu/barra/issues/94)) e ADR-0030.
