# 03 — Cada modelo com a sua Coordenação por modelo

**O que construir:** cada modelo precisa ter o seu próprio grupo de **Coordenação por modelo** — o grupo de 2 participantes (o número dela + Fernando) que o glossário define. Hoje Tatiane e Lucia apontam para o **mesmo** `coordenacao_chat_id` (`120363407815206369@g.us`), provável resíduo do cutover EvoGo de 21/07.

Duas consequências, uma já ativa e outra futura: hoje qualquer **Card** de uma já é visível para a outra (o isolamento operacional entre modelos está furado agora, independentemente de qualquer feature nova); e no **Combo de grupo** o card por **Modelo convidada** fica impossível — os dois cards cairiam no mesmo lugar.

Toca produção (criação/vínculo de grupo na Evolution, escrita no cadastro) e **precisa de autorização explícita, frase a frase**.

**Bloqueado por:** nenhum — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Cada modelo não-inativa tem `coordenacao_chat_id` próprio e distinto
- [ ] `coordenacao_verificada_em` preenchido para as duas (hoje a Tatiane está nula)
- [ ] Card de uma modelo não aparece no grupo da outra
- [ ] Verificado que os comandos de grupo (`IA assume`, `fechado`, `perdido`) continuam funcionando em cada grupo novo
- [ ] Autorização registrada antes de qualquer ação em produção
