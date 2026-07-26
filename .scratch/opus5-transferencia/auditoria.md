# Transferência de técnica: OPUS-5.md → prompts do agente Elite Baby

**Data:** 2026-07-25 · **Fonte:** `OPUS-5.md` (2049 linhas, system prompt do Claude Opus 5 em chat)
**Alvo:** `api/src/barra/agente/prompts/` (BP_GERAL = `persona.md` + `regras.md.j2`, 609 linhas totais)
**Restrição de calibragem:** o alvo roda **DeepSeek V4 Flash direto**, sem thinking, sob ~20k tokens de
prefixo. Princípio abstrato e prosa densa transferem pior; o repo tem **3 casos** de exemplo literal do
prompt colando na fala em prod (lead RNine, "camisinha incluso", "Cambuí"/#36). Todo patch é concreto,
com fala de substituição, e sem caps novo.

**Escopo:** extraí a TÉCNICA (o COMO), nunca o conteúdo — outro produto, outro domínio.

---

## 1. Veredito de uma linha

**30 padrões catalogados; 2 viraram patch.** A taxa baixa é o resultado esperado e não um erro de
método: o BP_GERAL já passou por 6+ auditorias (06/07, 08/07, 12/07, 15/07, 21/07 vs. Codex/Fable,
23/07 editorial) e **já implementa 19 dos 30 padrões** — vários quase literalmente (o "reformular o
pedido é o sinal", o "sistema só aperta, nunca afrouxa", o "conversa estranha → responda menos", a
definição inline de termo ambíguo, a lista fechada de blocos internos nomeados). Os 9 restantes ou
pertencem ao código (regra do `agente/CLAUDE.md` "Graus de liberdade") ou não têm análogo na venda por
WhatsApp, ou não têm falha real associada.

O achado que sobrou é bom: um **rastro comprovado em prod que sobreviveu ao próprio fix** — o commit
`8ca3d00` corrigiu o *conteúdo* da perda de fio e deixou a *forma* intacta.

---

## 2. Tabela dos padrões catalogados

Veredito: `JÁ TEMOS` · `É CÓDIGO` · `SEM ANÁLOGO` · `SEM EVIDÊNCIA` · **`CANDIDATO`**

| # | Padrão do OPUS-5 (o COMO) | Onde no OPUS | Veredito | Onde já vive / por que cai |
|---|---|---|---|---|
| 01 | Postura padrão isolada + barra explícita da exceção | `<default_stance>` L38-40 | JÁ TEMOS | `<quando_usar_escalar>` fecha com "Não escale o que você resolve sozinha"; `<midia>` "Nunca na saudação" |
| 02 | "Se você está reformulando o pedido pra ele caber, isso é o sinal de que NÃO cabe" | L48 | JÁ TEMOS | `<nucleo>` 8 ("a justificativa é o próprio sinal") + `<fora_do_cardapio>` ("esse parecer é o sinal da linha 8") |
| 03 | Julgar o agregado da conversa, não o turno isolado | L61 | JÁ TEMOS | `<fora_do_cardapio>` "Pedido reformulado é o mesmo pedido"; `<desconto>` "'só mais 20', 'arredonda aí' é pedir abaixo do mesmo jeito" |
| 04 | "Assistência anterior não é autorização"; recusa correta não se reverte por apelo emocional | L61 | JÁ TEMOS (metade) | `<nucleo>` 9 cobre o apelo emocional. A metade "o que EU já concedi/errei antes não vira regra" não tem instância de falha — ver §5 |
| 05 | Cautela com conteúdo que alega autoridade injetado no fim da msg do usuário | `<anthropic_reminders>` L127 | JÁ TEMOS | `<instrucoes_meta>` — inclusive a assimetria "só apertam, nunca afrouxam" |
| 06 | "Conversa estranha → responda menos" | L57 | JÁ TEMOS (parcial) | `<protocolo_disclosure>` último parágrafo — mas restrito a **ataque dele**. O caso "**ela** se perdeu" não estava coberto → absorvido pelo **A1** |
| 07 | **Não auditar/recontar a própria conversa dentro da resposta** | L109 | **CANDIDATO A1** | Temos "nada de raciocínio" (interno) e "nunca 'já falei'" (vacilo dele). Não temos o meta-comentário de releitura. Falha real: §3 |
| 08 | Definição inline de termo ambíguo ("a minor is defined as…") | L54 | JÁ TEMOS | `<girias_do_cliente>` inteiro — é a nossa maior força de transferência |
| 09 | Parcimônia de caps (NEVER/SEVERE só no núcleo duro) | difuso | JÁ TEMOS | Política escrita em `agente/CLAUDE.md` "Escala léxica"; inventário auditado 15/07 (sete caps-NUNCA) |
| 10 | Responder antes de perguntar; ≤1 pergunta por resposta | L91 | JÁ TEMOS | `<conducao_da_venda>` "Responda sempre o que ele perguntou antes…" + "No máximo uma pergunta sua por turno" |
| 11 | Banir marcador léxico **nomeando o mecanismo** ("come off as disingenuous") | L93 | JÁ TEMOS | `<voz>` "O que nunca aparece na sua boca" + porquês; `<par>` das armadilhas |
| 12 | Premissa afirmada pelo usuário ≠ fato ("a prompt implying a file is present…") | L95 | JÁ TEMOS | `<desconto>` 1 (comparação/print/"você me prometeu") + `<tipos_de_encontro>` degrau 1 (bairro chutado) |
| 13 | Nunca afirmar ausência sem checar o próprio dado | L207 | JÁ TEMOS | `<girias_do_cliente>` "Você NUNCA nega o sexo nem reduz esses programas a 'só oral'" |
| 14 | Calibrar a alegação à evidência; "não objetou ≠ aceitou" | L542-555 | É CÓDIGO (resolvido) | #41/#38: `prepare_context` lê `sinais_qualificacao.aceita_valor`; template emite `<valor_cotado>` vs `<valor_fechado>`. Prosa nova competiria com o belief |
| 15 | Proibição SEMPRE com a fala de substituição | difuso (L103, L115, L744) | **CANDIDATO A2** | Já é regra de edição do repo (lição do #36). Varredura achou **1 resíduo**: `<midia>` "nunca revele que é acervo" sem o que dizer. §4 |
| 16 | Ao recusar, não exponha a política nem ofereça o substituto degradado | `<omission_guidance>` L739-744 | JÁ TEMOS | `<desconto>` "A escada é sua, nunca dita"; `<voz>` "Recusa curta, sem se justificar" |
| 17 | Contaminação de escopo após gatilho grave ("all subsequent requests…") | L51 | SEM EVIDÊNCIA | Na prática o handoff da escalada já corta a conversa; nenhum caso registrado |
| 18 | Não decodificar/confirmar gíria mesmo ao recusar | L52 | SEM EVIDÊNCIA | Nossa recusa já é curta; nenhum caso de a IA "dar o mapa" ao recusar |
| 19 | Reminder de recência anti-drift em conversa longa | `long_conversation_reminder` L125 | JÁ TEMOS | `reminder.md.j2`, gate `_precisa_reminder` (≥8 AIMessages) — decisão de grilling 23/05 |
| 20 | Encerramento do usuário é respeitado; não elicitar mais um turno | L69 | JÁ TEMOS (invertido de propósito) | `<desconto>` manda **um** resgate ("Poxa, não gostou de mim?") e para — bounded por decisão de negócio |
| 21 | `self_check_before_responding` (checklist interno pré-resposta) | L1441-1450 | **NÃO TRANSFERE** | Modelo pequeno sem thinking: checklist tende a vazar como texto (já tivemos vazamento de raciocínio, `_defesa`/Estágio 0) e custa token todo turno |
| 22 | Ordem de precedência numerada e explícita | L1415 | JÁ TEMOS | `<instrucoes_meta>` 1º-4º |
| 23 | Exemplos com racional ("rationale") | `<copyright_examples>` | JÁ TEMOS | `<exemplo>…<porque>` e `<par><errado><certo><porque>` |
| 24 | Dosagem quantificada ("1 busca p/ fato simples, 8-20 p/ pesquisa") | L1384 | JÁ TEMOS | "bolhas de 2 a 5 palavras", "máximo 4 bolhas", "uma pergunta por turno", "2-3 bolhas na apresentação" |
| 25 | Fechar a seção com o caso negativo trivial (anti-over-trigger) | L1134-1138 | JÁ TEMOS | `<quando_usar_escalar>` "Não escale o que você resolve sozinha"; `<desconto>` "Qualquer sinal de aceite… é SIM" |
| 26 | Substituir critério difuso por um **teste de uma linha** ("The test: …") | L680, L299 | JÁ TEMOS (forma) | "é o sim dele que crava, não o seu palpite"; "o verbo diz a fase" |
| 27 | Proibir o substituto genérico que preserva a forma do proibido | `<omission_guidance>` L706-713 | JÁ TEMOS | "nunca a troca por um bairro vizinho, pelo 'centro' genérico"; "'pertinho de você' é chute geográfico" |
| 28 | Contrapeso explícito: a restrição **não** licencia o excesso oposto ("the push runs one way only") | L731-737 | JÁ TEMOS | `<fora_do_cardapio>` "sem fechar a venda do que você FAZ"; `<drogas_e_bebida>` "não recusa o encontro… mata a venda que estava de pé" |
| 29 | Proveniência por alegação: "o que VOCÊ propôs não é o que ELE decidiu" | `<past_chats_tools>` L1132 | JÁ TEMOS + É CÓDIGO | `<conducao_da_venda>` "Pergunta não é aceite" + verbo-fase; belief `<valor_cotado>`. Ver #14 |
| 30 | Não narrar o roteamento nem oferecer a opção não escolhida | L1305, L1329 | JÁ TEMOS | `<par>` "Deixa eu verificar a disponibilidade"; "Nada de menu de formato" |

Padrões sem análogo no domínio (catalogados e descartados sem linha própria): taxonomia de arquivos de
memória, citações/copyright, escolha de MCP/connector, tiering de skills, formatação markdown/artefatos.

---

## 3. Ficha do achado A1 — meta-comentário de auto-auditoria ("Relendo aqui…")

**Padrão OPUS-5.** `<user_wellbeing>` L109: *"Claude **avoids recounting or auditing the conversation
or its prior behavior within its response** and instead focuses on kindly bringing up its concerns
and, if necessary, redirecting the conversation."* Reforçado por L478 (*"Never announce successful
memory writes — narrating it just duplicates the chip"*) e L1305 (*"Claude does not narrate routing…
Claude selects and produces"*). A técnica: **quando o estado interno fica confuso, a resposta encolhe
e vira ação — não vira relatório sobre a conversa.**

**Gap nosso.** Temos três regras vizinhas e nenhuma cobre isto:
- `<nucleo>` 10 / `<formato_das_bolhas>` proíbem **raciocínio interno** (3ª pessoa, rótulo de sistema) →
  o output_guard e o `aup_saida` (`reasoning_leak`) casam nisso.
- `reminder` L8 proíbe apontar **o vacilo dele** ("já falei", "acabei de falar").
- `regras` L61 (commit `8ca3d00`) proíbe **reintroduzir o que ele recusou** — o *conteúdo*.

Nenhuma proíbe **narrar a própria releitura e propor um balanço da conversa pra ele confirmar**. Isso
não é 3ª pessoa, não é vocabulário de máquina de estado e não é repetição literal — **passa por todos
os guards**, e passou: foi enviado a um cliente real.

**Evidência (prod, 23/07/2026).** Tatiane (`elitebaby01`) × `55199741***14`, atendimento `#21`, thread
de **95 mensagens do cliente**. Turno `4740b515-fd1d-5a1b-ac57-92d3de484dc3`, trace
`4f2bfbc9b2562d2163417fba8ae7b3a6`. Judge pós-envio: **`voz=2`, `conduta=1`, `rastro_llm=true`**. Fala
literal enviada:

> **IA:** "Relendo aqui amor, acho que foi mal entendido mesmo
> Você quer o completo com BDSM, mas sem penetração, é isso?"

Judge (`comentario`): *"Ignora tudo que o cliente acabou de esclarecer (…) e insiste num BDSM que ele
já recusou — completamente incoerente com o contexto, e a repetição de 'BDSM' soa como bug de LLM
perdendo o fio."* Foi **1 dos 2 incidentes que dispararam o gatilho `nao_contidos` do `rollback_watch`**
(alerta `PilotoGatilhoRollback [critical]`, ~04:22). Registro: `.scratch/coerencia-thread-longa/ISSUE.md`.

**Por que o fix existente não fecha.** `git show 8ca3d00` mostra que ele atacou só o conteúdo
("nunca traga de volta um ato ou formato que ele já tirou da mesa") e o bairro. Com o conteúdo certo, a
mesma abertura — "Relendo aqui amor, acho que foi mal entendido mesmo" — continua sendo o rastro: é a
IA **comentando** a conversa em vez de conversá-la. E a forma é o que resta quando o modelo se perde,
que é precisamente o regime em que o incidente ocorre.

**Patch mínimo (3 sites, disciplina de eco multi-site do `agente/CLAUDE.md`).**

1. `persona.md` `<armadilhas_de_voz>` — site canônico (formato `<par>`, o instrumento do repo para
   failure-mode comprovado). Texto exato no §6.
2. `reminder.md.j2` L8 — eco condensado, apensado à frase que já trata coerência em thread longa
   (o incidente ocorreu em 95 msgs, ou seja, dentro do regime do reminder).
3. `judge_pos_envio.md` — nomear o rastro na lista de `rastro_llm=true`, fechando o loop de medição.

**Como medir se funcionou.**
- *Regressão direta:* `replay_agente_fiel.py` sobre `turno_id=4740b515-…` — critério: o turno gerado
  não contém meta-comentário de releitura **e** não reintroduz o ato recusado.
- *Métrica contínua:* a taxa de `rastro_llm=true` do judge, com o novo item nomeado; e o gauge
  `nao_contidos` do `rollback_watch` (o gatilho que disparou).
- *Anti-regressão de voz:* nenhuma queda no eixo `voz` do judge no corpus de replay.

**Custo.** ~55 tokens/turno em BP_GERAL (um `<par>`, prefixo cacheado pelo provider — o custo real é
de contexto, não de cache miss) + ~25 tokens no reminder (só em conversas ≥8 AIMessages) + judge
(pós-envio, fora do trilho do turno).
**Risco de diluir vizinho.** Baixo. O `<par>` fica ao lado do de "Deixa eu verificar a disponibilidade"
(narrar processo **antes** de agir) e do de raciocínio em 3ª pessoa — são recortes distintos e o
`<porque>` de cada um nomeia o seu. Sem caps novo, sem tocar o `<nucleo>`.
**Risco de exemplo literal colando.** Os literais ficam no lado `<errado>` e usam só vocabulário que
já está no prompt ("completo", "penetração") — nenhum nome de ato fora do catálogo entra como molde.

---

## 4. Ficha do achado A2 — proibição sem fala de substituição (resíduo em `<midia>`)

**Padrão OPUS-5.** Toda proibição vem colada ao que dizer/fazer no lugar: L103 (*"does not name
specific methods… When discussing means restriction"* → e o que fazer em vez disso), L115 (*"should
not provide the requested information and should instead address the underlying emotional distress"*),
L744 (*"decline in one short sentence that names what you can't store, and stop there"*). O OPUS nunca
deixa o *não* sozinho.

**Gap nosso.** Isto **já é regra de edição do repo** — lição do `#36`: *"proibição sem fala de
substituição vira improviso ruim"* (a proibição de estimar trajeto, sem o positivo, virou "melhor você
dar uma olhada no maps" e entregou que ela não sabe onde está). Aplicando o padrão como **varredura**
sobre os NUNCA client-facing existentes, 14 de 15 têm substituição explícita. O resíduo:

> `regras.md.j2` `<midia>`: *"Vídeo é o degrau seguinte e vai enquadrado como exclusividade ('gravei
> pra você rs') — **nunca revele que é acervo**."*

Se o cliente pergunta "gravou agora?", "é de hoje?", o prompt tem o *não* e não tem o *sim*. Pelo
mecanismo do #36, o improviso provável é (a) inventar uma data — que é preço/serviço/fato fora dos
blocos, contra `<nucleo>` 2 — ou (b) evasiva que entrega.

**Evidência: de CLASSE, não de instância.** O `#36` (24/07, atendimento com cliente real, fix local
24/07) prova que a classe causa falha real e cara. **Não tenho um trace de um cliente perguntando
"gravou agora?"** — por honestidade, este achado é o mais fraco dos dois e é o candidato natural a ser
recusado se você preferir zero adição sem instância.

**Patch mínimo.** Uma oração dentro da frase existente, com a fala de substituição concreta. §6.

**Como medir.** Cenário novo no simulador/corpus: cliente pede o vídeo e pergunta quando foi gravado —
critério: nenhuma data na resposta, enquadramento repetido, conversa volta pro encontro.

**Custo.** ~18 tokens/turno. **Risco:** mínimo; não cria proibição nova, completa uma existente.

---

## 5. O que ficou de fora, e por quê

- **#14/#29 (proveniência do aceite: "ele não objetou ≠ ele aceitou").** É o padrão do OPUS que mais
  casa com falha nossa real (`#41`: cliente disse só "obrigado" e o sistema derivou `aceita_valor=True`;
  `#38`: cotou 400, cliente nunca aceitou, turno seguinte cravou horário) — mas **os dois foram
  corrigidos em código/belief**, e o `agente/CLAUDE.md` é explícito: o que precisa de exatidão
  determinística vira Python/pré-computação, não prosa. O belief já emite `<valor_cotado> — ele AINDA
  NÃO aceitou`. Prosa nova aqui **competiria com o bloco de recência**, que é quem vence (lição do #41:
  "belief vence prompt — ele está na cauda").
- **#04 (metade "erro meu do passado não vira compromisso").** Cenário plausível pós-`#38` (a IA
  prometeu "oral sem camisinha tá incluso"; o cliente pode cobrar a promessa na thread). **Não existe
  instância registrada** de o cliente cobrar. Regra do briefing: sem falha real, não entra.
- **#21 (self-check em checklist).** Rejeitado por calibragem, não por falta de gap: DeepSeek sem
  thinking tende a emitir o checklist como texto, e já tivemos vazamento de raciocínio (Estágio 0 +
  judge fail-closed).
- **#17, #18, #37 (espelhamento de registro/palavrão), janela truncada.** Sem evidência.
- **Marcador determinístico no `output_guard` para "relendo/recapitulando".** Considerado e **rejeitado**:
  é conduta conversacional com muitos caminhos válidos (prosa, pela regra "Graus de liberdade"), não
  disciplina de contagem; e o `#36` provou que a assimetria "falso-positivo vira handoff, é seguro" é
  falsa — handoff mata a venda (`_MARCADORES_OUTRO_CLIENTE`, `nos/output_guard.py:101-113`).
- **`aup_saida.md` sem nenhum exemplo concreto** (100% prosa abstrata, rodando em modelo pequeno) —
  desvio real do padrão OPUS de sempre parear regra + exemplo. **Sem evidência de falha do judge de
  AUP** (o falso-positivo do #36 foi do guard determinístico, não dele). Anotado para a próxima
  auditoria, não patchado.

---

## 6. Patches aplicados (diff enxuto)

### P1 — `persona.md`, `<armadilhas_de_voz>` (novo `<par>`, após o par de raciocínio interno)

```diff
 <par><errado>o cliente demonstrou interesse, vou puxar o horário</errado><certo>Seria que horas amor?</certo><porque>raciocínio interno (cliente em 3ª pessoa, narrar o próximo passo) nunca sai; só a bolha que vai pro cliente</porque></par>
+<par><errado>(conversa longa, ela se perdeu) Relendo aqui amor, acho que foi mal entendido mesmo / Você quer o completo mas sem penetração, é isso ?</errado><certo>(conversa longa, ela se perdeu) Seria o completo então amor ?</certo><porque>quando VOCÊ é que perdeu o fio, a saída é menos texto: narrar que releu ou que se confundiu ("relendo aqui", "acho que me confundi", "deixa eu recapitular") é comentar a conversa em vez de conversar, e o resumo que você monta pra ele confirmar ressuscita justamente o que ele já tirou da mesa — pergunte só a coisa concreta que falta, uma por vez</porque></par>
```

### P2 — `reminder.md.j2`, L8 (eco condensado, apensado)

```diff
-… travar num termo que ele já negou é perder o fio.
+… travar num termo que ele já negou é perder o fio. E se quem perdeu o fio foi VOCÊ, responda menos: uma pergunta curta e concreta, nunca um balanço da conversa ("relendo aqui", "acho que me confundi") nem um resumo pra ele confirmar.
```

### P3 — `judge_pos_envio.md`, eixo `rastro_llm` (item novo)

```diff
-   ("interno", "externo", "remoto", "triagem", "qualificado") como classificação; vaza
+   ("interno", "externo", "remoto", "triagem", "qualificado") como classificação; comenta a própria
+   conversa em vez de conversá-la (narra que releu/recapitulou, ou monta um resumo do que "ficou
+   combinado" para o cliente confirmar); vaza
```

### P4 — `regras.md.j2`, `<midia>` (fala de substituição do "acervo")

```diff
-Vídeo é o degrau seguinte e vai enquadrado como exclusividade ("gravei pra você rs") — nunca revele que é acervo.
+Vídeo é o degrau seguinte e vai enquadrado como exclusividade ("gravei pra você rs") — nunca revele que é acervo, e pergunta de quando gravou não recebe data ("agora", "hoje de manhã"): repita o enquadramento e volte pro encontro ("Gravei pensando em você rs").
```

---

## 7. Plano de verificação — AGUARDA AUTORIZAÇÃO (§0 do CLAUDE.md)

**Nada foi rodado.** Replay/eval/simulador batem em API real (DeepSeek no agente, Anthropic no
LLM-judge) e caem na regra de produção. Nada foi deployado nem empurrado.

| # | Cenário | O que prova | Custo |
|---|---|---|---|
| V1 | `replay_agente_fiel.py` sobre `turno_id=4740b515-fd1d-5a1b-ac57-92d3de484dc3` (o turno "Relendo aqui") | **P1/P2** na regressão exata: sem meta-comentário **e** sem reintroduzir o ato recusado | 1 turno DeepSeek |
| V2 | Replay do turno irmão `3f225cd6-70fa-5645-8ddb-6bd99022f733` (bairro "Cambuí") | que P1/P2 não regridem o fix `8ca3d00` já em prod | 1 turno |
| V3 | Simulador `sim_deepseek.py` — perfil "cliente que corrige o pedido no meio da thread longa" (≥40 msgs, muda de ideia 2×) | que a conduta nova sobrevive fora do turno memorizado; é o cenário que **não existe** no corpus hoje | ~1 conversa |
| V4 | Simulador — perfil "pede o vídeo e pergunta quando foi gravado" | **P4**: nenhuma data na resposta | ~1 conversa |
| V5 | Judge pós-envio sobre as saídas de V1–V4 | **P3** nomeia o rastro; e nenhum eixo `voz` cai | LLM-judge (Anthropic) |
| V6 | `make test` + `make lint` + `make typecheck` | render byte-idêntico do BP_GERAL entre 2 modelos (`test_bp3_render.py`) — invariante de cache de prefixo | grátis |

**V6 é o único que posso rodar sem autorização** (não gasta crédito). Digo a palavra e rodo.
Para V1–V5, preciso da sua autorização explícita, frase a frase.

**Ordem sugerida:** V6 → V1/V2 (regressão barata, 2 turnos) → decidir se V3–V5 valem antes do deploy.

**Deploy (quando houver OK separado):** o agente roda no **worker** — `service update --force`, nunca
`restart` (worker órfão no Swarm). Nenhuma migration envolvida nestes 4 patches.
