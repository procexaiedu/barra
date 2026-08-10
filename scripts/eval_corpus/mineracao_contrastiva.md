## Mineração contrastiva do corpus do Vendedor — relatório de ação

> Gerado por `wf_mineracao_contrastiva.js` (16/06). 39 agentes, read-only sobre `corpus.*`,
> moeda Claude Code (sem crédito Anthropic de prod). WIN=`fechou_logistica` vs
> LOSS=`desviou`/`objecao_preco` (exclui `silenciou`, que é alavanca de reengajamento).
> Mineração viu ~1/2 da população; verificação de lift rodou contra as 775 threads rotuladas.

**Resumo.** 104 candidatos brutos → 19 canônicos → **5 net-new com lift**, 6 já codificados,
6 folclore desmentido pelo número, 2 não-operacionalizáveis por regex. O achado mais forte e
operacionalizável é **ancorar horário concreto (hh:mm) no turno seguinte à cotação** — lift +0.26
com o maior n (97) entre os defensáveis, e o prompt hoje só proíbe a pergunta de fechamento
*colada no preço*, deixando o turno seguinte descoberto.

### Net-new com lift (ordenado por lift desc)

| comportamento | lift | n_com | momento | onde plugar |
|---|---|---|---|---|
| Sinaliza preparo pessoal pós-confirmação ("me arrumando pra você") | +0.37 | 38 | pós-fechamento | `regras.md.j2` `<pix_externo>` / fim da logística — conduta **anti no-show**, não conversão |
| Âncora de horário concreto (hh:mm) com pergunta de confirmação | +0.26 | 97 | turno N+1 da cotação | `regras.md.j2` `<cotacao>` (estende a regra do "seria hoje?" pro turno N+1) |
| Probe de ETA ("chega em quanto tempo?") logo após o "vou" | +0.24 | 74 | logística | `regras.md.j2` `encontro_e_endereco` |
| Gancho de escassez real de agenda ("fico até quinta", "de passagem") | +0.18 | 35 | reforço pós-cotação | `regras.md.j2` `<cotacao>` com guard de timing (proibido no turno do preço) |

> `logistica-completa-proativa-acesso` (lift +0.24, n=56) ficou **fora do top**: o regex mede
> majoritariamente "é atendimento interno" (logística de ap/andar/interfone só existe no interno,
> que já concentra intenção física), e a conduta colide com `encontro_e_endereco` ("segura o
> endereço completo até a hora"). Reverter regra vigente exige evidência causal, não associação
> confundida por `tipo_atendimento`.

### Redações sugeridas (tom do Vendedor, minimalista, sem em-dash)

**1. Âncora de horário concreto (`<cotacao>`):** Depois que você cota e o cliente responde
qualquer coisa, mesmo vago, não fique esperando ele puxar o horário. Já joga um horário concreto
pra ele confirmar: "consigo às 13h30, fecha?", "te encaixo às 23h, pode ser?". O número primeiro,
o horário vem no turno seguinte ao preço, nunca colado nele.

**2. Probe de ETA (logística):** Quando ele disser que vem ("vou sim", "tô indo"), já pergunta o
tempo de chegada numa bolha curta: "chega em quanto tempo amor?", "me avisa quando tiver chegando".
Isso prende o compromisso e te deixa pronta.

**3. Escassez de agenda (`<cotacao>`, pós-acordo só):** Se a sua agenda fecha de verdade, pode usar
isso como reforço depois que ele já mostrou interesse, nunca no turno do preço: "essa semana eu
fico só até quinta vida", "tô de passagem, saio terça". É informação calorosa de disponibilidade,
não pressão em cima da cotação.

**4. Preparo pessoal (pós-fechamento):** Com o horário já combinado, manda um toque de que tá te
esperando: "vou me arrumar todinha pra você 🥰", "já tô me produzindo". Humaniza e segura o cliente
até a hora. É conduta pós-fechamento, não pra empurrar venda.

### Descartados e por quê

**Já codificado (não fazer PR):** `desconto-unico-sem-espiral` (`<desconto>`), `upsell-duracao`
(`upsell é livre`), `da-preco-direto` (`<cotacao>`), `responde-fetiche-direto` (`<servicos_e_extras>`/
`<quote>`), `reengaja-com-acao` (`<reengajamento>`), `pix-proativo` (`<pix_externo>`).

**Folclore desmentido pelo número (novo_sem_lift):** `pede-nome-cliente` (+0.30 bruto colapsa ao
controlar comprimento), `transicao-imediata-logistica` (+0.26), `confirma-disponibilidade` (+0.21),
`follow-up-trajeto` (+0.20), `envio-de-midia-pos-cotacao` (+0.37) — todos survivorship/profundidade:
o texto aparece porque a thread já estava quente. Mídia pós-cotação inclusive **colide** com a
proibição de "mídia a frio". `propoe-horario-quando-adia` (+0.04) abaixo do limiar.

**Não-operacionalizável (candidatos a juiz LLM com janela de 2 turnos):** `freia-insistencia-apos-recusa`
(cross-tab dá o oposto, survivorship), `ignora-pedido-de-video-redireciona` (bigrama sequencial,
só 3 JIDs de evidência).

### Caveat honesto

Lift aqui é **associação, não causa.** Todos os 4 do top carregam confound de seleção/survivorship
(o Vendedor propõe horário/ETA/preparo quando a thread *já* está quente), então parte do efeito
reflete a qualidade do sinal de intenção, não só o texto. Separar causa de seleção exige A/B ao vivo
ou validação no simulador offline (`wf_simulador.js`). **Não colar no prompt sem validar.**
Recomendado começar pelo #2 (âncora de horário): maior n defensável e encaixe limpo numa regra
já existente.

---

## Rodada 2 — juiz LLM de janela 2-turnos (`wf_juiz_bigrama.js`, 16/06)

Testou os 2 candidatos `nao_operacionalizavel` que regex não pegava, com 3 juízes **cegos ao
desfecho** detectando o gatilho na fala do cliente + o braço da resposta do Vendedor, e
estratificando a conversão (`label_bin` GOOD%) por braço **dentro da população com gatilho**.
(Gotcha do run: o `fetch-labels` morreu num rate-limit transitório na 1ª passada — `labels=0`,
estrato vazio; o resume com retry resolveu. Não confundir com a ponte `@lid→telefone`: o
`label_bin` é chaveado por `(instancia, remote_jid)`, junta normal.)

**Recusa (`freia-insistencia-apos-recusa`) — SE SUSTENTA, merece A/B.**

| braço | n | GOOD% |
|---|---|---|
| recuou | 20 | 65.0% |
| insistiu | 26 | 34.6% |
| neutro | 15 | 53.3% |

recuou − insistiu = **+30.4pp, z=2.05** (~p<0.05). Recuar com leveza após recusa/encerramento é o
melhor braço; insistir é o pior. Conduta generaliza além do `<desconto>` (que já tem recusa-leve
só no eixo preço). → levar pro `wf_simulador.js` como braço A (recuar) vs B (insistir).

**Vídeo (`ignora-pedido-de-video-redireciona`) — INCONCLUSIVO, não mexer.** Gatilho raro (n=5 vs 5);
contraste −40pp, z=−1.58 (*contra* a hipótese). `ofereceu_midia` — a **conduta atual do prompt** —
fez 5/5: o teste **validou a regra vigente** (`protocolo_provas_humanidade`) em vez de derrubá-la.

Caveat persiste: a escolha do braço pelo Vendedor não foi randomizada (ele pode recuar justo nas
threads que já iam bem). z mede associação; só A/B fecha causa.

---

## Rodada 3 — A/B de conduta no simulador (`wf_simulador.js`, 16/06)

3 braços de prompt renderizados fiéis (editar `regras.md.j2` → render → reverter via git):
`base` (v1 atual), `+recusa` (novo bloco `<recuo>`), `+ancora` (estende `<cotacao>` pro turno N+1).
6 personas focadas × 2 reps = 36 conversas. **Mede CONDUTA, não conversão** (desfecho do simulador
é κ=0.07, inútil) — o gate é "a regra dispara sem efeito colateral". n=2/célula + truncamento por
rate-limit em alguns turnos → **direcional, não estatístico**.

| braço | empurrão | calor | robótico | violações |
|---|---|---|---|---|
| base | 33% | 83% | 50% | 0 |
| +recusa | 42% | 100% | 17% | 0 |
| +ancora | 8% | 83% | 0% | 0 |

**+ancora — vitória limpa.** Empurrão caiu 33%→8% e robótico zerou (o oposto do risco temido): a
regra reforça a separação "número primeiro, horário no turno seguinte, nunca colado", e o modelo
parou de grudar urgência no preço. Calor mantido, zero violação. → candidato a PR no `<cotacao>`.

**+recusa — direcionalmente bom, seguro.** Robótico 50%→17%, calor 83%→100%, zero violação. O
empurrão de 42% NÃO vem da regra: as notas mostram que é "seria hoje?"/CTA-logística colada na
**cotação** (= comportamento do base, ruído de n=2), não no momento da recusa. → seguro, mas
sinal mais turvo; vale re-run mais limpo (mais reps, sem truncamento) antes de commit definitivo.

Texto das regras testadas (fiéis às redações sugeridas da rodada 1):
- `<recuo>` (antes de `<reengajamento>`): "Quando o cliente recusa um serviço... ou sinaliza que vai
  pensar ('depois te chamo', 'outra hora', 'vou ver'), recue com leveza e sem reempurrar... Insistir
  ... depois que ele recuou afasta."
- `<cotacao>` +N+1: "No turno seguinte ao preço, quando o cliente responder qualquer coisa, mesmo
  vago... ofereça você um horário concreto pra ele confirmar... O número primeiro, o horário concreto
  vem no turno seguinte ao preço, nunca colado nele."
