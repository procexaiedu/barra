# 02 — Comando `IA pausa` no grupo de Coordenação

**What to build:** Fernando ou a modelo pausam a IA de um cliente específico por comando de texto no grupo de Coordenação por modelo, igual já funciona hoje para `IA assume`/`finalizado`.

**Blocked by:** Ticket 01 (reusa a mesma porta de comando operacional).

**Status:** ready-for-agent

- [ ] O parser de comandos do grupo reconhece `IA pausa` (como resposta/quote a um card) e `IA pausa #N` (fora de contexto de card).
- [ ] O autor do comando é registrado corretamente como Fernando ou a modelo, conforme o originador real do envio (mesma disciplina já usada em `IA assume`).
- [ ] Confirmação curta no grupo após o comando, no mesmo padrão dos outros comandos existentes.

Ver spec: `docs/specs/0003-handoff-manual-operador.md` (issue [#96](https://github.com/procexaiedu/barra/issues/96)) e ADR-0032.
