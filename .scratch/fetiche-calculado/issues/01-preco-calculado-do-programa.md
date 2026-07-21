# 01 — Preço do fetiche pago calculado a partir do programa vendido

**What to build:** Ao registrar um fetiche pago num atendimento (painel), o valor gravado (`preco_snapshot`) passa a ser calculado a partir do(s) programa(s) efetivamente vendido(s) naquele atendimento (preço-hora efetivo do pacote), em vez de lido de um valor cadastrado por modelo. Um fetiche incluso continua sem custo extra.

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Função pura de cálculo (preço de tabela ÷ duração em horas) existe e é testada: 1h/preço simples, múltiplas horas (Pernoite-like), preço não-múltiplo exato.
- [ ] O registro de fetiche no atendimento usa essa função para computar `preco_snapshot`, buscando o(s) serviço(s) vendidos no atendimento; erro claro se nenhum serviço foi registrado ainda.
- [ ] Atendimento com mais de um serviço vendido usa soma dos preços dos serviços ÷ MAX(duração) — mesma convenção de "duração sugerida" já documentada em CONTEXT.md (**Programa e duração**).
- [ ] Fetiche incluso continua gravando `preco_snapshot = NULL`.
- [ ] Teste unitário da função de cálculo + teste de integração (`needs_db`) cobrindo incluso, pago (serviço único e múltiplos serviços), e o caso de erro sem nenhum serviço vendido.

Ver spec: `docs/specs/0001-fetiche-calculado.md` (issue [#94](https://github.com/procexaiedu/barra/issues/94)) e ADR-0030.
