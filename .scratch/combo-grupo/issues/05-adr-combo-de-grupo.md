# 05 — ADR do Combo de grupo

**O que construir:** o registro da decisão de permitir que a IA de uma modelo ofereça, precifique e **reserve a agenda de outra**. Sem esse documento, quem ler `regras.md.j2` daqui a três meses vai encontrar o `"Só eu amor"` quebrado e concluir que foi por engano.

Bate os três critérios: **difícil de reverter** (a IA de A passa a escrever na agenda de B, e o cliente passa a saber que existem outras mulheres); **surpreendente** (contradiz frontalmente a conduta atual e o `_Avoid_` histórico do glossário, *"IA citando profissional contratada por outra modelo"*); e **resultado de trade-off real** — três alternativas foram consideradas e rejeitadas por motivos específicos.

O que o ADR precisa preservar, porque é o que evapora da memória:

- **Passar o contato da convidada** — rejeitado: destrói a porta única e cria conversas paralelas com **a mesma persona e a mesma voz** (persona e FAQ são gerais), no pior momento possível — quatro homens comparando na mesa.
- **Escalada para Fernando montar o combo** — rejeitado: a feature precisa ser autônoma; à 00h28 de uma sexta o lead esfria esperando humano.
- **Aceite da convidada antes de reservar** — rejeitado: insere latência humana no caminho crítico e criaria um estado "provisório" que não existe no domínio.
- **Tabela `combos` com estado agregado** — rejeitado: criaria uma segunda máquina de estados ao lado da que já existe.

E a distinção que sustenta o isolamento: o que passa a ser compartilhado é dado **da modelo** (nome, foto, preço, agenda), nunca dado **do cliente com outra modelo** (histórico, observações, recorrência) — que continua isolado por par. É por isso que o canário F0.3 permanece válido sem afrouxamento.

**Bloqueado por:** nenhum — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] ADR criado em `docs/adr/` com a numeração sequencial correta
- [ ] As quatro alternativas rejeitadas registradas com o motivo de cada uma
- [ ] A distinção "dado da modelo × dado do cliente com outra modelo" explicitada
- [ ] Relação com ADR 0025 (buffer), 0031 (desconto) e 0033 (piloto) declarada
- [ ] `CONTEXT.md` referenciado (verbetes **Combo de grupo** e **Modelo do canal / Modelo convidada** já foram escritos)
