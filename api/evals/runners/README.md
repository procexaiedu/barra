# Runners de evals

## `runner.py` — gate determinístico (EVAL-01)

Carrega as fixtures `.jsonl`, seeda o estado, roda o **grafo real** (sem checkpointer, P0) por
fixture e aplica os graders **determinísticos**, emitindo exit-code de gate (`0` se pass-rate
`>= --threshold`, senão `1`).

### Como rodar

```bash
# da raiz de api/, com o ambiente preparado:
export TEST_DATABASE_URL=...        # NUNCA prod direto sem rollback; o runner usa transação + ROLLBACK
export ANTHROPIC_API_KEY=...        # o nó llm chama o Sonnet real

make evals                          # todas as fixtures, threshold 1.0
make evals EVALS_ARGS="--subdir canonicos/leitura --threshold 0.8"
```

Sem `TEST_DATABASE_URL` o runner aborta (exit 2) — não roda contra prod por engano.

### Graders cobertos

Determinísticos (este runner): `tool_calls_obrigatorias` / `tool_calls_proibidas`,
`texto_resposta` (`nao_deve_conter` / `deve_conter_um_de` / `max_chars`), `ia_pausada_final`,
`estado_final_atendimento` e `state_check` (com os aliases soltos).

**Fora de escopo aqui:** rubricas `judge: llm` (LLM-judge → EVAL-02) e `nodes_proibidos` /
`NodesVisitedHandler` (→ EVAL-08) são ignoradas. O loop K=5 + CI bloqueante é EVAL-04/03.

### Verificação da lógica de gate

`tests/evals/test_runner_gate.py` exercita os graders puros (`avaliar`) e o `gate` sem DB/LLM —
roda no `make test`/CI sem credenciais. O caminho de invocação real espelha
`tests/agente/test_fixtures_leitura_decisao.py` (`needs_key` + `needs_db`).
