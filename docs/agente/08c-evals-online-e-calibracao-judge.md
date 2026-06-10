---
titulo: "Evals do Agente — Camada Online e Calibração do Judge (pesquisa jun/2026)"
arquivo: docs/agente/08c-evals-online-e-calibracao-judge.md
data: 2026-06-08
escopo: "Pesquisa fact-checada (deep-research, 6 ângulos / 20 fontes / 25 claims verificados adversarialmente) sobre eval de agentes conversacionais multi-turno em produção. Recorte: separar eval OFFLINE (gate em massa) de eval ONLINE (observabilidade ao vivo), calibração do LLM-judge contra anotação humana, detecção de regressão entre versões, e métricas além de pass/fail."
relacao_com_08: "Complementa, NÃO substitui, 08-evals.md (spec do runner) nem 08b-evals-pesquisa-producao.md (plano de cutover). Onde 08b já cobre um ponto, este doc só aprofunda o que a pesquisa nova adicionou — sobretudo a CAMADA ONLINE (ausente em 08/08b) e a calibração provável do judge."
precedencia: "Onde divergir de um ADR vigente (0015 LLM-judge/golden, 0016 output-guard) ou de decisão fechada, o ADR/decisão vence. Onde divergir do código, o código vence."
metodo: "Workflow /deep-research (wf_7964be6e-8bf): fan-out de busca → fetch → verificação adversarial 3-votos por claim (2/3 refutes mata). 25 claims verificados → 23 confirmados, 2 refutados. Fontes de peso: Anthropic eng, LangChain, ICLR 2025, NeurIPS 2025, ACM TIST."
---

# 08c — Camada Online e Calibração do Judge

> **O que este doc é.** Destilação fact-checada do estado da arte (jun/2026) sobre avaliar
> agentes conversacionais multi-turno **em produção**. Não redefine o gate (`08-evals.md`) nem o
> plano de cutover (`08b`). Traz o que a pesquisa recente adiciona em dois eixos onde o
> repo tem lacuna: **(1) a camada de eval ONLINE** sobre tráfego real (hoje inexistente — só
> temos o gate offline) e **(2) a calibração do judge contra rótulo humano** com garantia
> estatística (hoje `golden.jsonl` é placeholder, `JUDGE_VINCULANTE=False`).
>
> **Disciplina de citação.** Toda afirmação carrega fonte inline e o placar de verificação
> adversarial (`3-0` = unânime; `2-1` = confirmado com ressalva). Onde a pesquisa **refutou**
> uma ideia plausível, ela está em §6 com o placar `0-3` — não silenciada.

> ⚠️ **STATUS (2026-06-08): o LLM-judge dos evals foi REJEITADO (ADR 0015 → `rejected`).** Logo a
> **§5 inteira (calibração do judge)** e o **passe de judge amostrado da camada online** ficam como
> **registro do estado da arte**, não como plano ativo — não vamos calibrar nem operar um judge nos
> evals. **O que do doc segue válido:** a camada online **determinística** (invariantes in-app →
> feedback no trace, ex. `online_non_disclosure`, §2/§7) e o split **regressão ≠ capacidade** (§3).
> A revisão humana periódica (§1, camada 3) deixa de ser "para calibrar o judge" e passa a ser
> **diff manual contra a golden**. Nada disto toca o **output-guard runtime (ADR 0016)**, judge
> distinto e preservado. Este banner vence as menções a calibração abaixo.

---

## 1. Sumário executivo

O consenso 2025-2026 é que avaliar agentes conversacionais multi-turno em prod exige **três
camadas sobrepostas que não se substituem** (modelo "queijo suíço"):

1. **Offline / automated** — fixtures, golden sets, judge panel — rodando em **CI/CD a cada
   mudança de agente/modelo**. → *No Barra: já temos (`08-evals.md`, 61 fixtures, `make evals`).*
2. **Online / observability** — evaluators rodando **sobre traces de produção** (amostra), pra
   detectar degradação por update de modelo, drift de dados ou novo padrão de usuário. → 🟡
   *No Barra: PARCIAL (jun/2026). `coordenador._amostrar_eval_online` roda 4 invariantes
   determinísticos numa amostra (`eval_online_sample_rate`, 1 sorteio): `online_non_disclosure`,
   `online_system_leak`, `online_segredo_agenda` (regexes do output_guard, fonte única) e
   `online_formato_bolha` (bolha vazia/estourada/template residual) — cada um vira suite no
   `agente_eval_pass_rate` + **feedback no trace** (`registrar_feedback_online`). O alerta
   `AgenteEvalOnlineCaiu` cobre as 4 pelo label `suite`. Falta: o passe de judge amostrado.
   Ver §2 sobre por que os checks de TEXTO têm de rodar in-app (masking de PII).*
3. **Revisão humana periódica** — anotação para **calibrar o judge**, não para validar cada
   resposta. → ⚠️ *No Barra: LACUNA. O judge nunca foi calibrado (`golden.jsonl` placeholder).*

> *Anthropic:* "automated evals for fast iteration, production monitoring for ground truth, and
> periodic human review for calibration." (`3-0`)

O elo mais frágil é o **próprio judge**: LLM-judges são sistematicamente **superconfiantes e
enviesados por formatação**, então **acurácia sozinha não certifica um judge** — ele precisa ser
calibrado contra anotação humana, idealmente com garantia *distribution-free* (Trust-or-Escalate)
e métrica ciente de indeterminação. Isso casa com a moeda escassa do projeto: a calibração por
**escalada por confiança** (judge barato primeiro, escala pro forte só no incerto) é exatamente o
padrão que minimiza queima de crédito de API.

---

## 2. As duas/três camadas: offline ≠ online (e nenhuma substitui a outra)

**Claim (`3-0`, fonte: [Anthropic — Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [LangChain — Production monitoring](https://www.langchain.com/conceptual-guides/production-monitoring)).**
Offline e online são **camadas complementares, não substitutas**. Offline serve pré-launch e
CI/CD a cada mudança de agente/modelo (totalmente reproduzível, sem impacto no usuário); online
revela comportamento real em escala e pega o que o eval sintético não pega. Os times mais
efetivos combinam os dois **mais** revisão humana periódica.

**A camada online (a lacuna do Barra) — Claim (`3-0`, fonte: LangChain).**
Evaluators online rodam automaticamente sobre traces de produção (todos ou uma amostra) pra
rastrear qualidade ao longo do tempo e detectar degradação — distinto do batch offline.

- LangChain recomenda **amostrar 10-20% do tráfego** pra LLM-as-judge (controlar custo de
  inferência). *(Vendor self-recommendation — ver caveat §7.3.)*
- Padrão comum: **judge caro numa amostra pequena + checagens heurísticas leves em 100% do
  tráfego.** ← Isto encaixa perfeitamente no Barra: rodar o **output-guard / `state_check`
  determinístico (ADR 0016) em 100%** dos traces como tripwire, e judge completo só amostrado.
- Pra agentes multi-step, o eval online deve avaliar a **trajetória/caminho** (tools certas,
  ordem sensata, retrieval relevante), não só a saída final.

> **Aplicação Barra.** A camada online não existe hoje. O caminho de menor custo:
> (a) invariantes determinísticos (canary cross-modelo, `tool_calls_proibidas`, output-guard) em
> **100% dos traces** de prod via LangSmith; (b) passe de LLM-judge **amostrado** ou **periódico**
> (ver §7.4 sobre por que 10-20% pode ser esparso demais num WhatsApp de baixo volume).
>
> **⚠️ Correção (jun/2026, auditado nos traces reais).** O conteúdo de prod chega ao LangSmith
> **mascarado** (`setup_tracing` força o anonymizer: todo `content` de system/human/ai vira
> `[PII]`). Logo um evaluator que **lê o conteúdo do trace** é cego aos invariantes de TEXTO
> (disclosure, canary, videocall) — daria falso-verde. O caminho viável NÃO é "rodar invariante
> sobre o trace", e sim **rodar o invariante IN-APP (no worker, antes do masking) e gravar só o
> veredito (key+score, não-PII) como feedback no trace** — implementado p/ `online_non_disclosure`
> (`coordenador` + `registrar_feedback_online`). Para checagem de **trajetória** sobre o trace
> (nomes de tool/nó, que não são PII) seria preciso reconfigurar o masking p/ exemptá-los. Detalhe
> e shape dos traces na memória do projeto (`langsmith_prod_pii_masking_traces`). Nota lateral: o
> trace de prod agora carrega `atendimento_id`/`modelo_id` (via `metadata_trace_turno` no config do
> coordenador) — antes só tinha `thread_id`.

---

## 3. Regressão ≠ capacidade (rotular as fixtures explicitamente)

**Claim (`3-0`, fonte: Anthropic).** São suítes distintas:

- **Regressão** — "ainda lido com tudo que já passava?" → alvo **~100% de pass**; queda sinaliza
  que algo quebrou. É a proteção contra *backsliding* entre versões.
- **Capacidade** — "consigo fazer isto de forma confiável?" → dá o sinal de **melhoria** que uma
  suíte 100%-verde não dá.
- Tarefas de capacidade **graduam** para a suíte de regressão e passam a rodar continuamente.

> **Aplicação Barra.** O split já existe na prática (15 canônicas + 46 adversariais, `08b`). O
> reforço é **rotular** cada fixture como `regressao` (gate, alvo 100%) vs. `capacidade` (sinal de
> progresso, não-gate) — senão a suíte 100%-verde rastreia regressão mas esconde estagnação de
> capacidade.

---

## 4. Multi-turn muda o objeto de avaliação: a trajetória, não a resposta

**Claim (`3-0`, fontes: Anthropic; [arXiv 2503.22458](https://arxiv.org/pdf/2503.22458); [ACM TIST 10.1145/3793671](https://dl.acm.org/doi/10.1145/3793671)).**
Agentes agem em N turnos (tool calls, mutação de estado, adaptação) → **erros propagam e
compõem**. Empiricamente, **acurácia multi-turn cai ~39% vs. single-turn** (ICLR 2026 / beam.ai).
A avaliação precisa capturar:

- **transcript** (saídas + tool calls + raciocínio + resultados intermediários),
- **estado final do ambiente**,
- **interação de ferramentas** (quais tools, parâmetros, chamadas obrigatórias),

— não respostas isoladas.

> **Aplicação Barra.** Confirma a decisão do EVAL-10 de avaliar **por-conversa** (não por-resposta;
> já registrado na memória do projeto). O delta: avaliar também o **caminho** (a IA chamou
> `registrar_extracao`/`pedir_pix_deslocamento` na ordem certa?), via o `NodesVisitedHandler` que o
> runner já tem.
>
> **✅ Implementado (jun/2026).** O runner aceita **expectativas por-turno** dentro de cada item de
> `mensagens_entrada` (`tool_calls_obrigatorias`/`tool_calls_proibidas`/`nodes_obrigatorios`/
> `nodes_proibidos`/`state_check`, grader puro `_avaliar_turno`). A **ordem dos turnos** codifica a
> "ordem certa" (ex.: `pedir_pix_deslocamento` proibido em triagem, obrigatório pós-cotação) — sem
> DSL de subsequência. As expectativas de topo da fixture seguem como acumulado-da-conversa. Ver
> `evals/README.md` ("Expectativas POR TURNO").

---

## 5. Calibração do judge — o ponto mais acionável

### 5.1 Saia do pass/fail e do n-gram

**Claim (`3-0`, fontes: ACM TIST; arXiv 2503.22458).** BLEU/ROUGE/METEOR são **inadequados** pra
diálogo (medem sobreposição de superfície, não equivalência semântica). Avalie em **duas
taxonomias**:

- **O QUÊ:** task completion · qualidade da resposta · UX · **memória/retenção de contexto** ·
  planejamento/uso de ferramentas.
- **COMO:** anotação · métricas automáticas · híbrido humano+quantitativo · LLM self-judging.

LLM-as-judge é **uma de quatro** metodologias, não solução isolada.

### 5.2 O judge é superconfiante e enviesado por formatação

**Claim (`3-0`, fontes: [arXiv 2508.06225](https://arxiv.org/pdf/2508.06225); [Judging the Judges (ResearchGate / arXiv 2604.23178)](https://www.researchgate.net/publication/404249222_Judging_the_Judges_A_Systematic_Evaluation_of_Bias_Mitigation_Strategies_in_LLM-as-a-Judge_Pipelines)).**

- **"Overconfidence Phenomenon"**: em 14 modelos frontier (incl. Claude Sonnet 4), a confiança
  predita **supera** a correção real, clusterizada em 90-100%. → **acurácia sozinha não certifica
  o judge**; ele precisa de confiança bem-calibrada.
- **Viés de estilo/formatação domina (0.76-0.92)** — o judge prefere markdown sobre texto
  idêntico em plano — e **engole o viés de posição (≤0.04)**. Um painel pode ser dobrado por
  formatação sobre substância.
- **Debiasing funciona e é model-dependent** (18/20 configs melhoraram, sign test p<0.001). Pro
  **Claude Sonnet 4**: estratégia combinada **+11.2 pp** (p<0.0001), chain-of-thought **+7.2 pp**
  (p=0.004).

> *Caveat de força:* os números 0.76-0.92 e +11.2 pp vêm de **um preprint de abr/2026 ainda não
> peer-reviewed**, escopado a 5 modelos e pares sintéticos — **direcionais, não constantes
> universais.** (ver §7.1)

### 5.3 Calibre contra humano — com garantia, não no olho

**Claim (`2-1`/`3-0`, fontes: Anthropic; arXiv 2508.06225; LangChain Align Evals).**
LLM-judges **devem** ser calibrados contra anotação humana pra garantir baixa divergência;
reserve estudos humanos sistemáticos para **calibrar** o judge (ou avaliar saídas subjetivas).
[LangChain **Align Evals**](https://www.langchain.com/conceptual-guides/production-monitoring) foi
feito exatamente pra isso: alinha o evaluator a rótulos humanos, dá um *alignment score* e salva
baseline pra rastrear regressão do próprio judge.

**Calibração provável e confidence-gated — Claim (`3-0`, fonte: [ICLR 2025 Trust-or-Escalate (arXiv 2407.18370)](https://proceedings.iclr.cc/paper_files/paper/2025/file/08dabd5345b37fffcbe335bd578b15a0-Paper-Conference.pdf)).**

- **Selective LLM-judge evaluation** dá garantia *distribution-free* de que o acordo judge-humano
  atinge um nível α escolhido: dado tolerância α e erro δ,
  `P(judge concorda | judge não abstém) ≥ 1-α` vale com probabilidade ≥ `1-δ`, via calibração de
  um threshold de abstenção num set pequeno (~500).
- **Simulated Annotators** (razão de acordo de anotadores diversos in-context como confiança) corta
  o Expected Calibration Error em **50%** e melhora AUROC de predição de falha em **13%** (GPT-4).
- **Cascaded Selective Evaluation** (judge barato primeiro, escala pro forte só na baixa confiança)
  alcança alvos que o modelo barato sozinho não alcança: no alvo 0.85, **91% de sucesso de garantia
  a 63.2% de cobertura** vs. GPT-4 sozinho com ~77.8% de acordo e **0% de garantia**.

> *Caveat de transferência:* Trust-or-Escalate foi medido em **ChatArena pairwise, não multi-turn**
> — transfere pro judge por-conversa do Barra **por analogia**, precisa revalidar nos nossos dados.
> (ver §7.2)

### 5.4 Forced-choice esconde indeterminação

**Claim (`3-0`, fonte: [NeurIPS 2025 — rating indeterminacy (CMU/Microsoft, arXiv 2503.05965)](https://blog.ml.cmu.edu/2025/12/09/validating-llm-as-a-judge-systems-under-rating-indeterminacy/)).**
Forçar rótulo único é dominante mas **descarta informação de indeterminação** e pode enganar sobre
a qualidade do judge — escolher judge por acordo forced-choice pode pegar um **até 31% pior**
downstream (e elevou o viés de estimação em 28%). Intervenções concretas:

- adicionar opção **Maybe/Tie** pra especificar a tarefa por completo;
- coletar **response sets** (o rater marca **todas** as opções razoáveis);
- usar ~**100 exemplos pareados** pra estimar uma matriz de tradução/correção;
- preferir **MSE contínuo** a forced-choice; se forced-choice for inevitável, usar **KL-divergência
  na direção humano→judge** (não judge→humano).

---

## 6. ⚠️ Refutações a carregar (não ignore)

A verificação adversarial **matou** duas ideias plausíveis (`0-3`):

1. **"Viés de posição virou negligível (≤0.04), então pode largar a randomização de ordem (e até
   pode piorar a acurácia)."** → **REFUTADO 3-0.** **Mantenha o swap de ordem / randomização de
   posição** no judge panel. Largar pode prejudicar.
   *(fonte refutada: Judging the Judges preprint)*
2. **"Eval annotation-free opera em dois modos (point-wise e pairwise), e o pairwise é o primitivo
   relevante pra detecção de regressão entre versões."** → **REFUTADO 3-0** como afirmação geral —
   não tratar o pairwise como o primitivo de regressão por padrão. *(fonte refutada: ACM TIST)*

---

## 7. Caveats honestos sobre as fontes

1. **Números de viés/debiasing (0.76-0.92; +11.2 pp)** vêm de **um preprint de abr/2026 não
   peer-reviewed** (arXiv 2604.23178), escopado a 5 modelos e pares sintéticos próprios →
   **direcionais, não constantes universais.**
2. **Trust-or-Escalate / Cascaded Selective Evaluation** são benchmarkados em **ChatArena
   pairwise, não multi-turn** → transferência ao WhatsApp por-conversa é **por analogia**;
   revalidar com dados do projeto.
3. **Várias recomendações da LangChain** (sampling 10-20%, Align Evals) são **auto-recomendação de
   vendor** — atribuídas corretamente, mas não são benchmark independente.
4. **Mapear as taxonomias O-QUÊ/COMO do survey no split online/offline** é ponte interpretativa do
   sintetizador, não claim do paper — o eixo COMO (anotação/automática/híbrida/self-judging) é
   ortogonal ao eixo timing (ao-vivo vs. batch).

Campo em movimento rápido — todas as fontes são 2025-2026 e correntes na janela da pesquisa, mas
tooling de calibração e achados de viés podem mudar.

---

## 8. Perguntas em aberto (decisões que dependem do Fernando / de medição própria)

1. As garantias provadas do Trust-or-Escalate (ChatArena pairwise) valem pro judge por-conversa em
   **português / WhatsApp multi-turno**, ou precisamos de calibration set + threshold de abstenção
   tunados em conversas in-domain?
2. **Orçamento de anotação** vs. crédito escasso: quantas conversas rotular (~100 pra matriz de
   tradução; ~500 pra threshold) e com que cadência re-calibrar?
3. Quais **métricas multi-dimensionais** (além do gate de invariantes) operacionalizar o eixo
   O-QUÊ (task completion, memória/contexto, planejamento, uso de tools) pro nosso LangGraph, e
   como ponderá-las num score por-conversa?
4. Num WhatsApp de **baixo volume**, 10-20% de amostra pode ser esparso demais pra detectar
   regressão → trade-off vs. invariantes determinísticos em 100% dos traces + passes periódicos de
   judge completo.

---

## 9. Próximos passos acionáveis (mapeados ao stack)

| # | Ação | Camada | Custo | Estado |
|---|------|--------|-------|--------|
| 1 | Rotular fixtures como `regressao` (gate 100%) vs. `capacidade` (não-gate) | offline | Moeda A | rápido |
| 2 | Montar set de conversas rotuladas por humano (~100 pareadas; ~500 p/ threshold) | calibração | humano | bloqueador de #3 |
| 3 | Calibrar judge panel vs. rótulo humano (espírito Align Evals: alignment score + baseline) | calibração | Moeda B (rodar) | depende de #2 |
| 4 | Adotar **escalada por confiança** (Sonnet barato → escala só no incerto) no judge | calibração | Moeda B | casa c/ crédito escasso |
| 5 | **Debias de formatação** no prompt do judge (chain-of-thought / estratégia combinada) | calibração | Moeda A | rápido |
| 6 | **Manter** swap de ordem/posição no judge panel (refutação §6.1) | calibração | — | invariante |
| 7 | Camada online: invariantes determinísticos + judge amostrado/periódico no LangSmith | online | Moeda B | 🟡 parcial: 4 invariantes in-app (`non_disclosure`, `system_leak`, `segredo_agenda`, `formato_bolha`) → feedback no trace (jun/2026); falta judge amostrado |
| 8 | Trajetória por-turno no gate (tool/nó/state por turno em `mensagens_entrada`) | offline | Moeda A | ✅ feito (jun/2026) |

> **Moeda A** = plano Claude Code (abundante). **Moeda B** = crédito de API de prod (escasso —
> autorização explícita antes de rodar; ver `flywheel_iteracao_agente_decisoes`).

---

## 10. Fontes (primárias e peer-reviewed em negrito)

- **[Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)** (primária)
- [LangChain — Production monitoring](https://www.langchain.com/conceptual-guides/production-monitoring) (primária/vendor)
- **[ICLR 2025 — Trust or Escalate / Cascaded Selective Evaluation (arXiv 2407.18370)](https://proceedings.iclr.cc/paper_files/paper/2025/file/08dabd5345b37fffcbe335bd578b15a0-Paper-Conference.pdf)** (peer-reviewed)
- **[NeurIPS 2025 — Validating LLM-as-a-Judge under Rating Indeterminacy (arXiv 2503.05965)](https://blog.ml.cmu.edu/2025/12/09/validating-llm-as-a-judge-systems-under-rating-indeterminacy/)** (peer-reviewed)
- **[ACM TIST — Evaluating LLM-based Agents for Multi-Turn Conversations (10.1145/3793671)](https://dl.acm.org/doi/10.1145/3793671)** (peer-reviewed survey)
- **[arXiv 2508.06225 — Overconfidence in LLM-as-a-Judge](https://arxiv.org/pdf/2508.06225)** (preprint)
- **[arXiv 2503.22458 — survey multi-turn agent failures](https://arxiv.org/pdf/2503.22458)** (preprint)
- [Judging the Judges — bias mitigation in LLM-as-a-Judge (arXiv 2604.23178 / ResearchGate)](https://www.researchgate.net/publication/404249222_Judging_the_Judges_A_Systematic_Evaluation_of_Bias_Mitigation_Strategies_in_LLM-as-a-Judge_Pipelines) (preprint não peer-reviewed — direcional)

> **Veja também:** `08-evals.md` (spec do runner), `08b-evals-pesquisa-producao.md` (plano de
> cutover Vendedor→IA), `docs/adr/0015` (LLM-judge/golden), `docs/adr/0016` (output-guard).
