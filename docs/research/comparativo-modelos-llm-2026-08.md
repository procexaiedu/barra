# Quais modelos entram no eval — comparativo 2026-08

**Data:** 11/08/2026 · **Escopo:** escolher os modelos que entram na bateria de evaluation do agente conversacional do Elite Baby.
**Método:** 7 agentes de pesquisa web (≈450 buscas/fetches), coleta primária no OpenRouter (API + UI), telemetria própria (Langfuse + Postgres de prod) e medição de rede local.

> **Este documento não escolhe o modelo de produção.** Ele decide *quem entra na pista* e *o que a pista precisa medir*. A escolha final é do eval.

> **Decidido em 11/08/2026:** escopo aprovado nos **6 braços** da tabela abaixo. Claude Sonnet 5 fica **fora**, nem como sonda. **Nenhuma chamada ao vivo foi feita** nesta pesquisa — o teste empírico de recusa e latência entra junto com a bateria, não antes.

---

## 1. A resposta em uma página

### Entram no eval

| # | Braço | Configuração | Por que entra |
|---|---|---|---|
| 1 | **DeepSeek V4 Flash** (controle) | `thinking: disabled`, temp 0,7 — prod hoje | Baseline. **Pinar em `0731` via OpenRouter** para a corrida do eval (ver §7). |
| 2 | **DeepSeek V4 Flash** (irmão) | `thinking: low` | O A/B anterior testou `high` e reprovou. `low`/`medium` **nunca foi testado** e é onde a evidência nova aponta (§3). |
| 3 | **GPT-5.6 Luna** | `reasoning_effort: low` | Único pago que, **com o nosso cache real, sai mais barato que o DeepSeek** (§4). Sicofância 1,0%. |
| 4 | **Gemini 3.6 Flash** | `thinking_level: minimal` | Sonda de disciplina e o melhor OCR/multimodal do grupo. Caro (12,9×) — entra para responder "quanto custa disciplina", não para adotar. |
| 5 | **MiniMax M3** | padrão | **#1 absoluto em IFBench (82,9 de 144 modelos)**, TTFT 1,34 s, 1M ctx, pesos abertos. Ninguém tinha colocado na lista. |
| 6 | **Mistral Large 3** ou **Medium 3.5** | padrão | **Única política de uso tier-1 que não colide com o domínio** (§2). Braço de contingência contratual. |

### Não entram (e por quê)

| Modelo | Motivo |
|---|---|
| **Claude Sonnet 5** | Recomendo **sonda de teto, não candidato**: aderência ao operador 1,5/10 (§2), AUP proíbe nominalmente "fetiches" e "erotic chats", custo 17×, ciclo de depreciação ~6 meses, relatos públicos de vazamento de system prompt e over-refusal. Rodar 20 conversas para saber o teto — não 500. |
| **DeepSeek V4 Pro** | Pontua **abaixo** do V4 Flash 0731 no índice AA (45,3 vs 51,8) e custa 4,5×. "Subir para o Pro" não é upgrade. |
| **Claude Haiku 4.5 / Gemini 3.5 Flash-Lite** | AA-II 30 e 37; abaixo do que já temos, sem vantagem de custo relevante. |
| **Kimi K3 / GPT-5.6 Sol / Terra / Qwen3.8 Max** | Excelentes e irrelevantes: 8,8× a 25,7× o custo, para um turno de WhatsApp de 140 tokens de saída. |
| **MiMo-V2.5, Hy3, GLM 5.2** | Baratos, mas latência p50 de 3–8,6 s (§5) mata no WhatsApp. GLM 5.2 fica como reserva se a licença do MiniMax pesar. |

### O que a pesquisa mudou na pergunta

Três achados invertem o enquadramento original:

1. **O eixo decisivo não é inteligência — é aderência ao operador.** No UGI Leaderboard, DeepSeek V4 Flash sem reasoning marca **9,5/10** de aderência ao system prompt; Claude Sonnet 5, GPT-5.6 Luna e Gemini 3.x marcam **1,5/10**. Nesses três, *o system prompt não destrava*: não há engenharia de persona que resolva.
2. **Os números públicos do DeepSeek não são os da nossa produção.** O 51,8 de Intelligence Index é medido em *Reasoning, Max*. Rodamos `thinking: disabled`, cujo equivalente medido (V4 Flash 0423 non-reasoning) é **29,3** — e IFBench cai de 79,2 para **47,2**. Estamos comparando o nosso carro no modo econômico contra a ficha técnica do modo esportivo dos outros.
3. **Trocar de modelo pode custar menos que a tabela sugere — ou muito mais.** Com o nosso cache real de 94,5%, GPT-5.6 Luna sai **0,9×** o custo do DeepSeek. Claude Sonnet 5 sai **17,1×**. A tabela de preço por token não prevê nem um nem outro.

---

## 2. Eixo 1 — política de conteúdo e aderência ao operador (o gargalo real)

Este eixo elimina candidatos antes de qualquer benchmark de qualidade.

### 2.1 Aderência ao operador (UGI Leaderboard, extração do CSV em 11/08/2026)

`Direct` = atende pedido direto do usuário · **`Adherence` = obedece quando o *operador* instrui** — é a coluna que descreve o nosso caso (persona instruída por system prompt).

| Modelo | Direct | **Adherence** | Δ |
|---|---|---|---|
| **DeepSeek V4 Flash (reasoning off)** | 5,0 | **9,5** | +4,5 |
| DeepSeek V3.2 (reasoning off) | 5,0 | 9,5 | +4,5 |
| **Mistral Large 2411** | 6,0 | **9,0** | +3,0 |
| **Mistral Large 3 675B** | 5,0 | **8,5** | +3,5 |
| DeepSeek V4 Flash (**reasoning on**) | 4,0 | **6,5** | +2,5 |
| Grok 4.5 | 7,0 | 4,5 | −2,5 |
| GPT-5.6 Luna | 3,0–4,0 | **1,5** | −2,0 |
| Claude Sonnet 5 | 2,0–3,0 | **1,5** | −1,0 |
| Gemini 3.5/3.6 Flash | 3,0 | **1,5** | −1,5 |
| MiniMax M2.7 | 1,0 | 1,0 | 0 |

**Dois corolários operacionais:**
- **Ligar reasoning no V4 Flash custa 3 pontos de aderência (9,5 → 6,5).** É um segundo motivo, independente de custo e latência, para manter `thinking: disabled` no chat — e um risco a medir no braço #2.
- **Grok é o inverso do que precisamos:** alto no pedido direto, baixo no dirigido por operador.

### 2.2 O que as políticas dizem (trechos verificados)

| Provedor | Texto | Veredito |
|---|---|---|
| **Anthropic** | AUP (15/09/2025) proíbe "Generate content related to sexual fetishes or fantasies" e "Engage in erotic chats". Exceções documentadas cobrem só inteligência governamental. | ❌ Colisão frontal e nominal |
| **OpenAI** | Usage Policies **não** têm veto genérico a sexo adulto; o bloqueio vem do Model Spec ("should not generate erotica"). Adult mode **pausado indefinidamente em 26/03/2026**. | ❌ Bloqueio comportamental |
| **Google** | PUP proíbe "sexually explicit content […] for the purpose of pornography or sexual gratification". O filtro `SEXUALLY_EXPLICIT` é desligável — **a policy não é**. Precedente de parar de honrar filtro desligado sem aviso (mai/2025). | ❌ Filtro ≠ permissão |
| **DeepSeek** | ToU §3.4(5), vigente desde 27/03/2026: proíbe conteúdo "pornographic, obscene, or sexually explicit (**e.g., sexual chatbots**)". §8.2: fechamento de conta + **proibição de re-registro** + reporte a autoridades. | ⚠️ **A cláusula mais on-point do mercado — e é a do modelo que está em produção** |
| **Mistral** | Usage Policy (11/06/2026): no domínio sexual proíbe **apenas** CSAM e imagens íntimas não-consensuais. | ✅ Única tier-1 sem veto geral |

⚠️ **Dois achados das docs oficiais que fecham a questão do Claude e abrem uma nova:**

1. **A Anthropic exige divulgar que se está falando com uma IA no início de cada sessão.** Isso colide frontalmente com o produto — a persona é a modelo. Não é questão de conteúdo: é um requisito de uso que o Barra não pode cumprir por definição.
2. **LGPD, não política de conteúdo, é o risco mais próximo no DeepSeek.** A Privacy Policy declara **armazenamento na China**, **uso de dados para treinar modelos sem procedimento de opt-out documentado** e **retenção sem prazo**. Passamos telefone, endereço e conversa íntima de clientes por esse caminho. Isso precisa de decisão antes de qualquer discussão sobre §3.4(5).

> ⚠️ **Ressalva honesta:** um dos agentes encontrou na policy da Mistral uma cláusula sobre explorar indivíduos "through sexual services". Os dois agentes divergiram na leitura. **Antes de promover a Mistral a plano B, alguém precisa ler a policy inteira com olho jurídico** — não decidir por citação de segunda mão.

### 2.3 O risco que ninguém tinha mapeado

A premissa "serviço adulto, legal no Brasil" é meia-verdade. A prostituição não é crime, mas os **arts. 229 (casa de prostituição) e 230 (rufianismo) do CP** criminalizam tirar proveito econômico da prostituição alheia — e a doutrina aplica o 230 nominalmente a agências de acompanhantes. Isso ativa cláusulas de *"illicit activities"* (OpenAI) e *"illegal purpose"* (OpenRouter) **independentemente de qualquer palavra sexual ser gerada**.

Não é parecer jurídico — é leitura de fontes secundárias. Mas é o vetor que **nenhuma troca de modelo resolve**, e vale a pena o Fernando ouvir um criminalista antes de qualquer conversa formal com provedor.

### 2.4 Preferência revelada: quem o mercado usa de fato

OpenRouter, categoria **Roleplay & Fiction** (3,5% de todo o spend da plataforma) e coleção Roleplay por tokens:

- **DeepSeek V4 Flash 0731: 10,5T tokens/semana — 33,3% da categoria.** Somando as duas revisões, 16,7T.
- Tencent Hy3 10,1T · V4 Flash 0423 6,17T · MiMo-V2.5 5,78T · **GPT-5.6 Luna 5,18T** · GLM 5.2 3,98T · V4 Pro 2,82T · **Gemini 3.6 Flash 2,41T** · MiniMax M3 1,82T · Kimi K3 1,56T.
- No ranking por *spend*, o top 10 tem Claude Opus 4.6, Fable 5 e Sonnet 4.6 — mas **spend enviesa para modelo caro**; por token, DeepSeek domina.

### 2.5 O modo de falha que importa não é recusa

Estudo controlado (Lai, arXiv:2506.05514, 20 prompts × 4 níveis de explicitação):
- **Claude:** recusa 20/20, com quebra total de persona ("I'm Claude, an AI assistant…").
- **Gemini:** filtro por limiar — rico nos níveis 1–2, recusa categórica no 4.
- **DeepSeek:** inconsistente, e — o achado que nos atinge — **produz o moralismo e o conteúdo explícito na mesma resposta** ("…mas vou manter tasteful").

Ou seja: com DeepSeek o gate certo é **filtro de saída anti-preâmbulo** (o que o `output_guard` já faz), não jailbreak de entrada. Com Claude/Gemini, o gate não resolve — o modelo simplesmente não entra na persona.

---

## 3. Eixo 2 — inteligência no regime que realmente rodamos

### 3.1 A comparação que estava errada

O painel do OpenRouter mostra DeepSeek V4 Flash 0731 com **Intelligence Index 51,8**. Esse número é da configuração *Reasoning, Max*. Produção roda `thinking: disabled`.

| Modelo | Reasoning Max | **Non-reasoning / low** | Δ |
|---|---|---|---|
| DeepSeek V4 Flash 0423 | 42,1 · IFBench **79,2** | **29,3** · IFBench **47,2** | **−32 pts de IFBench** |
| DeepSeek V4 Pro | 45,3 · IFBench 76,5 | 31,9 · IFBench 45,8 | −30,7 |
| Gemini 3.5 Flash | 52,0 · IFBench 76,3 | 35,8 (minimal) · IFBench 47,3 | −29,0 |
| Grok 4.3 | — · IFBench 83,3 | 25,0 · IFBench 47,6 | −35,7 |
| Claude Haiku 4.5 | 29,9 · IFBench 54,3 | 24,1 · IFBench 42,0 | −12,3 |
| Claude Sonnet 5 | 55,3 | **42,6** (non-reasoning, high) | — |
| GPT-5.6 Luna | 52,3 | **26,8** non-reasoning · **33,9** low · **38,9** medium | — |

Não há medição publicada de non-reasoning para o **0731** especificamente; o 0423 é o proxy mais próximo.

**Consequência direta:** no regime de latência do WhatsApp, o nosso setup atual está na faixa de ~29–30 de AA-II, e **GPT-5.6 Luna em `low` (33,9) ou `medium` (38,9) supera isso mantendo TTFT de 1,77 s / 2,38 s.** Isso não estava visível em nenhuma comparação anterior.

**Isto não refuta o A/B de thinking que já rodamos** — aquele testou `high` e mediu conversão real (74,1% vs 73,3%, p95 de 96 s), que vale mais que IFBench. O que a evidência nova mostra é que **o meio-termo (`low`/`medium`) nunca foi testado**, e é exatamente onde o custo de latência desaba: Luna `low` entrega e2e de 5,1 s contra os 96 s de p95 que medimos com thinking alto.

### 3.2 Português brasileiro: o que existe e o que não existe

**Nenhum dos quatro modelos-alvo tem score público em benchmark de português.** Nem Global-MMLU (pt), nem Multi-IF PT, nem Prosa, nem CAPITU, nem BRACEval. O que existe é proxy de família (geração anterior):

| Benchmark PT (nativo) | Líder | Onde ficam as famílias |
|---|---|---|
| **Multi-IF PT** (instruction following, 3 turnos) | Gemini-3-Pro **88,0** | GPT-5.2 87,2 · Sabiá-4 82,0 · **DeepSeek-v3.2 81,5 (último)** |
| **BRACEval** (150 perguntas multi-turn, contexto BR) | Gemini-3-Pro **70,8** | Qwen3 65,6 · DeepSeek-v3.2 60,8 · GPT-5.2 60,2 |
| **Prosa** (1.000 chats reais de brasileiros, 51% multi-turn) | GPT-5.2 **88,6** | GPT-5 Mini 84,8 · Gemini 3 Pro 83,8 · **Gemini 3 Flash 78,8** · nenhum Claude ou DeepSeek avaliado |
| **CAPITU** (IF nativo pt-BR, 59 restrições) | GPT-5.2 **98,5** | Gemini-3-Pro 92,5 · Sabiazinho-4 87,0 · **Claude-Sonnet-4.5 86,0** · Haiku 4.5 73,5 |

Padrão: **família Google lidera conversa multi-turn em PT-BR; família OpenAI lidera seguir instrução redigida em português; família DeepSeek fica em último onde é medida.** Nenhum Claude aparece em Prosa ou BRACEval.

**Ponto cego relevante:** o benchmark mais próximo do nosso caso — *Sotaques Digitais* (90 cenários de gíria, ironia e regionalismo, texto "que circula em redes sociais e WhatsApp") — **não tem tabela pública**. A metodologia está publicada. Temos corpus de vendedor humano real, que é material melhor que o WildChat que eles usaram.

**Candidato brasileiro que ninguém listou:** Sabiazinho-4 marca **87,0 no CAPITU por US$ 0,13** — 8,6× mais barato que Claude Haiku 4.5, que fez 73,5. Fraco em conversa aberta (BRACEval 53,8). Vale como braço de curiosidade, não de produção.

### 3.3 Degradação multi-turn — e o nosso dado

A literatura é unânime: **queda média de 39% single-turn → multi-turn** em todos os modelos testados (Microsoft/Salesforce, ICLR 2026), por *não-confiabilidade*, não por perda de aptidão. O mecanismo: o modelo responde verboso cedo demais, chuta detalhe subespecificado e depois **se ancora no próprio erro anterior** — que é literalmente o "belief vence prompt" e o "merge `||` é latch" que já temos mapeados.

Persona drift medido (ContextEcho, 23 modelos): DeepSeek V3 **+0,65** · Sonnet 4.5 +0,63 · Haiku 4.5 +0,83 · Opus 4.1 −0,05 (único negativo). **Compactar contexto não reseta o drift.** A mitigação mais barata da literatura — uma âncora de ~80 tokens em turno de *usuário* — é exatamente o que o `reminder.md.j2` faz.

Relato de campo específico do V4 Flash: qualidade estável até ~turno 60, **"detalhes do personagem desvanecem a partir do turno 60+"** em sessões lore-heavy.

**Confrontando com o nosso banco (56 conversas de prod):**

| métrica | mensagens por conversa |
|---|---|
| média | 21,3 |
| **p50** | **11,5** |
| **p90** | **55** |
| p99 | 108,5 |
| máximo | 147 |

A conversa mediana é curta — onde o DeepSeek não sofre. Mas **10% delas passam de 55 mensagens**, entrando na faixa de degradação relatada. **O eval precisa estratificar por comprimento**, senão a cauda (onde moram os fechamentos difíceis e a recorrência) fica invisível na média.

---

## 4. Eixo 3 — custo, com o nosso perfil real de tokens

Medido no Langfuse (11/08/2026), turno completo = 1 chamada de chat + 1 de extração:

| Chamada | input | cache read | fresh | output | latência |
|---|---|---|---|---|---|
| nó `llm` | 24.291 | 22.912 (94,3%) | 1.379 | 21–35 | 1,72–1,90 s |
| nó `extrair` | 4.973 | 4.736 (95,2%) | 237 | 66–150 | 1,50–1,85 s |
| **turno** | **29.264** | **27.648 (94,5%)** | **1.616** | **~140** | **~3,4 s** |

Custo real hoje: **US$ 0,000274/turno → R$ 1,48 por 1.000 turnos.**

### Custo por 1.000 turnos com esse perfil (câmbio 5,40)

| Modelo | com cache (94,5%) | sem cache | R$/1k turnos | × DeepSeek |
|---|---|---|---|---|
| Qwen3.7 Flash | $0,23 | $0,90 | R$ 1,26 | 0,4× |
| MiMo-V2.5 | $0,34 | $4,14 | R$ 1,85 | 0,6× |
| **GPT-5.6 Luna** | **$0,52** | $3,01 | **R$ 2,82** | **0,9×** |
| **DeepSeek V4 Flash 0731** (promo −43%) | **$0,59** | $2,36 | **R$ 3,20** | **1,0×** |
| DeepSeek V4 Flash (tabela cheia) | $1,04 | $4,14 | R$ 5,61 | 1,8× |
| Gemini 3.1 Flash-Lite | $1,31 | $7,53 | R$ 7,05 | 2,2× |
| MiniMax M3 | $2,31 | $8,95 | R$ 12,48 | 3,9× |
| DeepSeek V4 Pro | $2,67 | $18,66 | R$ 14,42 | 4,5× |
| GLM 5.2 | $3,51 | $14,51 | R$ 18,97 | 5,9× |
| Claude Haiku 4.5 | $5,08 | $29,96 | R$ 27,44 | 8,6× |
| **Gemini 3.6 Flash** | **$7,62** | $44,95 | **R$ 41,15** | **12,9×** |
| **Claude Sonnet 5** | **$10,16** | $59,93 | **R$ 54,87** | **17,1×** |
| Kimi K3 | $15,24 | $89,89 | R$ 82,31 | 25,7× |

**Por que Luna sai mais barato que o DeepSeek:** o cache read dele é **US$ 0,01/M** contra US$ 0,016/M do 0731 em promoção (e 0,028 na tabela cheia). Como 94,5% do nosso turno é cache-hit, **o preço de cache domina o preço de lista**. Esse resultado só aparece com o perfil real; com o cenário genérico "25k in + 300 out sem cache", Luna custaria 2,6× mais.

### Três avisos de custo

1. **A DeepSeek avisou em 06/08/2026** (cinco dias atrás), na própria doc: *"We plan to raise the overall pricing for DeepSeek API services in the near future, with a significant increase expected."* Sem data nem magnitude. Há também sobretaxa de pico 2× anunciada em 30/06/2026, **ainda inativa**. A economia do nosso stack está apoiada num preço que o fornecedor avisou que vai subir.
2. **Claude Sonnet 5 tem imposto de tokenizer:** a doc da Anthropic registra que os modelos 4.7+ produzem **~30% mais tokens para o mesmo texto**. Os 17,1× viram ~22×, e os `max_tokens` calibrados quebram.
3. **Preço do Sonnet 5 em disputa entre fontes oficiais:** a página de notícias diz US$2/10 permanente desde 10/08/2026; a doc de pricing ainda lista US$3/15 a partir de 01/09/2026. Confirmar antes de orçar.

---

## 5. Eixo 4 — latência e confiabilidade

### Medido pelo OpenRouter (p50, melhor provedor)

| Modelo | Latência | Throughput | Uptime |
|---|---|---|---|
| **DeepSeek V4 Flash 0731** | **0,50 s** | **151 tok/s** | 96–100% (27 provedores) |
| Gemini 3.6 Flash | 1,50 s | 111 tok/s | 98,98% provider / 99,34% OR |
| Claude Sonnet 5 | 1,77 s | 100 tok/s | 99,83% |
| GPT-5.6 Luna | 0,95 s (Bedrock US) | 101 tok/s | 99,8% |
| MiMo-V2.5 / Hy3 | 3,05–3,07 s | 38–39 tok/s | — |
| MiniMax M3 | 3,84 s | 64 tok/s | — |
| GLM 5.2 | 8,64 s | 18 tok/s | — |

### A variável dominante é o effort, não o modelo

| Config | TTFT | e2e 500 tokens |
|---|---|---|
| GPT-5.6 Luna **max** | 136,6 s | 139,1 s |
| GPT-5.6 Luna **medium** | 2,38 s | 5,5 s |
| GPT-5.6 Luna **low** | 1,77 s | 5,1 s |
| Gemini 3.6 Flash **high** | 19,7 s | 21,9 s |
| Gemini 3.5 Flash **minimal** | 0,92 s | 4,0 s |
| DeepSeek V4 Flash **max** | 1,44 s | 20,5 s |

⚠️ **Gemini 3.x não permite desligar thinking** — `minimal` é o piso, e o default do 3.6 Flash é `medium`. Latência baixa garantida só no *Priority mode*, a 1,8× o preço.

### Latência de rede a partir daqui (São Paulo, 5 amostras, GET simples)

| Endpoint | TCP | TLS | TTFB |
|---|---|---|---|
| api.mistral.ai | 25 ms | 57 ms | 281 ms |
| api.deepseek.com | 50 ms | 82 ms | 550 ms |
| api.openai.com | 56 ms | 125 ms | 221 ms |
| api.anthropic.com | 61 ms | 145 ms | 221 ms |
| generativelanguage.googleapis.com | 74 ms | 248 ms | 437 ms |
| **openrouter.ai** | **161 ms** | **328 ms** | **560 ms** |

Piso de rede, não de inferência. Nenhum provedor tem penalidade proibitiva daqui — mas **o OpenRouter adiciona ~100 ms de RTT e ~180 ms de handshake** sobre ir direto. Nenhum dos quatro tem região South America para inferência; não existe medição pública de latência de LLM a partir do Brasil. **Nosso rig é a única fonte confiável disso.**

### Incidentes e limites

- **DeepSeek:** maior interrupção da história em **30/03/2026 (7h13min)**; nova queda em 31/03; degradação em 04/08/2026. Uptime 99,79–99,88%. **Sem RPM/TPM publicado** — só limite de concorrência (2.500 Flash / 500 Pro). **Sem batch API.**
- **OpenRouter:** sem SLA, sem crédito por downtime. ⚠️ No incidente de fev/2026, **80–90% das requisições falharam por 38 min retornando `401`, não `503`** — o modo de falha se disfarça de chave inválida e passa reto por retry que só trata 5xx.
- **Anthropic no tier de entrada:** 50 RPM contra 500 da OpenAI.

---

## 6. Eixo 5 — os outros papéis (extração, judge, vision, STT)

O chat é um dos cinco papéis. Nos outros, a conclusão é diferente — e mais dura.

### Extração estruturada

**DeepSeek não tem structured output estrito.** `response_format` aceita só `text` e `json_object`; o `strict:true` cobre **apenas argumentos de tool** e **só no endpoint `/beta`**. A doc oficial ainda carrega o aviso: *"The API may occasionally return empty content."* OpenAI (CFG, profundidade ≤5), Anthropic (gramática compilada, cacheada 24 h) e Google (`responseJsonSchema` com `anyOf` e `$ref` recursivo) dão **garantia por gramática**.

**Mas o dado medido contradiz o esperado.** Taxa de erro de structured output medida pelo OpenRouter em tráfego real:

| Modelo | Structured Output Error Rate | Tool Call Error Rate |
|---|---|---|
| **DeepSeek V4 Flash 0731** | **0,22 – 1,18%** | 0,68 – 0,88% |
| **Claude Sonnet 5** | **5,65% (Anthropic) – 13,96% (AWS)** | 0,07 – 1,90% |

Ou seja: o modelo com garantia formal mais fraca está errando **menos** na prática. Vale investigar antes de migrar a extração por argumento teórico.

⚠️ **Armadilha do DeepSeek que nos atinge:** com thinking ligado, `temperature`, `top_p`, `presence_penalty` e `frequency_penalty` são **silenciosamente ignorados**. Se a extração assume determinismo por `temperature=0`, a premissa é falsa nesse regime (hoje não é o caso — extração roda sem temperatura e com thinking off).

### Judge

Dois motivos independentes para **trocar o judge de família**:
1. **Self-preference de 10–25%** — hoje é DeepSeek julgando saída de DeepSeek.
2. **Gemini 3.1 Pro é o melhor juiz medido (κ = 0,511)**, com viés de posição de **0,002** — contra 0,192 dos modelos pequenos (variação de ~100×).

**Sobre o nosso κ ≈ 0,07 de desfecho:** a literatura (21 juízes, 541 mil julgamentos) mostra que **0,38–0,51 é o teto realista de juízes frontier**. Um κ de 0,07 aponta para **rubrica mal-especificada, não modelo errado**. Protocolo recomendado antes de trocar qualquer coisa: κ como métrica primária, AB+BA pareado para posição, ≥3 corridas a temperatura 0, validação em ≥2 conjuntos. E **não comprar ensemble como solução**: por erros correlacionados, **9 juízes valem ~2 votos independentes**.

Boa notícia: o viés de verbosidade praticamente sumiu nos modelos de 2026 (todos abaixo de 0,011). A literatura de 2023 sobre isso está desatualizada.

### Vision (OCR do Pix)

**DeepSeek está fora por construção** — a API oficial não aceita imagem. Entre generalistas, **Gemini lidera** (OCRBench v2: Gemini 3 Pro 63,4 · GPT-5 55,5 · **Claude Opus 4.6 48,4, o pior**). Modelos especializados (GLM-OCR 94,62, PaddleOCR-VL 94,50, ambos ~0,9B) batem todos os frontier no OmniDocBench.

Padrão sugerido: Gemini faz OCR **e** devolve o JSON com `responseJsonSchema` numa chamada só.

### STT

Manter OpenRouter, com duas ressalvas operacionais a verificar: **timeout de 60 s por request** e **limite de 25 MB** no multipart. Passar `pt` explicitamente em vez de deixar auto-detectar.

---

## 7. Eixo 6 — estabilidade de versão (o risco ao próprio eval)

Um eval calibrado contra um modelo que muda sob os pés vira ruído.

**Nosso risco concreto, confirmado no código:** `settings.py:85` usa `deepseek_model_chat = "deepseek-v4-flash"` — **id sem snapshot**. O próprio comentário registra que em **31/07/2026 o provider promoveu o V4-Flash-0731 atrás do mesmo id**, sem deploy nosso. A API oficial da DeepSeek **não oferece id datado**.

| Provedor | Garantia documentada | Perfil |
|---|---|---|
| **Anthropic** | **Todo model ID é snapshot fixado + 60 dias de aviso**, por escrito | A melhor garantia formal — mas ciclo agressivo: Sonnet 4 e Opus 4 aposentados em 15/06/2026, Opus 4.1 em 05/08/2026 |
| **OpenAI** | **6 meses** (GA) | Aliases sobrevivem, snapshots datados morrem; risco de **retune sem mudar o nome**. ⚠️ O alias `gpt-5.6` resolve para **Sol**, não Luna — usar o ID completo `gpt-5.6-luna` |
| **Google** | **Nenhuma** — a página de política dá 404 | Já redirecionou um ID de preview para outro modelo; sem data de shutdown para `gemini-3.6-flash` |
| **DeepSeek** | **Nenhuma** — troca o modelo sob o alias, sem ID datado | *"Evals contra `deepseek-v4-flash` não são reprodutíveis por contrato."* Mitigante: **pesos MIT** — no pior caso, self-hostar o checkpoint e o eval nunca é invalidado |

**Detalhes de caching que afetam o desenho** (docs oficiais): a **OpenAI** tem o melhor encaixe para WhatsApp (TTL de 30 min + `prompt_cache_key` explícito). A **Anthropic** exige mínimo de 4.096 tokens no Haiku 4.5 e **invalida o cache se o `effort` mudar entre turnos** — fatal para quem varia esforço por estado da conversa. O **Google** cobra storage por hora e trata o hit como best-effort, sem TTL nem regra de prefixo documentada.

**Recomendação concreta para a corrida do eval:** rodar o braço de controle **pelo OpenRouter no id datado `deepseek/deepseek-v4-flash-0731`**, aceitando o custo de perder o cache automático e enfrentar roleta de quantização (fp4/fp8/bf16 entre 27 provedores) — e registrar o provider usado em cada corrida. Produção continua na API direta pelo cache. **São dois caminhos com propósitos diferentes; hoje são o mesmo, e isso é uma armadilha.**

---

## 8. O que a bateria de eval precisa medir

A pesquisa acadêmica de venda prevê onde os modelos vão empatar e onde vão separar. Vale registrar as previsões **antes** de rodar.

### 8.1 Quatro referências que desenham o eval melhor que qualquer benchmark de modelo

**SalesLLM** (arXiv 2604.07054, 14 LLMs, 1.805 cenários de 30.074 configurações): **DeepSeek-Chat foi o melhor vendedor** (7,03 ZH / 5,80 EN), acima da **baseline humana de vendedor novato (6,33)** — correlação humano×juiz de 0,98. Três achados:
- agentes *"alucinam concessões não autorizadas — oferecendo descontos fora do script ou promessas além da sua autoridade"* → é literalmente o **Piso de desconto** e a **Autoridade de preço**;
- modelos fracos *"agem como bots passivos de Q&A"*; DeepSeek foi o mais **proativo** (faz pergunta de fechamento e conduz);
- ⚠️ **habilidade de venda NÃO transfere entre idiomas** — Doubao cai de 6,89 (ZH) para 5,48 (EN); só o Gemini-3-pro se manteve estável. **Qualquer número de venda medido em inglês ou chinês é inválido para PT-BR.** É o argumento mais forte a favor de eval próprio.

**TERMS-Bench** (Stanford, arXiv 2605.13909, 13 LLMs frontier):
- **Taxa de fechamento satura em 93–99%, mas a eficiência de excedente varia 3,7×.** Se o eval mede só conversão, **ele vai empatar tudo**.
- **"Cue penalty": sinais calorosos induzem sobre-concessão — nos 13 modelos.** Cliente simpático arranca desconto.
- **Erros de crença sobre o interlocutor crescem ao longo das rodadas** — o nosso "belief afirma falsidade".

**PrefBench** (arXiv 2605.22855, 7.500 episódios): LLMs fecham >99% dos negócios, mas **o lucro do melhor LLM fica pouco acima do aleatório e muito abaixo de uma heurística simples de concessão**. Conformidade de protocolo ≠ racionalidade econômica.

**Measuring Bargaining Abilities** (arXiv 2402.15813): acoplar um **gerador de oferta determinístico** ao LLM levou o deal rate de 26,67% → 88,88%. **Tradução: o número sai do resolver, o LLM só redige.** Valida a arquitetura que já temos com o piso de desconto.

### 8.2 O contraponto que incomoda: quem vende bem cede fácil

LLM Persuasion Benchmark (lechmazur, 15 modelos, 6.296 conversas de 8 turnos, stance medida 3× antes e 3× depois) — **os mais suscetíveis a mudar de posição sob argumentação**:

| Posição | Modelo | Suscetibilidade |
|---|---|---|
| 1º (pior) | Xiaomi MiMo V2 Pro | 1,996 |
| 2º | **Gemini 3.1 Pro Preview** | **1,810** |
| 3º | **DeepSeek V3.2** | **1,741** |
| … | | |
| mais resistentes | Grok 4.20 · Kimi K2.5 Thinking · **Claude Opus 4.6 (0,407)** · Claude Sonnet 4.6 (0,613) | |

**Os dois modelos com melhor prior de venda são justamente os mais suscetíveis a ceder sob pressão.** O construto não é idêntico ("mudar crença sobre proposição contestada" ≠ "conceder desconto"), mas é o proxy público mais próximo do cliente que insiste no preço — e vale para famílias, não para os snapshots exatos. **Isto precisa ser medido diretamente (§8.4), não assumido em nenhuma direção.**

### 8.3 Métricas obrigatórias

| Métrica | Por quê |
|---|---|
| **Ticket condicional ao fechamento** | Conversão vai saturar; a diferença mora aqui |
| **Violação de piso de desconto** e concessão não-autorizada | Modo de falha nomeado na literatura, e regra nossa |
| **Concessão sob calor social** (cenário dedicado: cliente simpático pedindo desconto) | Falha universal nos 13 modelos do TERMS-Bench; hoje o corpus provavelmente não cobre |
| **Taxa de recusa / moralização** no corpus de segurança e fetiches | Métrica de primeira classe, não de rodapé — é o gargalo do §2 |
| **Vazamento de raciocínio / system prompt** | Guard já existe; esperar que dispare mais com Sonnet 5 é sinal, não bug |
| **Estilometria**: travessão, emoji e markdown por 1.000 palavras | Única dimensão de "soar IA" que sobrevive a instrução explícita — e varia 5× entre fornecedores |
| **p95 de TTFT e e2e**, não média | O efeito do effort é de ordem de grandeza |
| **Custo por conversa fechada**, nunca $/M token | Verbosidade destrói a economia do preço de lista |
| **Estratificação por comprimento de conversa** (≤12, 13–55, >55 msgs) | p90 = 55 no nosso banco; a cauda é onde o DeepSeek degrada |

### 8.4 Arquitetura sugerida: três camadas, e a conversão fica de fora

| Camada | O que roda | Judge? | Decide |
|---|---|---|---|
| **L1 — gates determinísticos** | fixtures + parser + consulta ao resolver de preço | **não** | eliminação (gate vermelho = fora) |
| **L2 — conduta** | replay N−1 (triagem) + conversas on-policy | sim, κ-validado | ranking de condução |
| **L3 — desfecho econômico** | comprador **scriptado** com preço de reserva oculto | **não** (o ambiente verifica) | **margem** — o critério de desempate |

**A matemática que fecha a questão:** com baseline de 9% de conversão (Chat Commerce Report 2026, >1 bilhão de mensagens, 51 milhões de conversas no Brasil — onde agentes de IA já convertem **em paridade com humano**), detectar +20% relativo a 95%/80% exige **~4.400 conversas por braço**. Para +5% relativo, passa de 100 mil.

**Portanto: conversão não é métrica de bateria offline. É métrica do A/B sticky em produção — que já temos.** A bateria mede *processo*: gates, conduta e margem. Todas as três são detectáveis com N na casa das centenas.

Dimensionamento sugerido (~640 conversas por modelo, ~3.200 para 5 braços):

| Camada | Fixtures | Repetições | Conversas/modelo |
|---|---|---|---|
| L1 gates (inclui as 26 de segurança que já temos) | 60 | 3 (pass^3) | 180 |
| L2a replay N−1 | 800 turnos reais | 1 | — (turnos) |
| L2b conduta on-policy, 2 famílias de simulador | 80 | 1 | 160 |
| **L2c escada de pressão** | 40 × 5 degraus | 3 | 120 |
| L3 desfecho econômico | 60 | 3 | 180 |

**A escada de pressão (L2c) é o eval que não existe publicamente e que decide o nosso caso.** Cinco degraus escalonados de pedido de desconto: (1) "tá caro" · (2) âncora competitiva "fulano cobra menos" · (3) restrição orçamentária · (4) **apelo afetivo** (a tática que a NegotiationArena mostrou ser a mais eficaz contra LLM) · (5) ultimato. Métrica: **AUC da curva de capitulação** e degrau mediano de quebra, em pass^3.
⚠️ **Medir também o falso-rígido** — cliente qualificado que merecia o desconto autorizado e não recebeu. Sem esse contrapeso, selecionamos o modelo mais teimoso, não o melhor vendedor. Sicofância baixa por abstenção é armadilha conhecida.

**Dois cuidados com o simulador de cliente**, ambos documentados (Lost in Simulation, arXiv 2601.17087): usuários simulados têm **viés de benevolência** — são educados demais e cooperam demais — e miscalibram (subestimam em tarefa difícil, superestimam em tarefa moderada). Mitigações: (a) rodar **duas famílias de simulador** e checar se o ranking dos braços se mantém — se virar ao trocar de simulador, **o eval não decidiu nada, e isso deve ser publicado assim**; (b) usar comprador **scriptado determinístico** em L1 e L3, deixando o LLM só onde precisa de variedade linguística; (c) calibrar o simulador contra 30–50 conversas reais (nº de turnos, comprimento, taxa de pergunta) — senão medimos o simulador; (d) medir a taxa de *role inversion* (o "cliente" virando vendedor) como teste de sanidade: com simulador genérico foi de 17,4%.

**Sobre o judge:** rubrica **escopada por turno, não por conversa** — 57,2% dos erros de judge em compliance de diálogo são confusão de escopo. E vale considerar um **judge pequeno fine-tunado**: no CompliBench, um Qwen3-8B ajustado (51,47%) bateu o GPT-5 (47,26%) na detecção de violação. Temos corpus de segurança e corpus do vendedor — matéria-prima suficiente. Para intenção de compra, **classificador treinado, não judge**: no SalesLLM um BERT ajustado fez 93,51% contra 69,6% do GPT-4o.

### 8.5 Previsões falsificáveis (registrar agora, conferir depois)

1. Nenhum modelo vence em conversão bruta — todos empatam.
2. Cliente simpático arranca mais desconto de **todos** os braços.
3. DeepSeek **inventa** concessões e fatos; não recusa (SimpleQA 34,1%).
4. Claude Sonnet 5 **vaza system prompt e recusa** — é o único com relato público dos dois.
5. Gemini 3.6 Flash ganha em consistência, perde em latência e custo.
6. GPT-5.6 Luna custa mais que a tabela sugere por verbosidade (~2× tokens) — mas o nosso cache compensa.
7. O nosso "sicofância" não vai bater com nenhum leaderboard: são quatro construtos diferentes e vamos medir um quinto (concessão comercial sob calor social). **Nomear o construto no ADR.**
8. O DeepSeek vai ganhar em proatividade (conduzir, perguntar, fechar) e **perder na escada de pressão** — é o 3º mais suscetível a persuasão entre 15 modelos.
9. A vantagem do incumbente vem da conversa curta. Se o eval não estratificar por comprimento, a fraqueza dele (turno 60+) não aparece — e ela existe em 10% das nossas conversas.

### 8.6 Duas armadilhas de integração a testar cedo

- **GPT-5.6 Luna:** `Function tools with reasoning_effort are not supported in /v1/chat/completions` — exige `/v1/responses` ou `reasoning_effort: none`. Usamos tools no LangGraph: isso nos atinge direto.
- **Gemini 3.x:** *thought signatures* são **obrigatórias no retorno** durante function calling; sem elas, 4xx — inclusive no nível `minimal`, e em cadeia multi-step **todas** precisam voltar.

---

## 9. Riscos abertos e decisões que não são técnicas

| # | Risco | Ação |
|---|---|---|
| 🔴 1 | **DeepSeek anunciou aumento significativo de preço (06/08/2026)** + sobretaxa de pico 2× engatilhada | Ter o caminho de troca pronto **antes** de virar emergência. Braços #3 e #5 do eval servem a isso |
| 🔴 2 | **ToU §3.4(5) da DeepSeek cita "sexual chatbots" nominalmente**, com proibição de re-registro | Decisão do Fernando: aceitar o risco, provisionar plano B, ou buscar via com política compatível |
| 🔴 3 | **Exposição do art. 230 CP** ativa cláusulas de "illegal purpose" independentemente de conteúdo | Fora do escopo técnico. Ouvir criminalista |
| 🔴 3b | **LGPD:** a DeepSeek declara armazenamento na China, treino com dados de API **sem opt-out documentado** e retenção sem prazo — e passamos PII de cliente e conversa íntima por lá | Decisão do Fernando. É risco maior e mais imediato que o §3.4(5) |
| 🟠 4 | **Falha do OpenRouter se disfarça de `401`** | Retry/circuit-breaker precisa tratar rajada de 401 como falha de infra. Alertar por **taxa**, não por código |
| 🟠 5 | **Id sem snapshot na API DeepSeek** | Pinar `0731` via OpenRouter na corrida do eval; registrar provider por corrida |
| 🟡 6 | **Divergência de leitura da policy da Mistral** entre dois agentes | Ler a policy inteira antes de promover a plano B |
| 🟡 7 | **`thinking` ligado por padrão no DeepSeek** anula `temperature` silenciosamente | Já tratado por `extra_body`; vale um teste que asserte o payload |

---

## 10. Fontes

Coleta primária desta pesquisa: `openrouter.ai` (API `/models` e `/endpoints`, páginas de modelo, `/compare`, `/rankings`), Langfuse (traces de 11/08/2026), Postgres de produção, medição de rede local.

**Benchmarks e índices:** Artificial Analysis (Intelligence/Agentic Index, IFBench, AA-LCR, GPQA-D, τ³-Banking, TB2.1) · Scale MultiChallenge · Ai2 IFBench · OCRBench v2 · OmniDocBench V1.5 · BFCL v4 · UGI Leaderboard · Sycophancy leaderboard (Lech Mazur, 05/08/2026) · Design Arena.

**Papers — venda e negociação:** SalesLLM (arXiv 2604.07054) · TERMS-Bench (arXiv 2605.13909) · PrefBench (arXiv 2605.22855) · AgenticPay (arXiv 2602.06008) · Measuring Bargaining Abilities (arXiv 2402.15813) · NegotiationArena (arXiv 2402.05863) · The Illusion of Rationality (arXiv 2512.09254) · LLM Persuasion Benchmark (lechmazur) · Ψ-Bench (arXiv 2606.02754).

**Papers — conversa e degradação:** LLMs Get Lost In Multi-Turn Conversation (arXiv 2505.06120, ICLR 2026) · ContextEcho (arXiv 2605.24279) · Attractor States (arXiv 2606.30571) · Prosa (arXiv 2605.01630) · CAPITU (arXiv 2603.22576) · P3B3 (arXiv 2606.16753) · The Last Fingerprint (arXiv 2603.27006) · Round-Trip Translation (arXiv 2604.12911).

**Papers — avaliação:** Reliability without Validity (arXiv 2606.19544) · CompliBench (arXiv 2604.12312) · Nine Judges, Two Effective Votes (arXiv 2605.29800) · Pairwise or Pointwise? (arXiv 2504.14716) · Lost in Simulation (arXiv 2601.17087) · DIVERT (arXiv 2604.21480) · Reason Less Verify More (arXiv 2607.07405) · τ²-bench (arXiv 2506.07982) · ELEPHANT (arXiv 2505.13995) · SycEval · Sample-size for A/B (arXiv 2305.16459).

**Papers — conteúdo:** Can LLMs Talk "Sex"? (arXiv 2506.05514) · Verified Tool Calls Under Non-Atomic Failures (arXiv 2608.02645).

**Mercado BR:** Chat Commerce Report 2026 (OmniChat) — >1 bilhão de mensagens, 51 milhões de conversas, 22 milhões de consumidores, 2025: 96% das interações via WhatsApp; **agentes de IA convertem 9%, em paridade com humano**; 76% das conversas conduzidas por IA apresentaram intenção de compra.

**Políticas e docs oficiais:** Anthropic AUP + Constituição do Claude + model deprecations · OpenAI Usage Policies + Model Spec 2025-12-18 + deprecations · Google Generative AI PUP + safety settings + thought signatures · DeepSeek ToU (27/03/2026) + Open Platform ToS + thinking mode + pricing + changelog · Mistral Usage Policy (11/06/2026) · xAI AUP · OpenRouter ToS.

Detalhamento por fonte nos relatórios dos agentes e em `docs/research/modelos-llm-fontes-primarias.md`.
