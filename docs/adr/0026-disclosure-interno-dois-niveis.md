---
status: accepted
---

# Disclosure de endereço interno em 2 níveis (prédio público, unidade pós-portaria)

O ADR 0023 unificou a disclosure interna em **uma fase**: ao fechar o horário, a IA passava **rua + número + complemento (apartamento/quarto)** de uma vez, e a Foto de portaria deixava de gatilhar o número. O tradeoff aceito ali foi expor o **número/complemento exato antes** de o cliente provar presença — registrado com o pedido explícito de "não reintroduzir como 2-fase 'por segurança' sem rediscutir este tradeoff". Este ADR **é** essa rediscussão.

A premissa nova (decisão de produto, 18/06/2026): as modelos operam tipicamente em **prédio ou hotel**. Logo **rua + número do prédio** só leva o cliente até a **portaria/lobby** — é informação semi-pública e não revela onde a modelo está. O que expõe a modelo é a **unidade** (apartamento/quarto). A monitoria E2E (rig Lucia, cenário interno) flagrou a IA passando o endereço cedo como "violação", mas pela premissa do prédio isso não é problema: o que precisa de proteção é só a unidade.

## Decisão

- **Dois níveis de disclosure:**
  - **(a) rua + número do prédio/hotel + ponto de referência** — leva à portaria. A **IA** passa quando há **intenção real e o encontro está sendo combinado** (`Qualificado` em diante). No 1º contato / mera sondagem de preço, fala **no máximo a região** (preserva o espírito do guard pré-fechamento do 0023 contra quem só sonda e some).
  - **(b) apartamento/quarto (a unidade)** — dada pela **modelo (humana)**, no celular dela, **depois** que a **Foto de portaria** chega. A **IA nunca emite a unidade.**

> **Emenda 2026-07-22 (feedback Fernando, reunião pós-dia 1 de prod):** o nível (a) ganhou um degrau interno e um reforço estrutural, após a IA vazar rua+número em Triagem no 1º dia real (o DeepSeek ignorou a prosa):
> - **Degrau do número:** em `Qualificado`, a IA passa **nome do hotel + rua SEM o número**; o **número** entra só quando o cliente **confirma que vai / avisa que saiu / pede para se organizar**. A unidade segue como (b). O degrau do número é prosa (o dado completo está disponível a partir de `Qualificado`) — deliberado, porque o subcaso "confirmou que vai" acontece no mesmo estado.
> - **Gate estrutural:** o endereço saiu do BP_MODELO; entra no contexto do turno via bloco `<local_de_encontro>` **apenas** de `Qualificado` em diante e só no interno (`prepare_context._libera_local_de_encontro`). Em Novo/Triagem a IA **não tem** o endereço para vazar.
> - **Enquadramento:** o local se vende como **hotel elegante, seguro e discreto** — "prédio", "sala" e "escritório" são proibidos na fala com o cliente.

- **Por que é robusto e não repete a 2-fase do 0023:** a Foto de portaria pausa a IA (`ia_pausada=true`, `modelo_em_atendimento`) e a modelo assume. No instante em que a unidade é liberada, **a IA já está pausada e quem conduz é a humana** — a unidade sai dela naturalmente. Some a fragilidade que motivou o 0023 (o LLM anunciar "já te mando o número" e a sessão terminar sem mandar): a IA não tem o que lembrar de mandar.

- **Sem campo novo no schema.** `barravips.modelos.endereco_formatado` já é nível-prédio (auditoria: 0 modelos embutem apto/quarto) e **deve permanecer assim**. A IA nunca interpola a unidade, então não há de onde vazá-la.

- **Mudança só de prompt + documentação.** Reescreve `<encontro_e_endereco>` em `regras.md.j2`; atualiza o verbete **Atendimento interno** no `CONTEXT.md`. Sem migration.

## Considered Options

- **Manter o ADR 0023** (IA dá número + complemento exato no fechamento). Rejeitado: expõe a unidade a no-show; o próprio 0023 pediu rediscussão deste tradeoff, e a premissa do prédio mostra que a unidade — não a rua — é o que precisa de gate.

- **IA emite a unidade pós-foto (2-fase robusta no prompt).** Rejeitado: pós-foto a IA está **pausada**; teria de despausar só para soltar o número, reabrindo exatamente a fragilidade que matou o 0023.

- **Coluna `quarto`/`apto` no schema.** Rejeitado: a IA nunca emite a unidade (não precisa do dado), e quarto de hotel é **por-booking**, não atributo estável da modelo — modelar como coluna seria errado.

- **Afrouxar o nível (a) para qualquer momento (inclusive 1º contato).** Rejeitado: entregaria a rua a quem só sonda preço e nunca aparece. O gate em intenção real (`Qualificado`+) relaxa de verdade (rua em vez de só região) sem despejar o endereço para tire-kickers.

## Consequences

- **Supersede o ADR 0023.** A "Decisão" e as "Consequences" do 0023 (número exato no fechamento; foto deixa de ser gatilho) passam a estar incorretas; este ADR é a fonte de verdade.

- **Reintroduz um gate na unidade** que o 0023 havia removido — mas via **humana**, não via 2-fase de prompt. É deliberado e diferente do desenho antigo; registrado aqui para não ser lido como rollback cego.

- **Invariante de dado:** `endereco_formatado` deve permanecer **nível-prédio** (sem apto/quarto). Se uma modelo cadastrar a unidade nesse campo, a IA vazaria o nível (b) só por emitir o campo. Validação no cadastro (painel) fica fora do escopo deste ADR — registrado como risco a cobrir.

- **Output-guard (`aup_saida.md`):** a IA passa a emitir **menos** (rua+número, sem a unidade); o whitelist do ponto de encontro interno (memória `output_guard_falso_positivo_endereco_interno`) segue cobrindo rua+número sem reabrir o falso-positivo de `system_leak`.

- **Sem migration.** Deploy exige recarregar o worker (`docker service update --force <stack>_barra-worker`; nunca `restart` em Swarm). §0: deploy em prod só com autorização explícita.
