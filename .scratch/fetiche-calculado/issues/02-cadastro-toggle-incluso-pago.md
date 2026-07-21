# 02 — Cadastro por-modelo de fetiche vira toggle incluso/pago

**What to build:** No cadastro de uma modelo (painel, seção "Serviços e preços" → Fetiches), marcar um fetiche como incluso ou pago deixa de pedir um valor em reais — vira um toggle simples. A API para de aceitar um preço numérico livre para o vínculo modelo×fetiche.

**Blocked by:** None — pode rodar em paralelo com o ticket 01 (o cálculo do preço já trata qualquer valor não-nulo cadastrado como "pago", então a mudança de UI/API não depende do cálculo estar pronto).

**Status:** ready-for-agent

- [ ] Endpoint de vínculo modelo×fetiche aceita um campo booleano (`pago`) em vez de um `preco` numérico livre.
- [ ] Frontend do cadastro (Serviços e preços → Fetiches) mostra um toggle incluso/pago, sem campo de valor.
- [ ] Dado já existente em produção (fetiches cadastrados com um valor numérico) continua funcionando sem migration de schema — qualquer valor não-nulo é interpretado como "pago".
- [ ] Verificação manual/Playwright: cadastrar um fetiche como pago no painel e ver o toggle refletir corretamente ao recarregar a página.

Ver spec: `docs/specs/0001-fetiche-calculado.md` (issue [#94](https://github.com/procexaiedu/barra/issues/94)) e ADR-0030.
