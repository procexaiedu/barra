# Calibração dos judges contra rótulo humano

Os dois judges de LLM que rodam em produção **nunca foram calibrados**. Um deles é
**vinculante e fail-closed** — barra a bolha antes de sair e abre handoff. Ninguém sabe se o
`reprovado` dele concorda com o julgamento humano melhor do que uma moeda.

Este diretório mede isso. Uma métrica, um número: **Cohen's κ**.

## Os dois judges (fontes diferentes no banco)

| | `pos_envio` | `aup` |
|---|---|---|
| Onde roda | worker `workers/judge_pos_envio.py`, assíncrono, **depois** do envio | nó `agente/nos/output_guard.py`, síncrono, **antes** do envio |
| Vinculante? | não (telemetria pura) | **sim** — reprovou, a bolha é zerada + handoff |
| Reprovado = | `julgamentos_turno.rastro_llm = true` | `escaladas.observacao LIKE 'aup_saida_%'` |
| Aprovado = | `julgamentos_turno.rastro_llm = false` | a bolha saiu → `mensagens(direcao='ia')` |
| Consequência de errar | gatilho de rollback (`rollback_watch`) dispara à toa, ou não dispara | **cliente fica sem resposta e Fernando leva um handoff falso** |

O `aup` é o que mais importa calibrar e o que é mais difícil de calibrar — ver abaixo.

## Fluxo

```
1. exportar   ->  2. rotular (Fernando/dev, 50-100 linhas)  ->  3. computar  ->  4. decidir
```

### 1. Exportar

```bash
# dry-run: mostra o SQL de cada estrato, não conecta em nada
uv run --project api python scripts/calibracao/exportar_amostra.py --explicar --judge ambos

# export de verdade
CALIBRACAO_DSN="postgresql://..." uv run --project api \
  python scripts/calibracao/exportar_amostra.py \
    --judge ambos -n 100 --dias 30 --saida ~/amostra.csv --confirmo-remoto
```

- O DSN sai de `--dsn`, `$CALIBRACAO_DSN` ou `$TEST_DATABASE_URL`. **`DATABASE_URL` não é lida
  de propósito**: apontar para prod tem de ser um ato explícito.
- Host não-local exige `--confirmo-remoto`. Mesmo sendo leitura pura (a transação abre
  `read_only`), ler o banco de produção cai na regra do `CLAUDE.md` §0 — **peça autorização
  ao dono antes**.
- Amostra **estratificada 50/50** (metade reprovados, metade aprovados), reprodutível pelo
  `--seed`. Reprovado é raro em produção; sem estratificar, uma amostra de 100 traria ~0 deles
  e não mediria nada.

### 2. Rotular

Abra o CSV e preencha **só** `rotulo_humano` com `aprovado` ou `reprovado`. `nota_humana` é
opcional (por quê). Linhas em branco são ignoradas — dá para rotular em duas sessões.

A pergunta que o rotulador responde é a **mesma** que o judge respondeu:

- `pos_envio` → *um cliente atento perceberia rastro de IA neste turno?* (sim = `reprovado`)
- `aup` → *esta bolha deveria ter sido barrada?* (sim = `reprovado`)

**Rotule sem olhar a coluna `veredicto_judge`.** Se você lê o veredicto antes, o κ mede
ancoragem, não concordância. Esconda a coluna na planilha.

### 3. Computar

```bash
python3 scripts/calibracao/computar_kappa.py ~/amostra.csv
```

Sai matriz de confusão, acurácia, κ com a leitura, e precision/recall por classe — **por judge
separadamente** e no agregado.

### 4. Decidir

| κ | Leitura | O que fazer |
|---|---|---|
| < 0.20 | judge não confiável — reprova quase por acaso | **Reescrever a rubrica** do prompt do judge. Enquanto isso, o AUP fail-closed está barrando bolhas boas: considere afrouxar para só os motivos duros (`ia_self`, `system_leak`) |
| 0.20–0.40 | sinal fraco | Recalibrar o prompt do judge com os desacordos como contra-exemplos |
| 0.41–0.60 | moderado — triagem, não gate | Manter como telemetria; para o vinculante, olhar `precision(reprovado)`: se for baixa, o custo é handoff falso — ajustar o threshold/motivos |
| > 0.60 | substancial | Confiar. Revisar só as bordas |

Olhe **precision e recall separados**, não só o κ:

- `precision(reprovado)` baixa no `aup` = **falso positivo caro**: bolha boa barrada, cliente
  mudo, handoff inútil para Fernando.
- `recall(reprovado)` baixa no `pos_envio` = o gatilho `nao_contidos` do `rollback_watch` está
  cego para incidentes reais.

## Judge de AUP: o limite estrutural

**O texto da bolha reprovada pela AUP não existe no Postgres.** O `output_guard` zera a bolha
antes do envio; o que sobra é a linha em `escaladas` com o motivo (`aup_saida_ia_self`, …) e o
resumo fixo. O texto só está no **trace do Langfuse**.

Consequência prática: nas linhas `aup/reprovado` a coluna `texto_bolha` sai vazia e
`onde_achar_o_texto` diz onde procurar. Sem o texto **não dá para rotular**. Duas saídas:

1. **Manual** — para cada linha, abrir o trace no Langfuse pela conversa/janela e colar o texto
   barrado na coluna `texto_bolha`. Viável para 25-50 linhas.
2. **Estrutural (recomendado se isto virar rotina)** — passar a persistir o texto barrado. Hoje
   um incidente de AUP é irreproduzível fora do Langfuse, o que também dificulta o diagnóstico
   normal. É mudança em `api/src/barra/` — fora do escopo deste diretório, precisa de decisão.

## Nota de método

O κ medido sobre amostra estratificada 50/50 **não é o κ da população** (onde reprovado é
raro): ele tende a ser mais alto. Trate o número como **teto otimista** — se já der baixo aqui,
em produção é pior. A estratificação está certa para precision/recall por classe, que é o que
manda na decisão.

## Estado

O tooling está pronto e verificado com CSV sintético. **Nenhuma amostra real foi exportada** —
isso depende de autorização para ler o banco de produção.
