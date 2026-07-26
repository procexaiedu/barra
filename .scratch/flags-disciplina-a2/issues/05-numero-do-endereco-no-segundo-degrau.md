# 05 — O número do endereço só quando o encontro está de pé

**What to build:** O bloco de ponto de encontro passa a chegar à IA **sem o número** enquanto o encontro não está confirmado — ela recebe nome do hotel e rua, e o número só entra quando o cliente já confirmou que vai. Hoje o endereço completo entra a partir de `Qualificado` e o prompt pede que ela corte o número sozinha; o primeiro dia de prod mostrou que a prosa de degraus não segura o DeepSeek. Mesmo molde do gate estrutural que já existe (o endereço nem entra no contexto antes de `Qualificado`) e do `<sem_periodo_longo>`: o que a IA não recebe, ela não vaza.

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [x] Segundo degrau no gate do local de encontro: em `Qualificado`, o endereço renderiza **sem o número**; de `Aguardando_confirmacao` em diante (ou com aviso de saída registrado), renderiza completo.
- [x] Remoção do número é determinística sobre o endereço formatado do cadastro, preservando logradouro, bairro e cidade. Testes com os formatos que o cadastro produz hoje, incluindo endereço sem número e número com complemento.
- [x] O texto do bloco acompanha o degrau: enquanto o número não está lá, a instrução diz o que fazer se ele pedir o número (confirmar que vai destrava), em vez de instruir a esconder um dado que ela tem.
- [x] O detector de "endereço já passado" continua funcionando nos dois degraus (ele já descarta tokens puramente numéricos) — teste de regressão.
- [x] O trecho de degraus do `<tipos_de_encontro>` encolhe no que virou estrutural; a conduta que **sobra** para a IA (vender o local como hotel, nunca revelar a unidade) permanece intacta.
- [ ] `make gate-conduta` e `make evals` verdes; gate padrão verde.

## Comments

**2026-07-25 — implementado.** Gate padrão verde (`make lint`, `make typecheck`, `make test`: 1679 passed). `make gate-conduta` e `make evals` **não rodaram**: o gate-conduta exige `TEST_DATABASE_URL` (ausente nesta máquina) mesmo com `ARGS="--fake"`, e os evals batem na Anthropic — crédito real, autorização à parte (CLAUDE.md §0). Ficam pendentes antes do redeploy.

O aviso de saída não virou condição própria: ele só é carimbado em interno + `Aguardando_confirmacao` (`_aviso_saida_aplicavel`) e o estado nunca regride, então já cai do lado liberado do degrau.

Como a mudança reverte uma escolha explícita do ADR 0026 ("o degrau do número é prosa — deliberado"), o ADR ganhou emenda 25/07 e o verbete de **Atendimento interno** do `CONTEXT.md` foi ajustado.
