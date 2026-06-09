# Tornar o gate de evals vinculante

Procedimento para o **gate de evals do agente** (`.github/workflows/evals.yml`) de fato **bloquear PR**, em vez de pular em silêncio. Criado em 2026-06-05.

## Por que este runbook existe

A maquinaria de evals **já está implementada e testada** — `api/evals/runners/runner.py` (multi-turno, K runs, agregação por fixture, exit-code, graders determinísticos + canary cross-modelo), `judge.py` (advisory), 61 fixtures de gate (15 canônicas + 46 adversariais), `make evals`. **O que não existe é o enforcement:** hoje um PR fica verde sem que **uma única** transição de estado, idempotência ou teste adversarial tenha rodado. Causas:

1. **`ci.yml` roda `pytest` sem `TEST_DATABASE_URL` nem `ANTHROPIC_API_KEY`** (de propósito — não toca prod nem gasta crédito). O conftest pula todos os `needs_db`/`needs_key`.
2. **`evals.yml` se auto-pula sem os secrets** (`Guard de secrets`) e **não é check obrigatório** na branch protection. Sem os secrets, o job termina verde sem rodar nada.
3. **Não há banco de teste** para apontar o `TEST_DATABASE_URL` do CI. O único Postgres hoje é o de produção (ver [topologia-banco.md](topologia-banco.md)) — e o runner **faz seed e depende de `ROLLBACK`**: apontá-lo para prod é arriscado (concorrência, resíduo se um teste estourar antes do rollback) e proibido aqui.

Uma suíte adversarial robusta que não bloqueia é **teatro de segurança**. Este runbook fecha o buraco.

## Pré-condição crítica: o `TEST_DATABASE_URL` NÃO é o prod

O runner insere modelo/cliente/conversa/atendimento + cardápio e confia no `ROLLBACK` por fixture para isolar. Em prod isso é frágil (concorrência) e perigoso. Use um **banco descartável**, com o **schema de `infra/sql/` aplicado mas SEM os seeds** (`*seed*`). Duas opções, da mais simples à mais trabalhosa:

- **(Recomendado) Branch de teste do Supabase self-hosted** — um banco efêmero com o mesmo schema (inclui `auth`, `realtime`, extensões), que é o ambiente que o runner espera. Aplique só as migrations de schema (`make migrate` com `AMBIENTE=producao` pula os `*seed*`; ou aplique seletivamente). Descarte ao fim.
- **Postgres limpo (container de CI)** — mais barato, mas o schema de `infra/sql/` tem dependências de Supabase (schemas `auth`/`realtime`, `GRANT`s, extensões) que **não sobem** num Postgres cru sem preparo. Exigiria um subconjunto schema-only curado. Só siga por aqui se aceitar manter esse subconjunto.

## Passos

1. **Provisione o banco de teste** (acima) e obtenha sua connection string. Confirme que **não** é o prod: `SELECT inet_server_addr();` deve diferir de `10.0.0.62`.
2. **Aplique o schema, nunca os seeds.** `AMBIENTE=producao DATABASE_URL=<teste> make migrate` (o alvo pula `*seed*`). Verifique que `barravips.modelos`, `barravips.atendimentos`, `barravips.escaladas`, `barravips.mensagens` e o cardápio (`modelo_programas`) existem.
3. **Adicione os secrets do repo** (Settings → Secrets and variables → Actions):
   - `TEST_DATABASE_URL` = a string do banco de teste (passo 1).
   - `ANTHROPIC_API_KEY` = uma chave com saldo (o gate gasta crédito; o corpus de 61 fixtures × K=5 ≈ algumas centenas de turnos).
4. **Rode uma vez manualmente** (re-trigger do `evals` num PR de teste) e confirme que o `Guard de secrets` agora resolve `rodar=true` e o runner executa. Espere falhas legítimas na primeira vez — calibre as fixtures que estiverem inconsistentes com o domínio (a Onda A já fez isso para o corpus atual, mas re-rode ao vivo).
5. **Torne o check obrigatório.** Settings → Branches → branch protection de `main` → *Require status checks* → marque **`evals`**. A partir daqui, PR que toca `agente/**` ou `evals/**` só mergeia com o gate verde.
6. **(Quando o operador validar) Gradue as adversariais de `capability` → `regressao`.** Hoje elas nascem `capability` (advisory) para não deixar o CI vermelho perpétuo (`_gate_da_fixture`). Após o primeiro run ao vivo estável, marque `"gate": "regressao"` nas fixtures adversariais que devem bloquear (disclosure, jailbreak, cross_modelo, pii são as candidatas óbvias). Sem isso, **a suíte de segurança não bloqueia** mesmo com o gate ligado.

## K=5 vs K=1

O `evals.yml` já chama `--k 5`. O critério de cutover (`08-evals.md §4.1`) é **pass^k por fixture** nas adversariais (0 falha em 5 runs) e ≥4/5 nas canônicas. Enquanto rodar `--k 1`, o `pass^k` degrada para `pass^1` e o gate é mais fraco do que parece. Mantenha K=5 no CI; use K=1 só em iteração local barata.

## Itens fora deste runbook (decisões/trabalho separados)

- **Judge calibrado (EVAL-10).** O LLM-judge é **advisory** (`JUDGE_VINCULANTE=False`) até medir TPR≥0.9/TNR≥0.85/kappa≥0.6 contra um golden humano — e o `golden.jsonl` é placeholder. Calibrar exige Fernando + sócia rotularem (pipeline em `api/evals/calibracao/`). Até lá, **só os graders determinísticos bloqueiam** (o que é o correto: LLM-judge tem agreeableness bias).
- **Judge cross-família.** O judge usa `settings.anthropic_modelo_judge` (default = mesmo modelo do agente → viés de auto-concordância). Aponte para um modelo diferente (ex. `claude-opus-4-8`) para mitigar já; cross-família real (GPT/Gemini via OpenRouter) é trabalho de P1.
