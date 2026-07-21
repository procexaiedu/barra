# 03 — Evals/fixtures cobrindo as 3 faixas de desconto

**What to build:** O gate de qualidade (evals) distingue corretamente os três comportamentos esperados na negociação de desconto: dentro do degrau, entre degrau e teto (ainda ok numa 2ª rodada), e abaixo do teto (deve escalar).

**Blocked by:** Ticket 02 (precisa do comportamento de 2 rodadas implementado para gerar as fixtures certas).

**Status:** ready-for-agent

- [ ] Fixtures de "tem que escalar" atualizadas/criadas cobrindo as 3 faixas (dentro do degrau, entre degrau e teto, abaixo do teto).
- [ ] Gate de evals (`make evals`) passa com as novas fixtures.

Ver spec: `docs/specs/0002-desconto-dois-degraus.md` (issue [#95](https://github.com/procexaiedu/barra/issues/95)) e ADR-0031.
