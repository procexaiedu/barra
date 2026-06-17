---
status: accepted
---

# Endereço do atendimento interno em fase única (número junto com a rua)

Em 17/06/2026 o agente passou a revelar o endereço do interno em **duas fases** (`regras.md.j2` `<encontro_e_endereco>`, memória `deploy_disclosure_interno_duracao_17-06`): **fase 1** — rua + referência quando o horário fecha; **fase 2** — número exato (apartamento/quarto) só quando o cliente chega à portaria, gatilhado pela **Foto de portaria**. A intenção era **discrição/segurança**: não entregar o número exato da modelo antes do cliente provar presença física, mitigando quem "zoa" e exposição do endereço a quem nunca aparece.

Na monitoria E2E ao vivo de 17/06 (rig Lucia, cenário "1. Interno — happy path") a 2-fase mostrou **fricção e fragilidade**:

- **Fricção de UX:** o cliente quer o endereço completo de uma vez para se organizar/navegar; o round-trip extra (chegar até a rua, avisar, então receber o número) atrapalha a experiência no momento mais sensível, perto do encontro.
- **Fragilidade de execução:** a 2-fase é **só prompt** (instrução em `<encontro_e_endereco>`), não guard determinístico — depende de o LLM lembrar de soltar o número no turno da chegada. No teste o agente **anunciou** "já te mando o número 😊" e a sessão terminou antes de mandar.

## Decisão

- **Endereço completo numa fase só, para todo interno.** Quando o horário fecha, a IA passa **rua + número/complemento + ponto de referência** de uma vez, para o cliente chegar direto. **Antes** do horário fechar continua valendo "no máximo a região" (a guarda pré-fechamento **não** muda).

- **A Foto de portaria continua confirmando a chegada** e disparando o handoff implícito (`Aguardando_confirmacao → Em_execucao`, IA pausada). Ela apenas **deixa de ser o gatilho** do número, que agora já saiu no fechamento.

- **Mudança só de prompt + documentação.** Reescreve `<encontro_e_endereco>` em `regras.md.j2`; não toca o nó `intercept_disclosure` (que trata *tentativas* de disclosure/jailbreak — sondagem precoce do cliente —, não a fala legítima do endereço). `CONTEXT.md` (verbete **Atendimento interno**) é atualizado junto.

## Considered Options

- **Manter as 2 fases.** Rejeitado: a discrição do apto-até-a-portaria não compensa a fricção no caso de uso real (decisão de produto do Fernando, 17/06). O ganho de segurança é marginal (o cliente já negociou e combinou horário) frente ao custo de UX.

- **Endurecer o T6 (mandar o número determinístico na chegada) e manter as 2 fases.** Resolveria a *fragilidade de execução*, mas não a *fricção* — que é o incômodo principal. Mais código (envio determinístico acoplado ao handoff da Foto de portaria) para preservar uma proteção que se decidiu não querer.

- **1 fase condicional (só recorrente / só quem pede o endereço completo).** Rejeitado: adiciona ramo de decisão no prompt e no teste sem ganho claro; a fricção vale para qualquer interno (§2 do `CLAUDE.md`, Simplicidade).

## Consequences

- **Tradeoff aceito:** o número/complemento exato passa a ser revelado **antes** de o cliente provar presença (no fechamento do horário, não na portaria). Exposição maior do endereço da modelo a no-shows; aceito em troca da conveniência. Registrado aqui para não ser reintroduzido como 2-fase "por segurança" sem rediscutir este tradeoff.

- **Reverte parcialmente o deploy de 17/06** (`deploy_disclosure_interno_duracao_17-06`): a parte de **duração** daquele deploy (`_DESC_DURACAO` na extração) permanece; só a disclosure de endereço volta a uma fase.

- **Deploy exige recarregar o worker** (`docker service update --force <stack>_barra-worker`; nunca `restart` em Swarm). Mudança de prompt **não tem migration**. §0: deploy em prod só com autorização explícita.

- **Sem guard determinístico novo:** a regra continua sendo instrução de prompt; a 1-fase é mais simples de o LLM seguir (uma única entrega) que a 2-fase.
