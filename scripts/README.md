# Scripts

Utilitarios de desenvolvimento e operacao local.

Nao colocar codigo de producao neste diretorio.

- `nova-trilha.ps1` — cria uma worktree dedicada para uma trilha de tasks do roadmap executavel (`git worktree add` da main + copia `api/.env` + deriva `TEST_DATABASE_URL`). Ver `docs/mvp/COMO-EXECUTAR.md`.
- `aplicar_sql.py` — aplica SQL no banco via psycopg.
- `reset_agente.py` — reset de estado do agente para testes.
- `vincular_instance_legacy.py` — vincula instancia Evolution legada a uma modelo.
