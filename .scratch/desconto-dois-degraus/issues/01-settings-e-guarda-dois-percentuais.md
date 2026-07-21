# 01 — Settings e guarda de código com dois percentuais (degrau, teto)

**What to build:** O sistema passa a ter dois percentuais de desconto configuráveis — um degrau intermediário e um teto — em vez de um único. A guarda de código que impede gravar um valor de fechamento abaixo do permitido passa a checar contra o teto (o maior dos dois).

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] `desconto_degrau_pct` e `desconto_teto_pct` existem em settings, configuráveis via variável de ambiente, com defaults calibrados no exemplo da reunião (~12,5% e ~25%).
- [ ] A guarda de código que hoje compara contra o único percentual antigo passa a comparar contra `desconto_teto_pct`.
- [ ] Testes unitários cobrindo: valor dentro do teto grava normalmente; valor abaixo do teto escala (`fora_de_oferta`); sem programa correspondente à duração escala.

Ver spec: `docs/specs/0002-desconto-dois-degraus.md` (issue [#95](https://github.com/procexaiedu/barra/issues/95)) e ADR-0031.
