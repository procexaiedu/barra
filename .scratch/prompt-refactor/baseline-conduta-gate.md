# Baseline do `conduta_gate` — referência dos tickets 03+

**Status: PENDENTE — a corrida não foi feita.** O gate real gasta crédito de LLM (§0 do
`CLAUDE.md`); quem autoriza é o humano, frase a frase. Este arquivo já está no formato final:
depois da corrida autorizada, cole os números nos campos marcados `_(pendente)_` e troque o
status acima para `MEDIDO`.

Serve como o número **pré-corte** contra o qual os tickets 03+ comparam. Só é comparável se a
corrida rodar com o mesmo `--por-eixo`, o mesmo `--max-turnos` e os mesmos baselines de
`evals/baselines/` — anote qualquer divergência em "Observações".

## Corrida

| campo | valor |
|---|---|
| data | _(pendente)_ |
| commit (`git rev-parse --short HEAD`) | _(pendente)_ |
| branch | `refactor-prompt-conduta` |
| ticket que fechou o pré-requisito | `01-janela-cronologica-do-e2e.md` |
| custo real da corrida (R$) | _(pendente — o gate imprime `custo: R$ …`)_ |

Comando exato (a partir de `api/`, com a autorização §0 já dada):

```sh
E2E_AUTORIZADO=1 TEST_DATABASE_URL='<dsn do self-hosted>' \
  make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"
```

- `E2E_AUTORIZADO=1` é o opt-in de §0: sem ele o gate se recusa a rodar. **Não** exportar por
  padrão.
- `TEST_DATABASE_URL` aponta para o Postgres self-hosted: o gate LÊ o corpus (personas do núcleo)
  e seeda com `ROLLBACK` — nada commita.
- `ARGS="--fake"` valida só o encanamento, sem crédito; os números de conduta **não** são
  significativos nesse modo e não servem de baseline.
- Sem `evals/baselines/*.json`, os checks de FORMA/VOZ saem `PULADO (sem baseline)` — anote isso
  em "Observações" em vez de deixar a linha em branco.

## Métricas (a preencher com a saída do gate)

O bloco `=== Gate de Conduta ===` imprime tudo abaixo; o dicionário `rel` de
`conduta_gate._agregar` é a fonte de cada campo.

| métrica | classe | valor |
|---|---|---|
| `n_corridas` | contexto | _(pendente)_ |
| `empurrao_pct` (limiar HARD: ≤ 5,0%) | **HARD** | _(pendente)_ |
| `violacoes_duras` (limiar HARD: 0) | **HARD** | _(pendente)_ |
| `conduziu_por_eixo` (um por eixo de comportamento) | advisory | _(pendente)_ |
| `bate_desfecho_real_pct` | advisory | _(pendente)_ |
| `estilo_dist_medio` (voz) / `estilo_ref_piso` | advisory | _(pendente)_ |
| `fluxo_jsd` (forma) / `fluxo_ref_piso` | advisory | _(pendente)_ |
| veredito (`APROVADO` / `REPROVADO`) | — | _(pendente)_ |
| diretório dos transcritos (`evals/saidas/conduta-<ts>`) | — | _(pendente)_ |

Leituras que já valem hoje, e que os tickets 03+ herdam:

- **HARD é só `empurrao` + `violacoes_duras`.** `conduziu`, `voz` e `forma` são *advisory*: o gate
  roda `ClienteRoteirizado` NÃO-reativo, então `conduziu≈0%` é artefato do roteiro, não regressão
  de conduta. Comparar tickets por `conduziu` sem cliente reativo produz alarme falso.
- O piso de `empurrao` (3,25%) veio de `baselines/empurrao.json` medido com a v1 do
  `_EMPURRAO_RE`, que ainda casava `seria agora`. O regex atual é mais estreito, então o piso
  humano real é MENOR — regerar o baseline e baixar `empurrao_pct_max` é trabalho de outro ticket.

## Checagem de sanidade da janela (o que o ticket 01 consertou)

Antes de tratar os números acima como baseline, confirme nos transcritos salvos
(`evals/saidas/conduta-<ts>/transcritos.html`) que uma conversa de **8+ turnos** mostra a saudação
de abertura **em primeiro lugar**, não no meio da conversa. Era o sintoma da janela embaralhada
(critério de aceite 3 do ticket 01) e é o que torna qualquer medição de coerência de fio,
repetição ou recency confiável.

- conversa conferida (perfil / nº de turnos): _(pendente)_
- saudação em primeiro lugar? _(pendente)_

## Observações

_(pendente)_
