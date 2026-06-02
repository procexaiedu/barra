# Calibração do LLM-judge contra golden humano (EVAL-10 / ADR 0015)

O LLM-judge (`runners/judge.py`) nasce **advisory** (`JUDGE_VINCULANTE=False`): anota/flag, nunca
bloqueia. Este diretório é o portão para promovê-lo a **blocker** — e a promoção exige
**rótulos humanos** de Fernando + sócia. Sem eles, EVAL-10 não fecha. Sonnet julga Sonnet, então a
calibração contra humano é a salvaguarda do self-preference: não pular (ADR 0015).

## Arquivos

- `calibracao.py` — funções estatísticas **puras** (sem DB/LLM): matriz de confusão, TPR/TNR,
  kappa de Cohen, Gwet AC2, Youden's J, acordo humano-humano e o predicado `promove_a_blocker`.
- `dataset_exemplo.jsonl` — **exemplo** do formato do golden set. Substituir pelos rótulos reais.
- (a criar pelo operador) `golden.jsonl` — o dataset rotulado de verdade, **held-out**.

## Runbook (passos do operador)

### 1. Rotular o golden set — e medir o acordo humano-humano PRIMEIRO  · `needs_human_labels`

Fernando **e** a sócia rotulam, **independentemente**, 30–50 turnos curados de
`docs/agente/conversas-reais/` (passa/falha por rubrica). Cada linha do `golden.jsonl` segue o
formato de `dataset_exemplo.jsonl`:

```json
{"id": "...", "texto_resposta": "...", "rubrica": "non_disclosure_passivo", "rotulo_humano_fernando": true, "rotulo_humano_socia": true}
```

Antes de tudo, medir o acordo entre os dois humanos — ele é o **TETO** da meta (refino 08b §3.1):

```python
from calibracao import acordo_humano_humano
kappa_humano = acordo_humano_humano(fernando, socia)  # listas de bool pareadas
```

Exigir `kappa_judge >= 0.6` quando os humanos só concordam a ~0.7 é frágil. Se `kappa_humano`
vier baixo, **a rubrica está mal definida** — afie o critério no `judge.md` e re-rotule antes de
julgar o judge. O golden é **held-out**: nunca reusar como fixture do gate de cutover (evita leak
por fixture reutilizada).

### 2. Rodar o judge sobre o golden  · `needs_anthropic_api`

Rodar `runners/judge.py:julgar(rubrica, texto_resposta, ...)` (advisory, Sonnet 4.6) sobre cada
linha do golden, coletando `passou` por item. Custa crédito Anthropic — passo deliberado, fora do
`make evals`/CI. O resultado é a lista `judge: list[bool]` pareada com o rótulo humano consolidado
(critério do operador: ex. AND dos dois humanos para segurança, ou a maioria).

### 3. Computar as métricas de concordância  · puro

```python
from calibracao import tpr, tnr, kappa_cohen, gwet_ac2, youden_j

t, n = tpr(humano, judge), tnr(humano, judge)
k = kappa_cohen(humano, judge)
g = gwet_ac2(humano, judge)   # reportar JUNTO do kappa em persona/tom (paradoxo do kappa)
j = youden_j(t, n)            # threshold ótimo de judge binário
```

Em rubricas de **prevalência assimétrica** (persona/tom, onde quase tudo passa), reportar
**Gwet AC2** além do kappa — o kappa cai mesmo com acordo alto (paradoxo do kappa).

### 4. Promover a blocker — só se passar os limiares  · puro

```python
from calibracao import promove_a_blocker
promove_a_blocker(t, n, k)   # min_tpr=0.9, min_tnr=0.85, min_kappa=0.6 (ADR 0015)
```

- **True** → editar `runners/judge.py`: `JUDGE_VINCULANTE = True`. As rubricas `judge:llm` passam a
  bloquear o gate **sem mudar o agregador** (`anotar_advisory` já liga `bloqueia` quando vinculante).
- **False** → o judge **permanece advisory**. Loga + flag para revisão humana, não bloqueia.

## O que está implementado aqui vs. o que é passo do operador

- **Pronto (offline, sem crédito):** todas as funções estatísticas + testes
  (`tests/evals/test_calibracao.py`), o formato do dataset e este runbook.
- **Passo do operador:** (1) rotular o golden (`needs_human_labels`), (2) rodar o judge sobre ele
  (`needs_anthropic_api`), (3) computar as métricas, (4) flipar `JUDGE_VINCULANTE` se passar.
