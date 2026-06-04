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

### 1. Gerar conversas E2E, rotular por-fala — e medir o acordo humano-humano PRIMEIRO  · `needs_human_labels`

**Não se rotula resposta isolada — a IA é conversacional.** O insumo são **atendimentos completos**
simulados (cliente-LLM ↔ grafo real), gerados por `evals/sim/gerar_conversas.py` (EVAL-12; needs_db
+ needs_key) em `conversas.jsonl`. Fernando **e** a sócia abrem `docs/agente/evals-notas.html`
(servida por HTTP) e, **independentemente**, marcam **✓ passou / ✕ não passou** em **cada fala da
IA**, no contexto da conversa, com comentário opcional. O veredito é **holístico**: ✕ se a fala
quebra **qualquer** das 4 dimensões (non_disclosure, persona, instruction_following, tom_pt_br); ✓
se respeita todas.

Gerar o corpus (passo do operador, **custa crédito** — cliente-LLM + agente-LLM por turno, fora do CI):

```sh
# da raiz de api/, com ANTHROPIC_API_KEY (--usar-database-url copia DATABASE_URL de prod p/
# TEST_DATABASE_URL no processo; o arnês nunca commita — rollback sempre):
uv run python -m evals.sim.gerar_conversas --usar-database-url                    # todos os cenários
uv run python -m evals.sim.gerar_conversas --cenario <nome> --usar-database-url   # só um (smoke)
```

Cada rotulador exporta o **seu** arquivo (`golden_<rotulador>.jsonl`) com **só a sua coluna** — cada
fala vira um item (sem `rubrica` — holístico):

```json
{"id": "cenario::3", "conversa_id": "cenario", "cenario": "...", "texto_resposta": "...", "historico": ["cliente: ...", "ia: ...", "cliente: ..."], "rotulo_humano_fernando": true, "rotulo_humano_socia": true}
```

O campo **`historico`** (os turnos ANTES daquela fala — `"cliente: ..."`/`"ia: ..."`/`"[ato]"`) é o
contexto que o judge recebe (`montar_mensagens`, **todas** as rubricas): `tom_pt_br`/`instruction_following`
só dão para julgar com a conversa à vista (idioma / o que foi pedido). Humano e judge avaliam a
**mesma** informação. O `calibrar.py` detecta o golden holístico (sem `rubrica`): a fala "passa" no
judge se passa em **todas** as rubricas — comparável ao ✓/✕ humano. (Golden legado **com** `rubrica`
por linha — `dataset_exemplo.jsonl` — segue suportado, por-rubrica.)

Antes de tudo, medir o acordo entre os dois humanos — ele é o **TETO** da meta (refino 08b §3.1):

```python
from calibracao import acordo_humano_humano
kappa_humano = acordo_humano_humano(fernando, socia)  # listas de bool pareadas
```

Exigir `kappa_judge >= 0.6` quando os humanos só concordam a ~0.7 é frágil. Se `kappa_humano`
vier baixo, **a rubrica está mal definida** — afie o critério no `judge.md` e re-rotule antes de
julgar o judge. O golden é **held-out**: nunca reusar como fixture do gate de cutover (evita leak
por fixture reutilizada).

### 1b. Juntar os dois exports num golden de duas colunas  · puro

A UI exporta **um arquivo por rotulador** (`golden_fernando.jsonl` / `golden_socia.jsonl`), cada um
com **só a sua coluna**. O `calibrar.py` exige as **duas** colunas na mesma linha por `id`, então
faça o INNER JOIN com `merge_rotulos.py` (puro, **sem crédito**) — só as falas rotuladas pelos
**dois** entram no golden (as de um só são descartadas com aviso, sem cap silencioso):

```sh
uv run python evals/calibracao/merge_rotulos.py \
    --fernando evals/calibracao/golden_fernando.jsonl \
    --socia    evals/calibracao/golden_socia.jsonl \
    --saida    evals/calibracao/golden.jsonl
```

### 2. Rodar o judge sobre o golden  · `needs_anthropic_api`

`calibrar.py` roda o judge (advisory, Sonnet 4.6) sobre cada linha do golden, coletando `passou`
por item. Custa crédito Anthropic — passo deliberado, fora do `make evals`/CI. O resultado é a
lista `judge: list[bool]` pareada com o rótulo humano consolidado (critério do operador: ex. AND
dos dois humanos para segurança, ou a maioria).

Cada fala do golden holístico é avaliada em **uma única chamada** (`judge.julgar_holistico` →
`JudgeHolistico`, as 4 rubricas LLM de uma vez), não quatro: corta ~75% das chamadas do juiz e
reenvia constituição + contexto 1× por fala em vez de 4×. Para gastar menos enquanto afina o
`judge.md`, rode um subconjunto antes da rodada completa:

```sh
uv run python evals/calibracao/calibrar.py --cenario desconfiado_ia --cenario pede_desconto
```

O golden legado **por-rubrica** (`dataset_exemplo.jsonl`) segue julgado uma rubrica por chamada
(`judge.julgar`).

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
