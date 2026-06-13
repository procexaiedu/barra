# 10 — Corpus real do Vendedor: taxonomia de jogadas validada

> **Projeto:** Central Inteligente de Atendimento — Elite Baby
> **Escopo:** base de evidência, minerada de conversas REAIS da operação, para reconstruir o system prompt do agente conversacional (persona/voz/FAQ geral + playbook de venda). **Não é o prompt** — é o insumo de decisão que o antecede.
> **Data:** 2026-06-12.
> **Audiência:** quem for editar `agente/prompts/*` (`03-prompts.md`) e o Fernando (decisões de produto em §6).
> **Precedência:** onde o corpus divergir de `CONTEXT.md`/ADRs, **a conduta aprovada vence** (corpus real ≠ conduta aprovada). Divergências mapeadas em §6 e §9.

---

## 1. Objetivo e o que mudou

Reconstruir o system prompt a partir do **comportamento real do Vendedor humano** (o respondente que se passa pela modelo, papel que a IA assume — ver `CONTEXT.md › Vendedor`), separando o que generaliza (persona/voz/jogadas) do que é dado da modelo, e o que **não** se replica (anti-padrões vs `_Avoid_`).

Tentativa anterior falhou por generalizar de **4 conversas avulsas** (overfit). Agora o corpus é real e amplo: **71.335 mensagens** de 4 linhas (eb01–eb04 na Evolution), **~1.520 threads** cliente-modelo. O risco deixou de ser "amostra pequena" e virou "amostrar/anotar com método sem confundir o-que-o-Vendedor-faz com o-que-converte".

## 2. Extração (Fase 0) — tabelas `corpus.*` no Postgres do barra

Extração read-only via Evolution REST (`POST /chat/findMessages/{inst}`, `sort:{id:asc}`, paginado). PII liberada pelo dev → sem de-identificação. Tabelas (mesmo Postgres do MCP):

| Tabela | Conteúdo |
|---|---|
| `corpus.mensagens_raw` | 71.335 mensagens cruas (jsonb + colunas de conveniência) |
| `corpus.turnos` | 29.054 turnos — bolhas consecutivas do mesmo lado colapsadas (gaps-and-islands); exclui `protocolMessage` e grupos `@g.us` |
| `corpus.threads` | 1.520 threads com sinais + proxy de desfecho |

**Gotchas duráveis:**
- `key.id` do WhatsApp **não é único** — PK correta é o `id` de topo do Evolution. Usar `key.id` derrubou ~14% via `ON CONFLICT`.
- Chave do thread = **`@lid`** (privacy id), não telefone. Estável por contato; **não** casa com o telefone E.164 do painel sem mapa LID→telefone.
- O nº "Chats" do dashboard Evolution infla (status/vazios); o real é ~1.520 threads.
- **eb01 é raso** (6 dias, 128 threads); **eb04 é o mais rico** (volta a 31/03). Hold-out cross-modelo deve segurar um modelo rico, nunca eb01.

## 3. Método (resumo) e pesquisa que o fundamenta

Pipeline: extrair → reconstruir turnos → marcar desfecho por **proxy objetivo** → **induzir** taxonomia (não inventar) → classificar em escala → validar convergência → cruzar com `_Avoid_`. Ancoragem da "verdade" sem anotação humana: proxies comportamentais + multi-juiz LLM + spot-check do Claude. Sem rodar o agente ao vivo (§0).

Fontes (jun/2026):
- Clonar agente de venda de **gravações reais top-performing** > instruções genéricas; prompt segmentado: [arXiv 2509.04871](https://arxiv.org/pdf/2509.04871).
- Indução de taxonomia em escala (summarize→refine→classify, validar por cobertura+humano+LLM-juiz): **TnT-LLM** [arXiv 2403.12173](https://arxiv.org/html/2403.12173v1).
- Few-shot p/ tom/estilo, poucos exemplos representativos, cuidado com over-prompting/ordem: [IBM](https://www.ibm.com/think/topics/few-shot-prompting), [best practices 2025](https://codesignal.com/blog/prompt-engineering-best-practices-2025/).
- LLM-as-judge offline binário, alinhado a humano, hold-out: [Evidently](https://www.evidentlyai.com/llm-guide/llm-as-a-judge), [LangChain](https://docs.langchain.com/langsmith/llm-as-judge).
- Pitfalls: overfit de prompt [Prompt Overfitting](https://www.emergentmind.com/topics/prompt-overfitting); viés de anotação por LLM [arXiv 2309.17147](https://arxiv.org/pdf/2309.17147).

## 4. Taxonomia de jogadas de venda (induzida)

V = turno da modelo/Vendedor, C = cliente. Jogadas do Vendedor:

| # | Jogada | Exemplo real |
|---|---|---|
| 1 | Saudação calorosa | "Oii ⏎ Boa noite 😊" |
| 2 | Sondagem de proximidade/timing | "Está em campinas amor?", "Seria hoje?" — qualifica local+tempo antes de cotar |
| 3 | Pitch de serviço não-solicitado | dispara "beijo na boca, oral sem, namoradinha" antes de perguntarem |
| 4 | Ponto de encontro padrão | "Av aquidabã 130 / Hotel Sirius / chácara da barra" |
| 5 | Cotação | `valor + duração + local`: "400 1h no meu local" |
| 6 | Mídia exclusiva como prova | manda álbum/foto/vídeo após interesse |
| 7 | Ancoragem no AGORA / escassez | "se vier agora 350", "último dia na cidade" |
| 8 | Desconto reativo condicional | "600… faço 500 se for hoje" |
| 9 | Upsell | "com anal 1000", "completo 1mil", "2h 700 + uber", dupla com a "amiga" |
| 10 | Contorno de objeção de preço | "aceito cartão / parcelo", "vale a pena", "me cuido" |
| 11 | Fechamento de horário | "Confirmado às 13hrs?" |
| 12 | Coleta de nome | "Qual seu nome amor?" |
| 13 | Passa ap/quarto **só na chegada** | "Chegar eu passo" → "2006 andar 20" |
| 14 | Fluxo externo uber+pix | "me manda o endereço pra ver o uber", "me manda o comprovante" |
| 15 | Recuperação calorosa pós-sumiço | "Te espero rs", "quando conseguir me avisa" |

## 5. Frequência por modelo e validade convergente (Fase 3, validada)

Workflow Claude Code: 49 agentes Sonnet classificaram **247 threads** (amostra estratificada por modelo × desfecho) nas 15 jogadas. Qualificados (chegaram à cotação) por modelo: eb01=32, eb02=53, eb03=43, eb04=60.

**% dos qualificados que exibem cada jogada:**

| # | Jogada | eb01 | eb02 | eb03 | eb04 | Tier |
|---|---|---|---|---|---|---|
| 1 | saudação | 97 | 98 | 93 | 100 | **universal** |
| 5 | cotação | 100 | 100 | 98 | 100 | **universal** |
| 3 | pitch não-solicitado | 88 | 77 | 88 | 82 | **universal** |
| 4 | ponto de encontro | 66 | 62 | 72 | 72 | forte |
| 2 | sondagem prox/timing | 50 | 57 | 51 | 73 | forte |
| 7 | ancoragem AGORA | 44 | 66 | 33 | 48 | forte |
| 6 | mídia exclusiva | 25 | 19 | 26 | 30 | situacional |
| 11 | fechamento horário | 16 | 36 | 16 | 48 | situacional |
| 10 | contorno objeção | 22 | 26 | 12 | 22 | situacional |
| 15 | recuperação pós-sumiço | 16 | 15 | 7 | 33 | situacional |
| 9 | upsell | 6 | 28 | 7 | 17 | situacional |
| 13 | passa ap/quarto | 6 | 15 | 12 | 28 | situacional |
| 8 | desconto reativo | 12 | 9 | 7 | 12 | raro |
| 14 | fluxo externo uber+pix | 12 | 11 | 2 | 7 | raro |
| 12 | coleta de nome | 3 | 6 | 5 | 7 | raro |

**RESULTADO CENTRAL — validade convergente confirmada:** **nenhuma jogada é single-model**; toda jogada que aparece, aparece em ≥2 modelos. A persona/playbook **generaliza** — comprova empiricamente a premissa "persona compartilhada" (`CONTEXT.md`, `03 §1`) e fecha a porta ao overfit anterior. O **fluxo externo ser raro** (≤12%) confirma que **o atendimento interno domina** a operação.

**Confiabilidade:** passe adversarial sobre 24 threads — **81%** dos moves alegados confirmados (~19% over-tag). As conclusões de convergência são robustas: para quebrar o "≥2 modelos" o erro teria que ser sistematicamente por-modelo, e não é.

## 6. Anti-padrões quantificados → decisões de produto (Fernando)

Contagem na amostra (247 threads):

| Anti-padrão | eb01 | eb02 | eb03 | eb04 | total | Decisão |
|---|---|---|---|---|---|---|
| `oral_gancho` (abre anunciando prática de risco) | 36 | 42 | 42 | 39 | **159** | **universal — a IA replica?** decisão mais pesada |
| `viajante` ("cheguei na cidade", "último dia") | 4 | 37 | 13 | 26 | 80 | **varia por modelo** — não botar na persona geral |
| `endereco_cedo` (vaza endereço completo cedo) | 10 | 21 | 17 | 24 | 72 | **conflita com CONTEXT** — endereço só no fechamento, nunca porta/apto |
| `agora_excessivo` (pressão desesperada) | 3 | 8 | 3 | 6 | 20 | calibrar tom |
| `desconto_cascata` (baixa preço livre, sem piso) | 1 | 5 | 0 | 2 | 8 | **fura Piso de desconto** — IA usa piso + oferta única |
| `bait_switch` (empurra a "amiga" sem avisar) | 1 | 5 | 0 | 1 | 7 | não replicar (cliente rejeita) |

## 7. Persona / voz — GERAL (vai no prompt compartilhado)

Consistente entre os 4 modelos (= persona, não dado da modelo):
- **Vocativo carinhoso constante** ("amor / vida / baby / anjo / gata").
- **Auto-descrição fixa**: "estilo namoradinha", "carinhosa e atenciosa", "bem tranquila".
- **Saudação por horário + emoji** ("Bom dia 🌻", "Boa noite 😊", "rs").
- **Bolhas curtas e múltiplas** (~2–3 por turno — já tratado pela humanização, `05`).
- **Push pro AGORA** ("Seria hoje?", "Vamos se ver agora?") — espinha da venda.

FAQ recorrente (geral): "tem local / atende a domicílio?", "onde fica?", "qual o valor?", "você faz X?", "atende casal?", "onde estaciono?", "que horas começa?", "forma de pagamento?".

## 8. Candidato → veículo (regra / few-shot / FAQ)

| Achado | Veículo | Nota |
|---|---|---|
| Vocativo/tom/auto-descrição | **regra + few-shot** | tom não se descreve só em prosa (`03 §2.2`) |
| Cadência de bolhas + push pro AGORA | **few-shot** | sabor; intensidade depende de §6 |
| Sequência sondagem→pitch→cotação→fechamento | **regra** | o funil |
| Cotação `valor+duração+local` | **regra** (formato) + **dado da modelo** (valores) | |
| Contorno de objeção (cartão/parcelo + desconto) | **regra** (piso + oferta única, **não** o cascata real) + **few-shot** (jeito) | |
| Upsell (duração maior, completo, dupla) | **regra** + **dado** | |
| Mídia exclusiva | **regra** (ordem foto→vídeo, `CONTEXT › Mídia exclusiva`) | |
| Fechamento / coleta de nome / passa-quarto-na-chegada | **regra** | alinhar à máquina de estados (`02`) |
| Recuperação pós-sumiço | **regra** | é o **Reengajamento** do CONTEXT — alinhar |
| FAQ recorrentes | **FAQ** (`faq.md`) | só o geral |
| "Você faz X?" (fetiches) | **dado da modelo** | já no CONTEXT |
| Anti-padrões (§6) | **regras de proibição** | nunca abaixo do piso, nunca bait-switch, endereço só no fechamento |

## 9. Tensões com o domínio (pro Fernando/ADRs)

1. **A operação é quase toda "agora"/same-day**, não agendamento futuro — tensiona com a máquina de estados que pressupõe agendamento (`02`, `03`).
2. **Lead inbound padrão** vem por anúncio ("Peguei seu contato no site Gsexy Campinas / Photo") — ponto de entrada real, útil pro reengajamento e p/ a IA reconhecer lead novo.
3. O Vendedor opera como **respondente único empurrando pro fechamento imediato** — o funil real é muito mais comprimido que o desenho.

## 10. Limitações e validade

- **Proxy de desfecho determinístico bate teto ~50% de precisão** em "convertido" (cliente a-caminho-que-voltou; "cheguei na cidade" da viajante). Conversão real tem assinatura limpa (recebe ap/quarto + "Cheguei"; ou uber+comprovante+chegada). Existe categoria de **ruído**: threads `@lid` que **não** são de cliente — coordenação operacional interna (model+assistente: lista de mercado, "manda o caixa", pix entre contas).
- **Eficácia de jogada é confundida** (atratividade da modelo, preço, demanda). A frequência valida *generalização*, não *causalidade de conversão*. "O que converte" é hipótese para A/B, não lei.
- **Sem anotação humana**; âncora = proxies + multi-juiz + spot-check do Claude. Adversarial 81%.
- Amostra de validação = 247 threads estratificados (não as 1.520). Suficiente para frequência/convergência; não para treinar classificador.

## 11. Por que os clientes não convertem (motivo de perda)

Workflow Claude Code: 40 agentes Sonnet classificaram **157 threads perdidos** (perdido_sumiu + perdido_objeção + qualificado_sem_prova, estratificado por modelo) no **Motivo de perda** do CONTEXT + se foi declarado ou sumiço mudo.

| Motivo | % | Declarado |
|---|---|---|
| **sumiu** (some sem dizer nada) | **53** | 100% mudo |
| indisponibilidade (timing: "hoje não dá", "te chamo") | 20 | declarado |
| preço ("tá salgado", "pensei que seria 250") | 13 | declarado |
| risco (desconfiança / "tô achando fake") | 5 | declarado |
| fora de área (distância) | 4 | — |
| fora de escopo (pediu o que ela não faz) | 3 | — |
| curioso / outro | 2 | — |

**Dois fatos centrais:**
1. **56% somem MUDOS** e **74% das perdas são pós-cotação** (só 18% reagem *ao* preço na hora). O problema dominante não é discordância — é **silêncio após ver o número**.
2. **Preço é minoria** (~13–18%). A operação **não** perde principalmente no preço; prompt focado em "contornar objeção" mira o alvo errado.

Consistente entre os 4 modelos (sumiço 43–62%, indisponibilidade 13–27%, preço 8–17%) → o padrão de perda **generaliza**.

**Implicação pro prompt** — a alavanca não é objection-handling, é:
- **Reengajar o silêncio** (= o **Reengajamento** do CONTEXT — é a perda nº1, valida a feature).
- **Momentum na cotação**: hoje o Vendedor solta o número e pergunta "seria agora?" → 53% somem ali. Amarrar a cotação a um próximo passo concreto.
- Timing (20%) → "revela a volta e ancora" (CONTEXT, fora-de-disponibilidade).

**Caveat:** verificação adversarial = **64% de concordância** (vs 81% nas jogadas). As discordâncias se concentram em **sumiu ↔ indisponibilidade** ("te chamo" + some = timing-declarado ou sumiço?). O split fino entre os dois é ruidoso; o robusto é o **bloco "drift pós-cotação" (~73%)**. Preço/risco são firmes.

## 12. Micro-análise do turno da cotação

§11 mostrou que a perda nasce **pós-cotação** (53% somem mudos ao ver o número). Esta seção zoom-in pergunta: **a forma de entregar a cotação separa quem engaja de quem some?** Workflow Claude Code: 20 agentes Sonnet codificaram **120 threads** com cotação (estratificadas por modelo × desfecho), marcando 9 traços da entrega + a **reação imediata** do cliente como ground-truth (não o proxy). Contraste mais limpo que ganhou-vs-perdeu: mesmo estado, reação oposta.

Distribuição das reações (n=119 com cotação): `fechou_logistica` 17, `engajou` 28 (**GOOD=45**), `silenciou` 34, `desviou` 23 (**BAD=57**), `objecao_preco` 17.

**A reação à cotação É o desfecho** (cross-check contra o proxy independente): das 34 que silenciaram, **28 viraram `perdido_sumiu`**; as 17 que fecharam logística tiveram **zero perdas**. Mas — e é o achado — **nenhum traço da *entrega* move a agulha, exceto calor**:

| Traço | GOOD% (n=45) | BAD% (n=57) | lift (G−B) |
|---|---|---|---|
| **f_warmth** (tom "amor/carinhosa") | 71 | 61 | **+10** |
| f_time_anchor | 7 | 5 | +2 |
| f_bare (preço seco) | 27 | 33 | −6 |
| f_next_step (empurra próximo passo) | 11 | 18 | −7 |
| f_media_near (mídia colada) | 33 | 42 | −9 |
| f_question_back (devolve pergunta) | 9 | 18 | −9 |
| **f_urgency** ("seria agora?", "vamos confirmar?") | 13 | 25 | **−12** |

**RESULTADO:** calor é a única alavanca positiva robusta; todo **empurrão** (urgência, CTA/pergunta colada ao preço, mídia a frio) aparece **mais em quem some** — quase certamente *reverse causation* (o Vendedor pressiona quando já sente o cliente esfriando), mas a conclusão prática é a mesma: **cotar limpo e caloroso, sem urgência nem pergunta colada; deixar o cliente conduzir.** Isso recalibra a jogada 7 (§4, "ancoragem no AGORA") e o anti-padrão `agora_excessivo` (§6): no turno da cotação, o AGORA **prejudica**.

**Candidato → veículo:** [regra] cotar com calor, nunca preço seco isolado; [regra] **proibir** pressão de urgência/pergunta no mesmo turno do preço; [few-shot] cotações vencedoras reais: `222535425773680` ("500 1h +uber amor" → "Bora"), `259523986112524` ("Meu cachê $600 1h, no meu local 😊" → cliente propôs horário).

**Confiabilidade:** re-codificação cega de 16 threads — **88% de concordância nos traços, 75% na reação** (fronteira engajou↔desviou é borrada). **Ressalva forte:** n pequeno (45/57); lifts de ±6–12pp são hipóteses sem significância. O sinal robusto é o cross-check (silenciou→sumiu), não os lifts finos. Confirma a virada de §11: **a alavanca não está em *como cotar* — está no reengajamento (§13).**

## 13. Mineração de reengajamento

Se o sumiço silencioso é a perda nº1 (§11) e a entrega da cotação quase não muda isso (§12), a alavanca é **reabrir quem sumiu**. Esta seção minera as cutucadas reais do Vendedor. Detecção no nível de mensagem (o construtor de turnos **não** quebra mesmo-lado por gap, então a cutucada-no-silêncio fica escondida dentro de um turno): **poke = mensagem `from_me` cujo anterior também é `from_me`** (cliente não respondeu no meio) com gap ≥ 40 min.

Base macro: **1.017 cutucadas em 477 threads** (~2,1 por thread → o humano é **multi-toque**); **32% tiveram resposta em 24h**. Workflow Claude Code: 20 agentes Sonnet codificaram **84 cutucadas** (1ª por thread, estratificada por modelo × respondeu) — movimento, gap, desconto, tipo de silêncio, resultado.

Resultado: **40% reviveu** (34/84), 18 morna, 32 silêncio.

| Eixo | Leitura |
|---|---|
| **Gap (tempo de silêncio)** | 40m–2h = **53%** → 2–12h 41% → 12–24h 40% → >24h **32%**: decay **monotônico**, gap curto vence |
| **Movimento** | `pergunta_leve` **78%** (n=9) > `calor_saudade` 38% (n=48, o cavalo) > `escassez_partida` 20% (n=10) > `midia_nova` **14%** (n=7) > `desconto` 0% (n=1) |
| **Desconto** | sem 41% (n=81) vs com 33% (n=3) — sem sinal a favor de descontar |
| **Tipo de silêncio** | silêncio total 46% (n=13) ≈ desviou-antes 39% (n=71) — vale cutucar os dois |

**Padrão vencedor: curto, caloroso, pergunta de logística — nunca mídia a frio, nunca desconto.** Templates reais: **"Seria hoje amor?"** (`pergunta_leve`, gap curto), **"Bom dia amor 🥰"** (`calor_saudade`, reabrir no dia seguinte), **"Quando estiver vindo me avisa rs"** (fecha logística do encontro).

**Tensões com a política do CONTEXT (`Reengajamento`) — decisão de produto do Fernando:**
- **(a) toque ÚNICO vs multi-toque humano (~2,1/thread):** **inconclusivo** — só medimos a 1ª cutucada. Único no piloto é defensável (anti-spam/bloqueio); um 2º toque é candidato natural à fase seguinte.
- **(b) ~30 min:** evidência **APOIA** — gap curto é o melhor (53%) com decay claro. Manter.
- **(c) sem desconto:** evidência **APOIA** — sem desconto revive mais. Manter.

**Confiabilidade:** re-codificação cega de 16 — **50% de concordância em `worked`, 56% em `move`** (mais fraca que §12; reviveu/morno e a classificação de movimento são ruidosos). Tratar taxas de baixo-n como direção, não verdade. **Ressalva central:** "reviveu" = reabriu a conversa, **não** = `Fechado` (mede reabertura, não conversão); e há **viés de sobrevivência** (só vimos cutucadas que o Vendedor escolheu mandar).

## 14. Próximos passos (não executados)

1. Decisões de produto do Fernando (§6, sobretudo `oral_gancho`; + as 3 tensões de §13 sobre a política de Reengajamento).
2. Redigir persona/regras/FAQ a partir de §7–§8, **incorporando §12** (cotar limpo+caloroso, sem urgência colada) e **§13** (templates de reengajamento curtos/calorosos), marcando os pontos de §6 como TODO até a decisão.
3. (Opcional) classificar as 1.520 threads para frequência completa + treinar classificador leve (TnT-LLM Phase 2).
4. Validar o prompt destilado com hold-out cross-modelo (segurar eb04) + LLM-as-judge offline sobre turnos reais segurados (§3).
