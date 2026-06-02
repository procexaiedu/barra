# Roadmap executável — fechar a auditoria do agente

> **Origem:** `docs/agente/auditoria-agente-best-practices.md` (54 agentes, 2026-06-02, `main 0dc2de8`).
> **Objetivo:** transformar as **lacunas confirmadas** (§4 da auditoria) numa fila de execução para o Claude, separando o que é fazível **agora** do que está **bloqueado** por fatores externos.
> **Regra de ouro deste roadmap:** o código é a fonte de verdade. Cada item de código termina com um **critério de verificação objetivo** (teste que reproduz → passa + `mypy`/`ruff` limpos), conforme `CLAUDE.md` §4/§5. Itens que só fecham com **run live de evals** estão marcados 🔴 e não são "feitos" até a verificação live rodar.

---

## 0. O que bloqueia o quê (ler primeiro)

A auditoria já marcou A1/A2 como **feitos** e A4 como "outro fluxo". O que sobra divide-se em **três classes**, e a classe define a ordem:

| Classe | Significado | Quem destrava |
|---|---|---|
| 🟢 **Fazível agora** | Código + testes sem-DB + fixtures + docs. Verificável localmente. | Claude, sozinho |
| 🔴 **Precisa de run live** | A mudança é fazível, mas a **verificação** exige rodar o grafo real contra `TEST_DATABASE_URL` + Anthropic (créditos esgotados, ver memória `anthropic_creditos_esgotados_prod`). | Claude escreve; verificação espera créditos |
| 🟦 **Ação do operador** | Fora do alcance do Claude: secrets no GitHub, branch protection, rotulagem humana do golden. | Fernando / sócia |

> **Consequência prática:** o Claude pode **fechar quase tudo de código (Ondas A + B) sem créditos**. A graduação do gate de evals e a calibração do judge (Onda C) ficam *staged* — código pronto, atrás de uma flag/PR que só vira "verde" quando os créditos voltarem e o operador puxar os gatilhos do GitHub.

---

## Onda A — Endurecimento de código (🟢 fazível agora, sem run live)

Mudanças cirúrgicas com teste sem-DB. Prioridade ALTA→MÉDIA da §4. Agrupadas em PRs coerentes.

### PR-A1 · Núcleo de robustez do turno (`agente/`)

> ✅ **Concluído (sessão 2026-06-02).** M3a + STOP-03 + STOP-06 + SO-03 + REL-OBS-02 + bucket `modelo_truncado`. 12 testes novos + 643 sem-DB verdes, mypy/ruff limpos, revisores LangGraph e segurança sem achados bloqueantes. Pendência: validação `needs_db` contra Postgres real (deixada p/ CI/local com `TEST_DATABASE_URL` — o `.env` local aponta p/ prod, não rodei testes de escrita contra prod).

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **M3a** | Tornar o incremento de `disclosure_tentativas` idempotente cross-retry. Hoje o replay do mesmo `turno_id` conta 2× e pode escalar 1 toque antes. Guardar via `_executar_idempotente` (mesmo padrão de `tool_calls`, chave `turno_id`). | `agente/nos/intercept_disclosure.py:130-143` (TODO M3a explícito) | Teste: dois `ainvoke` com o mesmo `turno_id` → `disclosure_tentativas` incrementa **uma vez**; o caminho de escalada 3/24h dispara no toque correto. |
| **STOP-03** | Guarda de `tool_use` truncado por `max_tokens`. Hoje só faz `TURNO_TRUNCADO.inc()`. Se `stop_reason=='max_tokens'` **e** o último bloco for `tool_use`, **não despachar** a tool (args incompletos): reinvocar com teto maior **ou** escalar `modelo_indisponivel`. | `agente/nos/llm.py:111-115` | Teste com fake chat devolvendo `stop_reason=max_tokens` + bloco `tool_use` parcial → não cai em `Command(goto="tools")`; roteia p/ escalada/reinvocação. |
| **STOP-06** | Ramo próprio p/ `model_context_window_exceeded` (improvável com janela de 20, mas barato). | `agente/nos/llm.py:99-115` | Teste do switch de `stop_reason` cobre o novo ramo. |
| **SO-03** | Judge do `output_guard` checar o próprio `stop_reason` (refusal/max_tokens) antes de confiar no veredito, em vez de depender só do default-seguro. | `agente/nos/output_guard.py` (etapa 2) | Teste: judge com `stop_reason=refusal` → cai em bloqueia+escala explicitamente. |
| **REL-OBS-02** | Logar `message._request_id` da Anthropic no ramo de erro/refusal (chave do ticket de suporte), além do `turno_id` interno. | `agente/nos/llm.py:106-122` | Teste verifica que o log de refusal/erro inclui o `_request_id` da resposta. |

### PR-A2 · Proveniência de conteúdo não-confiável (`agente/`, entrada)

> ✅ **Concluído (sessão 2026-06-02).** SEC-PI-03 (spotlighting da legenda de imagem via helper `_cercar_dado_midia`, áudio byte-idêntico) + AGT-07 (cap `_MAX_BLOQUEIOS=50` + sufixo de truncamento). 4 testes novos + 647 sem-DB verdes, mypy/ruff limpos, security-reviewer sem achados. Texto cru **não** foi cercado de propósito (canal conversacional primário; injeção via texto é mitigada no `output_guard`).

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **SEC-PI-03** | Estender o spotlighting (hoje só no áudio) à **legenda de imagem** e ao texto cru: cerca/rótulo de proveniência `DADO`/`source` (ou JSON-encoding), igual ao padrão da transcrição. | `agente/nos/prepare_context.py` (montagem da cauda) | Teste de byte: legenda de imagem entra cercada; snapshot do prefixo cacheado **inalterado** (cerca vive na cauda, fora do cache). |
| **AGT-07** | `consultar_agenda` capar por **nº de bloqueios** (top-N + sufixo de truncamento), não só pela janela de 14d. | `agente/ferramentas/leitura.py` (`consultar_agenda`) | Teste: agenda com N+1 bloqueios → retorno tem ≤N itens + marcador de truncamento. |

> **SEC-JB-01** (harmlessness screen leve na entrada, ex. Haiku/structured output p/ conteúdo AUP-duro — menor/não-consentido) é **MÉDIA mas custa um modelo extra por turno**. Decisão de produto/custo: tratar como item **à parte** (ver Onda D), não embutir aqui sem o Fernando aprovar o custo.

### PR-A3 · Resiliência ARQ / webhook (`workers/`, `webhook/`)

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **REL-ARQ-02** | `arq.Retry` nos crons (`lembrete_valor`, `timeouts`) p/ exceção transitória reagendar em vez de perder o toque até a próxima varredura. | `workers/lembrete_valor.py`, `workers/timeouts.py` (nenhum usa `arq.Retry` hoje) | Teste: cron com exceção transitória mockada → `raise Retry(...)`, não engole; guarda de estado/toques preservada. |
| **REL-WH-02** | Janela `max-age` no dedup do webhook (contra replay de payload antigo). Severidade baixa — dedup por persistência já mitiga. | `webhook/routes.py` / `webhook/filtro.py` | Teste: payload com timestamp fora da janela → descartado. |
| **REL-RETRY-02** | (Baixa, opcional) Circuit breaker p/ 529 prolongado da Anthropic, além do retry do SDK. Avaliar se vale o complexidade — pode ficar como nota. | `agente/nos/llm.py` / `core/llm.py` | Só implementar se simples; senão registrar como dívida consciente. |

### PR-A4 · Testes do grafo (🟢, cobre buracos de teste)

| ID | O que fazer | Verificação |
|---|---|---|
| **LG-18** | Teste do caminho `except GraphRecursionError → escalar_por_exaustao`. | Teste novo verde. |
| **LG-10** | `output_guard` reconferir estado terminal antes de pagar o judge (turno descartável) + teste "terminal mid-turno". | Teste novo verde; judge não roda em turno já terminal. |
| **LG-16** | Teste leve (fakes) da sequência de roteamento por `Command`, reduzindo dependência de `needs_db`. | Roda sem DB. |

**Critério de saída da Onda A:** `make test` (631+ sem-DB) verde com os novos testes, `make typecheck` e `make lint` limpos. Rodar os 3 revisores especializados (isolamento-de-domínio, segurança, LangGraph) nos diffs de `agente/` e `webhook/`.

---

## Onda B — Maquinaria de evals offline (🟢 fazível agora)

Tudo aqui é determinístico/offline: roda sem Anthropic. A **verificação** que precisa de run live é a da Onda C.

### PR-B1 · Barras de erro e comparação (`evals/runners/`)

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **EVAL-05** | Emitir IC bootstrap **clusterizado por fixture** (SE/IC95, nº de clusters) junto do pass-rate agregado. Hoje só há contagens absolutas. | `evals/runners/runner.py` (agregação) | Teste com amostra sintética → relatório traz `ic95_baixo/alto` e `n_clusters`. |
| **EVAL-06** | Expor `bootstrap_pareado` via **subcomando do runner** (hoje só tem 3 testes, **não é órfão** — corrige a §4 da auditoria) + registrar o MDE para o N atual. | `evals/runners/runner.py:615-646` | Subcomando roda e imprime `delta ± IC95` + MDE. |

### PR-B2 · Métricas de tool no runner (A5 / AGT-08)

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **A5 / AGT-08** | Adicionar `num_tool_calls`, tokens (input/output/cache) e runtime por fixture à `Captura`; fazer `avaliar()` **ler** os blocos `metricas` (hoje código morto). | `evals/runners/runner.py:90-109` (`Captura`), `:185` (`avaliar`) | 🔴 Código pronto + teste com `Captura` sintética. **Valor real do número só com run live** — marcar a fixture-gate como advisory até lá. |

### PR-B3 · Qualidade do judge e datasets (`evals/`)

| ID | O que fazer | Arquivo:âncora | Verificação |
|---|---|---|---|
| **EVAL-11** | Saída `'Unknown'` no judge (abstém quando incerto) + manter as 4 rubricas isoladas. | `evals/runners/judge.py:33-35` | Teste: caso ambíguo → `Unknown`, não força veredito. |
| **EVAL-16** | Campo de **versão/changelog** nos datasets + checagem de near-duplicate por embeddings (anti-contaminação). | `evals/` (metadados das fixtures) | Teste: fixture sem versão falha o lint do dataset; near-dup acima do limiar é flagado. |

### PR-B4 · Fixtures novas (🟢 escrever; gradação fica na Onda C)

| ID | O que fazer | Arquivo:âncora |
|---|---|---|
| **A3 (fixtures)** | Mais fixtures de ofuscação além das 2 atuais: **hex, homoglyph, base64 aninhado, emoji-smuggling**. Entram como `capability`/advisory. | `evals/adversariais/prompt_injection/`, `.../jailbreak/` |
| **EVAL-13** | Fluxos multi-turno como fixtures de gate: **reengajamento** (1 toque, sem desconto) e **handoff + devolução**. | `evals/` (suite multi-turno) |

**Critério de saída da Onda B:** novos testes de `evals/` verdes sem DB; as fixtures novas carregam e validam no schema; nenhuma fixture nova promovida a `regressao` ainda (isso é Onda C).

---

## Onda C — Graduação, calibração e gate (🔴 run live + 🟦 operador)

**Esta onda não fecha sem créditos Anthropic e sem ação do Fernando no GitHub.** O Claude deixa tudo *staged*; o disparo é externo.

| ID | O que fica pronto (Claude) | O que falta (bloqueio) |
|---|---|---|
| **A4 — Calibrar judge** | `gerar_candidatos.py` + `para_rotular.jsonl` (28 itens reais) já prontos; `calibracao.py` computa TPR/TNR/kappa/Gwet AC2. | 🟦 Fernando + sócia rotulam o golden independentemente → 🔴 rodar `calibrar.py` → promover `JUDGE_VINCULANTE` só se TPR≥0.9 / TNR≥0.85 / κ≥0.6 (ADR 0015). Reportar **Gwet AC2** (EVAL-10). |
| **EVAL-07 — Judge de família distinta** | Implementar judge alternativo via OpenRouter (GPT/Gemini, já usado no Pix) atrás de flag, p/ quebrar self-preference. | 🔴 Verificar concordância vs. Sonnet exige run live. |
| **A3 — Gate de evals real** | Fixtures de `prompt_injection/jailbreak/cross_modelo/pii/injecao_midia` prontas p/ graduar a `gate:'regressao'`. | 🔴 graduar exige run live (senão CI fica vermelho por flaky) + 🟦 secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY` no GitHub + branch protection (tornar `evals` **required check**). |
| **A5 — Verificar métricas de tool** | Instrumentação da Onda B já no runner. | 🔴 número real só com run live de evals. |
| **EVAL-17** | Esqueleto do pipeline trace-de-prod → fixture (online amostra disclosure que passou). | 🔴 precisa de tráfego real + run live p/ fechar o loop. |

---

## Onda D — P1 / deferidos (registrar, não fazer agora)

| ID | O que é | Por que adiar |
|---|---|---|
| **CTX-05** | Sumarização/notas do par p/ threads além de 20 msgs. | P1 explícito; sem perda crítica no P0 (janela + colunas externas cobrem). |
| **SEC-JB-01** | Harmlessness screen Haiku na entrada. | Custo de modelo extra por turno — decisão de produto/$ do Fernando. |
| **Docs defasados** | Alinhar `03 §5.3` (cita `AsyncPostgresSaver` ao fim do turno), `04/05/06` (assinaturas antigas), docs de evals (citam ~11 fixtures, são 99). | `01`/`02` já corrigidos; o resto é trabalho de doc à parte (o código vence). |

---

## Sequência de execução sugerida (para o Claude)

```
1. PR-A1 (núcleo robustez)        → verificar: testes sem-DB + mypy/ruff + 3 revisores
2. PR-A2 (proveniência/entrada)   → verificar: byte-identidade do prefixo + teste de cerca
3. PR-A3 (resiliência ARQ/webhook)→ verificar: testes de retry/replay
4. PR-A4 (testes do grafo)        → verificar: cobre GraphRecursionError + terminal mid-turno
5. PR-B1..B4 (evals offline)      → verificar: testes de evals sem DB + schema das fixtures
   ── ponto de parada: tudo de código fechado sem créditos ──
6. Onda C: abrir PRs staged atrás de flag; aguardar créditos + operador
7. Onda D: registrar como dívida/P1
```

**Cada PR segue `CLAUDE.md`:** mudança cirúrgica (só o necessário), teste que reproduz antes de corrigir, e fecha com verificação objetiva. PRs que tocam `agente/`, `dominio/` ou `webhook/` passam pelos revisores especializados antes do merge.

---

## Bloqueios que dependem só do operador (🟦 — fora do Claude)

Listados aqui para o Fernando puxar quando puder; o Claude não consegue executar:

1. **Restaurar créditos Anthropic** (Plans & Billing) — destrava toda a Onda C e a verificação de A5.
2. **Secrets no GitHub Actions:** `TEST_DATABASE_URL`, `ANTHROPIC_API_KEY` — o `evals.yml` pula silenciosamente sem eles.
3. **Branch protection:** tornar o check `evals` **required** na `main`.
4. **Rotular o golden:** Fernando + sócia rotulam 30–50+ turnos de `docs/agente/conversas-reais/` independentemente (entrada de A4).
```
