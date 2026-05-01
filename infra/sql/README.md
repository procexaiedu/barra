# SQL

SQL versionado de infraestrutura e bootstrap.

Migrations da aplicacao devem ficar aqui como SQL puro sequencial:

- `0001_schema_inicial.sql`
- `0002_envios_evolution.sql`
- `NNNN_nome_descritivo.sql`

Sem ORM nem migration framework: aplicar via `psql -f` ou Supabase Studio na ordem numerica.
