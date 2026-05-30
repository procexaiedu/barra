# Infra

Infraestrutura operacional da Elite Baby.

- `compose/`: stacks e configuração de serviços.
- `sql/`: SQL versionado da aplicação, aplicado em ordem (numérica/timestamp) via `psql` ou Supabase Studio. Regras em `sql/CLAUDE.md`.
- `runbooks/`: procedimentos manuais de operação. **Antes de tocar em produção, leia `runbooks/topologia-banco.md` e `runbooks/aplicar-migrations-prod.md`** — dev e prod são o mesmo banco.
