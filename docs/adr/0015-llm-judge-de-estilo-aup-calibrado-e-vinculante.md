---
status: proposed
---

# LLM-judge de estilo e AUP calibrado e vinculante

As fixtures adversariais e canônicas já declaram rubricas com `judge: llm` — `non_disclosure_passivo`, e as planejadas `persona`, `instruction_following`, `tom_pt_br` — com `limiar_aceite` exigido pelo gate de cutover (`api/evals/README.md:135`: "AUP/disclosure = 0 vazamento confirmado em qualquer run (judge-flag → revisão humana)"). Mas o juiz não existe: `README.md:133` marca `runners/judge.md` e `runners/checks.py` como **TODO M6**, e fixtures como `api/evals/adversariais/disclosure/001_pergunta_direta.jsonl:1` ficam com a parte determinística (regex `nao_deve_conter`, `tool_calls_proibidas`) sob enforcement e a rubrica subjetiva sem nada por trás. Risco de produção: regex só pega vazamento **literal** ("sou uma IA", "Anthropic"); quebra de persona parafraseada, tom fora do PT-BR coloquial, deriva de personagem em turno tardio e recusa nuançada de AUP passam pelo gate e só seriam detectadas pelo próprio cliente no WhatsApp da modelo — exatamente o que a persona GERAL compartilhada existe para nunca deixar acontecer. Agrava: agente e juiz são ambos Sonnet 4.6 (memória "Fallback Haiku removido"), então um juiz ingênuo herda **self-preference** e pode aprovar a própria voz. Sem calibração contra golden humano, ligar o juiz como blocker é tão arriscado quanto não tê-lo.

## Decisões

- **Implementar `runners/judge.md` + `runners/checks.py`** cobrindo as rubricas `judge: llm` já declaradas. O juiz recebe só o `texto_resposta` final (e o histórico do turno quando a rubrica é de drift), nunca o gabarito determinístico, e devolve `{passou: bool, score: float, justificativa: str}` por rubrica via structured output (Anthropic GA, ver memória de structured outputs). Sonnet 4.6 (sem fallback Haiku — memória "Fallback Haiku removido").
- **Calibrar contra held-out humano ANTES de virar blocker.** Curar um golden set rotulado por humano (passa/falha) a partir do corpus de conversas reais (`docs/agente/conversas-reais/`). O juiz só entra no gate de cutover quando atingir limiares mínimos de concordância — **TPR ≥ 0.9 em vazamento/quebra de persona, TNR ≥ 0.85, kappa de Cohen ≥ 0.6** contra o humano. Abaixo disso, o veredito do juiz é **advisory** (loga + flag para revisão humana, não bloqueia), preservando o "judge-flag → revisão humana" que o `README.md:135` já prevê.
- **Mitigar os três vieses conhecidos** (memória "Pesquisa evals externa 27/05": position 10-15pt, verbosity 15-30pt; self-preference por mesmo modelo):
  - **Posição/verbosidade:** rubrica binária por critério (não comparação A/B; não há par para inverter posição), com instrução explícita no `judge.md` de ignorar comprimento e julgar só o critério.
  - **Self-preference:** o juiz **nunca** julga "qual resposta soa melhor", só **aderência a um critério objetivado** (a resposta nega a identidade de IA? mantém o tom coloquial PT-BR? respeita a instrução?). A calibração contra humano é a salvaguarda: se o kappa cair, o viés está mascarado e o juiz não promove a blocker.
- **Juiz de voz em 3 eixos rodando em turnos tardios.** Adicionar a rubrica `persona` (voz coerente), `instruction_following` e `tom_pt_br`, e marcar fixtures de **turno tardio** (5+ trocas, ex. `disclosure.003`) onde o drift aparece. Sem isso o juiz só cobre o turno 1 e a deriva — o modo de falha mais provável da persona em produção — fica sem teste.
- **Não construir o baseline persistido / tripwire nightly** (continua adiado pro P1 por `README.md:151`). Escopo cirúrgico: só o juiz, sua calibração e sua entrada no gate one-shot K=5 existente.

## Considered Options

- **Manter só regex/determinístico (status quo, TODO indefinido).** Rejeitado: regex pega vazamento literal mas é cego a paráfrase, tom e drift — justamente as rubricas subjetivas que as fixtures já declaram e o gate `README.md:135` exige a 0 vazamento.
- **Ligar o juiz como blocker imediatamente, sem calibração.** Rejeitado: juiz não-calibrado e auto-referente (Sonnet julgando Sonnet) pode tanto deixar passar vazamento (TNR ruim) quanto reprovar respostas boas (TPR ruim) e travar o cutover por flake de juiz. Calibrar contra humano é pré-condição para confiar no veredito.
- **Trocar o juiz para Haiku para quebrar o self-preference.** Rejeitado: memória "Auditoria best-practices agente" diz que Haiku-judge precisa de calibração própria e o fallback Haiku foi removido do stack; manter Sonnet + objetivar o critério + calibrar contra humano resolve o viés sem reintroduzir Haiku.
- **Juiz comparativo A/B (resposta do agente vs. referência).** Rejeitado: amplifica position bias (10-15pt) e exige curar uma resposta de referência por fixture; rubrica binária por critério é mais barata e menos enviesada.
- **Esperar produção e curar falhas reais (error analysis weekly do P0).** Rejeitado como **única** rede: detectar quebra de persona pelo cliente real é o risco que o ADR existe para fechar; o error-analysis weekly complementa o juiz, não o substitui.

## Consequences

- **Arquivos novos:** `api/evals/runners/judge.md` (prompt do juiz, com instruções anti-viés) e `api/evals/runners/checks.py` (rubricas determinísticas + invocação do juiz). Sem migration — evals não tocam schema.
- **Golden set humano** curado de `docs/agente/conversas-reais/` (memória "Corpus conversas reais"), com rótulos passa/falha por rubrica; vive em `api/evals/` como dataset de calibração, separado das fixtures de cutover (held-out, não reusado no gate — evita o vetor de leak "fixture reutilizada" da memória "Pesquisa evals externa 27/05").
- **Métricas de calibração** (TPR/TNR/kappa) reportadas uma vez na promoção do juiz a blocker; não são gate recorrente no P0.
- **Custo/latência:** cada rubrica `judge: llm` adiciona uma chamada Sonnet por fixture por run; com K=5 e ~30 adversariais isso multiplica chamadas de eval — aceitável (eval, não hot path). O prompt do juiz é estável e pode ser cacheado (cache mín. Sonnet 1024 tokens, memória "Auditoria best-practices agente").
- **Fixtures de turno tardio** novas (5+ trocas) por eixo de voz; contam na meta P0 de ≥6 adversariais por categoria (`README.md:147`).
- **Dependências:** depende do corpus de conversas reais já extraído (memória "Corpus conversas reais") para o golden set; e do runner E6/K=5 já descrito em `README.md:134` e `docs/agente/08-evals.md §4.1`, no qual o juiz se encaixa sem mudar o agregador (pass por fixture = todas as rubricas ≥ limiar). Enquanto o juiz for advisory, o gate roda como hoje (só determinístico bloqueia); ao calibrar, as rubricas `judge: llm` passam a bloquear sem outra mudança de runner.
- **CONTEXT.md / docs/agente/08-evals.md:** sem termo novo de domínio; atualizar `08-evals.md` para refletir que o juiz saiu de TODO e descrever o portão de calibração (advisory → blocker).
