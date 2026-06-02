# Scripts

Utilitarios de desenvolvimento e operacao local.

Nao colocar codigo de producao neste diretorio.

- `nova-trilha.ps1` — cria uma worktree dedicada para uma trilha de tasks isolada (`git worktree add` da main + copia `api/.env` + deriva `TEST_DATABASE_URL`).
- `aplicar_sql.py` — aplica SQL no banco via psycopg.
- `reset_agente.py` — reset de estado do agente para testes.
- `vincular_instance_legacy.py` — vincula instancia Evolution legada a uma modelo.
- `repara_encoding_evals.py` — conserta mojibake (dupla codificacao latin-1<->utf-8) nas fixtures `.jsonl` de `api/evals/`. Idempotente; `--dry-run` so reporta.
- `gera_indice_evals.py` — gera `docs/agente/evals-fixtures-indice.html`, indice navegavel das fixtures de `api/evals/{canonicos,adversariais}` com selo BARRA/AVISA (gate espelhado do `runner.py`). Regenere quando as fixtures mudarem.
