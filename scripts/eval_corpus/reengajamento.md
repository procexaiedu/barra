# Eval de reengajamento (ponto 5 do flywheel) — §13

> **Ponto 5** do plano de destilação. Mina as **cutucadas (pokes) reais** do Vendedor e mede empiricamente **o que reabre quem sumiu** — a perda nº1 do corpus (55% de sumiço mudo, ponto 2). Replica/refuta os achados de `docs/agente/10 §13`, agora com **ground-truth determinístico** (n grande) em vez das 84 cutucadas codificadas à mão do doc.
> **Gerado:** 2026-06-13 por workflows Claude Code offline (moeda abundante; NÃO consumiu crédito de API de prod, NÃO subiu o agente, NÃO mandou nada ao WhatsApp; §0 do `CLAUDE.md` respeitado). Read-only sobre `corpus.mensagens_raw/threads`; só a tabela NOVA `corpus.eval_reengajamento` recebeu DDL/INSERT/UPDATE.

## Ponto de design CRÍTICO resolvido: o reengajamento é CANNED, não LLM

O reengajamento NÃO é gerado pelo LLM — é um **template determinístico** sorteado de um pool fixo no worker. Evidência:

- **Pool de 3 strings fixas**: `api/src/barra/agente/_canned.py:46-50` (`REENGAJAMENTO_CANNED`), sorteadas por `escolher_reengajamento()` (`random.choice`, `_canned.py:53-55`).
- **Disparado por cron ARQ** `reengajar_silenciosos` (`api/src/barra/workers/timeouts.py:126-210`): consulta o DB por alvos (`Triagem`/`Qualificado`, `intencao IN ('cotacao','agendamento')`, `ia_pausada=false`, `reengajado_em IS NULL`, última msg do cliente entre `reengajamento_delay_min` e 24h, dentro do horário de operação BRT) e **enfileira `enviar_turno` direto com `chunks=[escolher_reengajamento()]`, `midias=[]`** (`timeouts.py:197-207`). **Nunca invoca o grafo / ChatAnthropic.**
- Registrado em `api/src/barra/workers/settings.py:224-228` (cron a cada 5 min).
- **Toque único** garantido por `reengajado_em IS NULL` + `UPDATE ... SET reengajado_em=now()` atômico (`FOR UPDATE SKIP LOCKED`).
- Flag `reengajamento_ativo` default **OFF** (`api/src/barra/settings.py:204-206`); `reengajamento_delay_min` default **30** (`:208-212`).
- O bloco `<reengajamento>` em `api/src/barra/agente/prompts/regras.md.j2:95-97` é **documentação não-fiada** — nenhuma referência no código Python o injeta num turno de reengajamento. (Ele guia o tom geral da IA, mas o toque proativo de reengajo não passa por ele.)

**Consequência para a FASE B:** não há prompt a otimizar no reengajamento. A "pontuação" vira: **o template canned adere aos sinais robustos da FASE A?** E o veredito é uma **recomendação de produto** (mix de movimento / política), não de prompt. → GEPA não tem alvo aqui; ver FASE B.

## FASE A — `corpus.eval_reengajamento`

### Detecção de poke (nível de MENSAGEM)

poke = mensagem `from_me=true` cujo ANTERIOR na thread (por `ts, msg_id`) também é `from_me=true`, com gap ≥ 40 min (`reengajamento_ddl.sql` + insert determinístico). **Sanity-check OK:** detectamos **1019 pokes em 477 threads** vs ~1.017/477 do §13 — bate.

`reviveu`, `gap_bucket`, `tem_midia`, `comprimento_chars` são **determinísticos via SQL** (sem juiz). `reviveu` = existe msg do cliente (`from_me=false`) na mesma thread em ≤24h após o poke. Só `movimento`/`tem_desconto`/`tipo_silencio` vêm do juiz (3× Sonnet, voto majoritário — `wf_reeng.js`, mesmo padrão de `wf_cotacao.js`).

### População limpa

Das 1019 cutucadas, a análise de movimento roda nas **718 limpas** = threads de cliente `@lid` com `thread_ops=false` (exclui 113 pokes de grupos `@g.us`/Coordenação e 188 `thread_ops` — caixa do dia, repasses, "Vitoria"/"Yalla", templates de captação; o piloto revelou essa contaminação). Codificação: **89.8% unânime (3/3)**, concordância média **0.969** — muito acima dos 56% em `move` do §13 (o ground-truth determinístico + enum mais nítido + pré-derivação de gap/mídia deixaram a codificação robusta).

### Resultado 1 — decay por GAP (revival, população limpa n=718)

| gap_bucket | n | reviveu% | Wilson 95% |
|---|---|---|---|
| **40m–2h** | 114 | **62.3%** | [53.1, 70.6] |
| 2–12h | 153 | 52.9% | [45.1, 60.7] |
| 12–24h | 91 | 47.3% | [37.3, 57.4] |
| **>24h** | 360 | **37.2%** | [32.4, 42.3] |

**Decay monotônico, altamente significativo** (Cochran-Armitage trend z=−5.12, **p=3e-07**; χ² indep p=8e-06). **REPLICA §13** (53→41→40→32) com shape limpo e n grande. → **CONTEXT `Reengajamento` "~30min" está APOIADO empiricamente** (gap curto vence). Base rate da 1ª cutucada/thread = 47.2% (≈ os 40% do §13 em n=84).

### Resultado 2 — lift por MOVIMENTO (revival, n=718)

| movimento | n | reviveu% | share humano | vs resto (Fisher) |
|---|---|---|---|---|
| **pergunta_leve** | 73 | **68.5%** | 10.2% | OR 2.85, **p=5.8e-05** |
| midia_nova | 29 | 55.2% | 4.0% | OR 1.48, p=0.34 (ns) |
| calor_saudade | 376 | 50.0% | 52.4% | OR 1.43, p=0.02 |
| outro | 55 | 45.5% | 7.7% | OR 0.98, p=1.0 (ns) |
| **escassez_partida** | 176 | **27.8%** | 24.5% | OR 0.36, **p=3.2e-08** |
| **desconto** | 9 | **11.1%** | 1.3% | OR 0.15, p=0.04 |

### Confound de GAP controlado (chave da honestidade)

Gap e movimento são **entrelaçados**: `escassez_partida` é **94% gap>24h** (169/176 — "último dia na cidade" mandado dias depois); `pergunta_leve` skewa curto; `calor_saudade` é **chato em todos os buckets (~50% em cada)**. Controlando o gap:

- **pergunta_leve vs calor dentro de 40m–2h:** 82% (n=34) vs 50% (n=56), **p=0.003** → pergunta_leve vence **no mesmo gap** (efeito real de movimento, não só timing).
- **calor vs escassez dentro de >24h:** 49% (n=150) vs 28% (n=169), **p=8.5e-05** → escassez perde **no mesmo gap** (movimento genuinamente net-negativo, além do timing tardio).

### O que REPLICA vs o que era artefato de n pequeno (§13)

| Achado §13 | n §13 | Aqui | Veredito |
|---|---|---|---|
| `pergunta_leve` é o melhor (78%) | 9 | **68.5% (n=73), p=5.8e-05, vence mesmo gap-controlado** | **REPLICA — agora SIGNIFICANTE** |
| `desconto` é o pior (0%) / sem desconto melhor | 1 | 11.1% (n=9), p=0.04; sem desconto = 46% | **REPLICA** |
| gap curto vence, decay monotônico | 84 | z=−5.12, p=3e-07 | **REPLICA — forte** |
| `escassez_partida` fraco (20%) | 10 | 27.8% (n=176), p=3e-08, perde gap-controlado | **REPLICA — forte; é o move mais usado-e-ruim** |
| `calor_saudade` é "o cavalo" (38%) | 48 | 50% (n=376), gap-insensível | **REPLICA (papel), número maior** |
| `midia_nova` é o pior frio (14%) | 7 | **55.2% (n=29), ns (p=0.34)** | **REFUTA — artefato de n=7; mídia é mediana, não tóxica** |
| silêncio total ≈ desviou-antes | 13/71 | — (não foi o gargalo; vale cutucar os dois) | neutro |

**Generaliza cross-modelo** (hold-out eb04): a ordem pergunta_leve > calor > escassez se mantém em eb01-03 (63/54/31%) e eb04 (77/46/24%).

### Ressalva central (igual §13)

`reviveu` = **reabriu a conversa em 24h, NÃO = `Fechado`** (mede reabertura, não conversão final). Há **viés de sobrevivência**: só vimos cutucadas que o Vendedor escolheu mandar — o efeito causal de *adicionar* uma cutucada não é estimável offline. As taxas absolutas (revival) são mais altas que as do §13 porque "qualquer msg do cliente em 24h" é uma barra mais frouxa que o "reviveu/morno" codificado à mão do doc; a **ordem relativa** é o sinal robusto, não os níveis.

## FASE B — o template canned adere aos sinais robustos?

Threads-alvo (silenciaram pós-cotação): `eval_cotacao.reacao_real='silenciou'` e/ou `eval_perda.motivo='sumiu'`. Como o reengajo é **canned** (não LLM), não geramos texto de candidato; avaliamos **o pool fixo** contra os 4 sinais robustos da FASE A, comparando com o **baseline humano** (o mix real de movimento do Vendedor).

### Os 3 cards do pool (`_canned.py:46-50`) classificados pela rubrica §13

| string | len | movimento | tem_desconto | mídia |
|---|---|---|---|---|
| `seria hoje amor? 🥰` | 18 | **pergunta_leve** | não | não |
| `vamos se ver vida, que horario te serve?` | 40 | **pergunta_leve** | não | não |
| `oi sumido rs, ainda quer marcar? que dia fica bom pra vc?` | 57 | **pergunta_leve** | não | não |

Os 3 são **pergunta_leve** (pergunta de logística), curtos (18–57 chars vs mediana 22 / máx 44 do pergunta_leve real — o 3º estoura um pouco o teto humano mas segue uma pergunta curta de logística), **zero desconto**, **zero mídia a frio**, tom caloroso.

### Aderência aos sinais robustos

| sinal robusto (FASE A) | exige | pool canned | baseline humano |
|---|---|---|---|
| movimento = `pergunta_leve` (68.5%, o melhor) | usar | **100% pergunta_leve** | **só 10.2%** dos pokes |
| sem desconto (desconto = 11.1%, o pior) | obrigatório | **0% desconto** | 1.3% (raro, ok) |
| sem mídia a frio | preferível | **0% mídia** | 4.0% |
| curto + caloroso | preferível | **sim (18–57 ch, "amor"/"vida"/🥰)** | varia |
| gap curto (decay forte) | ~30 min | **`delay=30`min** (`settings.py:208`) | mediana ~horas, multi-toque |

### Veredito de produto

**O template canned já está alinhado ao que converte — e melhor que o humano médio.** O insight central da FASE B é de **alocação**: o Vendedor humano gasta **52% das cutucadas em calor_saudade (50%)** e **24% em escassez_partida (27.8% — o pior move produtivo)**, mas só **10% em pergunta_leve (68.5% — o melhor)**. **O sistema acerta o que o humano erra:** sorteia 100% pergunta_leve, sem desconto, com `delay=30min` (o bucket de gap vencedor). Não há gap a fechar entre o template e o ótimo offline.

- **GEPA / otimização de prompt: SEM ALVO no reengajamento.** Não há texto LLM aqui; e o pool já é o movimento certo. Nenhuma redação de prompt move a métrica.
- **As alavancas de produto que SOBRAM (não-prompt, exigem A/B ao vivo):**
  1. **toque único vs 2º toque** — §13 deixou inconclusivo (medimos só a 1ª cutucada/thread; o humano é ~2,1/thread). Decay é forte mas existe sinal em gap médio; um 2º toque curto é candidato natural — **decisão de produto do Fernando + A/B**.
  2. **encurtar `delay` < 30min?** — o bucket 40m-2h (62%) é o melhor *observado*, mas não há dado < 40min (o detector exige gap ≥ 40min por construção). Não dá pra afirmar offline que 15min > 30min; **A/B**.
  3. **expandir o pool sem sair de pergunta_leve** — variar a redação evita o "tell" canned em quem insiste, mantendo o movimento vencedor. Cosmético, baixo risco; não precisa de eval.
- **A alavanca não é capturável offline além disto:** `reviveu ≠ Fechado` + viés de sobrevivência ⇒ o ganho marginal real de cutucar (e de um 2º toque) **só se mede com A/B ao vivo** (cutuca on/off, 1 vs 2 toques), exatamente como a cotação (ponto 4) concluiu para a conversão.

## Reprodutibilidade

- `reengajamento_ddl.sql` — DDL de `corpus.eval_reengajamento` (PK no nível de mensagem).
- `wf_reeng.js` — workflow de codificação de movimento (3 juízes, multi-voto). O `/tmp/reeng_judge_prompt.md` é a versão paramétrica por partição usada nesta rodada (8 partições × 3 juízes sobre a população limpa).
- `persistir_reeng.py` — agrega os votos dos juízes e dá UPDATE só nas colunas do juiz (reviveu/gap/mídia já entraram determinísticos). `DATABASE_URL=... python persistir_reeng.py /tmp/reeng_votes/p*.json`.
- SQL das tabelas de resultado: ver as queries em `metricas_reeng.sql`.
