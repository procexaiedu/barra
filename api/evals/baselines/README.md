# Baselines do gate de conduta

Baselines humanos **congelados** que os scorers de `evals/conduta.py` usam para medir se o
agente conduz a venda com a mesma **forma, voz e disciplina** que o Vendedor humano. São
**agregados** (distribuições, taxas, trigramas, pisos de ruído) — **nenhuma mensagem literal**,
baixo risco de PII; por isso são commitados, embora o corpus de origem siga no `.gitignore`.

## Arquivos

| Arquivo | Conteúdo | Piso (ruído de referência) |
|---|---|---|
| `fluxo_atos.json` | Counter de transições de atos do funil (`saudacao>cotacao`, …) | `piso_jsd_eb_split` (JSD eb01-03 × eb04, ~0.0318) |
| `estilo_corpus.json` | Perfil estilométrico d'ELA (6 features) | `piso_ela_vs_ela` (split de paridade, ~0.0035) |
| `empurrao.json` | Taxa de empurrão do detector regex sobre as cotações humanas | refs do juiz LLM (humano ~26%, v1 ~0.3%) |

## Como (re)gerar — §0 read-only

Os JSONs **não** ficam no repo até serem gerados (dependem de leitura do corpus de prod). Rode
uma vez, do diretório `api/`, e **commite** os agregados:

```bash
DATABASE_URL=<prod-self-hosted> uv run python -m evals.baselines.gerar
```

É só `SELECT` em `corpus.turnos` / `corpus.mensagens_raw` — não muta prod, não gasta crédito.
Sem os JSONs, `make gate-conduta` aborta com mensagem clara apontando para cá; os **testes
unitários** (`tests/agente/test_conduta.py`) não dependem deles (injetam baseline sintético).

## Calibração

Os limiares de aprovação (pass bar) **não** vivem aqui — vivem na política do gate
(`evals/e2e/conduta_gate.py`, `_LIMIARES`), expressos como múltiplos destes pisos. Recalibre-os
após a primeira corrida real autorizada (§0), quando os números do agente forem conhecidos.
