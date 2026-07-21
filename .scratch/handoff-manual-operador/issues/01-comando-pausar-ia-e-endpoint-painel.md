# 01 — Comando `pausar_ia` + endpoint no painel

**What to build:** Fernando pausa a IA de um atendimento específico a qualquer momento pelo painel, sem depender de um evento automático do sistema (Pix, foto de portaria). A reativação usa o fluxo de Devolução já existente.

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Novo comando `pausar_ia` na porta única de comandos operacionais, análogo (na direção inversa) ao comando de devolução já existente.
- [ ] Novo tipo de escalada distinto do usado hoje para comportamento suspeito do cliente (que tem semântica diferente — é sobre o cliente, não sobre a resposta da IA).
- [ ] Endpoint `POST /atendimentos/{id}/pausar` no painel, mesmo padrão de autenticação do endpoint de devolução.
- [ ] Atendimento pausado manualmente reativa normalmente pelo fluxo de Devolução (`IA assume`/botão no painel).
- [ ] Atendimento novo do mesmo par (recorrência) nasce com IA ativa, independente da pausa manual do atendimento anterior.
- [ ] Teste de integração cobrindo idempotência (pausar um atendimento já pausado não quebra).

Ver spec: `docs/specs/0003-handoff-manual-operador.md` (issue [#96](https://github.com/procexaiedu/barra/issues/96)) e ADR-0032.
